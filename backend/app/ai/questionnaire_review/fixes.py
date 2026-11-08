"""Suggested fixes are Phase 3 edit operations. Before one is shown to the person it is replayed on a copy of
the questionnaire; if the engine refuses it, needs confirmation, blocks it, or it changes nothing, it is dropped."""

from __future__ import annotations

from typing import Any

from app.ai.questionnaire_edit.diff import preview_operations
from app.ai.questionnaire_edit.snapshot import Snapshot
from app.ai.questionnaire_review.schemas import Finding

MAX_VERIFIED = 80


def verify_fix(snapshot: Snapshot, op: dict[str, Any]) -> str | None:
    """Return a one-line description of the change if ``op`` is safely applicable, else ``None``."""
    try:
        preview = preview_operations(snapshot, [op])
    except Exception:  # an unusable operation must never break the review
        return None
    if preview.rejected or preview.blocked or preview.requires_confirmation or not preview.has_changes:
        return None
    if len(preview.operations) != 1:
        return None
    # A suggestion may only touch what it is about. Side effects on other questions (for example the engine
    # clearing skip logic that pointed at a deleted question) are never offered as a one-click fix.
    target = op.get("code")
    if target:
        touched = [c for c in (*preview.added, *preview.modified, *preview.deleted) if c.item_type == "question"]
        if any(c.code != target for c in touched):
            return None
    return preview.operations[0].summary


def verify_fixes(snapshot: Snapshot, findings: list[Finding]) -> list[Finding]:
    """Keep each finding; keep its ``fix`` only when it verifies. Verification never mutates the snapshot."""
    checked = 0
    for f in findings:
        if f.fix is None:
            continue
        if checked >= MAX_VERIFIED:
            f.fix = None
            f.fix_summary = None
            continue
        checked += 1
        summary = verify_fix(snapshot, f.fix)
        if summary is None:
            f.fix = None
            f.fix_summary = None
        elif not f.fix_summary:
            f.fix_summary = summary
    return findings
