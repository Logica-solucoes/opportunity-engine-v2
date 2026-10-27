"""runs and their log lines

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-27
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

STATUSES = ("queued", "running", "succeeded", "inconclusive", "failed")


def upgrade() -> None:
    op.create_table(
        "runs",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("workspace_id", sa.BigInteger(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "simulation_id", sa.BigInteger(), sa.ForeignKey("simulations.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("status", sa.Enum(*STATUSES, name="run_status"), nullable=False),
        sa.Column("config", postgresql.JSONB(), nullable=False),
        sa.Column("inputs", postgresql.JSONB(), nullable=False),
        sa.Column("confirmed_warnings", postgresql.JSONB(), nullable=False),
        sa.Column("engine_version", sa.Text(), nullable=True),
        sa.Column("results_uri", sa.Text(), nullable=True),
        sa.Column("summary", postgresql.JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_by", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_by", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_runs_workspace_id", "runs", ["workspace_id"])
    op.create_index("ix_runs_simulation_id", "runs", ["simulation_id"])
    op.create_index(
        "runs_one_active_per_simulation",
        "runs",
        ["simulation_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )
    op.create_table(
        "run_logs",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("run_id", sa.BigInteger(), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("level", sa.Text(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
    )
    op.create_index("ix_run_logs_run_id", "run_logs", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_run_logs_run_id", table_name="run_logs")
    op.drop_table("run_logs")
    op.drop_index("runs_one_active_per_simulation", table_name="runs")
    op.drop_index("ix_runs_simulation_id", table_name="runs")
    op.drop_index("ix_runs_workspace_id", table_name="runs")
    op.drop_table("runs")
    sa.Enum(name="run_status").drop(op.get_bind())
