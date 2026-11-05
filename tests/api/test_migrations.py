import importlib.util
from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import text

import api.models  # noqa: F401
from api.db import Base
from api.models import Run

MIGRATION = Path(__file__).resolve().parents[2] / "api/migrations/versions/0006_rename_require_params.py"


def load_0006():
    spec = importlib.util.spec_from_file_location("migration_0006", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migrations_match_models(db):
    assert compare_metadata(MigrationContext.configure(db.connection()), Base.metadata) == []


def test_0006_renames_the_require_keys_and_keeps_their_values(db, make_user, make_workspace, make_simulation):
    user = make_user("ana@x.com")
    ws = make_workspace("a", [(user, "analyst")])
    simulation = make_simulation(ws, user)
    simulation.config = {"require_significance": False, "require_good_fit": True, "p_value_threshold": 0.1}
    run = Run(
        workspace_id=ws.id,
        simulation_id=simulation.id,
        created_by=user.id,
        status="succeeded",
        config={"require_good_fit": False},
        inputs={},
        confirmed_warnings=[],
    )
    db.add(run)
    db.flush()
    migration = load_0006()

    for sql in migration.statements(migration.RENAMES):
        db.execute(text(sql))
    db.refresh(simulation)
    db.refresh(run)

    assert simulation.config == {
        "require_statistical_significance": False,
        "require_model_fit": True,
        "p_value_threshold": 0.1,
    }
    assert run.config == {"require_model_fit": False}
