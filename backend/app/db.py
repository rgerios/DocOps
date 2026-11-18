from sqlalchemy import JSON, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings

_sqlite = settings.database_url.startswith("sqlite")
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    **({"connect_args": {"check_same_thread": False}} if _sqlite else {"pool_size": 10, "max_overflow": 20}),
)
SessionLocal = sessionmaker(engine, expire_on_commit=False)

# JSONB no Postgres, JSON nos demais (testes com SQLite)
JSONType = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
