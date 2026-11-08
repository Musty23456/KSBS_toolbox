"""Helpers that keep secrets out of logs and error text."""

from __future__ import annotations

import re

# Google API keys start with "AIza"; also catch bearer tokens and generic
# key=... / api_key: ... assignments.
_PATTERNS = [
    re.compile(r"AIza[0-9A-Za-z_\-]{20,}"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{10,}"),
    re.compile(r"(?i)(api[_-]?key|token|secret)(\s*[=:]\s*)[^\s,;&\"']+"),
]


def redact(text: str, *extra_secrets: str) -> str:
    """Return ``text`` with API keys/tokens (and any exact secrets given) masked."""
    for secret in extra_secrets:
        if secret:
            text = text.replace(secret, "[REDACTED]")
    text = _PATTERNS[0].sub("[REDACTED]", text)
    text = _PATTERNS[1].sub("Bearer [REDACTED]", text)
    text = _PATTERNS[2].sub(lambda m: f"{m.group(1)}{m.group(2)}[REDACTED]", text)
    return text
