"""
Clean-up and safety checks for translated text, whoever wrote it (the AI or a person).

``normalize_translation`` tidies the text; ``check_translation`` returns issues. BLOCK issues stop the text
from being saved (it would break the screen or the message); WARN issues are advice shown to the translator.
Because identifiers are never translation units, a translation can never change a question code, a choice
value, a validation rule or skip logic: what is checked here is only that the visible text stays usable.
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable, Optional

from app.ai.translation import protect
from app.ai.translation.languages import get_language
from app.ai.translation.units import Unit, UnitId

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_LETTER = re.compile(r"[^\W\d_]", re.UNICODE)


@dataclass(frozen=True)
class Issue:
    severity: str  # "BLOCK" | "WARN"
    code: str
    message: str

    def as_dict(self) -> dict:
        return {"severity": self.severity, "code": self.code, "message": self.message}


def normalize_translation(unit: Unit, text: object) -> str:
    """Strip control and direction characters, NFC-normalise, tidy whitespace."""
    if not isinstance(text, str):
        return ""
    cleaned = unicodedata.normalize("NFC", protect.BIDI_CONTROLS.sub("", _CONTROL.sub("", text)))
    cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n")
    if unit.multiline:
        cleaned = "\n".join(re.sub(r"[ \t]+", " ", line).strip() for line in cleaned.split("\n"))
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    else:
        cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def _letters(text: str) -> list[str]:
    return _LETTER.findall(text)


def _is_arabic(ch: str) -> bool:
    cp = ord(ch)
    return 0x0600 <= cp <= 0x06FF or 0x0750 <= cp <= 0x077F or 0xFB50 <= cp <= 0xFDFF or 0xFE70 <= cp <= 0xFEFF


def _paragraphs(text: str) -> int:
    return len([p for p in re.split(r"\n\s*\n", text) if p.strip()])


def check_translation(unit: Unit, text: str, language: str) -> list[Issue]:
    """``text`` should already be normalised. Returns BLOCK and WARN issues."""
    issues: list[Issue] = []
    if not text:
        return [Issue("BLOCK", "EMPTY", "The translation is empty.")]
    if len(text) > unit.max_len:
        issues.append(Issue("BLOCK", "TOO_LONG", f"Too long ({len(text)} characters; the limit is {unit.max_len})."))

    lost = protect.missing_tokens(unit.source, text)
    if lost:
        issues.append(Issue("BLOCK", "PLACEHOLDER_MISSING", "Must keep exactly as written: " + ", ".join(lost) + "."))
    invented = protect.added_tokens(unit.source, text)
    if invented:
        issues.append(Issue("BLOCK", "PLACEHOLDER_ADDED", "Contains something that is not in the source: " + ", ".join(invented) + "."))

    nums = protect.missing_numbers(unit.source, text)
    if nums:
        issues.append(Issue("WARN", "NUMBER_MISSING", "The source mentions " + ", ".join(nums) + " but the translation does not."))

    if unit.multiline and _paragraphs(unit.source) != _paragraphs(text):
        issues.append(Issue("WARN", "STRUCTURE", "The number of paragraphs differs from the source."))

    src_letters = _letters(unit.source)
    if len(src_letters) >= 4 and text.strip().lower() == unit.source.strip().lower():
        issues.append(Issue("WARN", "UNCHANGED", "Identical to the source text. Is it really untranslated?"))

    if unit.source.rstrip().endswith("?") and not text.rstrip().endswith(("?", "؟", "？")):
        issues.append(Issue("WARN", "QUESTION_MARK", "The source is a question but the translation has no question mark."))

    lang = get_language(language)
    letters = _letters(text)
    if lang and len(letters) >= 3:
        arabic_share = sum(1 for ch in letters if _is_arabic(ch)) / len(letters)
        if lang.script == "arabic" and arabic_share < 0.5:
            issues.append(Issue("WARN", "WRONG_SCRIPT", "Arabic was expected but most of the text is not in Arabic script."))
        elif lang.script == "latin" and arabic_share > 0.2:
            issues.append(Issue("WARN", "WRONG_SCRIPT", f"{lang.name} is written in Latin script but the text contains Arabic script."))
    return issues


def has_blocking(issues: Iterable[Issue]) -> bool:
    return any(i.severity == "BLOCK" for i in issues)


def duplicate_choice_issues(items: Iterable[tuple[Unit, str]]) -> dict[UnitId, list[Issue]]:
    """Two choices of one question that end up with the same label cannot be told apart by a respondent."""
    seen: dict[tuple[str, str], list[Unit]] = defaultdict(list)
    for unit, text in items:
        if unit.entity_type == "CHOICE" and text:
            seen[(unit.group, text.casefold())].append(unit)
    out: dict[UnitId, list[Issue]] = {}
    for units in seen.values():
        if len(units) > 1:
            for unit in units:
                out[unit.id] = [Issue("WARN", "DUPLICATE_CHOICE", "Another choice of this question has the same translated label.")]
    return out


def safe_value(unit: Unit, text: object, language: str) -> tuple[Optional[str], list[Issue]]:
    """Normalise then check. Returns (clean text, issues); the text is None when something blocks it."""
    cleaned = normalize_translation(unit, text)
    issues = check_translation(unit, cleaned, language)
    return (None if has_blocking(issues) else cleaned), issues
