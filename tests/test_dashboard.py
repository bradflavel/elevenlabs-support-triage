import json

from tests.test_webhook import _make_payload, _post


def test_root_redirects_to_tickets(db_client):
    response = db_client.get("/", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/tickets"


def test_tickets_empty_state(db_client):
    response = db_client.get("/tickets")
    assert response.status_code == 200
    assert "No tickets yet" in response.text


def test_tickets_renders_row_after_webhook(db_client, webhook_secret, sign_body):
    payload = _make_payload(summary="Caller disputes a charge they did not recognize.")
    body = json.dumps(payload)
    _post(db_client, body, sig=sign_body(body, webhook_secret))

    response = db_client.get("/tickets")
    assert response.status_code == 200
    assert "billing" in response.text
    assert "complete" in response.text
    assert "Caller disputes a charge" in response.text


def test_tickets_does_not_leak_conversation_id_or_raw_payload(
    db_client, webhook_secret, sign_body
):
    payload = _make_payload()
    payload["data"]["analysis"]["data_collection_results"]["hidden_debug_field"] = (
        "SHOULD_NEVER_APPEAR_ON_DASHBOARD"
    )
    body = json.dumps(payload)
    _post(db_client, body, sig=sign_body(body, webhook_secret))

    response = db_client.get("/tickets")
    assert response.status_code == 200
    # conversation_id must not be rendered (privacy rule)
    assert payload["data"]["conversation_id"] not in response.text
    # Raw payload / extracted_data JSONB must not be rendered either
    assert "SHOULD_NEVER_APPEAR_ON_DASHBOARD" not in response.text


def test_tickets_intent_filter_excludes_non_matching_rows(db_client, webhook_secret, sign_body):
    p1 = _make_payload(
        intent="billing",
        billing_issue_type="charge_dispute",
        summary="Billing summary should stay visible",
    )
    p2 = _make_payload(
        intent="cancellation",
        billing_issue_type=None,
        summary="Cancellation summary should be filtered out",
        extra_dc={"cancellation_reason": "price"},
    )
    for p in [p1, p2]:
        body = json.dumps(p)
        _post(db_client, body, sig=sign_body(body, webhook_secret))

    filtered = db_client.get("/tickets?intent=billing")
    assert filtered.status_code == 200
    assert "Billing summary should stay visible" in filtered.text
    assert "Cancellation summary should be filtered out" not in filtered.text


def test_tickets_renders_unknown_for_null_intent(db_client, webhook_secret, sign_body):
    payload = _make_payload(
        intent=None,
        billing_issue_type=None,
        summary="Caller gave context but intent extraction failed",
    )
    body = json.dumps(payload)
    _post(db_client, body, sig=sign_body(body, webhook_secret))

    response = db_client.get("/tickets")
    assert response.status_code == 200
    assert "unknown" in response.text
    assert "partial" in response.text


def test_tickets_needs_review_visual_flag(db_client, webhook_secret, sign_body):
    payload = _make_payload(ambiguity_flag=True)
    body = json.dumps(payload)
    _post(db_client, body, sig=sign_body(body, webhook_secret))

    response = db_client.get("/tickets")
    assert response.status_code == 200
    assert "row-needs_review" in response.text
    assert "status-needs_review" in response.text
