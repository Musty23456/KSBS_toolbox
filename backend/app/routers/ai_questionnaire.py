"""
AI questionnaire generator endpoints (Phase 2).

    GET  /api/ai/questionnaire/availability
    POST /api/ai/questionnaire/generate
    POST /api/ai/questionnaire/regenerate-question
    POST /api/ai/questionnaire/regenerate-section

None of these write a survey. They return validated *previews*; the user edits
them in the Survey Builder and saves through the existing POST /api/surveys.
"""

from __future__ import annotations

import logging
from dataclasses import replace

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.ai.config import get_ai_config
from app.ai.errors import AIRequestTooLargeError
from app.ai.questionnaire.schemas import (
    GeneratedQuestionnairePreview,
    QuestionnaireAvailability,
    QuestionnaireBrief,
    RegeneratedQuestion,
    RegeneratedSection,
    RegenerateQuestionRequest,
    RegenerateSectionRequest,
)
from app.ai.questionnaire.service import QuestionnaireGenerator
from app.ai.rate_limit import ai_limiter
from app.ai.service import AIService
from app.database import get_db
from app.dependencies import get_current_user, require_roles
from app.models.user import RoleName, User
from app.services.audit import log_action

logger = logging.getLogger("app.ai.questionnaire")

router = APIRouter(prefix="/api/ai/questionnaire", tags=["ai-questionnaire"])

# Anyone who may create surveys may use the generator (admins create global
# surveys; everyone else creates personal ones). Rate limits keep cost bounded.
_ALL_ROLES = (RoleName.ADMINISTRATOR, RoleName.SUPERVISOR, RoleName.ENUMERATOR)


async def enforce_generation_size(request: Request) -> None:
    """Questionnaire requests carry more context than Phase 1 calls, so they get a larger cap."""
    limit = get_ai_config().generation_max_request_bytes
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            if int(declared) > limit:
                raise AIRequestTooLargeError()
        except ValueError:
            raise AIRequestTooLargeError() from None
    elif len(await request.body()) > limit:
        raise AIRequestTooLargeError()


def generation_access(bucket: str):
    """Authenticate -> authorise -> size check -> per-user rate limit (same order as Phase 1)."""

    def dependency(
        user: User = Depends(require_roles(*_ALL_ROLES)),
        _size: None = Depends(enforce_generation_size),
    ) -> User:
        ai_limiter.check(f"questionnaire-{bucket}:{user.id}", get_ai_config().rate_limit_per_minute)
        return user

    return dependency


def get_generation_ai_service(db: Session = Depends(get_db)) -> AIService:
    """AIService with the longer generation timeout. Tests override this dependency."""
    cfg = get_ai_config()
    return AIService(config=replace(cfg, timeout_seconds=cfg.generation_timeout_seconds), db=db)


def get_generator(service: AIService = Depends(get_generation_ai_service)) -> QuestionnaireGenerator:
    return QuestionnaireGenerator(service)


def _audit(db: Session, user: User, action: str, **details) -> None:
    """Record that AI was used (counts and language only; never prompts or output)."""
    try:
        log_action(db, user.id, action, "AIQuestionnaire", None, **details)
    except Exception:  # noqa: BLE001 - auditing must never break the user's request
        db.rollback()
        logger.warning("Could not write AI questionnaire audit entry", exc_info=False)


@router.get("/availability", response_model=QuestionnaireAvailability)
def availability(current_user: User = Depends(get_current_user)):
    """Is the generator usable right now? Never calls the provider and costs no quota."""
    cfg = get_ai_config()
    if not cfg.enabled:
        message = "AI features are switched off on this server."
    elif not cfg.has_api_key:
        message = "AI is enabled but not configured on this server."
    else:
        message = "AI questionnaire generation is available."
    return QuestionnaireAvailability(
        available=cfg.is_ready,
        enabled=cfg.enabled,
        configured=cfg.has_api_key,
        max_questions=cfg.generation_max_questions,
        message=message,
    )


@router.post("/generate", response_model=GeneratedQuestionnairePreview)
def generate_questionnaire(
    brief: QuestionnaireBrief,
    db: Session = Depends(get_db),
    current_user: User = Depends(generation_access("generate")),
    generator: QuestionnaireGenerator = Depends(get_generator),
):
    preview = generator.generate(brief, current_user.id)
    _audit(
        db,
        current_user,
        "AI_QUESTIONNAIRE_GENERATED",
        questions=len(preview.questions),
        sections=len(preview.sections),
        language=brief.language,
    )
    return preview


@router.post("/regenerate-question", response_model=RegeneratedQuestion)
def regenerate_question(
    payload: RegenerateQuestionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(generation_access("regen-question")),
    generator: QuestionnaireGenerator = Depends(get_generator),
):
    result = generator.regenerate_question(payload, current_user.id)
    _audit(db, current_user, "AI_QUESTION_REGENERATED", language=payload.brief.language)
    return result


@router.post("/regenerate-section", response_model=RegeneratedSection)
def regenerate_section(
    payload: RegenerateSectionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(generation_access("regen-section")),
    generator: QuestionnaireGenerator = Depends(get_generator),
):
    result = generator.regenerate_section(payload, current_user.id)
    _audit(
        db,
        current_user,
        "AI_SECTION_REGENERATED",
        questions=len(result.questions),
        language=payload.brief.language,
    )
    return result
