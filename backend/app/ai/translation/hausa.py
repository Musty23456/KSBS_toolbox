"""
Special Hausa quality review: deterministic rules + scoring.

The rules are deliberately modest. They catch things that are wrong or suspicious whatever the dialect or
topic (left untranslated, English left inside, wrong script, same word translated two ways, a handful of
very common words normally written with a hooked letter). Judgement about accuracy, naturalness and
register is the optional AI pass in ``service.HausaReviewer``. Neither replaces a native-speaker review:
the report says so, and nothing here ever marks a translation REVIEWED.

The score is computed by code, never by the AI.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Optional

from app.ai.translation import protect
from app.ai.translation.reconcile import UnitState
from app.ai.translation.units import UnitId, normalize_source

CATEGORIES = ("ACCURACY", "FLUENCY", "ORTHOGRAPHY", "REGISTER", "CLARITY", "CONSISTENCY", "TERMINOLOGY", "COMPLETENESS")
SEVERITIES = ("WARNING", "SUGGESTION")

_ENGLISH = frozenset(
    "the and of your you please how many what are is do does have has with this that any other not for on at from "
    "was were will which who when where would should could been".split()
)

# Very common Hausa words that are normally written with a hooked letter. Whole-word, case-insensitive.
_HOOKED = {
    "kudi": "kuɗi",
    "kudin": "kuɗin",
    "kauye": "ƙauye",
    "kauyuka": "ƙauyuka",
    "dalibi": "ɗalibi",
    "daya": "ɗaya",
}
_HOOKED_PHRASES = {"karamar hukuma": "ƙaramar hukuma"}

_ISSUE_MAP = {  # check_translation code -> (severity, category)
    "NUMBER_MISSING": ("SUGGESTION", "ACCURACY"),
    "STRUCTURE": ("SUGGESTION", "ACCURACY"),
    "QUESTION_MARK": ("SUGGESTION", "CLARITY"),
    "WRONG_SCRIPT": ("WARNING", "ORTHOGRAPHY"),
    "DUPLICATE_CHOICE": ("WARNING", "CLARITY"),
}


@dataclass
class Finding:
    entity_type: str
    entity_key: str
    field: str
    label: str
    severity: str
    category: str
    message: str
    suggestion: Optional[str] = None
    source: str = "RULE"  # RULE | AI

    @property
    def unit_id(self) -> UnitId:
        return (self.entity_type, self.entity_key, self.field)

    def as_dict(self) -> dict:
        return {
            "entity_type": self.entity_type, "entity_key": self.entity_key, "field": self.field,
            "label": self.label, "severity": self.severity, "category": self.category,
            "message": self.message, "suggestion": self.suggestion, "source": self.source,
        }


def _finding(st: UnitState, severity: str, category: str, message: str, suggestion: Optional[str] = None) -> Finding:
    u = st.unit
    return Finding(u.entity_type, u.entity_key, u.field, u.label, severity, category, message, suggestion)


def _words(text: str) -> list[str]:
    stripped = text
    for pattern in protect._PROTECTED:  # noqa: SLF001 - same package, same definition of "protected"
        stripped = pattern.sub(" ", stripped)
    return re.findall(r"[^\W\d_]+", stripped.lower())


def _match_case(original: str, replacement: str) -> str:
    return replacement[:1].upper() + replacement[1:] if original[:1].isupper() else replacement


def _apply_hooked(text: str) -> tuple[str, list[tuple[str, str]]]:
    changes: list[tuple[str, str]] = []
    out = text
    for wrong, right in _HOOKED_PHRASES.items():
        def swap_phrase(m: re.Match, right=right) -> str:
            changes.append((m.group(0), _match_case(m.group(0), right)))
            return _match_case(m.group(0), right)
        out = re.sub(rf"(?<![^\W\d_]){re.escape(wrong)}(?![^\W\d_])", swap_phrase, out, flags=re.IGNORECASE)
    for wrong, right in _HOOKED.items():
        def swap(m: re.Match, right=right) -> str:
            changes.append((m.group(0), _match_case(m.group(0), right)))
            return _match_case(m.group(0), right)
        out = re.sub(rf"(?<![^\W\d_]){wrong}(?![^\W\d_])", swap, out, flags=re.IGNORECASE)
    return out, changes


def review_rules(states: list[UnitState]) -> list[Finding]:
    """Rule findings for every translated, up-to-date unit. Outdated and missing units are not reviewed."""
    reviewed = [st for st in states if st.row is not None and st.status != "OUTDATED"]
    findings: list[Finding] = []

    for st in reviewed:
        text, source = st.row["value"], st.unit.source
        letters = len(re.findall(r"[^\W\d_]", source))

        if letters >= 4 and normalize_source(text).casefold() == normalize_source(source).casefold():
            findings.append(_finding(st, "WARNING", "COMPLETENESS", "Left untranslated: identical to the English source."))
        else:
            words = _words(text)
            english = {w for w in words if w in _ENGLISH}
            if len(english) >= 2 or (english and len(words) >= 4 and sum(1 for w in words if w in _ENGLISH) / len(words) >= 0.25):
                findings.append(_finding(st, "WARNING", "FLUENCY", "English words left in the Hausa text: " + ", ".join(sorted(english)) + "."))

        fixed, changes = _apply_hooked(text)
        if changes:
            pairs = "; ".join(f"'{a}' is normally written '{b}'" for a, b in changes[:3])
            findings.append(_finding(st, "SUGGESTION", "ORTHOGRAPHY", pairs + " (hooked letter).", fixed))

        if len(source) >= 25:
            ratio = len(text) / max(1, len(source))
            if ratio > 2.5:
                findings.append(_finding(st, "SUGGESTION", "CLARITY", "Much longer than the source. Check that nothing was added."))
            elif ratio < 0.4:
                findings.append(_finding(st, "SUGGESTION", "ACCURACY", "Much shorter than the source. Check that nothing was left out."))

        for issue in st.issues:
            mapped = _ISSUE_MAP.get(issue.code)
            if mapped:
                findings.append(_finding(st, mapped[0], mapped[1], issue.message))
            elif issue.severity == "BLOCK":
                findings.append(_finding(st, "WARNING", "ACCURACY", issue.message))

    # The same short English text (Yes, Other, None...) should be translated the same way everywhere.
    groups: dict[str, list[UnitState]] = defaultdict(list)
    for st in reviewed:
        if st.unit.entity_type in ("CHOICE", "SYSTEM") and len(st.unit.source) <= 60:
            groups[normalize_source(st.unit.source).casefold()].append(st)
    for members in groups.values():
        counts = Counter(m.row["value"].casefold() for m in members)
        if len(counts) > 1:
            common = counts.most_common(1)[0][0]
            example = next(m.row["value"] for m in members if m.row["value"].casefold() == common)
            for m in members:
                if m.row["value"].casefold() != common:
                    findings.append(_finding(m, "SUGGESTION", "CONSISTENCY",
                                             f"The same English text is translated as '{example}' elsewhere.", example))
    return findings


def score(findings: list[Finding], reviewed_units: int) -> int:
    """
    100 minus a penalty per unit: 6 if it has any warning, 2 if it only has suggestions, scaled by the number
    of units reviewed. Same findings always give the same score. No units reviewed = 0.
    """
    if reviewed_units <= 0:
        return 0
    worst: dict[UnitId, int] = {}
    for f in findings:
        worst[f.unit_id] = max(worst.get(f.unit_id, 0), 6 if f.severity == "WARNING" else 2)
    return max(0, round(100 - 100 * sum(worst.values()) / (6 * reviewed_units)))


def grade_for(value: int) -> str:
    for floor, name in ((90, "Excellent"), (75, "Good"), (60, "Fair"), (40, "Needs improvement")):
        if value >= floor:
            return name
    return "Poor"


def sort_findings(findings: list[Finding]) -> list[Finding]:
    return sorted(findings, key=lambda f: 0 if f.severity == "WARNING" else 1)
