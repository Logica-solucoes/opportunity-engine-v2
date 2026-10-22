import os

from sqlalchemy import create_engine, make_url, text

target = make_url(os.environ["DATABASE_URL"])
server = create_engine(target.set(database="postgres"), isolation_level="AUTOCOMMIT")
with server.connect() as conn:
    if not conn.scalar(text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": target.database}):
        conn.execute(text(f'CREATE DATABASE "{target.database}"'))
