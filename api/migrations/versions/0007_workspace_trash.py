"""workspace trash: deleted_at and deleted_by

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-10
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("workspaces", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "workspaces",
        sa.Column("deleted_by", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("workspaces", "deleted_by")
    op.drop_column("workspaces", "deleted_at")
