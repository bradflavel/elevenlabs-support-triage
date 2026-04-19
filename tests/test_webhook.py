import json
import uuid
from typing import Any

from sqlalchemy import select

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


# ---------------------------------------------------------------------------
# Signature / transport contract
# ---------------------------------------------------------------------------


def test_missing_signature_returns_401(client):
    body = json.dumps(_make_payload())
    assert _post(client, body, sig=None).status_code == 401


def test_bad_signature_returns_401(client):
    body = json.dumps(_make_payload())
    response = _post(client, body, sig="t=1234567890,v0=deadbeef")
    assert response.status_code == 401


def test_valid_signature_non_json_body_returns_400(client, webhook_secret, sign_body):
    body = "this is not json"
    response = _post(client, body, sig=sign_body(body, webhook_secret))
    assert response.status_code == 400


def test_missing_transport_fields_returns_422(client, webhook_secret, sign_body):
    # No `data.conversation_id` -> Pydantic raises -> 422
    body = json.dumps({"data": {"agent_id": "x", "analysis": {"data_collection_results": {}}}})
    response = _post(client, body, sig=sign_body(body, webhook_secret))
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Persistence + idempotency
# ---------------------------------------------------------------------------


def test_complete_billing_payload_persists_row(client, webhook_secret, sign_body, db_session):
    payload = _make_payload()
    body = json.dumps(payload)
    response = _post(client, body, sig=sign_body(body, webhook_secret))

    assert response.status_code == 200
    row = _fetch(db_session, payload["data"]["conversation_id"])
    assert row.intent == Intent.BILLING
    assert row.extraction_status == ExtractionStatus.COMPLETE
    assert row.extracted_data["billing_issue_type"] == "charge_dispute"
    assert row.raw_payload["data"]["conversation_id"] == payload["data"]["conversation_id"]
    assert row.call_started_at is not None
    assert row.call_ended_at is not None


def test_replay_is_idempotent(client, webhook_secret, sign_body, db_session):
    payload = _make_payload()
    body = json.dumps(payload)
    sig = sign_body(body, webhook_secret)

    r1 = _post(client, body, sig)
    r2 = _post(client, body, sig)

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


def test_missing_billing_issue_type_is_partial(client, webhook_secret, sign_body, db_session):
    payload = _make_payload(billing_issue_type=None)
    body = json.dumps(payload)
    response = _post(client, body, sig=sign_body(body, webhook_secret))

    assert response.status_code == 200
    row = _fetch(db_session, payload["data"]["conversation_id"])
    assert row.intent == Intent.BILLING
    assert row.extraction_status == ExtractionStatus.PARTIAL


def test_ambiguity_flag_sets_needs_review(client, webhook_secret, sign_body, db_session):
    payload = _make_payload(ambiguity_flag=True)
    body = json.dumps(payload)
    response = _post(client, body, sig=sign_body(body, webhook_secret))

    assert response.status_code == 200
    row = _fetch(db_session, payload["data"]["conversation_id"])
    assert row.intent == Intent.NEEDS_REVIEW
    assert row.extraction_status == ExtractionStatus.NEEDS_REVIEW


def test_unknown_intent_maps_to_other_partial(client, webhook_secret, sign_body, db_session):
    # "weather_forecast" is outside our enum but confident -> other + partial
    payload = _make_payload(intent="weather_forecast", billing_issue_type=None)
    body = json.dumps(payload)
    response = _post(client, body, sig=sign_body(body, webhook_secret))

    assert response.status_code == 200
    row = _fetch(db_session, payload["data"]["conversation_id"])
    assert row.intent == Intent.OTHER
    assert row.extraction_status == ExtractionStatus.PARTIAL


def test_missing_intent_is_needs_review(client, webhook_secret, sign_body, db_session):
    payload = _make_payload(intent=None, billing_issue_type=None)
    body = json.dumps(payload)
    response = _post(client, body, sig=sign_body(body, webhook_secret))

    assert response.status_code == 200
    row = _fetch(db_session, payload["data"]["conversation_id"])
    assert row.intent == Intent.NEEDS_REVIEW
    assert row.extraction_status == ExtractionStatus.NEEDS_REVIEW


# ---------------------------------------------------------------------------
# Data Collection value-unwrapping
# ---------------------------------------------------------------------------


def test_value_wrapped_data_collection_fields_are_unwrapped(
    client, webhook_secret, sign_body, db_session
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
    response = _post(client, body, sig=sign_body(body, webhook_secret))

    assert response.status_code == 200
    row = _fetch(db_session, payload["data"]["conversation_id"])
    assert row.intent == Intent.BILLING
    assert row.extraction_status == ExtractionStatus.COMPLETE


# ---------------------------------------------------------------------------
# Summary sanitizer
# ---------------------------------------------------------------------------


def test_summary_pii_is_sanitized_end_to_end(client, webhook_secret, sign_body, db_session):
    payload = _make_payload(
        summary="Caller john.doe@example.com at 555-123-4567 account 987654321 disputes charge"
    )
    body = json.dumps(payload)
    response = _post(client, body, sig=sign_body(body, webhook_secret))

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
