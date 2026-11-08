"""Provider-neutral interface. A new provider implements ``AIProvider`` only."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ProviderResponse:
    text: str
    model: str
    finish_reason: Optional[str] = None


class AIProvider(ABC):
    name: str = "base"

    def __init__(self, model: str):
        self.model = model

    @abstractmethod
    def generate_text(
        self,
        prompt: str,
        *,
        system_instruction: Optional[str] = None,
        max_output_tokens: Optional[int] = None,
        json_mode: bool = False,
    ) -> ProviderResponse:
        """Run one generation. Must raise subclasses of ``AIError`` only.

        ``json_mode=True`` asks the provider to return a JSON document only.
        Callers must still parse and validate the result: it is a hint, not a guarantee.
        """
