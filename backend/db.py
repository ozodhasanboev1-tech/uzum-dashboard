"""
Supabase/Postgres ulanishi. DATABASE_URL muhit o'zgaruvchisidan olinadi.

Supabase loyihasi yaratilgach, "Project Settings -> Database -> Connection string ->
URI" bo'limidan olingan qatorni shu yerga (yoki Railway/Render environment
variables ichiga) DATABASE_URL nomi bilan qo'ying. Masalan:

postgresql://postgres:PASSWORD@db.xxxxxxxx.supabase.co:5432/postgres
"""

import os
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/postgres")

engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_size=5, max_overflow=5)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


@contextmanager
def get_conn():
    """`with get_conn() as conn:` -> SQLAlchemy connection, avtomatik commit/rollback."""
    conn = engine.connect()
    trans = conn.begin()
    try:
        yield conn
        trans.commit()
    except Exception:
        trans.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """schema.sql faylini ishga tushirib, jadvallarni yaratadi (agar mavjud bo'lmasa)."""
    schema_path = os.path.join(os.path.dirname(__file__), "..", "db", "schema.sql")
    with open(schema_path, "r", encoding="utf-8") as f:
        sql = f.read()
    with engine.begin() as conn:
        for statement in sql.split(";"):
            statement = statement.strip()
            if statement:
                conn.execute(text(statement))
