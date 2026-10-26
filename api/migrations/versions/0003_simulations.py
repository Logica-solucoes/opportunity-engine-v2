"""simulations and their uploaded files

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-26
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "simulations",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("workspace_id", sa.BigInteger(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("config", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("validation", postgresql.JSONB(), nullable=True),
        sa.Column("created_by", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_simulations_workspace_id", "simulations", ["workspace_id"])
    op.create_table(
        "simulation_files",
        sa.Column(
            "simulation_id",
            sa.BigInteger(),
            sa.ForeignKey("simulations.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "kind",
            sa.Enum("investment", "performance", "trends", name="simulation_file_kind"),
            primary_key=True,
        ),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("columns", postgresql.JSONB(), nullable=False),
        sa.Column("uploaded_by", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("simulation_files")
    op.drop_index("ix_simulations_workspace_id", table_name="simulations")
    op.drop_table("simulations")
    sa.Enum(name="simulation_file_kind").drop(op.get_bind())
