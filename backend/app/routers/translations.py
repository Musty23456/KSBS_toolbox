from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user, require_roles
from app.models.question import Choice
from app.models.group import QuestionGroup
from app.models.survey import Survey, SurveyStatus
from app.models.translation import Translation
from app.models.user import RoleName, User
from app.ai.translation.languages import list_languages

router = APIRouter(prefix="/api/surveys", tags=["translations"])

# Single source of truth for the supported languages (adds native_name and rtl; code and name are unchanged).
SUPPORTED_LANGUAGES = list_languages()


class TranslationIn(BaseModel):
    entity_type: str = Field(pattern="^(SURVEY|SECTION|GROUP|QUESTION|CHOICE)$")
    entity_id: str
    field: str = Field(pattern="^(title|description|label|hint)$")
    language_code: str = Field(min_length=2, max_length=20)
    value: str


class TranslationOut(TranslationIn):
    id: str


@router.get("/languages")
def languages():
    return SUPPORTED_LANGUAGES


def _survey(db: Session, survey_id: str) -> Survey:
    survey = db.query(Survey).filter(Survey.id == survey_id).first()
    if not survey:
        raise HTTPException(status_code=404, detail="Survey not found")
    return survey


@router.get("/{survey_id}/translations", response_model=list[TranslationOut])
def list_translations(survey_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _survey(db, survey_id)
    return db.query(Translation).filter(Translation.survey_id == survey_id).order_by(Translation.language_code, Translation.entity_type).all()


@router.put("/{survey_id}/translations", response_model=TranslationOut)
def upsert_translation(survey_id: str, payload: TranslationIn, db: Session = Depends(get_db), current_user: User = Depends(require_roles(RoleName.ADMINISTRATOR, RoleName.SUPERVISOR))):
    _survey(db, survey_id)
    existing = db.query(Translation).filter(
        Translation.survey_id == survey_id,
        Translation.entity_type == payload.entity_type,
        Translation.entity_id == payload.entity_id,
        Translation.field == payload.field,
        Translation.language_code == payload.language_code,
    ).first()
    if existing:
        existing.value = payload.value
    else:
        existing = Translation(survey_id=survey_id, **payload.model_dump())
        db.add(existing)
    db.commit(); db.refresh(existing)
    return existing


@router.delete("/{survey_id}/translations/{translation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_translation(survey_id: str, translation_id: str, db: Session = Depends(get_db), current_user: User = Depends(require_roles(RoleName.ADMINISTRATOR, RoleName.SUPERVISOR))):
    item = db.query(Translation).filter(Translation.id == translation_id, Translation.survey_id == survey_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Translation not found")
    db.delete(item); db.commit()


@router.get("/{survey_id}/localized")
def localized_survey(survey_id: str, language_code: str = "en", db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    survey = _survey(db, survey_id)
    version = next((v for v in survey.versions if v.is_current), survey.versions[-1] if survey.versions else None)
    if not version:
        raise HTTPException(status_code=404, detail="Survey has no version")
    rows = db.query(Translation).filter(Translation.survey_id == survey_id, Translation.language_code == language_code).all()
    t = {(r.entity_type, r.entity_id, r.field): r.value for r in rows}
    def tr(kind, entity_id, field, fallback):
        return t.get((kind, entity_id, field), fallback)
    return {
        "language_code": language_code,
        "fallback_language": "en",
        "survey": {"id": survey.id, "title": tr("SURVEY", survey.id, "title", survey.title), "description": tr("SURVEY", survey.id, "description", survey.description)},
        "sections": [{"id": s.id, "title": tr("SECTION", s.id, "title", s.title), "description": tr("SECTION", s.id, "description", s.description)} for s in version.sections],
        "groups": [{"id": g.id, "title": tr("GROUP", g.id, "title", g.title), "description": tr("GROUP", g.id, "description", g.description)} for g in version.groups],
        "questions": [{"id": q.id, "code": q.code, "label": tr("QUESTION", q.id, "label", q.label), "hint": tr("QUESTION", q.id, "hint", q.hint), "choices": [{"id": c.id, "value": c.value, "label": tr("CHOICE", c.id, "label", c.label)} for c in q.choices]} for q in version.questions],
    }
