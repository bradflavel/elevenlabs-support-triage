import json
import uuid
from typing import Any

import pytest
from sqlalchemy import select

import app.webhook as webhook_module
from app.enums import INTENT_REQUIRED_FIELD
from app.models import ExtractionStatus, Intent, Ticket
from app.webhook import sanitize_summary


def _make_payload(
    conversation_id: str | None = None,
    intent: str | None = "billing",
    billing_issue_type: str | None = "charge_dispute",
    summary: str = "Caller disputes a charge that they do not recognize.",
    ambiguity_flag: bool = False,
    include_metadata: bool = True,
    extra_dc: dict[str, Any] | None = None,
) -> dict[str, Any]:
    conv_id = conversation_id or f"conv_{uuid.uuid4().hex[:10]}"
    dc: dict[str, Any] = {"summary": summary, "ambiguity_flag": ambiguity_flag}
    if intent is not None:
        dc["intent"] = intent
    if billing_issue_type is not None:
        dc["billing_issue_type"] = billing_issue_type
    if extra_dc:
        dc.update(extra_dc)

    payload: dict[str, Any] = {
        "type": "post_call_transcription",
        "event_timestamp": 1739000000,
        "data": {
            "agent_id": "agent_test",
            "conversation_id": conv_id,
            "analysis": {"data_collection_results": dc},
        },
    }
    if include_metadata:
        payload["data"]["metadata"] = {
            "start_time_unix_secs": 1738999900,
            "call_duration_secs": 75,
        }
    return payload


def _post(client, body: str, sig: str | None):
    headers = {"content-type": "application/json"}
    if sig is not None:
        headers["elevenlabs-signature"] = sig
    return client.post("/webhooks/elevenlabs", content=body, headers=headers)


def _fetch(db_session, conversation_id: str) -> Ticket:
    return db_session.execute(
        select(Ticket).where(Ticket.conversation_id == conversation_id)
    ).scalar_one()


def _make_intent_payload(intent: Intent, subtype_value: str | None, summary: str) -> dict[str, Any]:
    extra_dc: dict[str, Any] = {}
    billing_issue_type = None
    required_field = INTENT_REQUIRED_FIELD.get(intent)

    if required_field == "billing_issue_type":
        billing_issue_type = subtype_value
    elif required_field is not None and subtype_value is not None:
        extra_dc[required_field] = subtype_value

    return _make_payload(
        intent=intent.value,
        billing_issue_type=billing_issue_type,
        summary=summary,
        extra_dc=extra_dc or None,
    )


# ---------------------------------------------------------------------------
# Signature / transport contract
# ---------------------------------------------------------------------------


def test_missing_signature_returns_401_without_creating_session(client, monkeypatch):
    monkeypatch.setattr(
        webhook_module,
        "SessionLocal",
        lambda: (_ for _ in ()).throw(AssertionError("SessionLocal should not be called")),
    )
    body = json.dumps(_make_payload())
    assert _post(client, body, sig=None).status_code == 401


def test_bad_signature_returns_401_without_creating_session(client, monkeypatch):
    monkeypatch.setattr(
        webhook_module,
        "SessionLocal",
        lambda: (_ for _ in ()).throw(AssertionError("SessionLocal should not be called")),
    )
    body = json.dumps(_make_payload())
    response = _post(client, body, sig="t=1234567890,v0=deadbeef")
    assert response.status_code == 401


def test_valid_signature_non_json_body_returns_400_without_creating_session(
    client, webhook_secret, sign_body, monkeypatch
):
    monkeypatch.setattr(
        webhook_module,
        "SessionLocal",
        lambda: (_ for _ in ()).throw(AssertionError("SessionLocal should not be called")),
    )
    body = "this is not json"
    response = _post(client, body, sig=sign_body(body, webhook_secret))
    assert response.status_code == 400


@pytest.mark.parametrize(
    "payload",
    [
        {"data": {"agent_id": "x", "analysis": {"data_collection_results": {}}}},
        {"data": {"conversation_id": "conv_missing_agent", "analysis": {"data_collection_results": {}}}},
        {"data": {"agent_id": "x", "conversation_id": "conv_missing_analysis"}},
    ],
)
def test_missing_transport_fields_return_422_without_creating_session(
    client, webhook_secret, sign_body, monkeypatch, payload
):
    monkeypatch.setattr(
        webhook_module,
        "SessionLocal",
        lambda: (_ for _ in ()).throw(AssertionError("SessionLocal should not be called")),
    )
    body = json.dumps(payload)
    response = _post(client, body, sig=sign_body(body, webhook_secret))
    assert response.status_code == 422


def test_valid_payload_with_session_creation_failure_returns_500(
    client, webhook_secret, sign_body, monkeypatch
):
    monkeypatch.setattr(
        webhook_module,
        "SessionLocal",
        lambda: (_ for _ in ()).throw(RuntimeError("db unavailable")),
    )
    body = json.dumps(_make_payload())
    response = _post(client, body, sig=sign_body(body, webhook_secret))
    assert response.status_code == 500


# ---------------------------------------------------------------------------
# Persistence + idempotency
# ---------------------------------------------------------------------------


def test_complete_billing_payload_persists_row(db_client, webhook_secret, sign_body, db_session):
    payload = _make_payload()
    body = json.dumps(payload)
    response = _post(db_client, body, sig=sign_body(body, webhook_secret))

    assert response.status_code == 200
    row = _fetch(db_session, payload["data"]["conversation_id"])
    assert row.intent == Intent.BILLING
    assert row.extraction_status == ExtractionStatus.COMPLETE
    assert row.extracted_data["billing_issue_type"] == "charge_dispute"
    assert row.raw_payload["data"]["conversation_id"] == payload["data"]["conversation_id"]
    assert row.call_started_at is not None
    assert row.call_ended_at is not None


def test_replay_is_idempotent(db_client, webhook_secret, sign_body, db_session):
    payload = _make_payload()
    body = json.dumps(payload)
    sig = sign_body(body, webhook_secret)

    r1 = _post(db_client, body, sig)
    r2 = _post(db_client, body, sig)

    assert r1.status_code == 200
    assert r2.status_code == 200
    rows = (
        db_session.execute(
            select(Ticket).where(Ticket.conversation_id == payload["data"]["conversation_id"])
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1


# ---------------------------------------------------------------------------
# Extraction-status derivation
# ---------------------------------------------------------------------------


def test_missing_billing_issue_type_is_partial(db_client, webhook_secret, sign_body, db_session):
    payload = _make_payload(billing_issue_type=None)
    body = json.dumps(payload)
    response = _post(db_client, body, sig=sign_body(body, webhook_secret))

    assert response.status_code == 200
    row = _fetch(db_session, payload["data"]["conversation_id"])
    assert row.intent == Intent.BILLING
    assert row.extraction_status == ExtractionStatus.PARTIAL


def test_ambiguity_flag_preserves_intent_and_sets_needs_review(
    db_client, webhook_secret, sign_body, db_session
):
    payload = _make_payload(ambiguity_flag=True)
    body = json.dumps(payload)
    response = _post(db_client, body, sig=sign_body(body, webhook_secret))

    assert response.status_code == 200
    row = _fetch(db_session, payload["data"]["conversation_id"])
    assert row.intent == Intent.BILLING
    assert row.extraction_status == ExtractionStatus.NEEDS_REVIEW


def test_unknown_intent_is_null_partial(db_client, webhook_secret, sign_body, db_session):
    payload = _make_payload(intent="weather_forecast", billing_issue_type=None)
    body = json.dumps(payload)
    response = _post(db_client, body, sig=sign_body(body, webhook_secret))

    assert response.status_code == 200
    row = _fetch(db_session, payload["data"]["conversation_id"])
    assert row.intent is None
    assert row.extraction_status == ExtractionStatus.PARTIAL


def test_missing_intent_is_null_partial(db_client, webhook_secret, sign_body, db_session):
    payload = _make_payload(intent=None, billing_issue_type=None)
    body = json.dumps(payload)
    response = _post(db_client, body, sig=sign_body(body, webhook_secret))

    assert response.status_code == 200
    row = _fetch(db_session, payload["data"]["conversation_id"])
    assert row.intent is None
    assert row.extraction_status == ExtractionStatus.PARTIAL


@pytest.mark.parametrize(
    ("intent", "valid_value", "bogus_value"),
    [
        (Intent.BILLING, "charge_dispute", "bogus_billing_type"),
        (Intent.TECHNICAL, "login", "bogus_technical_type"),
        (Intent.ACCOUNT_CHANGE, "email", "bogus_account_change_type"),
        (Intent.CANCELLATION, "price", "bogus_cancellation_reason"),
    ],
)
def test_intent_specific_enum_values_are_enforced(
    db_client,
    webhook_secret,
    sign_body,
    db_session,
    intent: Intent,
    valid_value: str,
    bogus_value: str,
):
    valid_payload = _make_intent_payload(
        intent,
        valid_value,
        summary=f"Valid {intent.value} issue for enum enforcement",
    )
    valid_body = json.dumps(valid_payload)
    valid_response = _post(db_client, valid_body, sig=sign_body(valid_body, webhook_secret))

    assert valid_response.status_code == 200
    valid_row = _fetch(db_session, valid_payload["data"]["conversation_id"])
    assert valid_row.intent == intent
    assert valid_row.extraction_status == ExtractionStatus.COMPLETE

    invalid_payload = _make_intent_payload(
        intent,
        bogus_value,
        summary=f"Invalid {intent.value} issue for enum enforcement",
    )
    invalid_body = json.dumps(invalid_payload)
    invalid_response = _post(db_client, invalid_body, sig=sign_body(invalid_body, webhook_secret))

    assert invalid_response.status_code == 200
    invalid_row = _fetch(db_session, invalid_payload["data"]["conversation_id"])
    assert invalid_row.intent == intent
    assert invalid_row.extraction_status == ExtractionStatus.PARTIAL


# ---------------------------------------------------------------------------
# Data Collection value-unwrapping
# ---------------------------------------------------------------------------


def test_value_wrapped_data_collection_fields_are_unwrapped(
    db_client, webhook_secret, sign_body, db_session
):
    # Analyzer sometimes returns {"value": X, "rationale": "..."} objects
    payload = _make_payload()
    dc = payload["data"]["analysis"]["data_collection_results"]
    payload["data"]["analysis"]["data_collection_results"] = {
        "intent": {"value": "billing", "rationale": "caller said billing"},
        "billing_issue_type": {"value": "charge_dispute", "rationale": "disputed charge"},
        "summary": {"value": dc["summary"]},
        "ambiguity_flag": {"value": False},
    }
    body = json.dumps(payload)
    response = _post(db_client, body, sig=sign_body(body, webhook_secret))

    assert response.status_code == 200
    row = _fetch(db_session, payload["data"]["conversation_id"])
    assert row.intent == Intent.BILLING
    assert row.extraction_status == ExtractionStatus.COMPLETE


# ---------------------------------------------------------------------------
# Summary sanitizer
# ---------------------------------------------------------------------------


def test_summary_pii_is_sanitized_end_to_end(db_client, webhook_secret, sign_body, db_session):
    payload = _make_payload(
        summary="Caller john.doe@example.com at 555-123-4567 account 987654321 disputes charge"
    )
    body = json.dumps(payload)
    response = _post(db_client, body, sig=sign_body(body, webhook_secret))

    assert response.status_code == 200
    row = _fetch(db_session, payload["data"]["conversation_id"])
    assert row.summary is not None
    assert "john.doe@example.com" not in row.summary
    assert "555-123-4567" not in row.summary
    assert "987654321" not in row.summary
    assert "[redacted" in row.summary


def test_sanitize_summary_unit_email():
    out = sanitize_summary("Contact test.user+tag@example.co.uk for details")
    assert "test.user+tag@example.co.uk" not in out
    assert "[redacted email]" in out


def test_sanitize_summary_unit_phone():
    out = sanitize_summary("Call (555) 123-4567 back tomorrow about charge")
    assert "555" not in out or "[redacted" in out
    assert "[redacted phone]" in out


def test_sanitize_summary_unit_account_number():
    out = sanitize_summary("Account 123456789 is the one in question for billing")
    assert "123456789" not in out
    assert "[redacted" in out


def test_sanitize_summary_unit_fallback_when_empty_after_redaction():
    out = sanitize_summary("john@x.io 555-123-4567")
    # After redacting everything, residual is too short; fall back to placeholder
    assert out is not None
    assert "withheld for privacy" in out


def test_sanitize_summary_unit_none_passthrough():
    assert sanitize_summary(None) is None
    assert sanitize_summary("") == ""
