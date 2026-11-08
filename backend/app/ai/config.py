"""
Read-only view of the AI settings.

``AIConfig`` deliberately has no way to print or serialise the API key:
the key lives in a ``SecretStr`` and is only revealed by ``reveal_api_key()``
inside the provider that needs it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import SecretStr

from app.config import get_settings


@dataclass(frozen=True)
class AIConfig:
    enabled: bool
    provider: str
    model: str
    timeout_seconds: int
    max_retries: int
    rate_limit_per_minute: int
    max_request_bytes: int
    max_prompt_chars: int
    api_key: SecretStr = field(default=SecretStr(""), repr=False)
    # Phase 2 questionnaire generation limits (defaulted so older call sites keep working).
    generation_timeout_seconds: int = 90
    generation_max_request_bytes: int = 65536
    generation_max_prompt_chars: int = 30000
    generation_max_output_tokens: int = 32768
    generation_max_questions: int = 100
    # Phase 3 editor: the request body carries the whole questionnaire.
    edit_max_request_bytes: int = 262144

    @property
    def has_api_key(self) -> bool:
        return bool(self.api_key.get_secret_value())

    def reveal_api_key(self) -> str:
        return self.api_key.get_secret_value()

    @property
    def is_ready(self) -> bool:
        """AI can actually be used: switched on and a key is present."""
        return self.enabled and self.has_api_key


def get_ai_config() -> AIConfig:
    """Build the config from the current settings (cheap; not cached so tests can override)."""
    s = get_settings()
    return AIConfig(
        enabled=bool(s.AI_ENABLED),
        provider=s.AI_PROVIDER,
        model=s.GEMINI_MODEL,
        timeout_seconds=s.AI_REQUEST_TIMEOUT,
        max_retries=s.AI_MAX_RETRIES,
        rate_limit_per_minute=s.AI_RATE_LIMIT_PER_MINUTE,
        max_request_bytes=s.AI_MAX_REQUEST_BYTES,
        max_prompt_chars=s.AI_MAX_PROMPT_CHARS,
        api_key=SecretStr(s.GEMINI_API_KEY or ""),
        generation_timeout_seconds=s.AI_GENERATION_TIMEOUT,
        generation_max_request_bytes=s.AI_GENERATION_MAX_REQUEST_BYTES,
        generation_max_prompt_chars=s.AI_GENERATION_MAX_PROMPT_CHARS,
        generation_max_output_tokens=s.AI_GENERATION_MAX_OUTPUT_TOKENS,
        generation_max_questions=s.AI_GENERATION_MAX_QUESTIONS,
        edit_max_request_bytes=s.AI_EDIT_MAX_REQUEST_BYTES,
    )
