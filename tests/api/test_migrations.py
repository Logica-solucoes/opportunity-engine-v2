from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

import api.models  # noqa: F401
from api.db import Base


def test_migrations_match_models(db):
    assert compare_metadata(MigrationContext.configure(db.connection()), Base.metadata) == []
