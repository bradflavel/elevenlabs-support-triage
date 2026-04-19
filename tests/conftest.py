import hashlib
import hmac
import os
import time
from collections.abc import Callable

import pytest

# These must exist before importing app modules; pydantic-settings reads them
# at import time. Tests override get_db to use the fixture session, so the
# real DATABASE_URL still has to resolve to a running Postgres (dev DB).
os.environ.setdefault(
    "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/postgres"
)
os.environ.setdefault("ELEVENLABS_WEBHOOK_SECRET", "test_secret_for_pytest")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import event  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.db import engine, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base  # noqa: E402


@pytest.fixture(scope="session")
def _prepared_schema():
    # Create tables once per session. Per-test isolation comes from nested
    # SAVEPOINTs below, not from dropping tables.
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture
def db_session(_prepared_schema):
    """Per-test session with outer transaction + nested SAVEPOINT rollback.

    Any `db.commit()` inside the handler commits to the SAVEPOINT, which is
    rolled back when the test ends. The outer transaction is always rolled
    back, so nothing persists.
    """
    connection = engine.connect()
    outer = connection.begin()
    session = Session(bind=connection, expire_on_commit=False)
    nested = connection.begin_nested()

    @event.listens_for(session, "after_transaction_end")
    def _restart_savepoint(sess, trans):
        nonlocal nested
        if not nested.is_active:
            nested = connection.begin_nested()

    try:
        yield session
    finally:
        session.close()
        outer.rollback()
        connection.close()


@pytest.fixture
def client(db_session):
    def _override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def webhook_secret() -> str:
    return os.environ["ELEVENLABS_WEBHOOK_SECRET"]


@pytest.fixture
def sign_body() -> Callable[[str, str], str]:
    """Return a function that produces a valid elevenlabs-signature header.

    Matches the SDK's construct_event contract: `t=<ts>,v0=<hex_sha256_hmac>`
    where the HMAC is over `f"{ts}.{body}"` with the secret.
    """

    def _sign(body: str, secret: str, timestamp: int | None = None) -> str:
        ts = timestamp if timestamp is not None else int(time.time())
        message = f"{ts}.{body}".encode("utf-8")
        digest = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
        return f"t={ts},v0={digest}"

    return _sign
