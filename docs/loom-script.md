# Loom Walkthrough Script

A 3-5 minute voiceover for the demo walkthrough. Record after the deployed agent is working end-to-end and after the test matrix is populated.

Target length: aim for around 4 minutes. This is a guide, not a word-for-word reading — speak naturally, rephrase on the fly, add asides if they come up.

---

## Setup before recording

1. Open four browser tabs in this order (left to right):
   - The deployed ElevenLabs agent widget (the page you call from).
   - The deployed `/tickets` dashboard.
   - The GitHub repo, scrolled to the README.
   - `tests/test_matrix.md` on GitHub, ready to scroll.
2. Have [app/webhook.py](../app/webhook.py) open in a code editor, scrolled to the HMAC section.
3. Demo with the populated dashboard — keeps the live link looking alive after the recording.

---

## Script

Treat everything below as **talking points**, not lines to recite. If you hit a moment and a different phrasing feels more natural, use it.

### 0:00 - 0:20 — Intro

> "Hey, quick walkthrough of a voice agent demo I built. Someone calls in, the ElevenLabs agent triages the call, and a structured ticket ends up on a public dashboard. I'll make a call, show you the ticket appearing, then walk through a bit of the code and the test matrix I ran against it."

Keep this short. Don't explain the whole architecture up front — the call will do that for you.

### 0:20 - 1:40 — Live call

> "So here's the widget. I'll pretend I'm calling in about a billing issue."

Start the call. Use Scenario 1 phrasing — clean and unambiguous:

> "Hi, I'm looking at my statement and there's a charge for twenty-nine ninety-nine I don't recognize. Can you help me figure out what that was?"

Let the agent ask its follow-up questions, answer naturally. When it closes, let the call end.

> "Okay, so that's done. Behind the scenes, the agent's analyzer has already run over the transcript, pulled out the intent and the key fields, and fired a webhook to my backend. It's verified the signature, written a row to Postgres, and the dashboard should be live."

### 1:40 - 2:30 — Dashboard

Switch to `/tickets`, refresh.

> "And there it is at the top. Billing, complete, clean summary."

Pause for a beat so it's readable.

> "A few things I want to point out about this dashboard. First, what's *not* on it — no conversation IDs, no transcripts, no raw payloads, no account identifiers. All that stuff exists in the database but it's never rendered. That's deliberate: sensitive data can't leak through a template it never reaches. The privacy isn't a setting, it's architectural."

Point at the intent column.

> "Second — the intent classifications come from the analyzer but they're constrained to our enum at the platform level. One of the things I learned from testing was that when no enum value fits, the platform actually returns null rather than forcing a pick, which is nice."

Point at status.

> "And the status column — complete means everything extracted cleanly, partial means the call happened but the analyzer couldn't fill some required field. There's a third state, `needs_review`, for ambiguous or multi-intent calls, but that's a v1.1 feature — I ended up deferring the ambiguity signal because getting an LLM to self-report its own confidence reliably is harder than it looks."

Click the billing filter to show it working, click back to all.

### 2:30 - 3:30 — Code

Switch to `webhook.py`.

> "Okay, quick code tour. Three things worth calling out in the webhook handler."

Scroll to `construct_event`.

> "First, signature verification. I'm using the ElevenLabs SDK's `construct_event` against the raw request body, and crucially I read the bytes *before* FastAPI parses anything — because the signature is computed over the exact bytes the platform sent. If you let FastAPI re-serialize the JSON, verification breaks. Small thing, easy to get wrong."

Scroll to `derive_intent_and_status`.

> "Second, how I handle what comes back from the analyzer. If the intent is one of the five we support, we use it. If it's something weird or missing, we store null and mark the ticket partial — we don't force it into `other`. Partial and `other` mean different things and I wanted to keep them distinct."

Scroll to `on_conflict_do_update`.

> "Third, idempotency. I upsert by conversation ID. ElevenLabs retries webhooks on any non-200 response, and I only return 200 after the row actually commits. So retries are safe — they just write the same row — and that safety lets me honestly return a 500 when the database is genuinely down. I don't have to fake success to avoid retry storms."

### 3:30 - 4:10 — Test matrix and close

Switch to `tests/test_matrix.md`.

> "Last thing — the test matrix. I ran 12 scenarios against the deployed agent: clean calls across each intent, plus some harder ones like vague input, multi-intent calls, self-correction, a caller who refuses to say why they're calling, and a deliberate PII leak test where I put an email right in the opening line."

Scroll to the observations.

> "Eleven pass, one fail, and the fail's actually interesting. The analyzer occasionally populates an intent-specific field on calls where it shouldn't — like tagging a login call with a `password_change` type because it saw the word password. Strengthening the field descriptions reduced it but didn't eliminate it. The fix is about ten lines of backend validation, which I wrote up as the v1.1 priority. I wanted the matrix to capture the bug honestly instead of silently patching it — same defence-in-depth idea as the PII sanitizer."

Switch briefly to the README.

> "Everything else is in the repo. Architecture, tech choices, the full failure modes table, all the planning docs. Thanks for watching."

---

## Delivery notes

- **Contractions everywhere.** "It's" not "it is", "I'm" not "I am", "that's" not "that is".
- **Shorter sentences.** If a sentence runs more than two lines in the script, it'll sound like reading. Break it.
- **Little asides land well.** "Small thing, easy to get wrong" or "harder than it looks" make technical content feel conversational.
- **It's okay to pause.** Two seconds of silence while the dashboard loads is fine. Don't fill every gap.
- **If you stumble, keep going.** Recruiters watch recorded content at 1.25x. One flubbed word is invisible.

## Recording tips

- Two takes max. Pick the less stilted one even if the wording's imperfect.
- Preload every tab. Slow refreshes kill pace.
- Level voice and desktop audio separately; voice should be clearly dominant.
- After uploading, update `<!-- LOOM_URL_PLACEHOLDER -->` in `README.md`, commit as `docs: add loom walkthrough link`, tag `v1.0`.