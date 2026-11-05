"""rename the provisional require_* params to the engine's names

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-05
"""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

# keeps the values: a saved False may be the analyst's choice, and nothing tells it from a default
RENAMES = {"require_significance": "require_statistical_significance", "require_good_fit": "require_model_fit"}


def statements(renames: dict[str, str]) -> list[str]:
    return [
        f"UPDATE {table} SET config = (config - '{old}') || jsonb_build_object('{new}', config -> '{old}') "
        f"WHERE config ? '{old}'"
        for table in ("simulations", "runs")
        for old, new in renames.items()
    ]


def upgrade() -> None:
    for sql in statements(RENAMES):
        op.execute(sql)


def downgrade() -> None:
    for sql in statements({new: old for old, new in RENAMES.items()}):
        op.execute(sql)
