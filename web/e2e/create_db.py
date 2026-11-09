import os

from sqlalchemy import create_engine, make_url, text

target = make_url(os.environ["DATABASE_URL"])
assert target.database.endswith("_e2e"), "refusing to drop a database that is not the e2e one"
server = create_engine(target.set(database="postgres"), isolation_level="AUTOCOMMIT")
with server.connect() as conn:
    # a fresh database per run: the tables paginate, and rows left by earlier runs push new ones off the page
    conn.execute(text(f'DROP DATABASE IF EXISTS "{target.database}" WITH (FORCE)'))
    conn.execute(text(f'CREATE DATABASE "{target.database}"'))
