# Customer Support Triage Voice Agent

[![CI](https://github.com/bradflavel/elevenlabs-support-triage/actions/workflows/ci.yml/badge.svg)](https://github.com/bradflavel/elevenlabs-support-triage/actions/workflows/ci.yml)

A deployable voice-agent demo for customer-support triage. An ElevenLabs Conversational AI agent handles inbound web-widget calls, routes across five support intents (billing, technical, account change, cancellation, other), and uses the platform's built-in Data Collection analysis to extract structured fields. A post-call webhook fires to a FastAPI backend which verifies the HMAC signature, persists a ticket row to Postgres (idempotent upsert), and exposes a public read-only `/tickets` dashboard showing privacy-safe curated fields.

> **Try it:** Live demo at [web-production-e61e1.up.railway.app/tickets](https://web-production-e61e1.up.railway.app/tickets). Call the agent via the embedded widget and your ticket will appear on the public dashboard within seconds of the call ending.

## Architecture

```mermaid
flowchart LR
    Caller([Caller - web widget])
    Agent[ElevenLabs agent]
    Analyzer[Data Collection analyzer]
    Webhook[POST /webhooks/elevenlabs<br/>HMAC verified]
    DB[(Postgres tickets)]
    Dash[GET /tickets<br/>curated Jinja view]
    Viewer([Recruiter / public])

    Caller -->|voice| Agent
    Agent -->|post-call| Analyzer
    Analyzer -->|structured fields| Webhook
    Webhook -->|upsert by conversation_id| DB
    DB -->|read| Dash
    Dash -->|HTML| Viewer
```

End-to-end flow:

1. Caller clicks the browser widget, speaks with the agent. The agent follows the Phase 2 prompt in [docs/agent-prompts.md](docs/agent-prompts.md) to identify the intent and collect the key details.
2. When the call ends, ElevenLabs runs the Data Collection analyzer against the transcript and fires a post-call webhook to our FastAPI service.
3. The handler verifies the HMAC signature via the ElevenLabs SDK's `construct_event`, validates the transport-level fields with Pydantic (`extra="allow"`), and derives `intent` and `extraction_status` from the analyzer output.
4. The handler upserts the ticket row by `conversation_id` - retries are safe. The row carries normalized columns (for the dashboard) plus two JSONB columns (full `extracted_data` and `raw_payload`) for resilience against payload evolution.
5. The `/tickets` dashboard reads the normalized columns only - transcripts and raw payloads are never rendered.

## Tech stack

- Python 3.11+
- [FastAPI](https://fastapi.tiangolo.com/) - web framework
- [SQLAlchemy 2.0](https://www.sqlalchemy.org/) + [psycopg 3](https://www.psycopg.org/psycopg3/) - Postgres client
- [Pydantic](https://docs.pydantic.dev/) + `pydantic-settings` - payload validation + env loading
- [Jinja2](https://jinja.palletsprojects.com/) - dashboard templating
- [elevenlabs](https://pypi.org/project/elevenlabs/) SDK (pinned at **2.43.0**) - HMAC webhook verification via `construct_event`
- [uv](https://docs.astral.sh/uv/) - package and environment management
- [Railway](https://railway.app/) - hosting (native Python build via nixpacks, no Dockerfile)
- [ngrok](https://ngrok.com/) - local webhook tunnelling during development

## Tech choices - why this, not that

| Decision | Alternative considered | Why |
| --- | --- | --- |
| **Postgres, not SQLite** | SQLite | Railway volume ephemerality means disk is not durable. Postgres is the only safe option on this platform. Also, JSONB for `extracted_data` and `raw_payload`. |
| **Postgres, not Airtable** | Airtable | Real-time upsert semantics and HMAC-signed ingest are cleaner with a proper DB. Airtable adds rate limits, auth indirection, and schema fragility. |
| **Post-call webhook, not server tools** | Mid-call server tools | Server tools would be the wrong abstraction - this is an after-the-fact ingest of a finished conversation's structured analysis, not a mid-call API lookup. |
| **Jinja2, not React** | React / SPA | Dashboard is read-only, five columns, no interactive state. Jinja renders in one request with zero JS; shipping a React app would triple the build surface for no user-visible benefit. |
| **JSONB + normalized columns, not pure relational** | Columns only | The ElevenLabs payload shape can evolve. Normalized columns power the dashboard and filters; JSONB guarantees we never lose a field that changed upstream, and `raw_payload` is the debugging escape hatch. |
| **Platform enums + backend re-validation, not backend-only** | Enforce enums only in backend | Declaring enum values in the ElevenLabs Data Collection config constrains the analyzer at generation time. Backend Pydantic validation then acts as belt-and-braces. Live testing confirmed the platform returns `null` (not a forced pick) when no enum value fits, so backend logic treats null as `partial` rather than a bad value. |
| **Split LLMs: Haiku 4.5 for conversation, Sonnet 4.6 for analysis** | One model for both | The agent LLM runs in real-time during the call; latency matters more than marginal accuracy gains, so Haiku 4.5 (~790ms) is the right trade-off. The analysis model runs offline post-call where latency is irrelevant and extraction accuracy is everything, so Sonnet 4.6 earns the cost. This split mirrors how a production system would balance real-time constraints against accuracy. |
| **SDK `construct_event`, not hand-rolled HMAC** | `hmac.compare_digest` | SDK is the reference implementation for this version of the webhook format (timestamp tolerance + `v0=` signature scheme). Less crypto code to audit and maintain. |
| **`create_all` on startup, not Alembic** | Alembic migrations | Single-model demo. Alembic is correct for anything real; here it would be ceremony without payoff. Flagged explicitly in `PLAN.md` so the choice is visible. |
| **uv, not pip/poetry** | pip + requirements.txt; Poetry | Fast resolver, single lockfile, works out of the box with Railway's nixpacks Python provider. |
| **No auth on the dashboard** | Basic auth / magic link | Public by design - this is a demo. Privacy is enforced by **not rendering** the sensitive data in the first place: curated columns only, PII sanitizer on `summary`, `raw_payload` and `extracted_data` never touch the template. |

## Privacy

The public `/tickets` dashboard only renders `created_at`, `intent`, `extraction_status`, and `summary`. `conversation_id`, `extracted_data`, `raw_payload`, and the platform's built-in per-conversation summary are never surfaced by any route.

`summary` is passed through a sanitizer before persistence that redacts emails, phone numbers, and long numeric tokens (6+ digits). If redaction would leave an empty string, a neutral placeholder (`"Caller described a support issue; details withheld for privacy."`) is used instead.

The agent system prompt in [docs/agent-prompts.md](docs/agent-prompts.md) instructs the agent to avoid soliciting full credit card numbers, passwords, bank details, and names in the spoken summary. The backend sanitizer is the last line of defense; agent instructions are not sufficient on their own.

### Voice-channel limitations

Voice-to-text introduces a category of failure that text input doesn't. Callers naturally say "at" and "dot" when spelling email addresses, and STT transcribes these as literal words rather than `@` and `.`. Live testing captured `"test at symbol email.com"` as an `account_identifier` rather than `test@email.com`.

This is why the privacy architecture matters: `account_identifier` is captured but **not rendered on the public dashboard**. Even if STT produces a mangled or partially-captured identifier, it stays in the database and never reaches the template. Production systems handling real PII via voice should use a secondary channel (SMS verification, post-call email confirmation) for structured identifiers rather than relying on STT alone.

## Local development

See [RUNBOOK.md](RUNBOOK.md) for the full linear checklist. Fast path:

```bash
# Install uv first: https://docs.astral.sh/uv/getting-started/installation/
git clone <this-repo>
cd elevenagents-support-triage
cp .env.example .env
# Fill .env with DATABASE_URL and ELEVENLABS_WEBHOOK_SECRET
uv sync
uv run uvicorn app.main:app --reload
# In another terminal:
ngrok http 8000
# Paste the ngrok URL into the ElevenLabs agent's post-call webhook config.
```

## Running tests

```bash
uv run pytest -v
```

Test coverage (current count visible in CI badge output):

- Signature rejection (missing / bad) -> 401
- Malformed JSON with valid signature -> 400
- Missing transport-level required fields -> 422
- Idempotent replay (two identical POSTs = one row)
- All four extraction-status derivation paths (complete / partial / needs_review / intent-outside-enum)
- Value-unwrapping for Data Collection objects that arrive as `{value: X, rationale: "..."}`
- Summary sanitizer: emails, phone numbers, account-number-like tokens (unit + end-to-end)
- Dashboard: empty state, render with row, redirect, privacy regression (no `conversation_id` or debug fields leak into HTML), `needs_review` visual flag, intent filter (asserts filtered content, not just UI state)

Integration tests use a per-test transactional rollback fixture so nothing persists across runs.

## Test matrix

Extraction behaviour was validated against 12 scenarios executed against the deployed Phase 2 agent, spanning the five intents plus adversarial cases: vague input, multi-intent calls, self-correction, uncooperative callers, partial extraction, and a deliberate PII-leak regression test. Each scenario records the caller script, the full Data Collection extraction output, and the derived `extraction_status`.

**Results:** 11 PASS, 1 hard FAIL (plus 2 partial-fails on cross-field null discipline that PASS on primary classification). Status distribution: 11 `complete`, 1 `partial`, 0 `needs_review` (path intentionally deferred to v1.1 — see Observations below).

Full per-scenario results in [tests/test_matrix.md](tests/test_matrix.md).

### Observations from live extraction testing

Matrix execution surfaced four findings that shape the v1.0 architecture and inform v1.1 priorities:

1. **Platform-level enums return `null`, not a forced pick, when no value fits.** An out-of-scope call (caller describing a login issue on a billing-only Phase 1 agent) produced `intent: other` with `billing_issue_type: null`, correctly acknowledging that no billing category applied. Backend logic treats null required fields as `partial`, not as a classification — the three-state status model expresses this directly.

2. **The analyzer respects anti-hallucination instructions on optional fields.** Scenario 2 and earlier vague-caller tests produced `amount_disputed: null` when no amount was specified, and Scenario 11 produced `account_change_type: null` when the caller couldn't articulate what they wanted to change. Strongly-worded field descriptions ("leave empty if...") prevent the analyzer from inventing values to fill slots. Scenario 11 is a textbook `partial` case and the strongest validation of the three-state status model in the matrix.

3. **Cross-field pattern-matching persists despite guard-clause descriptions.** Three scenarios (3, 5, 9) showed intent-specific fields populating on calls where they shouldn't have — `account_change_type: password` on a login call; `billing_issue_type: subscription_change` on cancellation and plan-change calls. Strengthened descriptions with explicit "leave empty if not [X]" guard clauses reduced but did not eliminate the behaviour. The analyzer occasionally surface-matches on vocabulary even when instructed otherwise. This is the clearest signal in the matrix that prompt-based defences alone are insufficient; backend cross-field validation is planned for v1.1 (approximately 10 lines of code in `app/webhook.py` that null intent-specific fields when they don't match primary intent).

4. **PII defence-in-depth validated against hostile input.** Scenario 12 deliberately embedded `test@email.com` in the caller's opening statement. The rendered `/tickets` dashboard contains no email in the summary, despite the caller explicitly stating it. The `account_identifier` field captured the email for downstream specialist use but is not rendered publicly. Two-layer defence (LLM description instructing no-PII in summary + backend regex sanitizer) confirmed end-to-end against a deliberately adversarial test.

## Failure modes considered

| Failure | Response |
| --- | --- |
| Bad HMAC signature | 401, no DB write. |
| Missing `elevenlabs-signature` header | 401. |
| Stale signature timestamp (>30 min old) | 401 via SDK `BadRequestError`. |
| Signed but non-JSON body | 400. |
| Missing `conversation_id` or `agent_id` | 422, no DB write. Caller should never retry this. |
| Unknown Data Collection field appears | Tolerated (`extra="allow"`), persisted in `extracted_data` JSONB. |
| Analyzer returns `null` for intent (no enum value fits) | Row persisted, `intent = null`, `extraction_status = partial`. Observed in out-of-scope test scenario. |
| Analyzer returns intent outside our enum (defensive path) | Row persisted, `intent = null`, `extraction_status = partial`. Platform-level enum enforcement makes this path unlikely; backend re-validation is belt-and-braces. |
| Analyzer flags ambiguity / multi-intent | Row persisted with `intent = needs_review`, `extraction_status = needs_review`. Note: this path is plumbed but the `ambiguity_flag` signal was deferred to v1.1 — see Observations. |
| **Cross-field leakage (intent-specific field populated on non-matching call)** | v1.0 behaviour: stored as-returned by analyzer. v1.1 fix: backend nulls intent-specific fields when they don't match primary intent. Observed in three matrix scenarios; does not affect primary classification or dashboard rendering. |
| Caller provides email by voice | STT transcribes as natural-language ("test at email dot com") rather than `test@email.com`. Captured in `account_identifier` which is never rendered publicly; downstream systems needing email format should verify via SMS/email rather than STT. |
| Summary contains PII | Redacted before persistence; placeholder used if fully redacted. Validated against hostile input (Scenario 12). |
| DB unreachable | 500. ElevenLabs retries on non-200; upsert by `conversation_id` makes retry safe. |
| Webhook delivered twice (retry or duplicate) | Idempotent: `INSERT ... ON CONFLICT DO UPDATE` keyed on `conversation_id`. |
| Railway volume reset | Filesystem is ephemeral; all durable state lives in Postgres. |

## Project structure

```
elevenagents-support-triage/
  Procfile                  # Railway web process
  railway.toml              # Railway build + deploy config
  pyproject.toml + uv.lock  # uv-managed deps
  .env.example              # env var inventory
  .github/workflows/ci.yml  # pytest against a Postgres service
  PLAN.md                   # design rationale
  RUNBOOK.md                # linear operator checklist
  docs/
    agent-prompts.md        # Phase 1 + Phase 2 system prompts
    data-collection-schema.md  # Data Collection field spec
    ticket-schema.md        # DB schema doc
  app/
    main.py                 # FastAPI app + lifespan create_all
    config.py               # pydantic-settings
    db.py                   # SQLAlchemy engine, session, URL normalizer
    models.py               # Ticket model + enums
    schemas.py              # Pydantic payload models
    webhook.py              # HMAC verify + upsert + sanitizer
    dashboard.py            # /tickets Jinja view
    templates/
      _base.html
      tickets.html
  tests/
    conftest.py             # DB fixture + signature helper
    test_webhook.py
    test_dashboard.py
    test_matrix.md          # scenario documentation
```

## Roadmap

**v1.1 — immediate follow-ups from the matrix run:**

- **Backend cross-field validation**: null intent-specific fields when they don't match primary intent (Observations #3). Approximately 10 lines of code in `app/webhook.py`. Completes the defence-in-depth story for extraction, exactly as the PII sanitizer does for summary privacy.
- **Extractive ambiguity signal**: declare `mentioned_issues` as a list of strings in Data Collection config; derive `needs_review` in the backend when list length > 1. Replaces the deferred `ambiguity_flag` boolean with a concrete extractive task the LLM can do reliably.

**v2 — larger scope:**

- **Real phone numbers via Twilio / ElevenLabs phone**: the demo uses the browser widget only. A production deployment would route PSTN calls into the same agent.
- **Email/identifier verification channel**: when voice callers provide an email, surface a post-call SMS or email confirmation rather than relying on STT to capture the identifier correctly.
- **Retry/backoff metrics**: currently relying on ElevenLabs' retry policy. A real system would track delivery attempts per `conversation_id` and alarm on persistent failures.
- **Alembic migrations**: single-model schema is fine for a demo. Adding a second model without Alembic would be the trigger to introduce it.
- **Authenticated admin view**: a companion route behind auth for ops staff to view `extracted_data`, `raw_payload`, and transcript excerpts for rows flagged `needs_review`. The public dashboard would remain curated-only.
- **Structured logging + tracing**: request IDs, correlation with `conversation_id`, export to an APM. Current setup is stdlib `logging` only.
- **Dashboard search and pagination**: the current view is capped at 200 rows, unpaginated. Trivial to extend once the volume warrants it.
- **Agent prompt A/B**: multiple prompt variants keyed off a feature flag, with the test matrix re-run against each.

## Documents

- [PLAN.md](PLAN.md) - design decisions and architecture rationale
- [RUNBOOK.md](RUNBOOK.md) - step-by-step operator setup
- [docs/agent-prompts.md](docs/agent-prompts.md) - the agent's system prompts
- [docs/data-collection-schema.md](docs/data-collection-schema.md) - extraction field spec
- [docs/ticket-schema.md](docs/ticket-schema.md) - database schema doc
- [tests/test_matrix.md](tests/test_matrix.md) - full 12-scenario extraction test matrix with results

## Loom walkthrough

A 3-5 minute walkthrough recorded against the deployed service: a live call from the browser widget, the ticket appearing on the public `/tickets` dashboard within seconds, and a brief tour of the webhook handler's HMAC verification, idempotent upsert, and PII sanitizer.

<!-- LOOM_URL_PLACEHOLDER - populated after recording -->

---

Built across several focused sessions, each structured around a single deliverable - spec, implementation, audit, live extraction testing. Architecture, design decisions, agent prompts, Data Collection schema, and the test matrix are my work; Claude was used heavily for implementation velocity under direction. Every design trade-off in this README was defended before code was written. See the commit log for the build sequence.