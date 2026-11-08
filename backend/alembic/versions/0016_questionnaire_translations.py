"""questionnaire_translations: multilingual questionnaire translations keyed by stable keys (Phase 5)

Revision ID: 0016_questionnaire_translations
Revises: 0015_survey_version_history

A new table only. The older ``translations`` table and its endpoints are left exactly as they were.
"""

from alembic import op
import sqlalchemy as sa


revision = "0016_questionnaire_translations"
down_revision = "0015_survey_version_history"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "questionnaire_translations",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("survey_id", sa.String(length=36), sa.ForeignKey("surveys.id", ondelete="CASCADE"), nullable=False),
        sa.Column("language_code", sa.String(length=10), nullable=False),
        sa.Column("entity_type", sa.String(length=20), nullable=False),
        sa.Column("entity_key", sa.String(length=400), nullable=False),
        sa.Column("field", sa.String(length=30), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("source_hash", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="AI_DRAFT"),
        sa.Column("updated_by_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.UniqueConstraint("survey_id", "language_code", "entity_type", "entity_key", "field", name="uq_questionnaire_translation"),
    )
    op.create_index("ix_questionnaire_translations_survey_id", "questionnaire_translations", ["survey_id"])
    op.create_index("ix_questionnaire_translations_language_code", "questionnaire_translations", ["language_code"])


def downgrade():
    op.drop_index("ix_questionnaire_translations_language_code", table_name="questionnaire_translations")
    op.drop_index("ix_questionnaire_translations_survey_id", table_name="questionnaire_translations")
    op.drop_table("questionnaire_translations")
