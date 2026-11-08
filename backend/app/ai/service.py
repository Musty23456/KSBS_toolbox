"""
AIService: the one place that turns a feature's request into a provider call.

    validate -> (enabled / configured checks) -> provider (with retries)
             -> response checks -> usage log

Future features (e.g. questionnaire generation) should call
``AIService.generate_text`` rather than talking to a provider directly, so
validation, retries, error mapping and usage logging apply uniformly.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Callable, Optional

from sqlalchemy.orm import Session

from app.ai.config import AIConfig, get_ai_config
from app.ai.errors import (
    AIDisabledError,
    AIError,
    AIInvalidResponseError,
    AINotConfiguredError,
)
from app.ai.providers import AIProvider, ProviderResponse, build_provider
from app.ai.schemas import AIStatusResponse, AITestConnectionResponse
from app.ai.usage import record_usage
from app.ai.validation import SYSTEM_GUARD, validate_prompt, wrap_untrusted

logger = logging.getLogger("app.ai.service")

# Upper bound on what we accept back from a provider (characters).
MAX_RESPONSE_CHARS = 100_000
BACKOFF_BASE_SECONDS = 0.5


class _ConnectionState:
    """Last known connection result, kept in memory so /status never spends quota."""

    def __init__(self):
        self._lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        with self._lock:
            self.key: Optional[tuple[str, str]] = None
            self.state = "unknown"
            self.checked_at: Optional[datetime] = None
            self.error_code: Optional[str] = None

    def record(self, provider: str, model: str, success: bool, error_code: Optional[str]) -> None:
        with self._lock:
            self.key = (provider, model)
            self.state = "connected" if success else "failed"
            self.checked_at = datetime.now(timezone.utc)
            self.error_code = None if success else error_code

    def snapshot(self, provider: str, model: str):
        with self._lock:
            if self.key != (provider, model):  # config changed since last check
                return "unknown", None, None
            return self.state, self.checked_at, self.error_code


connection_state = _ConnectionState()


class AIService:
    def __init__(
        self,
        config: Optional[AIConfig] = None,
        provider: Optional[AIProvider] = None,
        db: Optional[Session] = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.config = config or get_ai_config()
        self._provider = provider
        self.db = db
        self._sleep = sleep

    # ------------------------------------------------------------------ status

    def status(self) -> AIStatusResponse:
        cfg = self.config
        state, checked_at, error_code = connection_state.snapshot(cfg.provider, cfg.model)
        if not cfg.enabled:
            message = "AI is disabled. Set AI_ENABLED=true on the server to turn it on."
            state, checked_at, error_code = "unknown", None, None
        elif not cfg.has_api_key:
            message = "AI is enabled but GEMINI_API_KEY is not set on the server."
            state, checked_at, error_code = "unknown", None, None
        elif state == "connected":
            message = "Last connection test succeeded."
        elif state == "failed":
            message = "Last connection test failed. Use Test connection after fixing the cause."
        else:
            message = "AI is configured. Run a connection test to verify it."
        return AIStatusResponse(
            enabled=cfg.enabled,
            configured=cfg.has_api_key,
            provider=cfg.provider,
            model=cfg.model,
            available=cfg.is_ready,
            connection_status=state,
            last_checked_at=checked_at,
            last_error_code=error_code,
            message=message,
        )

    # -------------------------------------------------------------- generation

    def _require_ready(self) -> None:
        if not self.config.enabled:
            raise AIDisabledError()
        if not self.config.has_api_key:
            raise AINotConfiguredError()

    def _get_provider(self) -> AIProvider:
        if self._provider is None:
            self._provider = build_provider(self.config)
        return self._provider

    def generate_text(
        self,
        prompt: str,
        *,
        user_id: Optional[str],
        request_type: str,
        system_instruction: Optional[str] = None,
        max_output_tokens: Optional[int] = None,
        untrusted: bool = True,
        json_mode: bool = False,
        max_prompt_chars: Optional[int] = None,
    ) -> ProviderResponse:
        """
        Validate and run one generation.

        ``untrusted=True`` (default) fences the prompt as user data and
        prepends the injection-resistant system guard. Pass False only for
        fixed, server-authored prompts such as the connection test.

        ``json_mode`` asks the provider for JSON only; the caller still has to
        parse and validate it. ``max_prompt_chars`` lets a feature raise the
        default prompt limit (the questionnaire generator does).
        """
        self._require_ready()
        cleaned = validate_prompt(prompt, max_chars=max_prompt_chars or self.config.max_prompt_chars)
        if untrusted:
            cleaned = wrap_untrusted(cleaned)
            system_instruction = f"{SYSTEM_GUARD}\n{system_instruction}" if system_instruction else SYSTEM_GUARD

        provider = self._get_provider()
        started = time.monotonic()
        try:
            response = self._call_with_retries(provider, cleaned, system_instruction, max_output_tokens, json_mode)
            if len(response.text) > MAX_RESPONSE_CHARS:
                raise AIInvalidResponseError()
        except AIError as exc:
            self._finish(user_id, request_type, started, success=False, error_code=exc.code)
            raise
        self._finish(user_id, request_type, started, success=True)
        return response

    def _call_with_retries(
        self, provider, prompt, system_instruction, max_output_tokens, json_mode: bool = False
    ) -> ProviderResponse:
        attempts = self.config.max_retries + 1
        # Only pass json_mode when requested so providers written before it existed keep working.
        extra = {"json_mode": True} if json_mode else {}
        for attempt in range(1, attempts + 1):
            try:
                return provider.generate_text(
                    prompt,
                    system_instruction=system_instruction,
                    max_output_tokens=max_output_tokens,
                    **extra,
                )
            except AIError as exc:
                if not exc.retryable or attempt == attempts:
                    raise
                logger.info("Retrying AI call after %s (attempt %d/%d)", exc.code, attempt, attempts)
                self._sleep(BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)))
        raise AIInvalidResponseError()  # pragma: no cover - loop always returns or raises

    def _finish(self, user_id, request_type, started, *, success: bool, error_code: Optional[str] = None) -> None:
        duration_ms = int((time.monotonic() - started) * 1000)
        connection_state.record(self.config.provider, self.config.model, success, error_code)
        record_usage(
            self.db,
            user_id=user_id,
            provider=self.config.provider,
            model=self.config.model,
            request_type=request_type,
            success=success,
            duration_ms=duration_ms,
            error_code=error_code,
        )

    # --------------------------------------------------------------- test call

    def test_connection(self, user_id: Optional[str]) -> AITestConnectionResponse:
        started = time.monotonic()
        response = self.generate_text(
            "Reply with the single word: OK",
            user_id=user_id,
            request_type="test_connection",
            max_output_tokens=16,
            untrusted=False,
        )
        return AITestConnectionResponse(
            success=True,
            provider=self.config.provider,
            model=response.model,
            latency_ms=int((time.monotonic() - started) * 1000),
            message="Connection to the AI provider succeeded.",
        )
