import hashlib
import hmac
import os
import time
from collections.abc import Callable

import pytest
from sqlalchemy import event, text
from sqlalchemy.orm import Session

if not os.environ.get("DATABASE_URL"):
    pytest.exit("DATABASE_URL is required for DB-backed tests; see RUNBOOK.md section 5")

# These must exist before importing app modules; pydantic-settings reads them
# at import time.
os.environ.setdefault("ELEVENLABS_WEBHOOK_SECRET", "test_secret_for_pytest")

from fastapi.testclient import TestClient  # noqa: E402

from app import main as main_module  # noqa: E402
from app import webhook as webhook_module  # noqa: E402
from app.db import engine, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base  # noqa: E402


@pytest.fixture(scope="session")
def _prepared_schema():
    # Create tables once per session. Per-test isolation comes from nested
    # SAVEPOINTs below, not from dropping tables.
    with engine.begin() as connection:
        Base.metadata.create_all(bind=connection)
        connection.execute(text("ALTER TABLE tickets ALTER COLUMN intent DROP NOT NULL"))
    yield


@pytest.fixture
def db_connection(_prepared_schema):
    connection = engine.connect()
    outer = connection.begin()
    try:
        yield connection
    finally:
        outer.rollback()
        connection.close()


@pytest.fixture
def test_session_factory(db_connection):
    """Create sessions bound to one connection with nested SAVEPOINT rollback.

    Any `db.commit()` inside the handler commits to the SAVEPOINT, which is
    rolled back when the test ends. The outer transaction is always rolled
    back, so nothing persists.
    """

    def _make_session() -> Session:
        session = Session(bind=db_connection, expire_on_commit=False)
        nested = db_connection.begin_nested()

        @event.listens_for(session, "after_transaction_end")
        def _restart_savepoint(sess, trans):
            nonlocal nested
            if not nested.is_active:
                nested = db_connection.begin_nested()

        return session

    return _make_session


@pytest.fixture
def db_session(test_session_factory):
    session = test_session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main_module, "init_db", lambda: None)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def db_client(test_session_factory, monkeypatch):
    def _override_get_db():
        session = test_session_factory()
        try:
            yield session
        finally:
            session.close()

    monkeypatch.setattr(main_module, "init_db", lambda: None)
    monkeypatch.setattr(webhook_module, "SessionLocal", test_session_factory)
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
