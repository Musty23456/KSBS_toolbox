"""
A questionnaire as a list of translatable units, each with a STABLE key.

Every save of a survey creates a new version with brand-new row ids, so a translation cannot be tied to a
row id. The keys used instead survive saves:

    SURVEY    "survey"                            title, description
    SECTION   "t:<hash of the source title>"      title, description   (sections have no code)
    GROUP     "t:<hash of the source title>"      title, description
    QUESTION  the question code                   label, hint
    CHOICE    "<question code>::<choice value>"   label
    SYSTEM    "msg.required", "ui.submit", ...    text

Sections and groups are keyed by a hash of their title, so adding or reordering sections never moves a
translation onto the wrong section. Renaming a section makes it a new, untranslated section (which is the
honest answer: the text it was translated from no longer exists).

Only human-readable text becomes a unit. Question codes, choice values, question types, expressions,
regular expressions and every other internal identifier are never units: they cannot be sent to the model
and cannot be changed by a translation. Each unit also remembers a hash of the source text it was
translated from, which is how an edited source is detected (the translation becomes "outdated").
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from app.ai.translation.catalog import SYSTEM_MESSAGES, describe

ENTITY_TYPES = ("SURVEY", "SECTION", "GROUP", "QUESTION", "CHOICE", "SYSTEM")
FIELDS = {
    "SURVEY": ("title", "description"),
    "SECTION": ("title", "description"),
    "GROUP": ("title", "description"),
    "QUESTION": ("label", "hint"),
    "CHOICE": ("label",),
    "SYSTEM": ("text",),
}

# Longest text a translation may have, per kind of text (the first two mirror the database columns).
_TITLE_MAX = 255
_CHOICE_MAX = 500
_LONG_MAX = 8000
_QUESTION_MAX = 2000

UnitId = tuple[str, str, str]  # (entity_type, entity_key, field)


def normalize_source(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text or "")).strip()


def source_hash(text: str) -> str:
    return hashlib.sha1(normalize_source(text).encode("utf-8")).hexdigest()[:16]


def title_key(title: str) -> str:
    return "t:" + source_hash(title)[:12]


def choice_key(question_code: str, value: str) -> str:
    return f"{question_code}::{value}"


@dataclass
class Unit:
    entity_type: str
    entity_key: str
    field: str
    source: str
    label: str  # where it lives, for people: "Question age"
    context: str = ""  # extra help for the translator (a choice's question, say)
    multiline: bool = False
    max_len: int = _LONG_MAX
    ref_ids: list[str] = field(default_factory=list)  # ids of the rows in the CURRENT version this applies to
    group: str = ""  # the question a choice belongs to (for the duplicate-label check)

    @property
    def id(self) -> UnitId:
        return (self.entity_type, self.entity_key, self.field)

    @property
    def hash(self) -> str:
        return source_hash(self.source)


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _get(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _order(items: Iterable[Any]) -> list[Any]:
    return sorted(items, key=lambda i: (_get(i, "order_index", 0) or 0))


def build_units(survey: dict, *, include_system: bool = True) -> list[Unit]:
    """
    ``survey``: {"id", "title", "description", "sections": [...], "groups": [...], "questions": [...]}
    where each question has "code", "label", "hint" and "choices": [{"id", "value", "label"}].
    Items may be dicts or objects. Duplicate keys (two sections with the same title, say) become ONE unit
    that applies to all of them.
    """
    units: dict[UnitId, Unit] = {}

    def add(unit: Unit, ref_id: Optional[str]) -> None:
        if not unit.source:
            return
        existing = units.get(unit.id)
        if existing is None:
            units[unit.id] = unit
            existing = unit
        if ref_id and ref_id not in existing.ref_ids:
            existing.ref_ids.append(ref_id)

    sid = _get(survey, "id")
    add(Unit("SURVEY", "survey", "title", _text(_get(survey, "title")), "Survey title", max_len=_TITLE_MAX), sid)
    add(
        Unit("SURVEY", "survey", "description", _text(_get(survey, "description")), "Survey description and instructions",
             multiline=True),
        sid,
    )

    for kind, items in (("SECTION", _get(survey, "sections", []) or []), ("GROUP", _get(survey, "groups", []) or [])):
        word = kind.capitalize()
        for item in _order(items):
            title = _text(_get(item, "title"))
            if not title:
                continue
            key, rid = title_key(title), _get(item, "id")
            add(Unit(kind, key, "title", title, f"{word}: {title}", max_len=_TITLE_MAX), rid)
            add(
                Unit(kind, key, "description", _text(_get(item, "description")), f"{word} description: {title}",
                     context=title, multiline=True),
                rid,
            )

    for q in _order(_get(survey, "questions", []) or []):
        code, label = _text(_get(q, "code")), _text(_get(q, "label"))
        if not code:
            continue
        qid = _get(q, "id")
        add(Unit("QUESTION", code, "label", label, f"Question {code}", multiline=True, max_len=_QUESTION_MAX), qid)
        add(
            Unit("QUESTION", code, "hint", _text(_get(q, "hint")), f"Hint for {code}", context=label, multiline=True,
                 max_len=_QUESTION_MAX),
            qid,
        )
        for c in _order(_get(q, "choices", []) or []):
            value = _text(_get(c, "value"))
            if not value:
                continue
            add(
                Unit("CHOICE", choice_key(code, value), "label", _text(_get(c, "label")),
                     f"Choice {code}: {value}", context=label, max_len=_CHOICE_MAX, group=code),
                _get(c, "id"),
            )

    if include_system:
        for key, english in SYSTEM_MESSAGES.items():
            add(Unit("SYSTEM", key, "text", english, describe(key), max_len=_TITLE_MAX), None)

    return list(units.values())


def is_valid_target(entity_type: str, field_name: str) -> bool:
    return field_name in FIELDS.get(entity_type, ())
