"""
The structured editing engine.

    run(snapshot, raw_operations) -> EngineResult

* Works on an in-memory copy. The input snapshot is never modified and nothing is saved.
* Each operation is checked *before* it changes anything; an invalid one is rejected with a reason
  and the rest carry on.
* After all operations are applied, the whole result is validated. Problems that the operations
  *introduced* (not ones the questionnaire already had) get the responsible operations rejected,
  and the batch is replayed without them - so the result is always valid.
* Guards stop an edit from wiping a questionnaire, and ask for explicit confirmation for large
  deletions.
* Nothing is silent: every side effect (choices dropped because a type changed, skip logic cleared
  because its question was deleted, ...) is reported as a warning and shows in the preview diff.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from app.ai.questionnaire.normalize import (
    CHOICE_TYPES,
    MAX_HINT_LEN,
    MAX_LABEL_LEN,
    NUMERIC_TYPES,
    TEXT_TYPES,
    YES_NO_VALUES,
    QuestionInfo,
    check_expression,
    clean_text,
    is_safe_regex,
    normalize_type,
    slugify_choice_value,
    slugify_code,
    unique_code,
)
from app.ai.questionnaire_edit.operations import (
    MAX_OPERATIONS,
    AddQuestion,
    AddSection,
    DeleteQuestion,
    DeleteSection,
    Operation,
    OperationError,
    ReorderQuestions,
    UpdateChoices,
    UpdateQuestion,
    UpdateSection,
    UpdateValidation,
    describe,
    parse_operation,
)
from app.ai.questionnaire_edit.snapshot import (
    Snapshot,
    WGroup,
    WorkingState,
    WQuestion,
    WSection,
)

MAX_TOTAL_QUESTIONS = 500
MAX_TOTAL_SECTIONS = 100
MAX_ROUNDS = 8

# A deletion needs an explicit extra confirmation once it removes this much.
CONFIRM_MIN_DELETED = 3
CONFIRM_FRACTION = 0.3
CONFIRM_ALWAYS_AT = 10

# Column limits of the database (strings are String(n) there).
DB_CODE_MAX = 100
DB_CHOICE_VALUE_MAX = 255
DB_CHOICE_LABEL_MAX = 500
DB_REGEX_MAX = 500
DB_DEFAULT_MAX = 500

_VALUE_OK = re.compile(r"^[A-Za-z0-9_.\-]+$")
_KEYWORDS = {"and", "or", "not", "in", "true", "false", "none", "null", "True", "False", "None", "contains"}


# --------------------------------------------------------------------------
# Result types
# --------------------------------------------------------------------------


@dataclass
class AppliedOp:
    index: int
    op: Operation
    raw: dict[str, Any]
    summary: str
    targets: set[str] = field(default_factory=set)


@dataclass
class RejectedOp:
    index: int
    raw: Any
    reason: str
    no_change: bool = False  # valid, but the questionnaire already looked like this


@dataclass
class EngineResult:
    original: WorkingState
    final: WorkingState
    applied: list[AppliedOp]
    rejected: list[RejectedOp]
    warnings: list[str]
    blocked: Optional[str] = None
    confirmation_reasons: list[str] = field(default_factory=list)

    @property
    def requires_confirmation(self) -> bool:
        return bool(self.confirmation_reasons)


@dataclass(frozen=True)
class Issue:
    rule: str
    target: str  # "q:<code>" | "s:<uid>"
    message: str
    causes: frozenset[str]

    @property
    def key(self) -> tuple[str, str]:
        return (self.rule, self.target)


class _Ctx:
    """Per-replay bookkeeping."""

    def __init__(self, refs: dict[str, int]):
        self.refs = refs  # original section aliases / ids / local refs -> section uid
        self.aliases: dict[str, str] = {}  # code the model asked for -> code actually assigned


Effect = tuple[set[str], list[str]]  # (targets touched, warnings)


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------


def _q_target(code: str) -> str:
    return f"q:{code}"


def _s_target(section: WSection) -> str:
    return f"s:{section.uid}"


def referenced_names(expression: Optional[str]) -> list[str]:
    """Question codes an expression refers to (string literals ignored)."""
    if not expression:
        return []
    stripped = re.sub(r"'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"", " ", expression)
    names = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", stripped)
    return list(dict.fromkeys(n for n in names if n not in _KEYWORDS))


def _checked_text(value: Optional[str], max_len: int, what: str) -> Optional[str]:
    """Clean text; refuse (rather than silently cut) anything over the limit."""
    cleaned = clean_text(value, max_len * 2 + 1)
    if cleaned is not None and len(cleaned) > max_len:
        raise OperationError(f"The {what} is too long (limit {max_len} characters).")
    return cleaned


def build_ref_map(state: WorkingState) -> dict[str, int]:
    refs: dict[str, int] = {}
    for i, s in enumerate(state.sections):
        refs[f"S{i + 1}"] = s.uid
        refs[f"local-{i}"] = s.uid
        if s.id:
            refs[s.id] = s.uid
    return refs


def _find_question(state: WorkingState, code: str, ctx: _Ctx) -> WQuestion:
    code = (code or "").strip()
    code = ctx.aliases.get(code, code)
    found = [q for q in state.questions if q.code == code]
    if not found:
        raise OperationError(f"There is no question with the code '{code[:60]}'.")
    if len(found) > 1:
        raise OperationError(f"The code '{code[:60]}' is used by more than one question, so it cannot be targeted.")
    return found[0]


def _find_section(state: WorkingState, ref: Optional[str], ctx: _Ctx) -> WSection:
    ref = (ref or "").strip()
    if not ref:
        raise OperationError("A section reference is missing.")
    for s in state.sections:
        if s.temp_ref and s.temp_ref == ref:
            return s
    key = ref.upper() if re.fullmatch(r"[sS]\d+", ref) else ref
    uid = ctx.refs.get(key)
    if uid is None:
        raise OperationError(f"There is no section '{ref[:40]}'.")
    for s in state.sections:
        if s.uid == uid:
            return s
    raise OperationError(f"Section '{ref[:40]}' was already removed earlier in this change.")


def _end_of_section_index(state: WorkingState, section: WSection) -> int:
    """List position where a new question for ``section`` should be inserted (after its last question)."""
    last = -1
    for i, q in enumerate(state.questions):
        if q.section is section:
            last = i
    if last >= 0:
        return last + 1
    # Empty section: go after the last question of any earlier section.
    order = {s.uid: i for i, s in enumerate(state.sections)}
    target = order[section.uid]
    pos = 0
    for i, q in enumerate(state.questions):
        if order[q.section.uid] <= target:
            pos = i + 1
    return pos


def _adapt_to_type(f: dict[str, Any], new_type: str, warnings: list[str]) -> None:
    """Remove settings that make no sense for ``new_type`` and say so."""
    label = (f.get("label") or f.get("code") or "question")[:50]
    if new_type not in CHOICE_TYPES and f.get("choices"):
        warnings.append(f"“{label}”: its {len(f['choices'])} answer option(s) were removed because the type is now {new_type}.")
        f["choices"] = []
    if new_type not in NUMERIC_TYPES and (f.get("min_value") is not None or f.get("max_value") is not None):
        warnings.append(f"“{label}”: the minimum/maximum value rule was removed because the type is now {new_type}.")
        f["min_value"] = f["max_value"] = None
    if new_type not in TEXT_TYPES and any(f.get(k) is not None for k in ("min_length", "max_length", "regex_pattern")):
        warnings.append(f"“{label}”: the length/format rules were removed because the type is now {new_type}.")
        f["min_length"] = f["max_length"] = f["regex_pattern"] = None


def _derive_choice_value(label: str, taken: set[str]) -> str:
    base = slugify_choice_value(label) or "OPTION"
    value, n = base, 2
    while value in taken:
        value = f"{base}_{n}"[:DB_CHOICE_VALUE_MAX]
        n += 1
    return value


def _choice_value(spec_value: Optional[str], label: str, taken: set[str]) -> str:
    raw = clean_text(spec_value, DB_CHOICE_VALUE_MAX) if spec_value else None
    if raw and _VALUE_OK.match(raw):
        value, n = raw, 2
        while value in taken:
            value = f"{raw}_{n}"[:DB_CHOICE_VALUE_MAX]
            n += 1
        return value
    return _derive_choice_value(raw or label, taken)


def _build_new_choices(specs: list, start_taken: Optional[set[str]] = None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    taken = set(start_taken or ())
    for spec in specs:
        label = _checked_text(spec.label or spec.value, DB_CHOICE_LABEL_MAX, "answer option")
        if not label:
            raise OperationError("Every answer option needs a label.")
        value = _choice_value(spec.value, label, taken)
        taken.add(value)
        out.append({"id": None, "value": value, "label": label, "order_index": 0, "cascade_parent_value": None})
    return out


def _reindex(choices: list[dict[str, Any]]) -> None:
    for i, c in enumerate(choices):
        c["order_index"] = i + 1


def _move_to_section(state: WorkingState, q: WQuestion, target: WSection, warnings: list[str]) -> None:
    if q.group is not None and q.group.section is not target:
        warnings.append(f"“{(q.f['label'] or q.code)[:50]}” left its group “{q.group.title}” because it moved to another section.")
        q.group = None
    q.section = target


# --------------------------------------------------------------------------
# Removal (shared by DELETE_QUESTION and DELETE_SECTION)
# --------------------------------------------------------------------------


def _check_removable(state: WorkingState, doomed: list[WQuestion]) -> None:
    gone = {q.uid for q in doomed}
    ids = {q.f["id"]: q for q in doomed if q.f.get("id")}
    codes = {q.code: q for q in doomed if q.code}
    for other in state.questions:
        if other.uid in gone:
            continue
        parent = other.f.get("cascade_parent_question_id")
        if parent and parent in ids:
            raise OperationError(
                f"“{codes_label(ids[parent])}” cannot be deleted: the answer options of “{codes_label(other)}” depend on it."
            )
        for name in referenced_names(other.f.get("calculation_expression")):
            if name in codes:
                raise OperationError(
                    f"“{codes_label(codes[name])}” cannot be deleted: it is used in a calculation in “{codes_label(other)}”."
                )


def codes_label(q: WQuestion) -> str:
    return q.code or (q.f.get("label") or "question")[:40]


def _remove_questions(state: WorkingState, doomed: list[WQuestion], warnings: list[str]) -> set[str]:
    """Delete questions. Skip logic elsewhere that pointed at them is cleared and reported."""
    gone = {q.uid for q in doomed}
    codes = {q.code for q in doomed if q.code}
    targets: set[str] = set()
    for other in state.questions:
        if other.uid in gone:
            continue
        expr = other.f.get("relevance_expression")
        if expr and codes.intersection(referenced_names(expr)):
            other.f["relevance_expression"] = None
            targets.add(_q_target(other.code))
            warnings.append(
                f"Skip logic on “{codes_label(other)}” was cleared because it depended on a deleted question, "
                "so that question will now always be shown."
            )
    state.questions = [q for q in state.questions if q.uid not in gone]
    for q in doomed:
        targets.add(_q_target(q.code) if q.code else f"q:#{q.uid}")
    return targets


# --------------------------------------------------------------------------
# Operation appliers. Each validates first, then changes the working copy.
# --------------------------------------------------------------------------


def _apply_add_question(state: WorkingState, op: AddQuestion, ctx: _Ctx) -> Effect:
    warnings: list[str] = []
    nq = op.question
    if len(state.questions) >= MAX_TOTAL_QUESTIONS:
        raise OperationError(f"A questionnaire cannot have more than {MAX_TOTAL_QUESTIONS} questions.")
    label = _checked_text(nq.label, MAX_LABEL_LEN, "question text")
    if not label:
        raise OperationError("A new question needs question text.")
    qtype = normalize_type(nq.type)
    if qtype is None:
        raise OperationError(f"'{str(nq.type)[:30]}' is not a supported question type.")

    after: Optional[WQuestion] = _find_question(state, op.after_code, ctx) if op.after_code else None
    if op.section_ref:
        section = _find_section(state, op.section_ref, ctx)
        if after is not None and after.section is not section:
            raise OperationError("'after_code' is in a different section than 'section_ref'.")
    elif after is not None:
        section = after.section
    else:
        section = state.sections[-1]

    choices: list[dict[str, Any]] = []
    if qtype in CHOICE_TYPES:
        choices = _build_new_choices(nq.choices)
    elif nq.choices:
        if qtype == "YES_NO":
            warnings.append(f"“{label[:50]}”: answer options were ignored because Yes/No questions have fixed answers.")
        else:
            raise OperationError(f"{qtype} questions cannot have answer options.")

    requested = (nq.code or "").strip()
    base = slugify_code(requested) or slugify_code(label[:40]) or "question"
    taken = {q.code for q in state.questions if q.code}
    code = unique_code(base, taken)
    if requested and code != requested:
        warnings.append(f"The code “{requested}” was changed to “{code}” (codes must be unique, lowercase letters, digits and underscores).")
    if requested and requested not in taken:
        # Only when the asked-for code was free. If it collided with an existing question, later
        # operations that use that code keep meaning the EXISTING question (never the other way round).
        ctx.aliases[requested] = code

    f: dict[str, Any] = {
        "id": None,
        "code": code,
        "label": label,
        "hint": _checked_text(nq.hint, MAX_HINT_LEN, "hint"),
        "type": qtype,
        "is_required": bool(nq.is_required),
        "min_value": nq.min_value,
        "max_value": nq.max_value,
        "min_length": nq.min_length,
        "max_length": nq.max_length,
        "regex_pattern": nq.regex_pattern.strip() if nq.regex_pattern and nq.regex_pattern.strip() else None,
        "relevance_expression": nq.relevance_expression.strip() if nq.relevance_expression and nq.relevance_expression.strip() else None,
        "calculation_expression": None,
        "default_value": nq.default_value.strip() if nq.default_value and nq.default_value.strip() else None,
        "cascade_parent_question_id": None,
        "choices": choices,
    }
    _reindex(choices)
    _adapt_to_type(f, qtype, warnings)

    index = state.question_index(after) + 1 if after is not None else _end_of_section_index(state, section)
    state.questions.insert(index, WQuestion(uid=state.new_uid(), f=f, section=section, group=None))
    return {_q_target(code), _s_target(section)}, warnings


def _apply_update_question(state: WorkingState, op: UpdateQuestion, ctx: _Ctx) -> Effect:
    warnings: list[str] = []
    q = _find_question(state, op.code, ctx)
    ch = op.changes
    sent = ch.model_fields_set
    updates: dict[str, Any] = {}

    if "label" in sent:
        label = _checked_text(ch.label, MAX_LABEL_LEN, "question text")
        if not label:
            raise OperationError("A question's text cannot be empty.")
        updates["label"] = label
    if "hint" in sent:
        updates["hint"] = _checked_text(ch.hint, MAX_HINT_LEN, "hint")
    if "is_required" in sent:
        if ch.is_required is None:
            raise OperationError("'is_required' must be true or false.")
        updates["is_required"] = ch.is_required
    if "default_value" in sent:
        updates["default_value"] = _checked_text(ch.default_value, DB_DEFAULT_MAX, "default value")
    if "relevance_expression" in sent:
        expr = (ch.relevance_expression or "").strip()
        updates["relevance_expression"] = expr or None
    new_type: Optional[str] = None
    if "type" in sent:
        new_type = normalize_type(ch.type)
        if new_type is None:
            raise OperationError(f"'{str(ch.type)[:30]}' is not a supported question type.")
    target_section: Optional[WSection] = _find_section(state, ch.section_ref, ctx) if "section_ref" in sent else None

    targets = {_q_target(q.code)}
    if updates:
        q.f.update(updates)
    if new_type is not None and new_type != q.type:
        if q.f.get("id"):
            warnings.append(
                f"“{codes_label(q)}” is already saved: changing its type to {new_type} may not match answers that were already collected."
            )
        q.f["type"] = new_type
        _adapt_to_type(q.f, new_type, warnings)
    if target_section is not None and target_section is not q.section:
        _move_to_section(state, q, target_section, warnings)
        if state.sorted_by_section:
            # Keep the form reading top to bottom: put it at the end of its new section.
            state.questions.remove(q)
            state.questions.insert(_end_of_section_index(state, target_section), q)
        targets.add(_s_target(target_section))
    return targets, warnings


def _apply_delete_question(state: WorkingState, op: DeleteQuestion, ctx: _Ctx) -> Effect:
    warnings: list[str] = []
    q = _find_question(state, op.code, ctx)
    _check_removable(state, [q])
    targets = _remove_questions(state, [q], warnings)
    return targets, warnings


def _apply_add_section(state: WorkingState, op: AddSection, ctx: _Ctx) -> Effect:
    if len(state.sections) >= MAX_TOTAL_SECTIONS:
        raise OperationError(f"A questionnaire cannot have more than {MAX_TOTAL_SECTIONS} sections.")
    title = _checked_text(op.title, 255, "section title")
    if not title:
        raise OperationError("A new section needs a title.")
    if op.temp_ref:
        ref = op.temp_ref.strip()
        if ref in ctx.refs or re.fullmatch(r"[sS]\d+", ref) or any(s.temp_ref == ref for s in state.sections):
            raise OperationError(f"The temporary reference '{ref[:40]}' is already in use.")
    description = _checked_text(op.description, 4000, "section description")
    section = WSection(uid=state.new_uid(), id=None, title=title, description=description, temp_ref=(op.temp_ref or "").strip() or None)
    position = min(op.position or len(state.sections) + 1, len(state.sections) + 1)
    state.sections.insert(position - 1, section)
    return {_s_target(section)}, []


def _apply_update_section(state: WorkingState, op: UpdateSection, ctx: _Ctx) -> Effect:
    warnings: list[str] = []
    section = _find_section(state, op.section_ref, ctx)
    ch = op.changes
    sent = ch.model_fields_set
    new_title: Optional[str] = None
    if "title" in sent:
        new_title = _checked_text(ch.title, 255, "section title")
        if not new_title:
            raise OperationError("A section's title cannot be empty.")
    new_description = _checked_text(ch.description, 4000, "section description") if "description" in sent else None

    targets = {_s_target(section)}
    if new_title is not None:
        section.title = new_title
    if "description" in sent:
        section.description = new_description
    if "position" in sent and ch.position is not None:
        before = {s.uid: i for i, s in enumerate(state.sections)}
        state.sections.remove(section)
        state.sections.insert(min(ch.position, len(state.sections) + 1) - 1, section)
        after = {s.uid: i for i, s in enumerate(state.sections)}
        for s in state.sections:
            if before[s.uid] != after[s.uid]:
                targets.add(_s_target(s))
                targets.update(_q_target(q.code) for q in state.questions_in(s) if q.code)
        if before[section.uid] != after[section.uid]:
            state.resort_by_section()
    return targets, warnings


def _apply_delete_section(state: WorkingState, op: DeleteSection, ctx: _Ctx) -> Effect:
    warnings: list[str] = []
    section = _find_section(state, op.section_ref, ctx)
    if len(state.sections) <= 1:
        raise OperationError("The questionnaire needs at least one section, so the last one cannot be deleted.")
    inside = state.questions_in(section)
    targets = {_s_target(section)}

    if op.questions == "DELETE":
        if op.move_to_section_ref:
            raise OperationError("'move_to_section_ref' cannot be combined with questions = DELETE.")
        _check_removable(state, inside)
        if inside:
            warnings.append(f"Section “{section.title}” and its {len(inside)} question(s) will be deleted.")
        targets |= _remove_questions(state, inside, warnings)
        gone_groups = {g.uid for g in state.groups if g.section is section}
        state.groups = [g for g in state.groups if g.uid not in gone_groups]
        for q in state.questions:  # defensive: a question elsewhere must never point at a deleted group
            if q.group is not None and q.group.uid in gone_groups:
                q.group = None
        state.sections.remove(section)
        return targets, warnings

    if op.move_to_section_ref:
        destination = _find_section(state, op.move_to_section_ref, ctx)
        if destination is section:
            raise OperationError("A section cannot be moved into itself.")
    else:
        # Default: the neighbouring section (the one before it, or after it when it is first).
        i = state.section_index(section)
        destination = state.sections[i - 1] if i > 0 else state.sections[1]
    for q in inside:
        q.section = destination
        if q.code:
            targets.add(_q_target(q.code))
    for g in state.groups:
        if g.section is section:
            g.section = destination
    if inside:
        warnings.append(f"The {len(inside)} question(s) of section “{section.title}” were moved to “{destination.title}”.")
    state.sections.remove(section)
    targets.add(_s_target(destination))
    state.resort_by_section()
    return targets, warnings


def _apply_reorder_questions(state: WorkingState, op: ReorderQuestions, ctx: _Ctx) -> Effect:
    warnings: list[str] = []
    codes = [c.strip() for c in op.ordered_codes]
    resolved = [ctx.aliases.get(c, c) for c in codes]
    if len(set(resolved)) != len(resolved):
        raise OperationError("'ordered_codes' lists the same question more than once.")
    questions = [_find_question(state, c, ctx) for c in resolved]
    target = _find_section(state, op.section_ref, ctx) if op.section_ref else None
    if target is None and state.sorted_by_section and len({q.section.uid for q in questions}) > 1:
        raise OperationError(
            "These questions are in different sections. Say which section they should be placed in (section_ref) to reorder or move them."
        )

    slots = sorted(state.question_index(q) for q in questions)
    for slot, q in zip(slots, questions):
        state.questions[slot] = q
    targets = {_q_target(q.code) for q in questions}
    if target is not None:
        for q in questions:
            if q.section is not target:
                _move_to_section(state, q, target, warnings)
        targets.add(_s_target(target))
        state.resort_by_section()
    return targets, warnings


def _apply_update_choices(state: WorkingState, op: UpdateChoices, ctx: _Ctx) -> Effect:
    warnings: list[str] = []
    q = _find_question(state, op.code, ctx)
    if q.type not in CHOICE_TYPES:
        raise OperationError(
            f"“{codes_label(q)}” is a {q.type} question and has no answer options. Change its type to a choice type first."
        )
    existing: list[dict[str, Any]] = q.f["choices"]
    by_value = {c["value"]: c for c in existing}
    label_name = codes_label(q)

    if op.mode == "REPLACE":
        new_choices: list[dict[str, Any]] = []
        taken: set[str] = set()
        for spec in op.choices:
            label = _checked_text(spec.label, DB_CHOICE_LABEL_MAX, "answer option")
            match = by_value.get(spec.value) if spec.value else None
            if match is not None and match["value"] not in taken:
                keep = dict(match)
                keep["label"] = label or match["label"]
                taken.add(keep["value"])
                new_choices.append(keep)
                continue
            label = label or _checked_text(spec.value, DB_CHOICE_LABEL_MAX, "answer option")
            if not label:
                raise OperationError("Every answer option needs a label.")
            value = _choice_value(spec.value, label, taken)
            taken.add(value)
            new_choices.append({"id": None, "value": value, "label": label, "order_index": 0, "cascade_parent_value": None})
        dropped = [c["value"] for c in existing if c["value"] not in taken]
        if dropped:
            warnings.append(
                f"“{label_name}”: {len(dropped)} answer option(s) removed ({', '.join(dropped[:8])}{'…' if len(dropped) > 8 else ''}). "
                "Answers already collected with these values are not changed."
            )
        _reindex(new_choices)
        q.f["choices"] = new_choices
    elif op.mode == "ADD":
        added = _build_new_choices(op.choices, start_taken=set(by_value))
        for spec in op.choices:
            if spec.value and spec.value in by_value:
                raise OperationError(f"The option '{spec.value[:40]}' already exists. Use UPDATE_LABELS to change its text.")
        if len(existing) + len(added) > 200:
            raise OperationError("A question cannot have more than 200 answer options.")
        q.f["choices"] = [*existing, *added]
        _reindex(q.f["choices"])
    elif op.mode == "REMOVE":
        missing = [v for v in op.remove_values if v not in by_value]
        if missing:
            raise OperationError(f"“{label_name}” has no answer option '{missing[0][:40]}'.")
        gone = set(op.remove_values)
        q.f["choices"] = [c for c in existing if c["value"] not in gone]
        _reindex(q.f["choices"])
        warnings.append(
            f"“{label_name}”: {len(gone)} answer option(s) removed. Answers already collected with these values are not changed."
        )
    else:  # UPDATE_LABELS
        new_labels: dict[str, str] = {}
        for spec in op.choices:
            if not spec.value or spec.value not in by_value:
                raise OperationError(f"“{label_name}” has no answer option '{(spec.value or '')[:40]}'.")
            label = _checked_text(spec.label, DB_CHOICE_LABEL_MAX, "answer option")
            if not label:
                raise OperationError("UPDATE_LABELS needs a label for every option.")
            new_labels[spec.value] = label
        q.f["choices"] = [{**c, "label": new_labels.get(c["value"], c["label"])} for c in existing]
    return {_q_target(q.code)}, warnings


def _apply_update_validation(state: WorkingState, op: UpdateValidation, ctx: _Ctx) -> Effect:
    q = _find_question(state, op.code, ctx)
    v = op.validation
    sent = v.model_fields_set
    t = q.type
    if sent & {"min_value", "max_value"} and t not in NUMERIC_TYPES:
        raise OperationError(f"Minimum / maximum value only apply to number questions, but “{codes_label(q)}” is {t}.")
    if sent & {"min_length", "max_length", "regex_pattern"} and t not in TEXT_TYPES:
        raise OperationError(f"Length and format rules only apply to text questions, but “{codes_label(q)}” is {t}.")
    updates: dict[str, Any] = {}
    for key in ("is_required", "min_value", "max_value", "min_length", "max_length"):
        if key in sent:
            updates[key] = getattr(v, key)
    if "regex_pattern" in sent:
        pattern = (v.regex_pattern or "").strip()
        updates["regex_pattern"] = pattern or None
    if t == "INTEGER":
        for key in ("min_value", "max_value"):
            if updates.get(key) is not None and float(updates[key]) != int(updates[key]):
                raise OperationError("Whole-number questions need whole-number limits.")
    q.f.update(updates)
    return {_q_target(q.code)}, []


_APPLY: dict[type, Callable[[WorkingState, Any, _Ctx], Effect]] = {
    AddQuestion: _apply_add_question,
    UpdateQuestion: _apply_update_question,
    DeleteQuestion: _apply_delete_question,
    AddSection: _apply_add_section,
    UpdateSection: _apply_update_section,
    DeleteSection: _apply_delete_section,
    ReorderQuestions: _apply_reorder_questions,
    UpdateChoices: _apply_update_choices,
    UpdateValidation: _apply_update_validation,
}


# --------------------------------------------------------------------------
# Validation of a whole questionnaire
# --------------------------------------------------------------------------


def validate_state(state: WorkingState) -> list[Issue]:
    issues: list[Issue] = []
    counts = Counter(q.code for q in state.questions if q.code)
    known: dict[str, QuestionInfo] = {}

    for q in state.questions:
        f = q.f
        code = q.code
        tgt = _q_target(code) if code else f"q:#{q.uid}"
        me = frozenset({tgt})
        name = codes_label(q)
        qtype = f["type"]

        def add(rule: str, message: str, causes: frozenset[str] = me) -> None:
            issues.append(Issue(rule, tgt, message, causes))

        if code and counts[code] > 1:
            add("code_duplicate", f"The code “{code}” is used by more than one question.")
        if len(code) > DB_CODE_MAX:
            add("code_too_long", f"The code of “{name}” is too long.")
        if not (f.get("label") or "").strip():
            add("label_empty", f"“{name}” has no question text.")

        choices = f.get("choices") or []
        if qtype in CHOICE_TYPES:
            if len(choices) < 2:
                add("choices_required", f"“{name}” is a {qtype} question and needs at least two answer options.")
        elif choices:
            add("choices_not_allowed", f"“{name}” is a {qtype} question and cannot have answer options.")
        seen: set[str] = set()
        for c in choices:
            value, label = c.get("value") or "", c.get("label") or ""
            if not value.strip() or not label.strip():
                add("choice_blank", f"“{name}” has an answer option with no value or no text.")
            elif value in seen:
                add("choice_duplicate", f"“{name}” has two answer options with the value '{value[:40]}'.")
            elif len(value) > DB_CHOICE_VALUE_MAX or len(label) > DB_CHOICE_LABEL_MAX:
                add("choice_too_long", f"An answer option of “{name}” is too long.")
            seen.add(value)

        if qtype not in NUMERIC_TYPES and (f.get("min_value") is not None or f.get("max_value") is not None):
            add("rule_not_applicable", f"“{name}” has a minimum/maximum value but is not a number question.")
        if qtype not in TEXT_TYPES and any(f.get(k) is not None for k in ("min_length", "max_length", "regex_pattern")):
            add("rule_not_applicable", f"“{name}” has length/format rules but is not a text question.")
        lo, hi = f.get("min_value"), f.get("max_value")
        if lo is not None and hi is not None and lo > hi:
            add("range_invalid", f"“{name}”: the minimum value is above the maximum.")
        lo, hi = f.get("min_length"), f.get("max_length")
        if lo is not None and hi is not None and lo > hi:
            add("range_invalid", f"“{name}”: the minimum length is above the maximum.")
        if (f.get("min_length") is not None and f["min_length"] < 0) or (f.get("max_length") is not None and f["max_length"] < 0):
            add("range_invalid", f"“{name}”: lengths cannot be negative.")
        pattern = f.get("regex_pattern")
        if pattern:
            ok, why = is_safe_regex(pattern)
            if not ok:
                add("regex_invalid", f"“{name}”: the format rule is not usable ({why}).")
            elif len(pattern) > DB_REGEX_MAX:
                add("regex_invalid", f"“{name}”: the format rule is too long.")
        if f.get("default_value") and len(f["default_value"]) > DB_DEFAULT_MAX:
            add("default_too_long", f"“{name}”: the default value is too long.")

        expr = f.get("relevance_expression")
        if expr and expr.strip():
            _normalised, reason = check_expression(expr, known=known, self_code=code or None)
            if reason:
                causes = me | {_q_target(n) for n in referenced_names(expr)}
                add("expression", f"Skip logic on “{name}” would stop working: {reason}.", frozenset(causes))

        if code:
            values = YES_NO_VALUES if qtype == "YES_NO" else frozenset(c.get("value") or "" for c in choices)
            known[code] = QuestionInfo(code=code, type=qtype, values=frozenset(values))

    for s in state.sections:
        if not (s.title or "").strip():
            issues.append(Issue("section_title_empty", _s_target(s), "A section has no title.", frozenset({_s_target(s)})))
    return issues


# --------------------------------------------------------------------------
# Running a batch
# --------------------------------------------------------------------------


def run(snapshot: Snapshot, raw_operations: list[Any]) -> EngineResult:
    if not isinstance(raw_operations, list):
        raise OperationError("'operations' must be a list.")
    if len(raw_operations) > MAX_OPERATIONS:
        raise OperationError(f"Too many operations in one change (limit {MAX_OPERATIONS}).")

    original = WorkingState.from_snapshot(snapshot)
    baseline = {i.key for i in validate_state(original)}
    refs = build_ref_map(original)

    parsed: dict[int, Operation] = {}
    rejected: dict[int, RejectedOp] = {}
    for i, raw in enumerate(raw_operations):
        try:
            parsed[i] = parse_operation(raw)
        except OperationError as exc:
            rejected[i] = RejectedOp(i, raw, str(exc))

    final = original
    applied: list[AppliedOp] = []
    warnings: list[str] = []
    settled = False
    for _round in range(MAX_ROUNDS):
        state = original.clone()
        ctx = _Ctx(refs)
        applied, warnings = [], []
        for i, op in parsed.items():
            if i in rejected:
                continue
            raw = raw_operations[i]
            before = state.fingerprint()
            try:
                targets, op_warnings = _APPLY[type(op)](state, op, ctx)
            except OperationError as exc:
                rejected[i] = RejectedOp(i, raw, str(exc))
                continue
            if state.fingerprint() == before:
                rejected[i] = RejectedOp(i, raw, "No change: the questionnaire already looks like this.", no_change=True)
                continue
            applied.append(AppliedOp(index=i, op=op, raw=raw, summary=describe(op), targets=targets))
            warnings.extend(w for w in op_warnings if w not in warnings)

        new_issues = [iss for iss in validate_state(state) if iss.key not in baseline]
        if not new_issues:
            final, settled = state, True
            break
        culprits: dict[int, str] = {}
        for iss in new_issues:
            # Blame the operations that touched the affected question itself; only if none did,
            # widen to the questions its skip logic depends on.
            own = [a for a in applied if iss.target in a.targets]
            for a in own or [a for a in applied if a.targets & iss.causes]:
                culprits.setdefault(a.index, iss.message)
        if not culprits:
            return _blocked(original, raw_operations, rejected, parsed, "These changes would leave the questionnaire invalid: " + new_issues[0].message)
        for idx, message in culprits.items():
            rejected[idx] = RejectedOp(idx, raw_operations[idx], f"Not applied: {message}")

    if not settled:  # pragma: no cover - cannot happen with MAX_ROUNDS > number of distinct culprits in practice
        return _blocked(original, raw_operations, rejected, parsed, "The changes could not be validated.")

    result = EngineResult(
        original=original,
        final=final,
        applied=applied,
        rejected=sorted(rejected.values(), key=lambda r: r.index),
        warnings=warnings,
    )
    if original.dangling_refs:
        result.warnings.append(
            f"{original.dangling_refs} item(s) pointed at a section or group that no longer exists and were treated as belonging to "
            "the first section / no group."
        )
    return _apply_guards(result)


def _blocked(
    original: WorkingState,
    raw_operations: list[Any],
    rejected: dict[int, RejectedOp],
    parsed: dict[int, Operation],
    message: str,
) -> EngineResult:
    for i, raw in enumerate(raw_operations):
        if i not in rejected:
            rejected[i] = RejectedOp(i, raw, f"Not applied: {message}")
    return EngineResult(
        original=original,
        final=original.clone(),
        applied=[],
        rejected=sorted(rejected.values(), key=lambda r: r.index),
        warnings=[],
        blocked=message,
    )


def _apply_guards(result: EngineResult) -> EngineResult:
    original, final = result.original, result.final
    kept = {q.uid for q in final.questions}
    deleted = [q for q in original.questions if q.uid not in kept]
    total = len(original.questions)

    if total > 0 and len(final.questions) == 0:
        message = (
            "These changes would delete every question in the questionnaire, so nothing was changed. "
            "To remove a questionnaire, archive it from the survey list instead."
        )
        for a in result.applied:
            result.rejected.append(RejectedOp(a.index, a.raw, f"Not applied: {message}"))
        result.rejected.sort(key=lambda r: r.index)
        result.applied = []
        result.final = original.clone()
        result.blocked = message
        result.warnings = []
        return result
    if total > 0 and len(final.sections) == 0:  # pragma: no cover - DELETE_SECTION refuses to remove the last one
        result.blocked = "A questionnaire needs at least one section."
        return result

    n = len(deleted)
    if n >= CONFIRM_ALWAYS_AT or (n >= CONFIRM_MIN_DELETED and total and n / total >= CONFIRM_FRACTION):
        result.confirmation_reasons.append(f"This change deletes {n} of the {total} questions.")
    lost_sections = [s for s in original.sections if s.uid not in {x.uid for x in final.sections}]
    if len(lost_sections) >= 2 and len(lost_sections) * 2 >= len(original.sections):
        result.confirmation_reasons.append(f"This change deletes {len(lost_sections)} of the {len(original.sections)} sections.")
    return result
