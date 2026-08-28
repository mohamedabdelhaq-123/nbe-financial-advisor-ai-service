"""add recommendation source statement id

Revision ID: c3e7a419d2f0
Revises: b7d2a48f9c1e
Create Date: 2026-08-27
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c3e7a419d2f0"
down_revision: Union[str, None] = "b7d2a48f9c1e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "ai_problem_statements",
        sa.Column("source_statement_id", sa.Uuid(), nullable=True),
    )
    op.create_unique_constraint(
        "uq_ai_problem_statements_source_statement_id",
        "ai_problem_statements",
        ["source_statement_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_ai_problem_statements_source_statement_id",
        "ai_problem_statements",
        type_="unique",
    )
    op.drop_column("ai_problem_statements", "source_statement_id")
