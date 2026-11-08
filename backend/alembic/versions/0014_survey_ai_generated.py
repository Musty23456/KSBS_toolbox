"""survey.ai_generated: provenance flag for AI-generated questionnaires

Revision ID: 0014_survey_ai_generated
Revises: 0013_survey_shares
"""

from alembic import op
import sqlalchemy as sa


revision = "0014_survey_ai_generated"
down_revision = "0013_survey_shares"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "surveys",
        sa.Column("ai_generated", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade():
    op.drop_column("surveys", "ai_generated")
