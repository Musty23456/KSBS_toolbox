"""
Google Gemini provider (official Google Gen AI SDK: ``google-genai``).

The SDK is imported lazily so the rest of the app (and the test suite) works
without it installed, and so the key is only handed to the SDK at call time.

Errors are classified by HTTP status / exception type using duck typing, so
the mapping does not depend on SDK internals and can be tested without it.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from typing import Any, Callable, Optional

from app.ai.config import AIConfig
from app.ai.errors import (
    AIAuthenticationError,
    AIBlockedContentError,
    AIError,
    AIInvalidRequestError,
    AIInvalidResponseError,
    AIModelNotFoundError,
    AINetworkError,
    AIQuotaExceededError,
    AIServiceUnavailableError,
    AITimeoutError,
)
from app.ai.providers.base import AIProvider, ProviderResponse
from app.ai.redaction import redact

logger = logging.getLogger("app.ai.gemini")


def classify_exception(exc: BaseException) -> AIError:
    """Translate any SDK/network exception into a safe AIError."""
    if isinstance(exc, AIError):
        return exc

    names = {cls.__name__.lower() for cls in type(exc).__mro__}
    code = getattr(exc, "code", None)
    if not isinstance(code, int):
        code = getattr(exc, "status_code", None)
    message = str(exc).lower()

    if isinstance(exc, TimeoutError) or any("timeout" in n for n in names):
        return AITimeoutError()
    if isinstance(code, int):
        if code in (401, 403):
            return AIAuthenticationError()
        if code == 400 and ("api key" in message or "api_key" in message):
            return AIAuthenticationError()
        if code == 404:
            return AIModelNotFoundError()
        if code == 429:
            return AIQuotaExceededError()
        if code in (408, 504):
            return AITimeoutError()
        if code >= 500:
            return AIServiceUnavailableError()
        if 400 <= code < 500:
            return AIInvalidRequestError("The AI provider rejected the request.")
    if isinstance(exc, (ConnectionError, OSError)) or any(
        n in names for n in ("connecterror", "networkerror", "connectionerror", "protocolerror", "readerror")
    ):
        return AINetworkError()
    return AIServiceUnavailableError()


class GeminiProvider(AIProvider):
    name = "gemini"

    def __init__(self, config: AIConfig, client_factory: Optional[Callable[[], Any]] = None):
        super().__init__(config.model)
        self._config = config
        self._client_factory = client_factory
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            if self._client_factory is not None:
                self._client = self._client_factory()
            else:
                try:
                    from google import genai
                    from google.genai import types
                except ImportError as exc:  # pragma: no cover - depends on install
                    logger.error("google-genai is not installed")
                    raise AIServiceUnavailableError(
                        "The Gemini SDK is not installed on the server."
                    ) from exc
                self._client = genai.Client(
                    api_key=self._config.reveal_api_key(),
                    # SDK timeout is in milliseconds; we also enforce our own below.
                    http_options=types.HttpOptions(timeout=self._config.timeout_seconds * 1000),
                )
        return self._client

    def _call(
        self,
        prompt: str,
        system_instruction: Optional[str],
        max_output_tokens: Optional[int],
        json_mode: bool = False,
    ) -> Any:
        client = self._get_client()
        config: dict[str, Any] = {}
        if system_instruction:
            config["system_instruction"] = system_instruction
        if max_output_tokens:
            config["max_output_tokens"] = max_output_tokens
        if json_mode:
            config["response_mime_type"] = "application/json"
        return client.models.generate_content(model=self.model, contents=prompt, config=config or None)

    def generate_text(
        self,
        prompt: str,
        *,
        system_instruction: Optional[str] = None,
        max_output_tokens: Optional[int] = None,
        json_mode: bool = False,
    ) -> ProviderResponse:
        # Hard wall-clock timeout independent of the SDK's own handling.
        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(self._call, prompt, system_instruction, max_output_tokens, json_mode)
        try:
            raw = future.result(timeout=self._config.timeout_seconds)
        except FutureTimeout as exc:
            future.cancel()
            raise AITimeoutError() from exc
        except AIError:
            raise
        except Exception as exc:  # noqa: BLE001 - everything is classified below
            error = classify_exception(exc)
            # Log type and mapped code only; never the raw message or request.
            logger.warning(
                "Gemini call failed: type=%s mapped=%s model=%r detail=%s",
                type(exc).__name__,
                error.code,
                self.model,
                redact(str(exc)[:200], self._config.reveal_api_key()),
            )
            raise error from exc
        finally:
            executor.shutdown(wait=False)

        return self._parse(raw)

    def _parse(self, raw: Any) -> ProviderResponse:
        feedback = getattr(raw, "prompt_feedback", None)
        if feedback is not None and getattr(feedback, "block_reason", None):
            raise AIBlockedContentError()

        try:
            text = getattr(raw, "text", None)
        except Exception as exc:  # noqa: BLE001 - SDK raises on empty/blocked candidates
            raise AIInvalidResponseError() from exc

        if not isinstance(text, str) or not text.strip():
            raise AIInvalidResponseError("The AI provider returned an empty response.")

        finish_reason = None
        candidates = getattr(raw, "candidates", None)
        if candidates:
            reason = getattr(candidates[0], "finish_reason", None)
            finish_reason = getattr(reason, "name", None) or (str(reason) if reason is not None else None)
        return ProviderResponse(text=text, model=self.model, finish_reason=finish_reason)
