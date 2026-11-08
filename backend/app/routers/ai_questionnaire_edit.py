"""
AI questionnaire editor endpoints (Phase 3).

    POST /api/ai/questionnaire/edit/propose   command + questionnaire -> AI -> validated preview
    POST /api/ai/questionnaire/edit/preview   operations + questionnaire -> validated preview (no AI)

Neither endpoint reads or writes a survey. The questionnaire travels in the request (it is what is open
in the Survey Builder, saved or not) and the response is only a *preview*. The person applies it to the
builder's draft and saves through the normal PUT /api/surveys/{id}, which creates a new version.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.ai.config import get_ai_config
from app.ai.errors import AIRequestTooLargeError
from app.ai.questionnaire_edit.diff import preview_operations
from app.ai.questionnaire_edit.operations import OperationError
from app.ai.questionnaire_edit.schemas import EditPreview, EditPreviewRequest, EditProposal, EditRequest
from app.ai.questionnaire_edit.service import QuestionnaireEditor
from app.ai.rate_limit import ai_limiter
from app.database import get_db
from app.dependencies import require_roles
from app.models.user import RoleName, User
from app.routers.ai_questionnaire import get_generation_ai_service
from app.services.audit import log_action

logger = logging.getLogger("app.ai.questionnaire_edit")

router = APIRouter(prefix="/api/ai/questionnaire/edit", tags=["ai-questionnaire-edit"])

_ALL_ROLES = (RoleName.ADMINISTRATOR, RoleName.SUPERVISOR, RoleName.ENUMERATOR)


async def enforce_edit_size(request: Request) -> None:
    limit = get_ai_config().edit_max_request_bytes
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            if int(declared) > limit:
                raise AIRequestTooLargeError()
        except ValueError:
            raise AIRequestTooLargeError() from None
    elif len(await request.body()) > limit:
        raise AIRequestTooLargeError()


def edit_access(user: User = Depends(require_roles(*_ALL_ROLES)), _size: None = Depends(enforce_edit_size)) -> User:
    return user


def propose_access(user: User = Depends(edit_access)) -> User:
    ai_limiter.check(f"questionnaire-edit:{user.id}", get_ai_config().rate_limit_per_minute)
    return user


def get_editor(service=Depends(get_generation_ai_service)) -> QuestionnaireEditor:
    return QuestionnaireEditor(service)


def _audit(db: Session, user: User, action: str, **details) -> None:
    """Counts only; never the command, prompts or content."""
    try:
        log_action(db, user.id, action, "AIQuestionnaireEdit", None, **details)
    except Exception:  # noqa: BLE001 - auditing must never break the request
        db.rollback()
        logger.warning("Could not write AI edit audit entry", exc_info=False)


@router.post("/propose", response_model=EditProposal)
def propose_edits(
    payload: EditRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(propose_access),
    editor: QuestionnaireEditor = Depends(get_editor),
):
    proposal = editor.propose(payload, current_user.id)
    _audit(
        db,
        current_user,
        "AI_QUESTIONNAIRE_EDIT_PROPOSED",
        operations=len(proposal.operations),
        rejected=len(proposal.rejected),
        blocked=bool(proposal.blocked),
    )
    return proposal


@router.post("/preview", response_model=EditPreview)
def preview_edits(payload: EditPreviewRequest, current_user: User = Depends(edit_access)):
    """Re-validate a chosen set of operations. Works even when AI is switched off: it never calls a model."""
    try:
        return preview_operations(payload.snapshot, payload.operations)
    except OperationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
