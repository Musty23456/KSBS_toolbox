"""Request models for the translation endpoints (the only Pydantic file in this package)."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

EntityType = Literal["SURVEY", "SECTION", "GROUP", "QUESTION", "CHOICE", "SYSTEM"]
FieldName = Literal["title", "description", "label", "hint", "text"]


class UnitRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_type: EntityType
    entity_key: str = Field(min_length=1, max_length=400)
    field: FieldName


class TranslateRequest(BaseModel):
    """
    Translate some or all of a questionnaire. ``scope`` picks which units; ``units`` / ``entity_types`` narrow it
    further (translate one question, or only the answer choices). Work done by a person is never overwritten
    unless ``overwrite_manual`` is true. ``max_units`` keeps one request short: call again until ``remaining`` is 0.
    """

    model_config = ConfigDict(extra="forbid")

    scope: Literal["missing", "outdated", "missing_and_outdated", "all"] = "missing_and_outdated"
    entity_types: Optional[list[EntityType]] = None
    units: Optional[list[UnitRef]] = Field(default=None, max_length=500)
    overwrite_manual: bool = False
    max_units: int = Field(default=60, ge=1, le=200)


class SaveUnit(BaseModel):
    """A person's edit. ``value`` omitted means "keep the text, only change the status" (e.g. mark as reviewed)."""

    model_config = ConfigDict(extra="forbid")

    entity_type: EntityType
    entity_key: str = Field(min_length=1, max_length=400)
    field: FieldName
    value: Optional[str] = Field(default=None, max_length=8000)
    status: Literal["EDITED", "REVIEWED"] = "EDITED"


class SaveUnitsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    units: list[SaveUnit] = Field(min_length=1, max_length=300)


class HausaReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    use_ai: bool = True
