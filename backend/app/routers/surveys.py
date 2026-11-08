from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.dependencies import get_current_user
from app.models.question import Choice, Question
from app.models.group import QuestionGroup
from app.models.survey import Survey, SurveyScope, SurveySection, SurveyStatus, SurveyVersion
from app.models.user import RoleName, User
from app.schemas.survey import (
    ShareTargetOut,
    SurveyCreate,
    SurveyDetailOut,
    SurveyPublishRequest,
    SurveySharesOut,
    SurveySharesUpdate,
    SurveySummaryOut,
    SurveyUpdate,
    SurveyVersionDetailOut,
    SurveyVersionSummaryOut,
    SectionOut,
)
from app.services.audit import log_action
from app.services.survey_access import (
    can_archive,
    can_create_global,
    can_edit,
    can_share,
    can_view,
    is_listed,
)

router = APIRouter(prefix="/api/surveys", tags=["surveys"])


def _current_version(survey: Survey) -> SurveyVersion | None:
    for version in survey.versions:
        if version.is_current:
            return version
    return survey.versions[-1] if survey.versions else None


def _to_detail(survey: Survey) -> SurveyDetailOut:
    version = _current_version(survey)
    return SurveyDetailOut(
        id=survey.id,
        title=survey.title,
        description=survey.description,
        status=survey.status,
        created_at=survey.created_at,
        current_version_number=version.version_number if version else None,
        current_version_id=version.id if version else None,
        sections=version.sections if version else [],
        groups=version.groups if version else [],
        questions=version.questions if version else [],
        assigned_enumerator_ids=[u.id for u in survey.assigned_enumerators],
        scope=survey.scope,
        created_by_id=survey.created_by_id,
        ai_generated=bool(survey.ai_generated),
    )


def _to_summary(survey: Survey) -> SurveySummaryOut:
    version = _current_version(survey)
    return SurveySummaryOut(
        id=survey.id,
        title=survey.title,
        description=survey.description,
        status=survey.status,
        created_at=survey.created_at,
        current_version_number=version.version_number if version else None,
        current_version_id=version.id if version else None,
        assigned_enumerator_ids=[u.id for u in survey.assigned_enumerators],
        scope=survey.scope,
        created_by_id=survey.created_by_id,
        ai_generated=bool(survey.ai_generated),
    )


def _load_survey_or_404(db: Session, survey_id: str) -> Survey:
    survey = (
        db.query(Survey)
        .options(
            joinedload(Survey.versions).joinedload(SurveyVersion.questions).joinedload(Question.choices),
            joinedload(Survey.versions).joinedload(SurveyVersion.sections),
            joinedload(Survey.versions).joinedload(SurveyVersion.groups),
            joinedload(Survey.assigned_enumerators),
            joinedload(Survey.shared_with),
        )
        .filter(Survey.id == survey_id)
        .first()
    )
    if not survey:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Survey not found")
    return survey


def _forbid_unless(allowed: bool, detail: str = "You do not have permission to perform this action") -> None:
    if not allowed:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def _apply_assignments(db: Session, survey: Survey, enumerator_ids: list[str]) -> None:
    if enumerator_ids:
        users = db.query(User).filter(User.id.in_(enumerator_ids)).all()
        survey.assigned_enumerators = users
    else:
        survey.assigned_enumerators = []


def _write_version_sections(db: Session, version: SurveyVersion, sections_in):
    mapping = {}
    for s_in in sections_in:
        section = SurveySection(survey_version_id=version.id, title=s_in.title, description=s_in.description, order_index=s_in.order_index)
        db.add(section); db.flush(); mapping[s_in.order_index] = section.id
        mapping[f"local-{s_in.order_index - 1}"] = section.id
        if s_in.id:  # a re-saved section: questions still carry its old id, point them at the new row
            mapping[s_in.id] = section.id
    return mapping


def _write_version_groups(db: Session, version: SurveyVersion, groups_in, section_map=None):
    mapping = {}
    for g_in in groups_in:
        group = QuestionGroup(
            survey_version_id=version.id,
            section_id=g_in.section_id if not section_map else section_map.get(g_in.section_id, g_in.section_id),
            title=g_in.title,
            description=g_in.description,
            order_index=g_in.order_index,
            repeatable=g_in.repeatable,
            min_repeats=g_in.min_repeats,
            max_repeats=g_in.max_repeats,
        )
        db.add(group); db.flush()
        mapping[g_in.order_index] = group.id
        mapping[f"local-{g_in.order_index - 1}"] = group.id
        if g_in.id:
            mapping[g_in.id] = group.id
    return mapping

def _write_version_questions(db: Session, version: SurveyVersion, questions_in, section_map=None, group_map=None) -> None:
    for q_in in questions_in:
        question = Question(
            survey_version_id=version.id,
            code=q_in.code,
            label=q_in.label,
            hint=q_in.hint,
            type=q_in.type,
            order_index=q_in.order_index,
            is_required=q_in.is_required,
            min_value=q_in.min_value,
            max_value=q_in.max_value,
            min_length=q_in.min_length,
            max_length=q_in.max_length,
            regex_pattern=q_in.regex_pattern,
            relevance_expression=q_in.relevance_expression,
            calculation_expression=q_in.calculation_expression,
            default_value=q_in.default_value,
            cascade_parent_question_id=q_in.cascade_parent_question_id,
            section_id=q_in.section_id if not section_map else section_map.get(q_in.section_id, q_in.section_id),
            group_id=q_in.group_id if not group_map else group_map.get(q_in.group_id, q_in.group_id),
        )
        db.add(question)
        db.flush()  # get question.id for its choices
        for c_in in q_in.choices:
            db.add(
                Choice(
                    question_id=question.id,
                    value=c_in.value,
                    label=c_in.label,
                    order_index=c_in.order_index,
                    cascade_parent_value=c_in.cascade_parent_value,
                )
            )


@router.get("", response_model=list[SurveySummaryOut])
def list_surveys(
    status_filter: SurveyStatus | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(Survey).options(
        joinedload(Survey.versions), joinedload(Survey.assigned_enumerators), joinedload(Survey.shared_with)
    )
    if status_filter:
        query = query.filter(Survey.status == status_filter)
    surveys = query.order_by(Survey.created_at.desc()).all()

    # Global surveys (respecting enumerator assignments) plus the caller's own
    # personal surveys. Other people's personal surveys are never listed.
    surveys = [s for s in surveys if is_listed(current_user, s)]

    return [_to_summary(s) for s in surveys]


@router.get("/share-targets", response_model=list[ShareTargetOut])
def list_share_targets(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Active enumerators (other than the caller) a personal survey can be shared with."""
    return (
        db.query(User)
        .filter(User.is_active.is_(True), User.role == RoleName.ENUMERATOR, User.id != current_user.id)
        .order_by(User.full_name)
        .all()
    )


@router.get("/{survey_id}", response_model=SurveyDetailOut)
def get_survey(survey_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    survey = _load_survey_or_404(db, survey_id)
    if not can_view(current_user, survey):
        # 404 rather than 403 so private survey ids are not revealed.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Survey not found")
    return _to_detail(survey)


@router.post("", response_model=SurveyDetailOut, status_code=status.HTTP_201_CREATED)
def create_survey(
    payload: SurveyCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Any signed-in user can create a PERSONAL survey; only administrators can create GLOBAL ones."""
    scope = payload.scope or (
        SurveyScope.GLOBAL.value if can_create_global(current_user) else SurveyScope.PERSONAL.value
    )
    if scope == SurveyScope.GLOBAL.value:
        _forbid_unless(can_create_global(current_user), "Only administrators can create global surveys")

    survey = Survey(
        title=payload.title,
        description=payload.description,
        created_by_id=current_user.id,
        scope=scope,
        ai_generated=payload.ai_generated,
    )
    db.add(survey)
    db.flush()

    if scope == SurveyScope.GLOBAL.value:
        _apply_assignments(db, survey, payload.assigned_enumerator_ids)

    version = SurveyVersion(survey_id=survey.id, version_number=1, is_current=True)
    db.add(version)
    db.flush()

    section_map = _write_version_sections(db, version, payload.sections)
    group_map = _write_version_groups(db, version, payload.groups, section_map)
    _write_version_questions(db, version, payload.questions, section_map, group_map)

    db.commit()
    survey = _load_survey_or_404(db, survey.id)
    log_action(db, current_user.id, "SURVEY_CREATED", "Survey", survey.id)
    return _to_detail(survey)


@router.put("/{survey_id}", response_model=SurveyDetailOut)
def update_survey(
    survey_id: str,
    payload: SurveyUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Editing title/description only patches the survey. Editing the question
    set creates a NEW immutable version (bumping version_number) so that
    historical submissions still point at the exact form they were
    collected against.
    """
    survey = _load_survey_or_404(db, survey_id)
    _forbid_unless(can_view(current_user, survey) and can_edit(current_user, survey))

    if payload.title is not None:
        survey.title = payload.title
    if payload.description is not None:
        survey.description = payload.description
    if payload.ai_generated:
        survey.ai_generated = True  # provenance only ever turns on

    if payload.assigned_enumerator_ids is not None and survey.scope == SurveyScope.GLOBAL.value:
        _apply_assignments(db, survey, payload.assigned_enumerator_ids)

    new_version = None
    if payload.questions is not None:
        current = _current_version(survey)
        # Never let a save silently empty a questionnaire. (Archiving is the way to retire a survey.)
        if not payload.questions and current is not None and current.questions:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Refusing to save a version with no questions. To retire a survey, archive it instead.",
            )
        for v in survey.versions:
            v.is_current = False
        new_version = SurveyVersion(
            survey_id=survey.id,
            version_number=(current.version_number + 1) if current else 1,
            is_current=True,
            change_summary=(payload.change_summary or "").strip() or None,
            change_source=payload.change_source or "MANUAL",
            created_by_id=current_user.id,
        )
        db.add(new_version)
        db.flush()
        section_map = _write_version_sections(db, new_version, payload.sections or [])
        group_map = _write_version_groups(db, new_version, payload.groups or [], section_map)
        _write_version_questions(db, new_version, payload.questions, section_map, group_map)

    db.commit()
    survey = _load_survey_or_404(db, survey.id)
    if new_version is not None:
        log_action(
            db, current_user.id, "SURVEY_UPDATED", "Survey", survey.id,
            version=new_version.version_number, source=new_version.change_source,
        )
    else:
        log_action(db, current_user.id, "SURVEY_UPDATED", "Survey", survey.id)
    return _to_detail(survey)


def _version_summary(version: SurveyVersion, names: dict[str, str]) -> dict:
    return dict(
        id=version.id,
        version_number=version.version_number,
        is_current=bool(version.is_current),
        created_at=version.created_at,
        created_by_id=version.created_by_id,
        created_by_name=names.get(version.created_by_id) if version.created_by_id else None,
        change_source=version.change_source,
        change_summary=version.change_summary,
        question_count=len(version.questions),
        section_count=len(version.sections),
    )


def _author_names(db: Session, survey: Survey) -> dict[str, str]:
    ids = {v.created_by_id for v in survey.versions if v.created_by_id}
    if not ids:
        return {}
    return {u.id: u.full_name for u in db.query(User).filter(User.id.in_(ids)).all()}


@router.get("/{survey_id}/versions", response_model=list[SurveyVersionSummaryOut])
def list_survey_versions(
    survey_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Version history, newest first. Only people who may edit the survey can see it."""
    survey = _load_survey_or_404(db, survey_id)
    if not can_view(current_user, survey):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Survey not found")
    _forbid_unless(can_edit(current_user, survey))
    names = _author_names(db, survey)
    ordered = sorted(survey.versions, key=lambda v: v.version_number, reverse=True)
    return [SurveyVersionSummaryOut(**_version_summary(v, names)) for v in ordered]


@router.get("/{survey_id}/versions/{version_id}", response_model=SurveyVersionDetailOut)
def get_survey_version(
    survey_id: str,
    version_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The full content of one past version. Read-only: loading it into the builder never changes it."""
    survey = _load_survey_or_404(db, survey_id)
    if not can_view(current_user, survey):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Survey not found")
    _forbid_unless(can_edit(current_user, survey))
    version = next((v for v in survey.versions if v.id == version_id), None)
    if version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version not found")
    return SurveyVersionDetailOut(
        **_version_summary(version, _author_names(db, survey)),
        sections=version.sections,
        groups=version.groups,
        questions=version.questions,
    )


@router.post("/{survey_id}/publish", response_model=SurveyDetailOut)
def publish_survey(
    survey_id: str,
    payload: SurveyPublishRequest | None = Body(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    survey = _load_survey_or_404(db, survey_id)
    _forbid_unless(can_view(current_user, survey) and can_edit(current_user, survey))
    if not survey.versions:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Add at least one question before publishing")
    # AI-generated content is never published without a person saying they reviewed it.
    if survey.ai_generated and not (payload and payload.confirm_ai_review):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This survey contains AI-generated content. Confirm that you have reviewed it before publishing.",
        )
    survey.status = SurveyStatus.PUBLISHED
    db.commit()
    log_action(db, current_user.id, "SURVEY_PUBLISHED", "Survey", survey.id)
    return _to_detail(_load_survey_or_404(db, survey_id))


@router.post("/{survey_id}/unpublish", response_model=SurveyDetailOut)
def unpublish_survey(
    survey_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    survey = _load_survey_or_404(db, survey_id)
    _forbid_unless(can_view(current_user, survey) and can_edit(current_user, survey))
    survey.status = SurveyStatus.DRAFT
    db.commit()
    log_action(db, current_user.id, "SURVEY_UNPUBLISHED", "Survey", survey.id)
    return _to_detail(_load_survey_or_404(db, survey_id))


@router.delete("/{survey_id}", status_code=status.HTTP_204_NO_CONTENT)
def archive_survey(
    survey_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Archives rather than hard-deletes, preserving submission history."""
    survey = _load_survey_or_404(db, survey_id)
    _forbid_unless(can_view(current_user, survey) and can_archive(current_user, survey))
    survey.status = SurveyStatus.ARCHIVED
    db.commit()
    log_action(db, current_user.id, "SURVEY_ARCHIVED", "Survey", survey.id)
    return None


@router.get("/{survey_id}/shares", response_model=SurveySharesOut)
def get_survey_shares(
    survey_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    survey = _load_survey_or_404(db, survey_id)
    _forbid_unless(can_share(current_user, survey), "Only the owner can manage sharing for a personal survey")
    return SurveySharesOut(survey_id=survey.id, user_ids=[u.id for u in survey.shared_with])


@router.put("/{survey_id}/shares", response_model=SurveySharesOut)
def set_survey_shares(
    survey_id: str,
    payload: SurveySharesUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Replace the list of people a personal survey is shared with. Send [] to stop sharing."""
    survey = _load_survey_or_404(db, survey_id)
    _forbid_unless(can_share(current_user, survey), "Only the owner can manage sharing for a personal survey")

    wanted = {uid for uid in payload.user_ids if uid != current_user.id}
    users = (
        db.query(User)
        .filter(User.id.in_(wanted), User.is_active.is_(True), User.role == RoleName.ENUMERATOR)
        .all()
    ) if wanted else []
    if len(users) != len(wanted):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="One or more selected users cannot receive shared surveys")

    survey.shared_with = users
    db.commit()
    log_action(db, current_user.id, "SURVEY_SHARED", "Survey", survey.id)
    return SurveySharesOut(survey_id=survey.id, user_ids=[u.id for u in users])
