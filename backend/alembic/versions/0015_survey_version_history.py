"""survey_versions: who/why metadata for version history (change_summary, change_source, created_by_id)

Revision ID: 0015_survey_version_history
Revises: 0014_survey_ai_generated

Additive and nullable: existing versions simply have no summary, source or author.
"""

from alembic import op
import sqlalchemy as sa


revision = "0015_survey_version_history"
down_revision = "0014_survey_ai_generated"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("survey_versions", sa.Column("change_summary", sa.Text(), nullable=True))
    op.add_column("survey_versions", sa.Column("change_source", sa.String(length=20), nullable=True))
    op.add_column("survey_versions", sa.Column("created_by_id", sa.String(length=36), nullable=True))
    op.create_foreign_key(
        "fk_survey_versions_created_by_id_users", "survey_versions", "users", ["created_by_id"], ["id"]
    )


def downgrade():
    op.drop_constraint("fk_survey_versions_created_by_id_users", "survey_versions", type_="foreignkey")
    op.drop_column("survey_versions", "created_by_id")
    op.drop_column("survey_versions", "change_source")
    op.drop_column("survey_versions", "change_summary")
