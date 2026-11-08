"""
The structured edit operations the AI may propose.

Nine operations, nothing else. The model returns JSON; each item is parsed
here into one of these models. Anything that does not parse is *rejected with a
reason* (it never becomes a partial or guessed operation).

Targets are always addressed by stable identifiers:
* a question by its ``code`` (unique within the questionnaire; never changed by an edit)
* a section by its ``section_ref``: the alias shown to the model (``S1``, ``S2`` ... in the
  order of the questionnaire it was shown), a real section id, or the ``temp_ref`` of a
  section added earlier in the same batch.
"""

from __future__ import annotations

from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

OP_ADD_QUESTION = "ADD_QUESTION"
OP_UPDATE_QUESTION = "UPDATE_QUESTION"
OP_DELETE_QUESTION = "DELETE_QUESTION"
OP_ADD_SECTION = "ADD_SECTION"
OP_UPDATE_SECTION = "UPDATE_SECTION"
OP_DELETE_SECTION = "DELETE_SECTION"
OP_REORDER_QUESTIONS = "REORDER_QUESTIONS"
OP_UPDATE_CHOICES = "UPDATE_CHOICES"
OP_UPDATE_VALIDATION = "UPDATE_VALIDATION"

OPERATION_NAMES: tuple[str, ...] = (
    OP_ADD_QUESTION,
    OP_UPDATE_QUESTION,
    OP_DELETE_QUESTION,
    OP_ADD_SECTION,
    OP_UPDATE_SECTION,
    OP_DELETE_SECTION,
    OP_REORDER_QUESTIONS,
    OP_UPDATE_CHOICES,
    OP_UPDATE_VALIDATION,
)

MAX_OPERATIONS = 200


class OperationError(ValueError):
    """An operation could not be parsed or applied. The message is safe to show to the user."""


# --------------------------------------------------------------------------
# Building blocks
# --------------------------------------------------------------------------


class ChoiceSpec(BaseModel):
    """An answer option. ``value`` is optional for new options (derived from the label)."""

    model_config = ConfigDict(extra="ignore")

    value: Optional[str] = Field(default=None, max_length=255)
    label: Optional[str] = Field(default=None, max_length=500)

    @field_validator("value", "label", mode="before")
    @classmethod
    def _text(cls, v: Any) -> Any:
        if v is None:
            return None
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return str(v)
        if not isinstance(v, str):
            raise ValueError("must be text")
        v = v.strip()
        return v or None


class NewQuestion(BaseModel):
    """The content of a question being added."""

    model_config = ConfigDict(extra="ignore")

    code: Optional[str] = Field(default=None, max_length=100)
    label: str = Field(max_length=2000)
    hint: Optional[str] = Field(default=None, max_length=1000)
    type: str
    is_required: bool = False
    choices: list[ChoiceSpec] = Field(default_factory=list, max_length=200)
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    min_length: Optional[int] = Field(default=None, ge=0)
    max_length: Optional[int] = Field(default=None, ge=0)
    regex_pattern: Optional[str] = Field(default=None, max_length=1000)
    relevance_expression: Optional[str] = Field(default=None, max_length=1000)
    default_value: Optional[str] = Field(default=None, max_length=500)

    @field_validator("is_required", mode="before")
    @classmethod
    def _bool(cls, v: Any) -> Any:
        if isinstance(v, str):
            return v.strip().lower() in {"true", "yes", "1"}
        return v


class QuestionChanges(BaseModel):
    """Fields UPDATE_QUESTION may change. Anything else (``code``, choices, ...) is refused."""

    model_config = ConfigDict(extra="forbid")

    label: Optional[str] = Field(default=None, max_length=2000)
    hint: Optional[str] = Field(default=None, max_length=1000)
    type: Optional[str] = None
    is_required: Optional[bool] = None
    default_value: Optional[str] = Field(default=None, max_length=500)
    relevance_expression: Optional[str] = Field(default=None, max_length=1000)
    section_ref: Optional[str] = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def _not_empty(self) -> "QuestionChanges":
        if not self.model_fields_set:
            raise ValueError("'changes' must name at least one field to change")
        return self


class SectionChanges(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Optional[str] = Field(default=None, max_length=255)
    description: Optional[str] = Field(default=None, max_length=4000)
    position: Optional[int] = Field(default=None, ge=1, le=1000)

    @model_validator(mode="after")
    def _not_empty(self) -> "SectionChanges":
        if not self.model_fields_set:
            raise ValueError("'changes' must name at least one field to change")
        return self


class ValidationChanges(BaseModel):
    """Validation rules. A field that is present is applied (``null`` clears it); absent fields are untouched."""

    model_config = ConfigDict(extra="forbid")

    is_required: Optional[bool] = None
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    min_length: Optional[int] = Field(default=None, ge=0)
    max_length: Optional[int] = Field(default=None, ge=0)
    regex_pattern: Optional[str] = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def _not_empty(self) -> "ValidationChanges":
        if not self.model_fields_set:
            raise ValueError("'validation' must name at least one rule to change")
        if "is_required" in self.model_fields_set and self.is_required is None:
            raise ValueError("'is_required' must be true or false")
        return self


# --------------------------------------------------------------------------
# The nine operations
# --------------------------------------------------------------------------


class _OperationBase(BaseModel):
    # Models often add harmless keys ("explanation", ...); those are ignored. The nested
    # ``changes`` / ``validation`` models are strict, so unsupported *edits* are refused.
    model_config = ConfigDict(extra="ignore")

    reason: Optional[str] = Field(default=None, max_length=500)


class AddQuestion(_OperationBase):
    op: Literal["ADD_QUESTION"] = "ADD_QUESTION"
    section_ref: Optional[str] = Field(default=None, max_length=100)
    after_code: Optional[str] = Field(default=None, max_length=100)
    question: NewQuestion


class UpdateQuestion(_OperationBase):
    op: Literal["UPDATE_QUESTION"] = "UPDATE_QUESTION"
    code: str = Field(min_length=1, max_length=100)
    changes: QuestionChanges


class DeleteQuestion(_OperationBase):
    op: Literal["DELETE_QUESTION"] = "DELETE_QUESTION"
    code: str = Field(min_length=1, max_length=100)


class AddSection(_OperationBase):
    op: Literal["ADD_SECTION"] = "ADD_SECTION"
    title: str = Field(min_length=1, max_length=255)
    description: Optional[str] = Field(default=None, max_length=4000)
    position: Optional[int] = Field(default=None, ge=1, le=1000)
    temp_ref: Optional[str] = Field(default=None, min_length=1, max_length=60)


class UpdateSection(_OperationBase):
    op: Literal["UPDATE_SECTION"] = "UPDATE_SECTION"
    section_ref: str = Field(min_length=1, max_length=100)
    changes: SectionChanges


class DeleteSection(_OperationBase):
    op: Literal["DELETE_SECTION"] = "DELETE_SECTION"
    section_ref: str = Field(min_length=1, max_length=100)
    # MOVE (default): the section's questions are kept and moved. DELETE: they are deleted too,
    # and show up as deleted questions in the preview. Nothing is ever deleted implicitly.
    questions: Literal["MOVE", "DELETE"] = "MOVE"
    move_to_section_ref: Optional[str] = Field(default=None, max_length=100)

    @field_validator("questions", mode="before")
    @classmethod
    def _upper(cls, v: Any) -> Any:
        return v.strip().upper() if isinstance(v, str) else v


class ReorderQuestions(_OperationBase):
    op: Literal["REORDER_QUESTIONS"] = "REORDER_QUESTIONS"
    ordered_codes: list[str] = Field(min_length=2, max_length=1000)
    # When given, every listed question is also moved into this section.
    section_ref: Optional[str] = Field(default=None, max_length=100)


class UpdateChoices(_OperationBase):
    op: Literal["UPDATE_CHOICES"] = "UPDATE_CHOICES"
    code: str = Field(min_length=1, max_length=100)
    mode: Literal["REPLACE", "ADD", "REMOVE", "UPDATE_LABELS"]
    choices: list[ChoiceSpec] = Field(default_factory=list, max_length=200)
    remove_values: list[str] = Field(default_factory=list, max_length=200)

    @field_validator("mode", mode="before")
    @classmethod
    def _upper(cls, v: Any) -> Any:
        return v.strip().upper().replace(" ", "_") if isinstance(v, str) else v

    @model_validator(mode="after")
    def _shape(self) -> "UpdateChoices":
        if self.mode == "REMOVE":
            if not self.remove_values:
                raise ValueError("REMOVE needs 'remove_values'")
        elif not self.choices:
            raise ValueError(f"{self.mode} needs 'choices'")
        return self


class UpdateValidation(_OperationBase):
    op: Literal["UPDATE_VALIDATION"] = "UPDATE_VALIDATION"
    code: str = Field(min_length=1, max_length=100)
    validation: ValidationChanges


Operation = Union[
    AddQuestion,
    UpdateQuestion,
    DeleteQuestion,
    AddSection,
    UpdateSection,
    DeleteSection,
    ReorderQuestions,
    UpdateChoices,
    UpdateValidation,
]

_MODELS: dict[str, type[_OperationBase]] = {
    OP_ADD_QUESTION: AddQuestion,
    OP_UPDATE_QUESTION: UpdateQuestion,
    OP_DELETE_QUESTION: DeleteQuestion,
    OP_ADD_SECTION: AddSection,
    OP_UPDATE_SECTION: UpdateSection,
    OP_DELETE_SECTION: DeleteSection,
    OP_REORDER_QUESTIONS: ReorderQuestions,
    OP_UPDATE_CHOICES: UpdateChoices,
    OP_UPDATE_VALIDATION: UpdateValidation,
}


def _where(err: dict[str, Any]) -> str:
    loc = ".".join(str(p) for p in err.get("loc", ()) if p != "op")
    return loc or "operation"


def parse_operation(raw: Any) -> Operation:
    """Turn one item of the model's ``operations`` list into an operation, or raise ``OperationError``."""
    if not isinstance(raw, dict):
        raise OperationError("The operation is not an object.")
    name = raw.get("op")
    if not isinstance(name, str):
        raise OperationError("The operation has no 'op' name.")
    key = name.strip().upper()
    model = _MODELS.get(key)
    if model is None:
        raise OperationError(f"'{name[:40]}' is not a supported operation.")
    try:
        return model.model_validate({**raw, "op": key})  # type: ignore[return-value]
    except ValidationError as exc:
        first = exc.errors()[0]
        problem = str(first.get("msg", "invalid")).removeprefix("Value error, ")
        raise OperationError(f"Invalid {key}: {_where(first)}: {problem}") from exc


# --------------------------------------------------------------------------
# Human-readable one-line summary (shown next to each operation in the preview)
# --------------------------------------------------------------------------


def _short(text: Optional[str], n: int = 60) -> str:
    text = (text or "").strip().replace("\n", " ")
    return text if len(text) <= n else text[: n - 1] + "…"


def describe(op: Operation) -> str:
    if isinstance(op, AddQuestion):
        return f'Add question "{_short(op.question.label)}"'
    if isinstance(op, UpdateQuestion):
        fields = ", ".join(sorted(f for f in op.changes.model_fields_set)).replace("_", " ")
        return f"Update {op.code}: {fields}"
    if isinstance(op, DeleteQuestion):
        return f"Delete question {op.code}"
    if isinstance(op, AddSection):
        return f'Add section "{_short(op.title)}"'
    if isinstance(op, UpdateSection):
        fields = ", ".join(sorted(op.changes.model_fields_set))
        return f"Update section {op.section_ref}: {fields}"
    if isinstance(op, DeleteSection):
        extra = " and its questions" if op.questions == "DELETE" else ""
        return f"Delete section {op.section_ref}{extra}"
    if isinstance(op, ReorderQuestions):
        moved = f" into {op.section_ref}" if op.section_ref else ""
        return f"Reorder {len(op.ordered_codes)} questions{moved}"
    if isinstance(op, UpdateChoices):
        return f"Change answer options of {op.code} ({op.mode.replace('_', ' ').lower()})"
    if isinstance(op, UpdateValidation):
        fields = ", ".join(sorted(op.validation.model_fields_set)).replace("_", " ")
        return f"Change rules of {op.code}: {fields}"
    return op.op  # pragma: no cover
