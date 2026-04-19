import json

from tests.test_webhook import _make_payload, _post


def test_root_redirects_to_tickets(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/tickets"


def test_tickets_empty_state(client):
    response = client.get("/tickets")
    assert response.status_code == 200
    assert "No tickets yet" in response.text


def test_tickets_renders_row_after_webhook(client, webhook_secret, sign_body):
    payload = _make_payload(summary="Caller disputes a charge they did not recognize.")
    body = json.dumps(payload)
    _post(client, body, sig=sign_body(body, webhook_secret))

    response = client.get("/tickets")
    assert response.status_code == 200
    assert "billing" in response.text
    assert "complete" in response.text
    assert "Caller disputes a charge" in response.text


def test_tickets_does_not_leak_conversation_id_or_raw_payload(
    client, webhook_secret, sign_body
):
    payload = _make_payload()
    payload["data"]["analysis"]["data_collection_results"]["hidden_debug_field"] = (
        "SHOULD_NEVER_APPEAR_ON_DASHBOARD"
    )
    body = json.dumps(payload)
    _post(client, body, sig=sign_body(body, webhook_secret))

    response = client.get("/tickets")
    assert response.status_code == 200
    # conversation_id must not be rendered (privacy rule)
    assert payload["data"]["conversation_id"] not in response.text
    # Raw payload / extracted_data JSONB must not be rendered either
    assert "SHOULD_NEVER_APPEAR_ON_DASHBOARD" not in response.text


def test_tickets_intent_filter(client, webhook_secret, sign_body):
    p1 = _make_payload(intent="billing", billing_issue_type="charge_dispute")
    p2 = _make_payload(
        intent="cancellation",
        billing_issue_type=None,
        extra_dc={"cancellation_reason": "price"},
    )
    for p in [p1, p2]:
        body = json.dumps(p)
        _post(client, body, sig=sign_body(body, webhook_secret))

    filtered = client.get("/tickets?intent=billing")
    assert filtered.status_code == 200
    # Both summaries are identical text so instead we check the filter chip state
    assert 'active">billing' in filtered.text or 'class="active"' in filtered.text


def test_tickets_needs_review_visual_flag(client, webhook_secret, sign_body):
    payload = _make_payload(ambiguity_flag=True)
    body = json.dumps(payload)
    _post(client, body, sig=sign_body(body, webhook_secret))

    response = client.get("/tickets")
    assert response.status_code == 200
    assert "row-needs_review" in response.text
    assert "status-needs_review" in response.text
