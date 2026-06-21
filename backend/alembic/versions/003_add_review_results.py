"""add review_results and extend review_jobs/files

Revision ID: 003
Revises: 002
Create Date: 2026-06-21
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("review_jobs", sa.Column("celery_task_id", sa.String(255), nullable=True))
    op.add_column("review_jobs", sa.Column("error_message", sa.Text(), nullable=True))

    op.add_column("review_files", sa.Column("parse_error", sa.Text(), nullable=True))
    op.add_column("review_files", sa.Column("total_pages", sa.Integer(), nullable=True))

    op.create_table(
        "review_results",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column(
            "file_id",
            sa.String(36),
            sa.ForeignKey("review_files.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("category", sa.String(30), nullable=False),
        sa.Column("detected_text", sa.Text(), nullable=False),
        sa.Column("suggestion", sa.Text(), nullable=True),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("context", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("(datetime('now'))"),
        ),
    )


def downgrade() -> None:
    op.drop_table("review_results")
