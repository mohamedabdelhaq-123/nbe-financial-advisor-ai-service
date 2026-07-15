"""drop_categories_table

The category taxonomy is now backend-owned (categories table in the Django
appdb, income/expense-typed) and read through the existing read-only mirror
(app.backend_db.models.Category) — this service no longer needs its own copy.

Revision ID: b7d2a48f9c1e
Revises: a6171cff73ac
Create Date: 2026-07-15
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b7d2a48f9c1e"
down_revision: Union[str, None] = "a6171cff73ac"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table("categories")


def downgrade() -> None:
    # Bare structure only — seeding is the backend's job now, not this
    # migration's (see a6171cff73ac's downgrade for the prior, fuller shape).
    op.create_table(
        "categories",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("label", sa.String(length=100), nullable=False),
        sa.Column("is_fallback", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
