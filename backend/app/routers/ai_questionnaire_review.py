"""
AI questionnaire reviewer endpoint (Phase 4).

    POST /api/ai/questionnaire/review    questionnaire (+ objectives) -> quality report

Read-only. The questionnaire travels in the request (what is open in the builder, saved or not); nothing is
read from or written to a survey. Applying a suggestion is done by the web app through the Phase 3
``/edit/preview`` endpoint and the builder's normal apply/undo/save flow.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.ai.config import get_ai_config
from app.ai.questionnaire_review.schemas import ReviewReport, ReviewRequest
from app.ai.questionnaire_review.service import QuestionnaireReviewer
from app.ai.rate_limit import ai_limiter
from app.database import get_db
from app.models.user import User
from app.routers.ai_questionnaire import get_generation_ai_service
from app.routers.ai_questionnaire_edit import edit_access
from app.services.audit import log_action

logger = logging.getLogger("app.ai.questionnaire_review")

router = APIRouter(prefix="/api/ai/questionnaire", tags=["ai-questionnaire-review"])


def review_access(user: User = Depends(edit_access)) -> User:
    ai_limiter.check(f"questionnaire-review:{user.id}", get_ai_config().rate_limit_per_minute)
    return user


def get_reviewer(service=Depends(get_generation_ai_service)) -> QuestionnaireReviewer:
    return QuestionnaireReviewer(service)


@router.post("/review", response_model=ReviewReport)
def review_questionnaire(
    payload: ReviewRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(review_access),
    reviewer: QuestionnaireReviewer = Depends(get_reviewer),
):
    report = reviewer.review(payload, current_user.id)
    try:  # counts only; never questionnaire text, objectives or prompts
        log_action(db, current_user.id, "AI_QUESTIONNAIRE_REVIEWED", "AIQuestionnaireReview", None,
                   score=report.score, critical=report.counts["CRITICAL"], warnings=report.counts["WARNING"],
                   ai_used=report.ai_used)
    except Exception:  # noqa: BLE001
        db.rollback()
        logger.warning("Could not write AI review audit entry", exc_info=False)
    return report
