from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.question import QuestionType
from app.models.survey import SurveyStatus


class ChoiceIn(BaseModel):
    value: str = Field(max_length=255)
    label: str = Field(max_length=500)
    order_index: int = 0
    cascade_parent_value: str | None = None


class ChoiceOut(ChoiceIn):
    model_config = ConfigDict(from_attributes=True)
    id: str


class SectionIn(BaseModel):
    # Optional id of the section being re-saved. Used only to re-point questions at the new version's rows.
    id: str | None = None
    title: str = Field(max_length=255)
    description: str | None = None
    order_index: int = 0


class QuestionGroupIn(BaseModel):
    id: str | None = None
    title: str = Field(max_length=255)
    description: str | None = None
    order_index: int = 0
    section_id: str | None = None
    repeatable: bool = False
    min_repeats: int = Field(default=1, ge=1)
    max_repeats: int | None = Field(default=None, ge=1)

class QuestionGroupOut(QuestionGroupIn):
    model_config = ConfigDict(from_attributes=True)
    id: str


class SectionOut(SectionIn):
    model_config = ConfigDict(from_attributes=True)
    id: str


class QuestionIn(BaseModel):
    code: str = Field(max_length=100)
    label: str
    hint: str | None = None
    type: QuestionType
    order_index: int = 0
    is_required: bool = False
    min_value: float | None = None
    max_value: float | None = None
    min_length: int | None = None
    max_length: int | None = None
    regex_pattern: str | None = None
    relevance_expression: str | None = None
    calculation_expression: str | None = None
    default_value: str | None = None
    cascade_parent_question_id: str | None = None
    choices: list[ChoiceIn] = []
    section_id: str | None = None
    group_id: str | None = None


class QuestionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    code: str
    label: str
    hint: str | None
    type: QuestionType
    order_index: int
    is_required: bool
    min_value: float | None
    max_value: float | None
    min_length: int | None
    max_length: int | None
    regex_pattern: str | None
    relevance_expression: str | None
    calculation_expression: str | None
    default_value: str | None
    cascade_parent_question_id: str | None
    section_id: str | None
    group_id: str | None
    choices: list[ChoiceOut] = []


class SurveyCreate(BaseModel):
    title: str = Field(max_length=255)
    description: str | None = None
    # None = default for the caller: GLOBAL for administrators, PERSONAL for
    # everyone else. Only administrators may explicitly ask for GLOBAL.
    scope: Literal["GLOBAL", "PERSONAL"] | None = None
    questions: list[QuestionIn] = []
    sections: list[SectionIn] = []
    groups: list[QuestionGroupIn] = []
    assigned_enumerator_ids: list[str] = []
    # True when the content came from the AI questionnaire generator.
    ai_generated: bool = False


class SurveyUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    description: str | None = None
    questions: list[QuestionIn] | None = None
    sections: list[SectionIn] | None = None
    groups: list[QuestionGroupIn] | None = None
    # None = leave assignments unchanged. [] = explicitly open to every
    # enumerator. A non-empty list = restrict to just those enumerator ids.
    assigned_enumerator_ids: list[str] | None = None
    # Only ever turns the provenance flag ON (an edit never makes AI content "not AI").
    ai_generated: bool | None = None
    # Version history note stored on the new version (only used when the questions change).
    change_summary: str | None = Field(default=None, max_length=1000)
    change_source: Literal["MANUAL", "AI_EDIT"] | None = None


class SurveyPublishRequest(BaseModel):
    """Optional body for publishing. AI-generated surveys require confirm_ai_review=true."""

    confirm_ai_review: bool = False


class SurveySummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    description: str | None
    status: SurveyStatus
    created_at: datetime
    current_version_number: int | None = None
    current_version_id: str | None = None
    assigned_enumerator_ids: list[str] = []
    scope: str = "GLOBAL"
    created_by_id: str | None = None
    ai_generated: bool = False


class SurveyDetailOut(SurveySummaryOut):
    sections: list[SectionOut] = []
    groups: list[QuestionGroupOut] = []
    questions: list[QuestionOut] = []


class ShareTargetOut(BaseModel):
    """A colleague a personal survey can be shared with."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    full_name: str
    email: str


class SurveySharesUpdate(BaseModel):
    user_ids: list[str] = []


class SurveySharesOut(BaseModel):
    survey_id: str
    user_ids: list[str] = []


class SurveyVersionSummaryOut(BaseModel):
    """One row of a survey's version history."""

    id: str
    version_number: int
    is_current: bool
    created_at: datetime
    created_by_id: str | None = None
    created_by_name: str | None = None
    change_source: str | None = None
    change_summary: str | None = None
    question_count: int = 0
    section_count: int = 0


class SurveyVersionDetailOut(SurveyVersionSummaryOut):
    """The full content of one (immutable) version, so it can be viewed or loaded into the builder."""

    sections: list[SectionOut] = []
    groups: list[QuestionGroupOut] = []
    questions: list[QuestionOut] = []
