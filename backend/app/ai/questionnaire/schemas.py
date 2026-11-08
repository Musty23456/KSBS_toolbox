"""
Request / response models for the questionnaire generator.

The generated questionnaire is expressed with the *existing* survey schemas
(``SectionIn``, ``QuestionGroupIn``, ``QuestionIn``) so the preview can be
loaded straight into the Survey Builder and saved through the normal
``POST /api/surveys`` - there is no second questionnaire format.
"""

from __future__ import annotations

from typing import Annotated, Any, Optional

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.models.question import QuestionType
from app.schemas.survey import QuestionGroupIn, QuestionIn, SectionIn

ShortCode = Annotated[str, StringConstraints(min_length=1, max_length=100)]
ChoiceValueStr = Annotated[str, StringConstraints(max_length=255)]


def _blank_to_none(value: Any) -> Any:
    if isinstance(value, str) and not value.strip():
        return None
    return value


# --------------------------------------------------------------------------
# Requests
# --------------------------------------------------------------------------


class QuestionnaireBrief(BaseModel):
    """What the user tells the AI about the study (the generator form)."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    research_topic: str = Field(min_length=3, max_length=500)
    survey_title: Optional[str] = Field(default=None, max_length=255)
    research_objectives: Optional[str] = Field(default=None, max_length=2000)
    target_respondents: Optional[str] = Field(default=None, max_length=1000)
    study_location: Optional[str] = Field(default=None, max_length=500)
    expected_question_count: int = Field(default=20, ge=3, le=200)
    language: str = Field(default="English", min_length=2, max_length=60)
    methodology: Optional[str] = Field(default=None, max_length=1000)
    additional_instructions: Optional[str] = Field(default=None, max_length=2000)

    @field_validator(
        "survey_title",
        "research_objectives",
        "target_respondents",
        "study_location",
        "methodology",
        "additional_instructions",
        mode="before",
    )
    @classmethod
    def _empty_text_is_none(cls, value: Any) -> Any:
        return _blank_to_none(value)


class ContextQuestion(BaseModel):
    """A compact view of another question, used so skip logic can reference it."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    code: ShortCode
    label: str = Field(default="", max_length=300)
    type: QuestionType
    choice_values: list[ChoiceValueStr] = Field(default_factory=list, max_length=60)


class RegenerateQuestionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    brief: QuestionnaireBrief
    section_title: Optional[str] = Field(default=None, max_length=255)
    question: QuestionIn
    instruction: Optional[str] = Field(default=None, max_length=1000)
    # Questions that appear before this one (skip logic may only use these).
    preceding_questions: list[ContextQuestion] = Field(default_factory=list, max_length=300)
    # Codes already used by every *other* question (so a new code cannot collide).
    other_codes: list[ShortCode] = Field(default_factory=list, max_length=600)

    @field_validator("instruction", "section_title", mode="before")
    @classmethod
    def _empty_text_is_none(cls, value: Any) -> Any:
        return _blank_to_none(value)


class RegenerateSectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    brief: QuestionnaireBrief
    section_title: str = Field(min_length=1, max_length=255)
    section_description: Optional[str] = Field(default=None, max_length=4000)
    current_questions: list[ContextQuestion] = Field(default_factory=list, max_length=150)
    preceding_questions: list[ContextQuestion] = Field(default_factory=list, max_length=300)
    other_codes: list[ShortCode] = Field(default_factory=list, max_length=600)
    question_count: Optional[int] = Field(default=None, ge=1, le=100)
    instruction: Optional[str] = Field(default=None, max_length=1000)

    @field_validator("instruction", "section_description", mode="before")
    @classmethod
    def _empty_text_is_none(cls, value: Any) -> Any:
        return _blank_to_none(value)


# --------------------------------------------------------------------------
# What the model is asked to return (envelope shape only).
#
# Questions stay plain dicts here on purpose: ``normalize.py`` repairs or drops
# an individual bad question with a warning, instead of throwing away a whole
# questionnaire because one question was malformed. Anything structurally
# wrong (sections not a list, a question that is not an object, ...) is
# rejected by these models.
# --------------------------------------------------------------------------


class WireGroup(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: Optional[str] = None
    description: Optional[str] = None
    repeatable: Any = False
    min_repeats: Any = None
    max_repeats: Any = None
    questions: list[dict[str, Any]] = Field(default_factory=list)


class WireSection(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: Optional[str] = None
    description: Optional[str] = None
    questions: list[dict[str, Any]] = Field(default_factory=list)
    groups: list[WireGroup] = Field(default_factory=list)


class WireQuestionnaire(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: Optional[str] = None
    description: Optional[str] = None
    introduction: Optional[str] = None
    respondent_instructions: Optional[str] = None
    instructions: Optional[str] = None  # tolerated alias
    sections: list[WireSection] = Field(min_length=1)


class WireSingleQuestion(BaseModel):
    model_config = ConfigDict(extra="ignore")

    question: dict[str, Any]


class WireSingleSection(BaseModel):
    model_config = ConfigDict(extra="ignore")

    section: WireSection


# --------------------------------------------------------------------------
# Responses
# --------------------------------------------------------------------------


class SkipLogicSuggestion(BaseModel):
    question_code: str
    expression: str
    explanation: str = ""


class GeneratedQuestionnairePreview(BaseModel):
    """A validated, *unsaved* questionnaire the user can review and edit."""

    title: str
    description: Optional[str] = None
    introduction: Optional[str] = None
    respondent_instructions: Optional[str] = None
    # description + introduction + instructions, ready for Survey.description
    composed_description: str = ""
    sections: list[SectionIn]
    groups: list[QuestionGroupIn] = Field(default_factory=list)
    questions: list[QuestionIn]
    skip_logic: list[SkipLogicSuggestion] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    model: str = ""
    requested_question_count: Optional[int] = None


class RegeneratedQuestion(BaseModel):
    question: QuestionIn
    skip_logic: list[SkipLogicSuggestion] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    model: str = ""


class RegeneratedSection(BaseModel):
    """Replacement content for one section.

    Group references on the questions are ``local-<n>`` indexes *within this
    response*; the client re-maps them when it merges the section in.
    """

    section: SectionIn
    groups: list[QuestionGroupIn] = Field(default_factory=list)
    questions: list[QuestionIn]
    skip_logic: list[SkipLogicSuggestion] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    model: str = ""


class QuestionnaireAvailability(BaseModel):
    available: bool
    enabled: bool
    configured: bool
    max_questions: int
    message: str
