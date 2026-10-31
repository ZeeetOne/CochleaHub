"""Request-scoped dependencies; overridden in tests (SQLite, fake object store)."""

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy.orm import Session

from cochleahub.db.session import SessionLocal
from cochleahub.storage.objects import ObjectStore


def get_session() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session


@lru_cache
def get_store() -> ObjectStore:
    return ObjectStore()
