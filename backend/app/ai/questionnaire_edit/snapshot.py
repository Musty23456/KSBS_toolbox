"""
The questionnaire as the Survey Builder holds it, and the engine's in-memory working copy of it.

Input (``Snapshot``) mirrors the builder's own state: sections, groups and questions, linked with
``section_id`` / ``group_id``. Saved items carry real ids; unsaved ones are referred to as
``local-<index>`` (their position in the list), exactly as the builder and ``POST /api/surveys`` do.

Because ``local-<index>`` references silently re-point whenever sections are inserted, removed or
reordered, the engine never edits those strings. It links questions to *section objects*, edits the
objects, and writes the ``section_id`` / ``group_id`` strings out once at the end from the final order.
"""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.ai.questionnaire.normalize import VALID_TYPES

MAX_SNAPSHOT_QUESTIONS = 1000
MAX_SNAPSHOT_SECTIONS = 100
MAX_SNAPSHOT_GROUPS = 300
MAX_SNAPSHOT_CHOICES = 500

_LOCAL_REF = re.compile(r"^local-(\d+)$")


# --------------------------------------------------------------------------
# Input / output shape (pass-through: unknown keys are kept, never dropped)
# --------------------------------------------------------------------------


class SnapshotChoice(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: Optional[str] = None
    value: str = Field(default="", max_length=1000)
    label: str = Field(default="", max_length=2000)
    order_index: int = 0
    cascade_parent_value: Optional[str] = None


class SnapshotQuestion(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: Optional[str] = None
    code: str = Field(default="", max_length=200)
    label: str = Field(default="")
    hint: Optional[str] = None
    type: str
    order_index: int = 0
    is_required: bool = False
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    min_length: Optional[int] = None
    max_length: Optional[int] = None
    regex_pattern: Optional[str] = None
    relevance_expression: Optional[str] = None
    calculation_expression: Optional[str] = None
    default_value: Optional[str] = None
    cascade_parent_question_id: Optional[str] = None
    choices: list[SnapshotChoice] = Field(default_factory=list, max_length=MAX_SNAPSHOT_CHOICES)
    section_id: Optional[str] = None
    group_id: Optional[str] = None

    @field_validator("type")
    @classmethod
    def _known_type(cls, v: str) -> str:
        if v not in VALID_TYPES:
            raise ValueError(f"unknown question type '{v[:30]}'")
        return v


class SnapshotSection(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: Optional[str] = None
    title: str = Field(default="", max_length=1000)
    description: Optional[str] = None
    order_index: int = 0


class SnapshotGroup(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: Optional[str] = None
    title: str = Field(default="", max_length=1000)
    description: Optional[str] = None
    order_index: int = 0
    section_id: Optional[str] = None
    repeatable: bool = False
    min_repeats: int = 1
    max_repeats: Optional[int] = None


class Snapshot(BaseModel):
    """The editable part of a questionnaire: its sections, groups and questions."""

    model_config = ConfigDict(extra="ignore")

    sections: list[SnapshotSection] = Field(default_factory=list, max_length=MAX_SNAPSHOT_SECTIONS)
    groups: list[SnapshotGroup] = Field(default_factory=list, max_length=MAX_SNAPSHOT_GROUPS)
    questions: list[SnapshotQuestion] = Field(default_factory=list, max_length=MAX_SNAPSHOT_QUESTIONS)


# --------------------------------------------------------------------------
# Working copy
# --------------------------------------------------------------------------

# Question keys the engine reads and writes. Anything else on a question is carried through untouched.
_QUESTION_KEYS = (
    "id",
    "code",
    "label",
    "hint",
    "type",
    "is_required",
    "min_value",
    "max_value",
    "min_length",
    "max_length",
    "regex_pattern",
    "relevance_expression",
    "calculation_expression",
    "default_value",
    "cascade_parent_question_id",
)


@dataclass
class WSection:
    uid: int
    id: Optional[str]
    title: str
    description: Optional[str]
    extra: dict[str, Any] = field(default_factory=dict)
    temp_ref: Optional[str] = None  # only for sections added in the current batch


@dataclass
class WGroup:
    uid: int
    id: Optional[str]
    title: str
    description: Optional[str]
    section: WSection
    repeatable: bool
    min_repeats: int
    max_repeats: Optional[int]
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class WQuestion:
    uid: int
    f: dict[str, Any]  # question fields; ``f["choices"]`` is a list of choice dicts
    section: WSection
    group: Optional[WGroup]
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def code(self) -> str:
        return self.f.get("code") or ""

    @property
    def type(self) -> str:
        return self.f["type"]


@dataclass
class WorkingState:
    sections: list[WSection]
    groups: list[WGroup]
    questions: list[WQuestion]
    # True when the question list is already ordered by section (the builder's usual shape). The
    # engine then keeps it that way; if the person has deliberately interleaved sections it leaves
    # the list order alone.
    sorted_by_section: bool = True
    next_uid: int = 1
    # How many items pointed at a section / group that does not exist (treated as "first section" / "none").
    dangling_refs: int = 0

    # ------------------------------------------------------------------ helpers

    def new_uid(self) -> int:
        self.next_uid += 1
        return self.next_uid

    def clone(self) -> "WorkingState":
        return copy.deepcopy(self)

    def section_index(self, section: WSection) -> int:
        for i, s in enumerate(self.sections):
            if s is section:
                return i
        raise ValueError("section is not part of this questionnaire")

    def question_index(self, q: WQuestion) -> int:
        for i, x in enumerate(self.questions):
            if x is q:
                return i
        raise ValueError("question is not part of this questionnaire")

    def resort_by_section(self) -> None:
        """Stable-sort questions by section order (only when the list was section-ordered to begin with)."""
        if not self.sorted_by_section:
            return
        order = {s.uid: i for i, s in enumerate(self.sections)}
        self.questions.sort(key=lambda q: order[q.section.uid])  # list.sort is stable

    def questions_in(self, section: WSection) -> list[WQuestion]:
        return [q for q in self.questions if q.section is section]

    def fingerprint(self) -> str:
        """Cheap content hash used to tell whether an operation changed anything."""
        return json.dumps(to_snapshot_dict(self), sort_keys=True, default=str)

    # ---------------------------------------------------------------- ingestion

    @classmethod
    def from_snapshot(cls, snap: Snapshot) -> "WorkingState":
        uid = 0

        def nxt() -> int:
            nonlocal uid
            uid += 1
            return uid

        raw_sections = snap.sections or [SnapshotSection(title="Section 1", description="", order_index=1)]
        sections = [
            WSection(
                uid=nxt(),
                id=s.id,
                title=s.title,
                description=s.description,
                extra=_extras(s, {"id", "title", "description", "order_index"}),
            )
            for s in raw_sections
        ]
        dangling = 0

        def resolve_section(ref: Optional[str]) -> WSection:
            nonlocal dangling
            if not ref:
                return sections[0]  # "no section" means the first section, as in the builder
            found = _lookup_ref(ref, sections)
            if found is None:
                dangling += 1
                return sections[0]
            return found

        groups = [
            WGroup(
                uid=nxt(),
                id=g.id,
                title=g.title,
                description=g.description,
                section=resolve_section(g.section_id),
                repeatable=g.repeatable,
                min_repeats=g.min_repeats,
                max_repeats=g.max_repeats,
                extra=_extras(g, {"id", "title", "description", "order_index", "section_id", "repeatable", "min_repeats", "max_repeats"}),
            )
            for g in snap.groups
        ]

        questions: list[WQuestion] = []
        for q in snap.questions:
            group: Optional[WGroup] = None
            if q.group_id:
                group = _lookup_ref(q.group_id, groups)
                if group is None:
                    dangling += 1
            fields = {k: getattr(q, k) for k in _QUESTION_KEYS}
            fields["code"] = (fields["code"] or "").strip()
            fields["choices"] = [
                {
                    "id": c.id,
                    "value": c.value,
                    "label": c.label,
                    "order_index": c.order_index,
                    "cascade_parent_value": c.cascade_parent_value,
                    **_extras(c, {"id", "value", "label", "order_index", "cascade_parent_value"}),
                }
                for c in q.choices
            ]
            questions.append(
                WQuestion(
                    uid=nxt(),
                    f=fields,
                    section=resolve_section(q.section_id),
                    group=group,
                    extra=_extras(q, set(_QUESTION_KEYS) | {"choices", "section_id", "group_id", "order_index"}),
                )
            )

        state = cls(sections=sections, groups=groups, questions=questions, next_uid=uid, dangling_refs=dangling)
        order = {s.uid: i for i, s in enumerate(sections)}
        ranks = [order[q.section.uid] for q in questions]
        state.sorted_by_section = all(a <= b for a, b in zip(ranks, ranks[1:]))
        return state


def _extras(model: BaseModel, known: set[str]) -> dict[str, Any]:
    return {k: v for k, v in (model.model_extra or {}).items() if k not in known}


def _lookup_ref(ref: str, items: list) -> Any:
    """Find a section/group by real id, or by ``local-<index>`` (position in the original list)."""
    for item in items:
        if item.id and item.id == ref:
            return item
    m = _LOCAL_REF.match(ref)
    if m:
        i = int(m.group(1))
        if 0 <= i < len(items):
            return items[i]
    return None


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------


def section_ref(state: WorkingState, section: WSection) -> str:
    return section.id or f"local-{state.section_index(section)}"


def group_ref(state: WorkingState, group: WGroup) -> str:
    for i, g in enumerate(state.groups):
        if g is group:
            return group.id or f"local-{i}"
    raise ValueError("group is not part of this questionnaire")


def to_snapshot_dict(state: WorkingState) -> dict[str, Any]:
    """The final questionnaire in the builder's shape. Order indexes are resequenced 1..n."""
    sections: list[dict[str, Any]] = []
    for i, s in enumerate(state.sections):
        item: dict[str, Any] = {**s.extra, "title": s.title, "description": s.description, "order_index": i + 1}
        if s.id:
            item["id"] = s.id
        sections.append(item)

    groups: list[dict[str, Any]] = []
    for i, g in enumerate(state.groups):
        item = {
            **g.extra,
            "title": g.title,
            "description": g.description,
            "order_index": i + 1,
            "section_id": section_ref(state, g.section),
            "repeatable": g.repeatable,
            "min_repeats": g.min_repeats,
            "max_repeats": g.max_repeats,
        }
        if g.id:
            item["id"] = g.id
        groups.append(item)

    questions: list[dict[str, Any]] = []
    for i, q in enumerate(state.questions):
        item = {**q.extra, **{k: v for k, v in q.f.items() if k not in ("choices", "id")}}
        if q.f.get("id"):
            item["id"] = q.f["id"]
        item["order_index"] = i + 1
        item["section_id"] = section_ref(state, q.section)
        item["group_id"] = group_ref(state, q.group) if q.group is not None else None
        item["choices"] = [_choice_out(c, j) for j, c in enumerate(q.f.get("choices", []))]
        questions.append(item)

    return {"sections": sections, "groups": groups, "questions": questions}


def _choice_out(c: dict[str, Any], index: int) -> dict[str, Any]:
    item = {k: v for k, v in c.items() if k != "id"}
    item["order_index"] = index + 1
    if c.get("id"):
        item["id"] = c["id"]
    return item
