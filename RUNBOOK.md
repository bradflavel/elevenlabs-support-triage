# Runbook - Operator Setup Checklist

Step-by-step setup for someone who has not used this stack before. Work through top to bottom; do not skip ahead. Boxes are check-off items.

See `PLAN.md` for the *why* and design rationale. This document is the *how*.

---

## 0. Prerequisites - accounts to create

Create these first. All are free tiers sufficient for the demo.

- [ ] **ElevenLabs account** - https://elevenlabs.io/sign-up. Free tier is fine for initial development; ElevenAgents usage will be billed per-minute once you exceed the free allowance.
- [ ] **Railway account** - https://railway.app. Sign in with GitHub for easiest deploys. You will need the hobby plan (~$5/mo) to keep services running 24/7, but you can develop on the free trial.
- [ ] **ngrok account** - https://dashboard.ngrok.com/signup. Free tier is enough. Copy the authtoken from the dashboard.
- [ ] **GitHub account** - already required by Railway.

---

## 1. Local workstation setup

- [ ] **Python 3.11+** installed. Verify: `python --version`.
- [ ] **uv** installed (https://docs.astral.sh/uv/getting-started/installation/). Verify: `uv --version`.
- [ ] **Git** installed and configured.
- [ ] **ngrok CLI** installed (https://ngrok.com/download). Authenticate once: `ngrok config add-authtoken <your-token>`.
- [ ] **psql** client installed (for poking at the Railway DB). Windows: via `winget install PostgreSQL.PostgreSQL` or the official installer.
- [ ] Clone/create the repo and `cd` into it.

---

## 2. Scaffold the Python project

In the repo root:

- [ ] `uv init --package .`
- [ ] `uv add fastapi 'uvicorn[standard]' sqlalchemy 'psycopg[binary]' pydantic-settings jinja2 elevenlabs`
- [ ] `uv add --dev pytest httpx`
- [ ] **Pin the `elevenlabs` SDK version** before writing any webhook code. Check `uv.lock` for the resolved version, then note the exact version in the README or in the commit that introduces webhook verification. The `construct_event` signature (string vs bytes) depends on the version - see `PLAN.md`.
- [ ] Copy `.env.example` to `.env` (create both if they do not exist yet; see env var table below).
- [ ] Add `.env` to `.gitignore` if it is not already.

---

## 3. Create the ElevenLabs agent (Phase 1: billing only)

In the ElevenLabs dashboard (https://elevenlabs.io/app/conversational-ai):

- [ ] Click **Create Agent**. Name it `support-triage-billing-dev` (or similar).
- [ ] **System prompt**: scoped to billing only. Refuse other intents politely. Draft lives in `docs/agent-prompts.md` (create this file during Phase 1 step 2).
- [ ] **Voice**: any default voice is fine for the demo.
- [ ] **Data Collection**: add the Phase 1 fields exactly as specified in [docs/data-collection-schema.md](docs/data-collection-schema.md). Field names, types, and descriptions must match.
- [ ] **Test in the widget** (the "Test AI Agent" panel in the dashboard). Run 3-4 sample billing conversations. Check the conversation analysis output and confirm the Data Collection fields populate cleanly before moving on.
- [ ] **Do not configure the post-call webhook URL yet** - that happens after the FastAPI server is running and ngrok is up.
- [ ] Record the **agent ID** and **agent secret / webhook secret** in your `.env` (see table below).

---

## 4. Provision Railway Postgres (prod + dev)

In the Railway dashboard (https://railway.app/dashboard):

- [ ] Create a new project called `elevenagents-support-triage`.
- [ ] Add a Postgres service: **+ New -> Database -> Add PostgreSQL**. Rename it to `support-triage-db-prod`.
- [ ] Add a second Postgres service the same way. Rename it to `support-triage-db-dev`.
- [ ] Click on `support-triage-db-dev` -> **Variables** tab -> copy the `DATABASE_URL`. This goes into your local `.env` as `DATABASE_URL`.
- [ ] The prod `DATABASE_URL` will be auto-wired into the deployed app later; do not copy it anywhere manually.
- [ ] Sanity check: `psql "$DATABASE_URL" -c '\conninfo'` should report a connected database.

---

## 5. Env var inventory

Put in your local `.env` (copied from `.env.example`):

| Variable | Where from | Used by | Notes |
| --- | --- | --- | --- |
| `DATABASE_URL` | Railway `support-triage-db-dev` service, Variables tab | FastAPI app, local + tests | Must be the **dev** URL locally. Prod URL is never pasted locally. |
| `ELEVENLABS_WEBHOOK_SECRET` | ElevenLabs dashboard -> agent -> webhook settings | Webhook HMAC verification | Same value used locally (for ngrok testing) and in prod. |
| `ELEVENLABS_AGENT_ID` | ElevenLabs dashboard -> agent overview | Logging / sanity check | Not strictly required at runtime but useful. |
| `APP_ENV` | you set it: `dev` locally, `prod` on Railway | App for logging / banner | |

In Railway (Variables tab on the deployed service, set during Phase 3):

| Variable | Value | Source |
| --- | --- | --- |
| `DATABASE_URL` | `${{support-triage-db-prod.DATABASE_URL}}` | Reference variable syntax; auto-wires prod DB |
| `ELEVENLABS_WEBHOOK_SECRET` | same secret as local | Manual paste |
| `APP_ENV` | `prod` | Manual |

`.env.example` committed to the repo should list every variable name with empty values - never commit a real secret.

---

## 6. Run locally + expose via ngrok

In two terminals:

- [ ] Terminal A: `uv run uvicorn app.main:app --reload --port 8000`
- [ ] Terminal B: `ngrok http 8000`
- [ ] Copy the `https://<something>.ngrok-free.app` URL from ngrok's output. This is your local webhook URL.
- [ ] Back in the ElevenLabs dashboard -> agent -> post-call webhook settings:
  - URL: `https://<something>.ngrok-free.app/webhooks/elevenlabs`
  - Secret: same value as `ELEVENLABS_WEBHOOK_SECRET` in your `.env`
  - Save.
- [ ] Make a test call in the widget. Watch terminal A for the POST hitting your webhook. Confirm 200 returned.
- [ ] Verify the row: `psql "$DATABASE_URL" -c "select conversation_id, intent, extraction_status, created_at from tickets order by created_at desc limit 5;"`

**Note**: the ngrok URL changes every time you restart ngrok on the free tier. You'll have to update the ElevenLabs webhook URL each time - or upgrade ngrok for a stable subdomain.

---

## 7. Deploy to Railway (Phase 3)

- [ ] Push the repo to GitHub.
- [ ] In the Railway project -> **+ New -> GitHub Repo -> pick the repo**. Railway detects Python via `pyproject.toml`.
- [ ] Confirm `Procfile` and `railway.toml` are in the repo root (see `PLAN.md` Phase 3 for exact contents).
- [ ] In the new service's **Variables** tab, set the prod env vars per the table above.
- [ ] Trigger a deploy. Watch build logs until `web` process is up.
- [ ] Click the service -> **Settings -> Networking -> Generate Domain**. Copy the public URL.
- [ ] Hit `https://<railway-url>/tickets` in a browser - should show the dashboard (possibly empty).
- [ ] In the ElevenLabs dashboard, update the post-call webhook URL from the ngrok URL to `https://<railway-url>/webhooks/elevenlabs`.
- [ ] Make one production test call. Confirm the ticket appears on the public `/tickets` page.

---

## 8. Post-deploy verification

Run through all checks in `PLAN.md` -> Verification section against the deployed URL, not localhost.

- [ ] Signature rejection: `curl -X POST https://<railway-url>/webhooks/elevenlabs -H "elevenlabs-signature: bogus" -d '{}'` returns `401`.
- [ ] Malformed body: valid signature header but non-JSON body -> `400`.
- [ ] Idempotency: use a **scrubbed local** `payload.json` sample with a fixed `conversation_id`, generate a valid `elevenlabs-signature` header from `ELEVENLABS_WEBHOOK_SECRET`, POST the same body twice, and confirm one row in DB.
- [ ] Public dashboard shows curated columns only; raw payload and transcript are not visible in HTML or page source, and `summary` contains no obvious email addresses, phone numbers, or account-number-like tokens.

PowerShell-friendly replay example:

```powershell
$secret = $env:ELEVENLABS_WEBHOOK_SECRET
$body = Get-Content -Raw .\payload.json
$webhookUrl = "https://<railway-url>/webhooks/elevenlabs"
$timestamp = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
$signedPayload = "$timestamp.$body"
$hmac = [System.Security.Cryptography.HMACSHA256]::new([System.Text.Encoding]::UTF8.GetBytes($secret))
$hashBytes = $hmac.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($signedPayload))
$hash = -join ($hashBytes | ForEach-Object { $_.ToString("x2") })
$signature = "t=$timestamp,v0=$hash"

1..2 | ForEach-Object {
  Invoke-WebRequest `
    -Method Post `
    -Uri $webhookUrl `
    -Headers @{
      "elevenlabs-signature" = $signature
      "Content-Type" = "application/json"
    } `
    -Body $body
}
```

Use a locally created, scrubbed `payload.json` that matches the documented webhook shape and contains no real transcript or personal data. Current ElevenLabs docs describe the signature header as `t=timestamp,v0=sha256_hmac(timestamp.body)`. After replaying twice, confirm the deployed app shows a single ticket for that `conversation_id` in the public `/tickets` page and, if needed, in the Railway Postgres query UI for `support-triage-db-prod`.

---

## Common gotchas

- **Forgot to decode the raw body** before passing to `construct_event`: HMAC fails even though the secret is correct. See `PLAN.md` Phase 1 step 7.
- **Railway prod DB is empty but local isn't**: prod and dev are separate services by design. Use the prod dashboard to see prod data.
- **ngrok URL changes mid-session** and ElevenLabs keeps retrying the dead URL: update the webhook URL in the ElevenLabs dashboard, then manually mark stale retries as ignorable.
- **`construct_event` raises `BadSignatureError` in prod but not locally**: usually means the `ELEVENLABS_WEBHOOK_SECRET` env var on Railway is stale or whitespace-padded. Re-paste exactly.
- **Tests polluting the dev DB**: tests must share the app's DB session dependency, run inside an outer transaction, and use nested SAVEPOINTs for request-handler commits. If you see test data sticking around, the fixture is not overriding the session correctly or the outer rollback is not happening.
