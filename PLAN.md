# Customer Support Triage Voice Agent - Implementation Plan

## Context

Build a deployable voice-agent demo for customer-support triage, targeted as recruiter signal. An ElevenAgents agent handles inbound web-widget calls, routes across 4-5 intents (billing, technical issue, account change, cancellation, other), and uses the platform's built-in Data Collection analysis to extract structured fields. A post-call webhook fires to a FastAPI backend, which verifies the HMAC signature, upserts a ticket row to Postgres keyed by `conversation_id`, and exposes a public read-only `/tickets` dashboard (Jinja2) showing curated, privacy-safe fields so a recruiter can click a link and see real extracted tickets.

The working directory is currently empty - this is a greenfield build. Total estimate: 4-5 days of focused work.

> This plan was revised after two written audits (see `PLAN_AUDIT.md`). Notable changes vs. v1: stricter webhook delivery contract (**200-only** success, per current ElevenLabs docs), JSON payload storage, privacy-safe dashboard, concrete Railway config, two separate Postgres services (prod + dev), explicit intent-mapping rule (`other` vs `needs_review`), `construct_event` called with the UTF-8-decoded raw body to match the current SDK example.
>
> **Companion docs**: operator setup checklist in [RUNBOOK.md](RUNBOOK.md); Data Collection field spec in [docs/data-collection-schema.md](docs/data-collection-schema.md). This file owns architecture and design; those own execution detail.

## Tech stack (confirmed)

- Python 3.11+
- **uv + `pyproject.toml`** for packaging/deps
- FastAPI (webhook endpoint + dashboard routes)
- ElevenAgents (agent + Data Collection + post-call webhooks)
- **Railway Postgres** - two separate Postgres services in one Railway project: `support-triage-db-prod` and `support-triage-db-dev`; tests run against dev by overriding the app session dependency and isolating each case with an outer transaction plus nested SAVEPOINTs
- SQLAlchemy + Pydantic (`extra = "allow"` on payload models)
- Jinja2 for `/tickets`
- `elevenlabs` Python SDK - use **`construct_event`** for HMAC verification
- Railway (native Python build via `Procfile` + `railway.toml`, no Dockerfile)
- ngrok for local webhook testing

Dropped from original brief: SQLite, Airtable, Docker, Twilio, React.

## Repo layout (target)

```
elevenagents-support-triage/
  pyproject.toml
  uv.lock
  Procfile
  railway.toml
  .env.example
  .gitignore
  README.md
  app/
    __init__.py
    main.py              # FastAPI app, route mounts, startup create_all
    config.py            # env parsing (pydantic-settings)
    db.py                # SQLAlchemy engine + session
    models.py            # Ticket ORM model
    schemas.py           # Pydantic webhook payload models (extra="allow")
    webhook.py           # POST /webhooks/elevenlabs (HMAC verify + upsert)
    dashboard.py         # GET / and GET /tickets (Jinja2)
    templates/
      tickets.html
  tests/
    conftest.py          # shared DB connection + nested SAVEPOINT rollback per test
    test_webhook.py      # signature verify + idempotency + partial extraction
    test_matrix.md       # Phase 1/2 extraction test matrix
  docs/
    agent-prompts.md     # system prompts for Phase 1 and Phase 2 agents
    data-collection-schema.md   # Data Collection field spec (paper first)
    ticket-schema.md            # DB schema spec (paper first)
```

## Data model

Ticket table carries **both** normalized columns (for indexing/filtering) and JSONB blobs (for resilience to payload evolution):

- `id` (uuid, pk)
- `conversation_id` (text, **unique**) - idempotency key
- `intent` (enum: `billing`, `technical`, `account_change`, `cancellation`, `other`, `needs_review`)
- `extraction_status` (enum: `complete`, `partial`, `needs_review`)
- `summary` (text, nullable) - short curated summary, sanitized before persistence/rendering because it is public-facing
- `created_at` (timestamptz, default now)
- `call_started_at` (timestamptz, nullable)
- `call_ended_at` (timestamptz, nullable)
- `extracted_data` (jsonb) - all Data Collection results, for future schema changes
- `raw_payload` (jsonb) - full webhook body, for debugging; never rendered on public dashboard

Pydantic payload model validates only the stable subset under `analysis.data_collection_results` and sets `model_config = ConfigDict(extra="allow")` so new fields don't break ingestion.

Because `summary` is shown on a public dashboard, the backend sanitizes it before persistence/rendering:

- redact email addresses
- redact phone numbers
- redact long account-number-like numeric tokens
- replace the result with `Caller described a support issue; details withheld for privacy.` if the redacted text is empty or no longer meaningful

This privacy sanitization is separate from extraction quality. Redacting `summary` must not change `extraction_status`.

## Webhook delivery contract (single source of truth)

- `401` - HMAC signature invalid or missing
- `400` - body is not valid JSON
- `422` - **transport-level** required fields missing from the parsed payload (see below)
- `200` - **only** after the row is durably persisted in Postgres
- `5xx` - transient server failure (DB unreachable, unexpected exception)

ElevenAgents retries on non-200. Because we upsert by `conversation_id`, retries are safe and desired - they are the recovery mechanism for transient failures, not a threat.

### 422 vs. persisted-partial - the distinction

Two different kinds of "missing field" exist, and they are handled differently:

- **Transport-level required fields** (the payload shape we depend on from ElevenLabs): `conversation_id`, `agent_id`, and the `analysis` block. If any of these are missing, the webhook is unusable - return **422**; no row is written. These are the trust boundary for ingestion; a 422 here means something is genuinely wrong with the delivery.
- **Data Collection extracted fields** (the things the LLM analyzer tried to pull out): these are allowed to be null or empty. The call happened, the platform delivered the payload correctly, but the analyzer didn't fill in every slot. **Persist the row with `extraction_status = partial`** and return **200**. Dashboard users can filter by `extraction_status` to see which tickets need human review.
- **Call timestamps** (`call_started_at`, `call_ended_at`): these are metadata, not trust-boundary fields. If they are present, persist them. If they are absent, store `null` and still return **200** as long as the transport-level fields above are valid.

The rule of thumb: 422 means "I can't trust this webhook"; partial means "I trust the webhook but the LLM didn't get everything." Which specific Data Collection fields must be non-null for `complete` vs. `partial` is defined in [docs/data-collection-schema.md](docs/data-collection-schema.md).

## Phase 1 - one intent end-to-end (2-3 days)

Goal: browser widget -> agent conversation -> post-call webhook -> verified and persisted -> row in Postgres -> visible at `/tickets`, for **billing only**.

Ordered steps:

1. **Read the docs**, including the dashboard quickstart. Talk to a trivial agent in the browser before writing any code.
2. **Design on paper first**:
   - `docs/ticket-schema.md` - columns, types, constraints, nullable vs required, `UNIQUE` on `conversation_id`, enum values.
   - `docs/data-collection-schema.md` - Data Collection field names, types, LLM-facing descriptions, and which fields are required vs optional. This is the product spec.
3. **Build the billing agent in the ElevenLabs dashboard**: system prompt for billing-only, declare Data Collection fields, test in the widget on 3-4 sample conversations until extraction is clean.
4. **Scaffold FastAPI** via `uv init`; add deps: `fastapi`, `uvicorn[standard]`, `sqlalchemy`, `psycopg[binary]`, `pydantic-settings`, `jinja2`, `elevenlabs`, `pytest`.
5. **Provision two Railway Postgres services** in the same Railway project: `support-triage-db-prod` (attached to the deployed app) and `support-triage-db-dev` (used by local dev and tests). Each service gets its own `DATABASE_URL`. Copy the dev `DATABASE_URL` and `ELEVENLABS_WEBHOOK_SECRET` into local `.env`. Tests connect to dev, override the FastAPI session dependency, share one DB connection with the app, run each test inside an outer transaction, and use nested SAVEPOINTs so commits inside request handlers stay isolated. The outer transaction rolls back after each test - no test data pollution, no shared state between tests.
6. **Write `models.py` / `db.py`** - `Ticket` model per the schema above. Call `Base.metadata.create_all()` on FastAPI startup. **Migrations (Alembic) are intentionally deferred** - acceptable for a single-model demo.
7. **Implement the webhook** at [app/webhook.py](app/webhook.py):
   - Read raw body via `raw = await request.body()` before any JSON parsing; also capture `sig = request.headers.get("elevenlabs-signature")`.
   - Call `elevenlabs.webhooks.construct_event(raw.decode("utf-8"), sig, secret)` per the current SDK example - raises on bad signature -> return 401. (If a future SDK version accepts bytes directly, the `.decode` can be dropped, but match the SDK example on the version pinned in `pyproject.toml`.)
   - Parse with Pydantic (`extra="allow"`); malformed JSON -> 400; missing transport-level required fields (`conversation_id`, `agent_id`, `analysis`) -> 422 per contract above.
   - Map call timestamps if present; otherwise persist `call_started_at = null` / `call_ended_at = null`.
   - Derive `extraction_status`: `complete` if all required Data Collection fields present and non-null; `partial` if any required field missing; `needs_review` if intent is ambiguous or multi-intent.
   - Intent mapping rule (locked): a **confident** classification that doesn't match a supported intent -> `other`; an **ambiguous** or **multi-intent** classification -> `needs_review`. These are distinct states and must not be conflated.
   - Sanitize `summary` before persistence/rendering: redact emails, phone numbers, and long account-number-like numeric tokens; if the result is empty or no longer meaningful, replace it with `Caller described a support issue; details withheld for privacy.` This privacy step must not change `extraction_status`.
   - Upsert by `conversation_id` with `INSERT ... ON CONFLICT (conversation_id) DO UPDATE`, storing both normalized columns and `extracted_data` + `raw_payload` JSONB.
   - Return 200 **only after** commit succeeds; DB errors -> 500.
8. **Test signature rejection and retry semantics** with pytest against an isolated schema:
   - bad signature -> 401
   - malformed JSON -> 400
   - missing transport-level required field (`conversation_id`, `agent_id`, or `analysis`) -> 422
   - valid payload with missing timestamps -> row persists, timestamps stored as `null`, response returns 200
   - replay same payload twice -> one row, second call returns 200
9. **Expose via ngrok**, register the URL in the ElevenLabs dashboard, make a test call, watch the row appear (`psql $DATABASE_URL -c "select conversation_id, intent, extraction_status from tickets;"`).
10. **Placeholder `/tickets` GET** - minimal HTML showing id, intent, extraction_status, created_at. No transcript, no raw payload.
11. **Build the test matrix** in [tests/test_matrix.md](tests/test_matrix.md) - 5-6 billing scenarios: varied phrasing, edge cases, a refusal, an ambiguous one, a partial extraction. Record extracted output and `extraction_status` for each.

**Done when**: a real call produces a verified, deduped row in Postgres visible in psql; signature/idempotency/partial-extraction tests pass; test matrix is in the repo.

## Phase 2 - full intent coverage, dashboard, polish (1-2 days)

1. Expand agent system prompt to route across all 4-5 intents. Add intent-specific Data Collection fields where useful (e.g. `billing_issue_type`, `cancellation_reason`). Update Pydantic subset accordingly.
2. Build the Jinja2 `/tickets` dashboard - plain HTML table, newest first, `?intent=billing` filter query param, `?status=needs_review` filter. **Curated columns only**: `created_at`, `intent`, `extraction_status`, `summary`. No transcript column. No raw payload column. `needs_review` rows visually flagged.
3. **Privacy discipline**: prefer synthetic/self-generated demo calls; if any real-sounding test uses personal-looking details, redact or overwrite before deploy. The `raw_payload` JSONB is never rendered in any route.
4. Harden [app/webhook.py](app/webhook.py) per the delivery contract above. All error paths logged with `conversation_id` where available.
5. Expand the test matrix to 10-12 scenarios across all intents including adversarial ones: ambiguous, multi-intent, user correcting themselves, user refusing. Confirm each maps to the right `extraction_status`.
6. **README** (3-4h of real writing time):
   - One-line "click here to try it" link
   - Architecture diagram (Mermaid)
   - Tech choices with "why this not that": SQLite vs Postgres vs Airtable; server tools vs post-call webhooks; Jinja vs React; JSONB + normalized columns vs. pure relational
   - Test matrix with extracted outputs
   - Failure modes: retries, idempotency, signature verification, partial extraction, Railway volume ephemerality
   - Privacy note: public dashboard shows curated fields only
   - Limitations and what v2 would add

## Phase 3 - deploy (1/2 day)

1. Railway project + Postgres addon (prod). `DATABASE_URL` injected automatically; set `ELEVENLABS_WEBHOOK_SECRET` manually.
2. Commit `Procfile`:
   ```
   web: uv run uvicorn app.main:app --host 0.0.0.0 --port $PORT
   ```
3. Commit `railway.toml`:
   ```toml
   [build]
   builder = "nixpacks"

   [deploy]
   startCommand = "uv run uvicorn app.main:app --host 0.0.0.0 --port $PORT"
   healthcheckPath = "/"
   restartPolicyType = "on_failure"
   ```
4. Deploy; confirm `/` and `/tickets` respond publicly.
5. Update the webhook URL in the ElevenLabs dashboard to the Railway URL.
6. End-to-end test on production.
7. Record a 3-5 minute Loom: make a call, show the ticket appearing on the deployed dashboard, walk through one piece of code you're proud of. Link from the README.

## Critical implementation notes (the three pitfalls)

- **Public URL for webhook testing** - use ngrok from day 1. Don't defer to "I'll just deploy first."
- **Idempotency** - `UNIQUE` constraint on `conversation_id`; `INSERT ... ON CONFLICT DO UPDATE`. Retries are the recovery path; upserts make them safe.
- **Garbage extraction on realistic speech** - test matrix with `extraction_status` per row is the gate for "Phase 1 done."

Additional:

- HMAC via `elevenlabs.webhooks.construct_event(raw_body.decode("utf-8"), header, secret)` to match the current SDK example. Read the raw body **before** FastAPI parses JSON (`raw = await request.body()`).
- DB work must be synchronous within the request; we only 200 after commit. Target sub-second webhook latency. No background tasks at this scale.
- Public `summary` values are privacy-hardened twice: the analyzer is instructed not to emit PII, and the backend sanitizes the stored/rendered text before it reaches `/tickets`.
- Railway filesystems are ephemeral - Postgres is the only durable store. Don't write uploads or logs to disk expecting them to survive.
- File encoding: all repo text files UTF-8; this plan is normalized to ASCII punctuation to avoid any mojibake risk.

## Out of scope (explicit)

- Twilio / real phone numbers
- Docker
- Auth on the dashboard (public by design, privacy maintained via field curation)
- Admin actions on tickets (read-only)
- Server tools / mid-call API lookups
- React / SPA frontend
- Alembic migrations (deferred; `create_all` on startup is the demo policy)

## Verification

- **Local**: `uv run uvicorn app.main:app --reload` + `ngrok http 8000` + test call from widget -> row appears -> `/tickets` shows curated fields.
- **Signature rejection**: `curl` with bad `elevenlabs-signature` header -> 401.
- **Malformed / missing fields**: `curl` with valid sig but bad body -> 400; valid JSON missing transport-level required fields -> 422.
- **Idempotency**: replay the same webhook payload twice -> one row, second call returns 200.
- **Missing timestamps**: valid webhook with absent call timestamps -> row persisted, `call_started_at = null`, `call_ended_at = null`, response returns 200.
- **Partial extraction**: payload with Data Collection required field null -> row persisted with `extraction_status = partial`; ambiguous intent -> `needs_review`.
- **Production**: call in the widget against the Railway-hosted agent -> row visible on the public `/tickets` URL; no transcript or raw payload exposed.
- **Privacy**: public `/tickets` output and page source show no obvious emails, phone numbers, or account-number-like tokens in `summary`.
- **Test matrix**: all 10-12 scenarios documented with extracted output and `extraction_status` in [tests/test_matrix.md](tests/test_matrix.md).
