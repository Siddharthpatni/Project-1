"""add job_items tender directory fields

Adds the denormalized projection columns the public browse-by-domain tender
directory queries (tender_title, tender_reference, deadline) plus a composite
index on (domain, status, deadline). Existing rows are backfilled best-effort
from their extraction_records.fields_json so the directory is populated
immediately rather than only for newly-extracted tenders.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-06-19 00:00:00.000000

"""
import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("job_items", sa.Column("tender_title", sa.String(), nullable=True))
    op.add_column("job_items", sa.Column("tender_reference", sa.String(), nullable=True))
    op.add_column("job_items", sa.Column("deadline", sa.DateTime(), nullable=True))
    op.create_index(
        "ix_job_items_directory", "job_items", ["domain", "status", "deadline"], unique=False
    )
    _backfill()


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_job_items_directory", table_name="job_items")
    op.drop_column("job_items", "deadline")
    op.drop_column("job_items", "tender_reference")
    op.drop_column("job_items", "tender_title")


def _backfill() -> None:
    """Populate the new columns from existing extraction records (best-effort).

    Never fails the migration: a malformed row is simply skipped. The directory
    treats a missing deadline as "unknown" (shown, never expired), so partial
    backfill coverage degrades gracefully.
    """
    from app.document_extractor.dates import parse_deadline

    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT job_item_id, fields_json FROM extraction_records")
    ).fetchall()

    update = sa.text(
        "UPDATE job_items SET tender_title = :title, "
        "tender_reference = :reference, deadline = :deadline WHERE id = :id"
    )
    for job_item_id, fields_json in rows:
        try:
            fields = json.loads(fields_json or "{}")
        except (TypeError, ValueError):
            continue
        conn.execute(update, {
            "id": job_item_id,
            "title": (fields.get("titel") or None),
            "reference": (fields.get("vergabenummer") or None),
            "deadline": parse_deadline(fields.get("abgabefrist")),
        })
