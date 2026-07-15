"""add_categories_table

Revision ID: a6171cff73ac
Revises: a1b2c3d4e5f6
Create Date: 2026-07-12
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a6171cff73ac"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Inlined rather than imported from app code (migrations are historical
# snapshots and must stay importable regardless of later refactors — this
# table and its seed are dropped by b7d2a48f9c1e anyway, now that the
# category taxonomy is backend-owned).
CATEGORY_SEED_DATA: list[dict] = [
    {"name": "groceries", "label": "Groceries", "is_fallback": False},
    {"name": "dining", "label": "Dining", "is_fallback": False},
    {"name": "transport", "label": "Transport", "is_fallback": False},
    {"name": "utilities", "label": "Utilities", "is_fallback": False},
    {"name": "rent", "label": "Rent", "is_fallback": False},
    {"name": "salary", "label": "Salary", "is_fallback": False},
    {"name": "transfer", "label": "Transfer", "is_fallback": False},
    {"name": "fees", "label": "Fees", "is_fallback": False},
    {"name": "entertainment", "label": "Entertainment", "is_fallback": False},
    {"name": "healthcare", "label": "Healthcare", "is_fallback": False},
    {"name": "shopping", "label": "Shopping", "is_fallback": False},
    {"name": "other", "label": "Other", "is_fallback": True},
]


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
