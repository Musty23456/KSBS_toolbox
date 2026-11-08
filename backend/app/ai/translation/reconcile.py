"""
Stored translations versus the questionnaire as it is NOW.

A stored row is a plain dict: {"entity_type", "entity_key", "field", "value", "source_hash", "status", "source"}.
Per unit this works out one state:

    MISSING    nothing stored for this language
    OUTDATED   the source text changed after it was translated (its stored source_hash no longer matches)
    AI_DRAFT   written by the AI, not yet looked at by a person
    EDITED     written or changed by a person
    REVIEWED   a person marked it as checked

Respondents only ever see MISSING-free, non-outdated, non-blocked text; anything else falls back to the
source text, field by field. So a half-translated questionnaire works, and a source that changed after it was
translated never shows a stale translation by default.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Optional

from app.ai.translation import checks
from app.ai.translation.languages import get_language
from app.ai.translation.units import Unit, UnitId

STATUSES = ("AI_DRAFT", "EDITED", "REVIEWED")


def row_id(row: dict) -> UnitId:
    return (row["entity_type"], row["entity_key"], row["field"])


@dataclass
class UnitState:
    unit: Unit
    row: Optional[dict]
    status: str  # MISSING | OUTDATED | AI_DRAFT | EDITED | REVIEWED
    issues: list[checks.Issue]

    @property
    def value(self) -> Optional[str]:
        return self.row["value"] if self.row else None

    @property
    def usable(self) -> bool:
        """Safe to show a respondent."""
        return self.row is not None and self.status not in ("MISSING", "OUTDATED") and not checks.has_blocking(self.issues)

    def as_dict(self) -> dict:
        u = self.unit
        return {
            "entity_type": u.entity_type, "entity_key": u.entity_key, "field": u.field,
            "label": u.label, "context": u.context, "multiline": u.multiline, "max_len": u.max_len,
            "source": u.source, "value": self.value, "status": self.status,
            "issues": [i.as_dict() for i in self.issues],
        }


def evaluate(units: list[Unit], rows: Iterable[dict], language: str) -> tuple[list[UnitState], list[dict]]:
    """Returns (one state per unit, in questionnaire order; orphaned rows that match no unit any more)."""
    by_id = {row_id(r): r for r in rows}
    states: list[UnitState] = []
    texts: list[tuple[Unit, str]] = []
    for unit in units:
        row = by_id.get(unit.id)
        if row is None:
            states.append(UnitState(unit, None, "MISSING", []))
            continue
        status = "OUTDATED" if row.get("source_hash") != unit.hash else (row.get("status") if row.get("status") in STATUSES else "EDITED")
        issues = checks.check_translation(unit, row["value"], language)
        states.append(UnitState(unit, row, status, issues))
        texts.append((unit, row["value"]))

    dupes = checks.duplicate_choice_issues(texts)
    for st in states:
        extra = dupes.get(st.unit.id)
        if extra:
            st.issues = st.issues + extra

    live = {u.id for u in units}
    orphans = [r for r in by_id.values() if row_id(r) not in live]
    return states, orphans


def summarize(states: list[UnitState], orphans: list[dict]) -> dict:
    total = len(states)
    count = {s: 0 for s in ("MISSING", "OUTDATED", "AI_DRAFT", "EDITED", "REVIEWED")}
    for st in states:
        count[st.status] += 1
    usable = sum(1 for st in states if st.usable)
    return {
        "total": total,
        "translated": total - count["MISSING"],
        "missing": count["MISSING"],
        "outdated": count["OUTDATED"],
        "ai_draft": count["AI_DRAFT"],
        "edited": count["EDITED"],
        "reviewed": count["REVIEWED"],
        "with_issues": sum(1 for st in states if st.row is not None and st.issues),
        "blocked": sum(1 for st in states if checks.has_blocking(st.issues)),
        "orphaned": len(orphans),
        "usable": usable,
        "percent_complete": 0 if total == 0 else int(100 * usable / total),
        "needs_attention": count["MISSING"] + count["OUTDATED"],
    }


def select_for_translation(
    states: list[UnitState],
    *,
    scope: str = "missing_and_outdated",
    only: Optional[set[UnitId]] = None,
    entity_types: Optional[set[str]] = None,
    overwrite_manual: bool = False,
) -> tuple[list[Unit], list[Unit]]:
    """
    Which units the AI should (re)translate. Returns (to_translate, skipped_because_a_person_wrote_them).
    A person's work (EDITED / REVIEWED) is never overwritten unless ``overwrite_manual`` is set.
    """
    wanted = {
        "missing": {"MISSING"},
        "outdated": {"OUTDATED"},
        "missing_and_outdated": {"MISSING", "OUTDATED"},
        "all": {"MISSING", "OUTDATED", "AI_DRAFT", "EDITED", "REVIEWED"},
    }[scope]
    chosen: list[Unit] = []
    protected: list[Unit] = []
    for st in states:
        if only is not None and st.unit.id not in only:
            continue
        if entity_types and st.unit.entity_type not in entity_types:
            continue
        if only is None and st.status not in wanted:
            continue
        if st.status in ("EDITED", "REVIEWED") and not overwrite_manual:
            protected.append(st.unit)
            continue
        chosen.append(st.unit)
    return chosen, protected


def localized_payload(language: str, states: list[UnitState], *, include_outdated: bool = False) -> dict:
    """
    What the respondent screen needs, keyed by the ids of the CURRENT version's rows. Only translated entries
    are present; the screen falls back to the source text for everything else.
    """
    lang = get_language(language)
    out: dict[str, Any] = {
        "language": language, "rtl": bool(lang and lang.rtl), "survey": {}, "sections": {}, "groups": {},
        "questions": {}, "choices": {}, "messages": {},
    }
    usable_count = 0
    for st in states:
        ok = st.usable or (include_outdated and st.status == "OUTDATED" and st.row is not None and not checks.has_blocking(st.issues))
        if not ok:
            continue
        usable_count += 1
        u, value = st.unit, st.row["value"]
        if u.entity_type == "SURVEY":
            out["survey"][u.field] = value
        elif u.entity_type == "SYSTEM":
            out["messages"][u.entity_key] = value
        else:
            bucket = {"SECTION": "sections", "GROUP": "groups", "QUESTION": "questions", "CHOICE": "choices"}[u.entity_type]
            for rid in u.ref_ids:
                if u.entity_type == "CHOICE":
                    out["choices"][rid] = value
                else:
                    out[bucket].setdefault(rid, {})[u.field] = value
    total = len(states)
    out["percent_complete"] = 0 if total == 0 else int(100 * usable_count / total)
    return out


def compare(units: list[Unit], rows_by_language: dict[str, list[dict]]) -> list[dict]:
    """Side by side: the source and each chosen language's text and status for every unit."""
    per_language = {lang: {s.unit.id: s for s in evaluate(units, rows, lang)[0]} for lang, rows in rows_by_language.items()}
    result = []
    for unit in units:
        cells = {}
        for lang, states in per_language.items():
            st = states[unit.id]
            cells[lang] = {"value": st.value, "status": st.status, "issues": [i.as_dict() for i in st.issues]}
        result.append({
            "entity_type": unit.entity_type, "entity_key": unit.entity_key, "field": unit.field,
            "label": unit.label, "source": unit.source, "translations": cells,
        })
    return result
