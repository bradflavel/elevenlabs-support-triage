# Loom Walkthrough Script

A 3-5 minute voiceover for the demo walkthrough. Record after the deployed agent is working end-to-end and after the test matrix is populated.

Target length: aim for 4 minutes. Faster is better than slower; recruiters skim.

---

## Setup before recording

1. Open three browser tabs in this order (left to right):
   - The deployed ElevenLabs agent widget (the page you call from).
   - The deployed `/tickets` dashboard.
   - The GitHub repo, scrolled to the README.
2. In a code editor, have [app/webhook.py](../app/webhook.py) open on the HMAC verification section (lines roughly around the `construct_event` call).
3. Start with an empty `/tickets` dashboard for the demo (make a fresh row on camera).

---

## Script

### 0:00 - 0:20 - Intro (15-20s)

> "This is a voice-agent demo for customer support triage. A caller speaks to an ElevenLabs Conversational AI agent, the agent classifies their intent and extracts the key details using the platform's built-in Data Collection analysis, and a post-call webhook lands a structured ticket in Postgres. The dashboard you're about to see is public and read-only - it shows only curated, privacy-safe fields. I'll make a live call, show the ticket appearing, then walk through one piece of the code I'm proud of."

### 0:20 - 1:40 - Live call (80s)

> "First, the call. I'm using the browser widget here."

Click to start the call. Say one of the test-matrix scenarios - recommend scenario 1 (clear billing charge dispute) for the demo because it's unambiguous and shows a clean `complete` status. Something like:

> "Hi, I'm looking at my statement and there's a charge for twenty-nine ninety-nine that I don't recognize. Can you help me figure out what that was?"

Let the agent do its turn. Answer naturally. When it wraps the call, let it end.

> "That's the call. The agent's already fired the post-call webhook to our FastAPI backend, which verified the signature and upserted a row in Postgres."

### 1:40 - 2:30 - Dashboard (50s)

Switch to the `/tickets` tab and refresh.

> "And here's the ticket. This is the public dashboard - the columns are deliberately narrow: timestamp, intent, extraction status, and a sanitized summary. Notice what's not here: no conversation ID, no transcript, no raw payload. Those fields exist in Postgres as JSONB, but they're never rendered. That's the privacy rule: the sensitive data can't leak through a template it never reaches."

Point to the intent and status columns.

> "The intent is classified as billing. The extraction status is `complete` because the analyzer filled every required field. When calls are ambiguous or multi-intent, you get `needs_review` instead, visually flagged. When the analyzer gets the intent but misses a sub-field, you get `partial`. That three-state distinction matters because support-ops cares about which tickets a human needs to look at."

Optionally click the intent filter to show `billing` filtered view, then click back to `all`.

### 2:30 - 3:45 - Code walkthrough (75s)

Switch to the editor showing [app/webhook.py](../app/webhook.py).

> "The piece I want to show is the webhook handler. Three things are worth calling out."

Scroll to the `construct_event` block.

> "First: HMAC verification. We use the ElevenLabs SDK's `construct_event` with the raw request body decoded to a string. Note we read the body **before** FastAPI parses JSON - the signature is computed over the exact bytes the platform sent, so any re-serialization would break verification."

Scroll to the `derive_intent_and_status` call.

> "Second: intent mapping. The analyzer can return one of our five supported intents, an unknown intent, a multi-intent signal, or nothing. A confident classification outside our enum becomes `other` with status `partial` - that's the 'we understood you but don't handle this' case. An ambiguous or multi-intent signal becomes `needs_review`. Those are deliberately distinct; collapsing them would hide exactly the cases support-ops needs to review."

Scroll to the `pg_insert` / `on_conflict_do_update` block.

> "Third: idempotency. We upsert by `conversation_id` with Postgres' `ON CONFLICT DO UPDATE`. ElevenLabs retries on non-200 responses - and we only return 200 once the row is committed. So retries are safe, and safe idempotency lets us return non-200 honestly when the DB is actually unreachable."

### 3:45 - 4:15 - Close (30s)

Switch to the README tab.

> "Everything else is in the repo. The README has the architecture diagram, the tech-choice rationale, the failure-modes table, and links to the planning docs - design, the operator runbook, the Data Collection field spec, and the agent prompts. CI runs on every push: 23 tests, including signature rejection, idempotent replay, partial-extraction status, and a privacy regression test that fails if the dashboard ever leaks a conversation ID."

> "Thanks for watching."

---

## Recording tips

- Speak like a human explaining something to a colleague, not like reading a script. If a line feels stilted, rephrase on the fly.
- If the agent call goes off the rails, stop and restart. The live call is 40% of the impact.
- Keep the dashboard tab loaded before recording so the refresh is instant.
- Volume-level your voice and desktop audio separately if possible - voice should be clearly dominant.
- After uploading, update the placeholder `<!-- LOOM_URL_PLACEHOLDER -->` in `README.md` with the real URL, commit as `docs: add loom walkthrough link`, and tag the commit `v1.0`.
