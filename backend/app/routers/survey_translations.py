"""
Multilingual questionnaire translation endpoints (Phase 5).

    GET    /api/surveys/{id}/i18n/overview            every language: how complete, what is missing / outdated
    GET    /api/surveys/{id}/i18n/available           languages a respondent can pick (any survey viewer)
    GET    /api/surveys/{id}/i18n/compare?languages=  source and several languages side by side
    GET    /api/surveys/{id}/i18n/{lang}              every translatable text with its translation and status
    GET    /api/surveys/{id}/i18n/{lang}/localized    what the respondent screen shows (any survey viewer)
    PUT    /api/surveys/{id}/i18n/{lang}/units        manual edits / mark reviewed (all-or-nothing)
    POST   /api/surveys/{id}/i18n/{lang}/translate    AI translation of all, or part, of the questionnaire
    DELETE /api/surveys/{id}/i18n/{lang}              remove one language version
    POST   /api/surveys/{id}/i18n/ha/review           special Hausa quality review (read-only)
    POST   /api/surveys/{id}/i18n/import-legacy       copy translations from the older per-row-id table

Translations never change the questionnaire: question codes, choice values, rules and logic are not translation
units. Reading or writing translations does not create a survey version and does not affect submissions, which
store choice VALUES, not the labels a respondent saw.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.ai.config import get_ai_config
from app.ai.rate_limit import ai_limiter
from app.ai.translation import checks, reconcile
from app.ai.translation.languages import LANGUAGES, as_dict, get_language
from app.ai.translation.schemas import HausaReviewRequest, SaveUnitsRequest, TranslateRequest
from app.ai.translation.service import HausaReviewer, TranslationService
from app.ai.translation.units import Unit, UnitId, build_units
from app.database import get_db
from app.dependencies import get_current_user
from app.models.questionnaire_translation import QuestionnaireTranslation
from app.models.translation import Translation
from app.models.user import User
from app.routers.ai_questionnaire import get_generation_ai_service
from app.routers.ai_questionnaire_edit import edit_access
from app.routers.surveys import _current_version, _load_survey_or_404
from app.services.audit import log_action
from app.services.survey_access import can_edit, can_view

logger = logging.getLogger("app.ai.translation")

router = APIRouter(prefix="/api/surveys", tags=["survey-translations"])


# ---------------------------------------------------------------- helpers


def _language(code: str):
    lang = get_language(code)
    if lang is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unsupported language")
    return lang


def _survey_for(db: Session, survey_id: str, user: User, *, editing: bool):
    survey = _load_survey_or_404(db, survey_id)
    if not can_view(user, survey):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Survey not found")  # do not reveal private ids
    if editing and not can_edit(user, survey):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not have permission to edit this survey's translations")
    return survey


def _units(survey) -> list[Unit]:
    version = _current_version(survey)
    return build_units({
        "id": survey.id,
        "title": survey.title,
        "description": survey.description,
        "sections": version.sections if version else [],
        "groups": version.groups if version else [],
        "questions": version.questions if version else [],
    })


def _orm_rows(db: Session, survey_id: str, language: Optional[str] = None) -> list[QuestionnaireTranslation]:
    query = db.query(QuestionnaireTranslation).filter(QuestionnaireTranslation.survey_id == survey_id)
    if language:
        query = query.filter(QuestionnaireTranslation.language_code == language)
    return query.all()


def _as_dict(row: QuestionnaireTranslation) -> dict:
    return {
        "entity_type": row.entity_type, "entity_key": row.entity_key, "field": row.field, "value": row.value,
        "source_hash": row.source_hash, "status": row.status,
    }


def _state(db: Session, survey, language: str):
    units = _units(survey)
    rows = _orm_rows(db, survey.id, language)
    states, orphans = reconcile.evaluate(units, [_as_dict(r) for r in rows], language)
    return units, rows, states, orphans


def _audit(db: Session, user: User, action: str, survey_id: str, **details) -> None:
    """Counts and codes only; never questionnaire text or translations."""
    try:
        log_action(db, user.id, action, "Survey", survey_id, **details)
    except Exception:  # noqa: BLE001 - auditing must never break the request
        db.rollback()
        logger.warning("Could not write translation audit entry", exc_info=False)


def _upsert(db: Session, survey_id: str, language: str, existing: dict, unit: Unit, value: str, row_status: str, user: User) -> None:
    row = existing.get(unit.id)
    if row is None:
        row = QuestionnaireTranslation(
            survey_id=survey_id, language_code=language, entity_type=unit.entity_type, entity_key=unit.entity_key,
            field=unit.field, value=value, source_hash=unit.hash, status=row_status, updated_by_id=user.id,
        )
        db.add(row)
        existing[unit.id] = row
    else:
        row.value, row.source_hash, row.status, row.updated_by_id = value, unit.hash, row_status, user.id


def ai_access(bucket: str):
    """Same checks as the other AI endpoints (auth, role, size) plus a per-user rate limit with its own bucket."""

    def dependency(user: User = Depends(edit_access)) -> User:
        ai_limiter.check(f"questionnaire-{bucket}:{user.id}", get_ai_config().rate_limit_per_minute)
        return user

    return dependency


translate_access = ai_access("translate")
hausa_review_access = ai_access("hausa-review")


# ---------------------------------------------------------------- reading


@router.get("/{survey_id}/i18n/overview")
def overview(survey_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    survey = _survey_for(db, survey_id, user, editing=True)
    units = _units(survey)
    version = _current_version(survey)
    by_language: dict[str, list[dict]] = {}
    for row in _orm_rows(db, survey_id):
        by_language.setdefault(row.language_code, []).append(_as_dict(row))
    languages = []
    for lang in LANGUAGES:
        states, orphans = reconcile.evaluate(units, by_language.get(lang.code, []), lang.code)
        languages.append({**as_dict(lang), **reconcile.summarize(states, orphans)})
    return {"survey_id": survey.id, "version_number": version.version_number if version else None,
            "total_units": len(units), "languages": languages}


@router.get("/{survey_id}/i18n/available")
def available(survey_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """The languages (besides the original) a respondent can switch to: those with at least one usable text."""
    survey = _survey_for(db, survey_id, user, editing=False)
    units = _units(survey)
    by_language: dict[str, list[dict]] = {}
    for row in _orm_rows(db, survey_id):
        by_language.setdefault(row.language_code, []).append(_as_dict(row))
    out = []
    for lang in LANGUAGES:
        if lang.code not in by_language:
            continue
        payload = reconcile.localized_payload(lang.code, reconcile.evaluate(units, by_language[lang.code], lang.code)[0])
        if payload["percent_complete"] > 0:
            out.append({**as_dict(lang), "percent_complete": payload["percent_complete"]})
    return out


@router.get("/{survey_id}/i18n/compare")
def compare_languages(
    survey_id: str,
    languages: str = Query(..., description="Comma separated language codes, e.g. ha,fr"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    survey = _survey_for(db, survey_id, user, editing=True)
    codes = list(dict.fromkeys(c.strip().lower() for c in languages.split(",") if c.strip()))
    if not codes or len(codes) > 4 or any(get_language(c) is None for c in codes):
        raise HTTPException(status_code=422, detail="Choose between one and four supported languages.")
    units = _units(survey)
    rows = {c: [_as_dict(r) for r in _orm_rows(db, survey_id, c)] for c in codes}
    return {"languages": [as_dict(get_language(c)) for c in codes], "rows": reconcile.compare(units, rows)}


@router.get("/{survey_id}/i18n/{language}")
def language_units(survey_id: str, language: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    lang = _language(language)
    survey = _survey_for(db, survey_id, user, editing=True)
    _units_list, _rows, states, orphans = _state(db, survey, lang.code)
    return {"language": as_dict(lang), "summary": reconcile.summarize(states, orphans), "units": [s.as_dict() for s in states]}


@router.get("/{survey_id}/i18n/{language}/localized")
def localized(
    survey_id: str, language: str, include_outdated: bool = False,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    """Keyed by the ids of the survey's current rows, so the respondent screen can overlay it. Missing items are
    simply absent: the screen shows the original text for them."""
    lang = _language(language)
    survey = _survey_for(db, survey_id, user, editing=False)
    _u, _r, states, _o = _state(db, survey, lang.code)
    return reconcile.localized_payload(lang.code, states, include_outdated=include_outdated)


# ---------------------------------------------------------------- writing


@router.put("/{survey_id}/i18n/{language}/units")
def save_units(
    survey_id: str, language: str, payload: SaveUnitsRequest,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    """Manual edits. All-or-nothing: if any text would break the questionnaire (lost placeholder, too long, empty
    where a value is required) nothing is saved and every problem is listed."""
    lang = _language(language)
    survey = _survey_for(db, survey_id, user, editing=True)
    units = {u.id: u for u in _units(survey)}
    existing = {(r.entity_type, r.entity_key, r.field): r for r in _orm_rows(db, survey_id, lang.code)}

    problems: list[dict] = []
    todo: dict[UnitId, tuple[Unit, Optional[str], str]] = {}
    for item in payload.units:
        uid = (item.entity_type, item.entity_key, item.field)
        unit = units.get(uid)
        if unit is None:
            problems.append({"question": f"{item.entity_type} {item.entity_key}", "message": "This text is not part of the current questionnaire."})
            continue
        if item.value is None:  # status only
            if uid not in existing:
                problems.append({"question": unit.label, "message": "There is no translation to mark yet."})
            else:
                todo[uid] = (unit, None, item.status)
            continue
        cleaned = checks.normalize_translation(unit, item.value)
        if not cleaned:
            todo[uid] = (unit, "", item.status)  # an empty text removes the translation
            continue
        issues = checks.check_translation(unit, cleaned, lang.code)
        blocking = [i.message for i in issues if i.severity == "BLOCK"]
        if blocking:
            problems.append({"question": unit.label, "message": " ".join(blocking)})
        else:
            todo[uid] = (unit, cleaned, item.status)
    if problems:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=problems)

    saved = removed = 0
    for uid, (unit, value, row_status) in todo.items():
        if value == "":
            row = existing.pop(uid, None)
            if row is not None:
                db.delete(row)
                removed += 1
        elif value is None:
            # A person confirms the text as it stands, so it now counts as matching the CURRENT source wording.
            row = existing[uid]
            row.status, row.source_hash, row.updated_by_id = row_status, unit.hash, user.id
            saved += 1
        else:
            _upsert(db, survey_id, lang.code, existing, unit, value, row_status, user)
            saved += 1
    db.commit()
    _audit(db, user, "TRANSLATION_EDITED", survey_id, language=lang.code, saved=saved, removed=removed)

    _u, _r, states, orphans = _state(db, survey, lang.code)
    changed = {uid for uid in todo}
    return {"saved": saved, "removed": removed, "summary": reconcile.summarize(states, orphans),
            "units": [s.as_dict() for s in states if s.unit.id in changed]}


@router.post("/{survey_id}/i18n/{language}/translate")
def translate(
    survey_id: str, language: str, payload: TranslateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(translate_access),
    ai=Depends(get_generation_ai_service),
):
    """
    Translate the units the request selects (default: everything missing or outdated), at most ``max_units`` per
    call. Only text that passes the safety checks is saved, as AI_DRAFT. A person's own edits are never overwritten
    unless ``overwrite_manual`` is true. Call again while ``remaining`` > 0 and ``translated`` > 0.
    """
    lang = _language(language)
    survey = _survey_for(db, survey_id, user, editing=True)
    units, rows, states, _orphans = _state(db, survey, lang.code)
    only = {(r.entity_type, r.entity_key, r.field) for r in payload.units} if payload.units is not None else None
    selected, protected = reconcile.select_for_translation(
        states, scope=payload.scope, only=only,
        entity_types=set(payload.entity_types) if payload.entity_types else None,
        overwrite_manual=payload.overwrite_manual,
    )
    chunk = selected[: payload.max_units]

    result = None
    accepted = 0
    if chunk:
        result = TranslationService(ai).translate(lang.code, chunk, survey_title=survey.title, user_id=user.id)
        existing = {(r.entity_type, r.entity_key, r.field): r for r in rows}
        by_id = {u.id: u for u in chunk}
        for uid, (text, _warnings) in result.accepted.items():
            _upsert(db, survey_id, lang.code, existing, by_id[uid], text, "AI_DRAFT", user)
            accepted += 1
        db.commit()
        _audit(db, user, "AI_TRANSLATION_RUN", survey_id, language=lang.code, selected=len(chunk), translated=accepted,
               rejected=len(result.rejected), not_returned=len(result.not_returned), ai_error=bool(result.ai_error))

    _u, _r, new_states, orphans = _state(db, survey, lang.code)
    return {
        "language": as_dict(lang),
        "selected": len(selected),
        "attempted": len(chunk),
        "translated": accepted,
        "remaining": len(selected) - accepted,
        "protected_skipped": len(protected),
        "rejected": [{"label": u.label, "reason": issues[0].message} for u, issues in (result.rejected if result else [])],
        "not_returned": len(result.not_returned) if result else 0,
        "ai_error": result.ai_error if result else None,
        "model": result.model if result else "",
        "summary": reconcile.summarize(new_states, orphans),
    }


@router.delete("/{survey_id}/i18n/{language}", status_code=status.HTTP_204_NO_CONTENT)
def delete_language(survey_id: str, language: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    lang = _language(language)
    _survey_for(db, survey_id, user, editing=True)
    removed = db.query(QuestionnaireTranslation).filter(
        QuestionnaireTranslation.survey_id == survey_id, QuestionnaireTranslation.language_code == lang.code
    ).delete(synchronize_session=False)
    db.commit()
    _audit(db, user, "TRANSLATION_LANGUAGE_DELETED", survey_id, language=lang.code, removed=removed)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------- Hausa review


@router.post("/{survey_id}/i18n/ha/review")
def review_hausa(
    survey_id: str, payload: HausaReviewRequest,
    db: Session = Depends(get_db),
    user: User = Depends(hausa_review_access),
    ai=Depends(get_generation_ai_service),
):
    """Read-only. Rule checks always run; the AI pass is skipped (and the report says so) if AI is off or fails."""
    survey = _survey_for(db, survey_id, user, editing=True)
    _u, _r, states, _o = _state(db, survey, "ha")
    report = HausaReviewer(ai).review(states, survey_title=survey.title, use_ai=payload.use_ai, user_id=user.id)
    warnings = sum(1 for f in report.findings if f.severity == "WARNING")
    _audit(db, user, "HAUSA_REVIEW_RUN", survey_id, score=report.score, warnings=warnings,
           findings=len(report.findings), ai_used=report.ai_used)
    return {
        "score": report.score, "grade": report.grade, "summary": report.summary,
        "findings": [f.as_dict() for f in report.findings],
        "reviewed_units": report.reviewed_units, "skipped_outdated": report.skipped_outdated,
        "skipped_human_reviewed": report.skipped_reviewed_by_ai, "ai_used": report.ai_used, "ai_units": report.ai_units,
        "ai_error": report.ai_error, "model": report.model, "limitations": report.limitations,
    }


# ---------------------------------------------------------------- legacy import


@router.post("/{survey_id}/i18n/import-legacy")
def import_legacy(survey_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """
    Copy translations entered on the older Languages page (stored against row ids) into the new stable-key table.
    Only rows that still match the current version are copied, and existing new-style translations are never
    overwritten. The older table is left untouched.
    """
    survey = _survey_for(db, survey_id, user, editing=True)
    units = _units(survey)
    by_ref: dict[tuple[str, str, str], Unit] = {}
    for unit in units:
        for ref in unit.ref_ids:
            by_ref[(unit.entity_type, ref, unit.field)] = unit
    imported = skipped = unmatched = 0
    existing_by_language: dict[str, dict] = {}
    for legacy in db.query(Translation).filter(Translation.survey_id == survey_id).all():
        lang = get_language(legacy.language_code)
        unit = by_ref.get((legacy.entity_type, legacy.entity_id, legacy.field))
        if lang is None or unit is None:
            unmatched += 1
            continue
        existing = existing_by_language.setdefault(
            lang.code, {(r.entity_type, r.entity_key, r.field): r for r in _orm_rows(db, survey_id, lang.code)})
        if unit.id in existing:
            skipped += 1
            continue
        cleaned = checks.normalize_translation(unit, legacy.value)
        if not cleaned or checks.has_blocking(checks.check_translation(unit, cleaned, lang.code)):
            unmatched += 1
            continue
        _upsert(db, survey_id, lang.code, existing, unit, cleaned, "EDITED", user)
        imported += 1
    db.commit()
    _audit(db, user, "TRANSLATIONS_IMPORTED", survey_id, imported=imported, skipped=skipped, unmatched=unmatched)
    return {"imported": imported, "skipped_existing": skipped, "not_matched": unmatched}
