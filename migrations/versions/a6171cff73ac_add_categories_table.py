"""add_categories_table

Revision ID: a6171cff73ac
Revises: a1b2c3d4e5f6
Create Date: 2026-07-12
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.features.ingestion.categories import CATEGORY_SEED_DATA

revision: str = "a6171cff73ac"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    categories_table = op.create_table(
        "categories",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("label", sa.String(length=100), nullable=False),
        sa.Column("is_fallback", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.bulk_insert(categories_table, CATEGORY_SEED_DATA)


def downgrade() -> None:
    op.drop_table("categories")
