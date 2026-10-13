"""Database engine and session helpers (SQLite via SQLModel)."""

from collections.abc import Iterator
from pathlib import Path

from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

from app import config

_engine: Engine | None = None


def make_engine(url: str | None = None) -> Engine:
    url = url or config.DATABASE_URL
    connect_args = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
        if url.startswith("sqlite:///"):
            Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    return create_engine(url, connect_args=connect_args)


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = make_engine()
    return _engine


def init_db(engine: Engine) -> None:
    from app import models  # noqa: F401  registers the tables

    SQLModel.metadata.create_all(engine)


def session_scope(engine: Engine) -> Iterator[Session]:
    with Session(engine) as session:
        yield session
