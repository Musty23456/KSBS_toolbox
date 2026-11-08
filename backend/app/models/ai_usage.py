from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import UUIDPrimaryKeyMixin, utcnow


class AIUsageLog(Base, UUIDPrimaryKeyMixin):
    """
    One row per AI provider call.

    Deliberately stores NO prompt text, response text, questionnaire data or
    free-form error messages - only who/what/when/outcome/duration, so the
    table cannot leak confidential responses.
    """

    __tablename__ = "ai_usage_logs"

    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    request_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    requested_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    error_code: Mapped[str] = mapped_column(String(50), nullable=True)  # stable code, never raw text
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
