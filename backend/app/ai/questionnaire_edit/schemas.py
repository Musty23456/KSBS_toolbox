"""Request / response models for the questionnaire editor (pure Pydantic, no web framework)."""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.ai.questionnaire_edit.operations import MAX_OPERATIONS
from app.ai.questionnaire_edit.snapshot import Snapshot

# --------------------------------------------------------------------------
# Requests
# --------------------------------------------------------------------------


class EditRequest(BaseModel):
    """Ask the AI to propose edits to the questionnaire currently open in the builder."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    instruction: str = Field(min_length=3, max_length=1000)
    snapshot: Snapshot
    survey_title: Optional[str] = Field(default=None, max_length=255)
    survey_description: Optional[str] = Field(default=None, max_length=2000)

    @field_validator("survey_title", "survey_description", mode="before")
    @classmethod
    def _blank_to_none(cls, v: Any) -> Any:
        return None if isinstance(v, str) and not v.strip() else v


class EditPreviewRequest(BaseModel):
    """Validate and preview a list of operations without calling the AI."""

    model_config = ConfigDict(extra="forbid")

    snapshot: Snapshot
    operations: list[dict[str, Any]] = Field(max_length=MAX_OPERATIONS)


# --------------------------------------------------------------------------
# Responses
# --------------------------------------------------------------------------


class OperationView(BaseModel):
    index: int
    op: str
    summary: str
    reason: Optional[str] = None
    # The operation exactly as it will be re-validated if the person ticks / unticks operations.
    raw: dict[str, Any]


class RejectedView(BaseModel):
    index: int
    op: str = ""
    summary: str = ""
    reason: str
    no_change: bool = False
    raw: Any = None


class FieldChange(BaseModel):
    field: str
    label: str
    before: Any = None
    after: Any = None


class ChoiceChange(BaseModel):
    kind: Literal["ADDED", "REMOVED", "CHANGED"]
    value: str
    before_label: Optional[str] = None
    after_label: Optional[str] = None


class ItemChange(BaseModel):
    item_type: Literal["question", "section"]
    change: Literal["ADDED", "MODIFIED", "DELETED"]
    key: str  # question code, or section alias (S1...) / "new:<n>"
    title: str
    code: Optional[str] = None
    position_before: Optional[int] = None
    position_after: Optional[int] = None
    fields: list[FieldChange] = Field(default_factory=list)
    choices: list[ChoiceChange] = Field(default_factory=list)
    before: Optional[dict[str, Any]] = None  # the original content (MODIFIED / DELETED)
    after: Optional[dict[str, Any]] = None  # the proposed content (ADDED / MODIFIED)


class OrderChange(BaseModel):
    item_type: Literal["question", "section"]
    key: str
    title: str
    from_position: int
    to_position: int


class ChangeSummary(BaseModel):
    added_questions: int = 0
    modified_questions: int = 0
    deleted_questions: int = 0
    added_sections: int = 0
    modified_sections: int = 0
    deleted_sections: int = 0
    reordered_questions: int = 0
    reordered_sections: int = 0
    questions_before: int = 0
    questions_after: int = 0


class EditPreview(BaseModel):
    """What would change, before anything is applied. ``result`` is the questionnaire *after* the changes."""

    operations: list[OperationView] = Field(default_factory=list)
    rejected: list[RejectedView] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    added: list[ItemChange] = Field(default_factory=list)
    modified: list[ItemChange] = Field(default_factory=list)
    deleted: list[ItemChange] = Field(default_factory=list)
    order_changes: list[OrderChange] = Field(default_factory=list)
    summary: ChangeSummary = Field(default_factory=ChangeSummary)
    has_changes: bool = False
    blocked: Optional[str] = None
    requires_confirmation: bool = False
    confirmation_reasons: list[str] = Field(default_factory=list)
    result: dict[str, Any] = Field(default_factory=dict)


class EditProposal(EditPreview):
    """An AI-proposed preview: the same thing plus what the assistant said."""

    message: str = ""
    model: str = ""
