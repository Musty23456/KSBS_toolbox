"""Provider registry. Add a new provider by registering its class here."""

from __future__ import annotations

from app.ai.config import AIConfig
from app.ai.errors import AIInvalidRequestError
from app.ai.providers.base import AIProvider, ProviderResponse
from app.ai.providers.gemini import GeminiProvider

_REGISTRY = {
    "gemini": GeminiProvider,
}


def build_provider(config: AIConfig) -> AIProvider:
    try:
        provider_cls = _REGISTRY[config.provider]
    except KeyError:
        raise AIInvalidRequestError("Unknown AI provider configured.") from None
    return provider_cls(config)


__all__ = ["AIProvider", "ProviderResponse", "GeminiProvider", "build_provider"]
