"""
Things a translation must keep exactly as they are.

* Placeholders ({min}, {{name}}, %s), URLs, e-mail addresses and markup are PROTECTED: losing or inventing one
  blocks the translation, because the screen would show it raw or the message would lose its number.
* Numbers are compared too, but only warn: a translator may legitimately write a number in words.
"""

from __future__ import annotations

import re
from collections import Counter

_PROTECTED = [
    re.compile(r"\{\{.*?\}\}"),
    re.compile(r"\{[A-Za-z_][A-Za-z0-9_.]*\}"),
    re.compile(r"%(?:\d+\$)?[sdif]"),
    re.compile(r"https?://[^\s)\]>]+"),
    re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"),
    re.compile(r"</?[A-Za-z][^>]*>"),
]

# Arabic-Indic and Persian digits are read as the Western digit they stand for.
_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")

# Invisible direction marks some models add around Arabic text. They are never needed, so they are removed.
BIDI_CONTROLS = re.compile("[\u200e\u200f\u202a-\u202e\u2066-\u2069]")


def protected_tokens(text: str) -> Counter:
    found: Counter = Counter()
    remaining = text or ""
    for pattern in _PROTECTED:
        for match in pattern.findall(remaining):
            found[match] += 1
        remaining = pattern.sub(" ", remaining)  # a URL's digits must not also count as a bare token
    return found


def missing_tokens(source: str, translated: str) -> list[str]:
    """Protected tokens the source has and the translation lacks (respecting repeat counts)."""
    need, have = protected_tokens(source), protected_tokens(translated)
    return sorted(token for token, count in need.items() if have[token] < count)


def added_tokens(source: str, translated: str) -> list[str]:
    """Protected tokens the translation invented."""
    need, have = protected_tokens(source), protected_tokens(translated)
    return sorted(token for token, count in have.items() if need[token] < count)


def numbers_in(text: str) -> Counter:
    without_tokens = text or ""
    for pattern in _PROTECTED:
        without_tokens = pattern.sub(" ", without_tokens)
    return Counter(_NUMBER.findall(without_tokens.translate(_DIGITS)))


def missing_numbers(source: str, translated: str) -> list[str]:
    need, have = numbers_in(source), numbers_in(translated)
    return sorted(n for n, count in need.items() if have[n] < count)
