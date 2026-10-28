"""usage view: runs per workspace, user and month

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-28
"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # the business month is São Paulo's: a run at 22:00 on the 31st belongs to that month, not the next
    op.execute(
        """
        CREATE VIEW usage AS
        SELECT
            workspace_id,
            created_by AS user_id,
            to_char(created_at AT TIME ZONE 'America/Sao_Paulo', 'YYYY-MM') AS month,
            count(*) FILTER (WHERE status = 'succeeded') AS succeeded,
            count(*) FILTER (WHERE status = 'inconclusive') AS inconclusive,
            count(*) FILTER (WHERE status = 'failed') AS failed,
            count(*) FILTER (WHERE status IN ('queued', 'running')) AS active,
            count(*) AS total,
            coalesce(sum(extract(epoch FROM finished_at - started_at)), 0)::bigint AS run_seconds
        FROM runs
        GROUP BY workspace_id, created_by, month
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW usage")
