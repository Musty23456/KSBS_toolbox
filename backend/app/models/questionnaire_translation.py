from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin


class QuestionnaireTranslation(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    One translated text of one survey in one language (Phase 5).

    Unlike the older ``translations`` table, a row is NOT tied to a row id. Every save of a survey creates a new
    version with new ids, so rows are tied to stable keys instead (see ``app/ai/translation/units.py``):
    the question code, "<code>::<choice value>", or a hash of the section/group title. ``source_hash`` is the
    hash of the source text it was translated from; when the source text changes the translation is "outdated".
    """

    __tablename__ = "questionnaire_translations"
    __table_args__ = (
        UniqueConstraint("survey_id", "language_code", "entity_type", "entity_key", "field", name="uq_questionnaire_translation"),
    )

    survey_id: Mapped[str] = mapped_column(String(36), ForeignKey("surveys.id", ondelete="CASCADE"), nullable=False, index=True)
    language_code: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(20), nullable=False)  # SURVEY SECTION GROUP QUESTION CHOICE SYSTEM
    entity_key: Mapped[str] = mapped_column(String(400), nullable=False)
    field: Mapped[str] = mapped_column(String(30), nullable=False)  # title description label hint text
    value: Mapped[str] = mapped_column(Text, nullable=False)
    source_hash: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="AI_DRAFT")  # AI_DRAFT EDITED REVIEWED
    updated_by_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
