"""add scraper_templates.learned_route

Adds a nullable JSON column that stores a replayable navigation route learned
by the CUA route learner after a CUA-only success. The LEARNED_ROUTE strategy
replays it cheaply on future visits to the same domain.

Revision ID: a1b2c3d4e5f6
Revises: 20197da623db
Create Date: 2026-06-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "20197da623db"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "scraper_templates",
        sa.Column("learned_route", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("scraper_templates", "learned_route")
