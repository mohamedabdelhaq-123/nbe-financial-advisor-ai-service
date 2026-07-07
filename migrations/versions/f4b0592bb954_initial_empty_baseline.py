"""initial_empty_baseline

Revision ID: f4b0592bb954
Revises:
Create Date: 2026-07-07 09:30:48.295459

Baseline: no tables yet. The AI service starts with an empty schema.
When the AI team adds the first model, they run:
    alembic revision --autogenerate -m "add_<model>_table"
and Alembic will detect only AI-service models (not Django's).

SCOPE BOUNDARY: never alter Django's tables from this migration tree.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f4b0592bb954'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
