"""Request / response models for the questionnaire reviewer (pure Pydantic)."""

from __future__ import annotations

import hashlib
import re
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.ai.questionnaire_edit.snapshot import Snapshot

Severity = Literal["CRITICAL", "WARNING", "SUGGESTION", "GOOD"]
Category = Literal[
    "CLARITY",
    "GRAMMAR",
    "DUPLICATE",
    "AMBIGUITY",
    "BIAS",
    "CHOICES",
    "QUESTION_TYPE",
    "REQUIRED",
    "CONSISTENCY",
    "SKIP_LOGIC",
    "VALIDATION",
    "COVERAGE",
    "STRUCTURE",
]
CATEGORIES: tuple[str, ...] = (
    "CLARITY", "GRAMMAR", "DUPLICATE", "AMBIGUITY", "BIAS", "CHOICES", "QUESTION_TYPE",
    "REQUIRED", "CONSISTENCY", "SKIP_LOGIC", "VALIDATION", "COVERAGE", "STRUCTURE",
)
SEVERITY_ORDER: dict[str, int] = {"CRITICAL": 0, "WARNING": 1, "SUGGESTION": 2, "GOOD": 3}


class ReviewRequest(BaseModel):
    """Review the questionnaire currently open in the builder (saved or not)."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    snapshot: Snapshot
    objectives: Optional[str] = Field(default=None, max_length=3000)
    survey_title: Optional[str] = Field(default=None, max_length=255)
    survey_description: Optional[str] = Field(default=None, max_length=2000)
    use_ai: bool = True

    @field_validator("objectives", "survey_title", "survey_description", mode="before")
    @classmethod
    def _blank_to_none(cls, v: Any) -> Any:
        return None if isinstance(v, str) and not v.strip() else v


def finding_id(category: str, code: Optional[str], title: str) -> str:
    """Stable across re-reviews, so an 'ignored' suggestion stays ignored."""
    key = f"{category}|{code or ''}|{re.sub(r'[^a-z0-9]+', ' ', title.lower()).strip()}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


class Finding(BaseModel):
    id: str
    severity: Severity
    category: Category
    question_code: Optional[str] = None
    question_label: Optional[str] = None
    title: str
    explanation: str = ""
    recommendation: str = ""
    # A Phase 3 edit operation that implements the recommendation. Only present when it was checked against
    # the questionnaire and is applicable. Applying it always goes through the preview the person confirms.
    fix: Optional[dict[str, Any]] = None
    fix_summary: Optional[str] = None
    source: Literal["RULE", "AI"] = "RULE"


class CoverageItem(BaseModel):
    objective: str
    covered: bool
    question_codes: list[str] = Field(default_factory=list)
    note: str = ""


class ReviewStats(BaseModel):
    questions: int = 0
    sections: int = 0
    required_questions: int = 0
    questions_with_hints: int = 0
    choice_questions: int = 0
    questions_with_skip_logic: int = 0


class ScoreBreakdown(BaseModel):
    critical_penalty: float = 0
    warning_penalty: float = 0
    suggestion_penalty: float = 0
    good_practice_bonus: float = 0
    size_scale: float = 1


class ReviewReport(BaseModel):
    score: int
    grade: str
    summary: str
    counts: dict[str, int]
    findings: list[Finding]
    coverage: list[CoverageItem] = Field(default_factory=list)
    objectives_checked: bool = False
    stats: ReviewStats
    score_breakdown: ScoreBreakdown
    ai_used: bool = False
    ai_error: Optional[str] = None
    model: str = ""
    generated_at: str
    limitations: list[str] = Field(default_factory=list)
