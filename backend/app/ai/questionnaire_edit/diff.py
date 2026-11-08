"""Original-vs-proposed comparison: what the person sees before pressing Apply."""

from __future__ import annotations

from typing import Any, Optional

from app.ai.questionnaire_edit.engine import EngineResult
from app.ai.questionnaire_edit.schemas import (
    ChangeSummary,
    ChoiceChange,
    EditPreview,
    FieldChange,
    ItemChange,
    OperationView,
    OrderChange,
    RejectedView,
)
from app.ai.questionnaire_edit.snapshot import WorkingState, WQuestion, WSection, to_snapshot_dict

_QUESTION_FIELDS: tuple[tuple[str, str], ...] = (
    ("label", "Question text"),
    ("hint", "Hint"),
    ("type", "Type"),
    ("is_required", "Required"),
    ("section", "Section"),
    ("group", "Group"),
    ("min_value", "Minimum value"),
    ("max_value", "Maximum value"),
    ("min_length", "Minimum length"),
    ("max_length", "Maximum length"),
    ("regex_pattern", "Format rule"),
    ("relevance_expression", "Skip logic"),
    ("calculation_expression", "Calculation"),
    ("default_value", "Default value"),
)


def _question_view(state: WorkingState, q: WQuestion) -> dict[str, Any]:
    f = q.f
    return {
        "code": q.code,
        "label": f.get("label") or "",
        "hint": f.get("hint"),
        "type": f["type"],
        "is_required": bool(f.get("is_required")),
        "section": q.section.title,
        "group": q.group.title if q.group is not None else None,
        "min_value": f.get("min_value"),
        "max_value": f.get("max_value"),
        "min_length": f.get("min_length"),
        "max_length": f.get("max_length"),
        "regex_pattern": f.get("regex_pattern"),
        "relevance_expression": f.get("relevance_expression"),
        "calculation_expression": f.get("calculation_expression"),
        "default_value": f.get("default_value"),
        "choices": [{"value": c.get("value", ""), "label": c.get("label", "")} for c in f.get("choices", [])],
    }


def _section_view(s: WSection) -> dict[str, Any]:
    return {"title": s.title, "description": s.description}


def _norm(value: Any) -> Any:
    return None if value == "" else value


def _choice_changes(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> list[ChoiceChange]:
    b = {c["value"]: c["label"] for c in before}
    a = {c["value"]: c["label"] for c in after}
    changes: list[ChoiceChange] = []
    for value, label in b.items():
        if value not in a:
            changes.append(ChoiceChange(kind="REMOVED", value=value, before_label=label))
        elif a[value] != label:
            changes.append(ChoiceChange(kind="CHANGED", value=value, before_label=label, after_label=a[value]))
    for value, label in a.items():
        if value not in b:
            changes.append(ChoiceChange(kind="ADDED", value=value, after_label=label))
    return changes


def _survivor_order(before: list[Any], after: list[Any]) -> list[tuple[Any, int, int]]:
    """Items present in both lists whose relative order changed: (item, old_position, new_position), 1-based."""
    keep = {x.uid for x in after}
    old_survivors = [x for x in before if x.uid in keep]
    new_survivors = [x for x in after if x.uid in {y.uid for y in before}]
    old_rank = {x.uid: i for i, x in enumerate(old_survivors)}
    out = []
    for i, x in enumerate(new_survivors):
        if old_rank[x.uid] != i:
            old_pos = next(n for n, y in enumerate(before, start=1) if y.uid == x.uid)
            new_pos = next(n for n, y in enumerate(after, start=1) if y.uid == x.uid)
            out.append((x, old_pos, new_pos))
    return out


def build_preview(result: EngineResult) -> EditPreview:
    original, final = result.original, result.final
    summary = ChangeSummary(questions_before=len(original.questions), questions_after=len(final.questions))
    added: list[ItemChange] = []
    modified: list[ItemChange] = []
    deleted: list[ItemChange] = []

    # ---------------------------------------------------------------- questions
    o_by_uid = {q.uid: q for q in original.questions}
    f_by_uid = {q.uid: q for q in final.questions}
    o_pos = {q.uid: i for i, q in enumerate(original.questions, start=1)}
    f_pos = {q.uid: i for i, q in enumerate(final.questions, start=1)}

    for q in final.questions:
        view = _question_view(final, q)
        if q.uid not in o_by_uid:
            added.append(
                ItemChange(
                    item_type="question",
                    change="ADDED",
                    key=q.code,
                    title=view["label"],
                    code=q.code,
                    position_after=f_pos[q.uid],
                    after=view,
                    choices=[ChoiceChange(kind="ADDED", value=c["value"], after_label=c["label"]) for c in view["choices"]],
                )
            )
            continue
        old_view = _question_view(original, o_by_uid[q.uid])
        fields = [
            FieldChange(field=name, label=label, before=old_view[name], after=view[name])
            for name, label in _QUESTION_FIELDS
            if name not in ("section", "group") and _norm(old_view[name]) != _norm(view[name])
        ]
        old_q = o_by_uid[q.uid]
        if old_q.section.uid != q.section.uid:  # compare by identity so renaming a section is not a change to its questions
            fields.append(FieldChange(field="section", label="Section", before=old_view["section"], after=view["section"]))
        if (old_q.group.uid if old_q.group else None) != (q.group.uid if q.group else None):
            fields.append(FieldChange(field="group", label="Group", before=old_view["group"], after=view["group"]))
        choices = _choice_changes(old_view["choices"], view["choices"])
        if fields or choices:
            modified.append(
                ItemChange(
                    item_type="question",
                    change="MODIFIED",
                    key=q.code,
                    title=view["label"] or old_view["label"],
                    code=q.code,
                    position_before=o_pos[q.uid],
                    position_after=f_pos[q.uid],
                    fields=fields,
                    choices=choices,
                    before=old_view,
                    after=view,
                )
            )

    for q in original.questions:
        if q.uid not in f_by_uid:
            view = _question_view(original, q)
            deleted.append(
                ItemChange(
                    item_type="question",
                    change="DELETED",
                    key=q.code or f"#{o_pos[q.uid]}",
                    title=view["label"],
                    code=q.code,
                    position_before=o_pos[q.uid],
                    before=view,
                    choices=[ChoiceChange(kind="REMOVED", value=c["value"], before_label=c["label"]) for c in view["choices"]],
                )
            )

    # ----------------------------------------------------------------- sections
    so_by_uid = {s.uid: s for s in original.sections}
    sf_by_uid = {s.uid: s for s in final.sections}
    alias = {s.uid: f"S{i}" for i, s in enumerate(original.sections, start=1)}
    s_o_pos = {s.uid: i for i, s in enumerate(original.sections, start=1)}
    s_f_pos = {s.uid: i for i, s in enumerate(final.sections, start=1)}

    for s in final.sections:
        if s.uid not in so_by_uid:
            added.append(
                ItemChange(
                    item_type="section",
                    change="ADDED",
                    key=f"new:{s.uid}",
                    title=s.title,
                    position_after=s_f_pos[s.uid],
                    after=_section_view(s),
                )
            )
            continue
        old = so_by_uid[s.uid]
        fields = [
            FieldChange(field=name, label=label, before=getattr(old, name), after=getattr(s, name))
            for name, label in (("title", "Section title"), ("description", "Description"))
            if _norm(getattr(old, name)) != _norm(getattr(s, name))
        ]
        if fields:
            modified.append(
                ItemChange(
                    item_type="section",
                    change="MODIFIED",
                    key=alias[s.uid],
                    title=s.title,
                    position_before=s_o_pos[s.uid],
                    position_after=s_f_pos[s.uid],
                    fields=fields,
                    before=_section_view(old),
                    after=_section_view(s),
                )
            )
    for s in original.sections:
        if s.uid not in sf_by_uid:
            n = len(original.questions_in(s))
            deleted.append(
                ItemChange(
                    item_type="section",
                    change="DELETED",
                    key=alias[s.uid],
                    title=s.title,
                    position_before=s_o_pos[s.uid],
                    before={**_section_view(s), "question_count": n},
                )
            )

    # ------------------------------------------------------------------- order
    order: list[OrderChange] = []
    for q, old_pos, new_pos in _survivor_order(original.questions, final.questions):
        order.append(OrderChange(item_type="question", key=q.code, title=q.f.get("label") or q.code, from_position=old_pos, to_position=new_pos))
        summary.reordered_questions += 1
    for s, old_pos, new_pos in _survivor_order(original.sections, final.sections):
        order.append(OrderChange(item_type="section", key=alias[s.uid], title=s.title, from_position=old_pos, to_position=new_pos))
        summary.reordered_sections += 1

    for change in added:
        if change.item_type == "question":
            summary.added_questions += 1
        else:
            summary.added_sections += 1
    for change in modified:
        if change.item_type == "question":
            summary.modified_questions += 1
        else:
            summary.modified_sections += 1
    for change in deleted:
        if change.item_type == "question":
            summary.deleted_questions += 1
        else:
            summary.deleted_sections += 1

    operations = [
        OperationView(index=a.index, op=a.op.op, summary=a.summary, reason=a.op.reason, raw=a.raw if isinstance(a.raw, dict) else {})
        for a in result.applied
    ]
    rejected = [_rejected_view(r) for r in result.rejected]

    return EditPreview(
        operations=operations,
        rejected=rejected,
        warnings=result.warnings,
        added=added,
        modified=modified,
        deleted=deleted,
        order_changes=order,
        summary=summary,
        has_changes=bool(added or modified or deleted or order),
        blocked=result.blocked,
        requires_confirmation=result.requires_confirmation,
        confirmation_reasons=result.confirmation_reasons,
        result=to_snapshot_dict(final),
    )


def _rejected_view(r) -> RejectedView:
    raw = r.raw if isinstance(r.raw, dict) else None
    name: Optional[str] = raw.get("op") if raw and isinstance(raw.get("op"), str) else None
    return RejectedView(
        index=r.index,
        op=(name or "")[:40],
        summary=_raw_summary(raw),
        reason=r.reason,
        no_change=r.no_change,
        raw=raw,
    )


def _raw_summary(raw: Optional[dict[str, Any]]) -> str:
    if not raw:
        return ""
    op = str(raw.get("op", ""))[:40]
    target = raw.get("code") or raw.get("section_ref") or (raw.get("question") or {}).get("label") or raw.get("title") or ""
    return f"{op} {str(target)[:50]}".strip()


def preview_operations(snapshot, raw_operations: list[Any]) -> EditPreview:
    """Apply ``raw_operations`` to a copy of ``snapshot`` and describe the difference. Saves nothing."""
    from app.ai.questionnaire_edit.engine import run

    return build_preview(run(snapshot, raw_operations))
