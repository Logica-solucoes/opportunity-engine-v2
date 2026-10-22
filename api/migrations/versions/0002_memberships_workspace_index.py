"""index memberships.workspace_id

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-22
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_memberships_workspace_id", "memberships", ["workspace_id"])


def downgrade() -> None:
    op.drop_index("ix_memberships_workspace_id", table_name="memberships")
