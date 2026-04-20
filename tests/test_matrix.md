# Extraction Test Matrix

Results from calling the deployed Phase 2 agent with a spread of scenarios. Each entry records the caller's prompt, the analyzer's output, and the resulting `extraction_status`.

The goal is not 100% `complete` — it is **correct** status assignment across the spectrum. A call that should be `partial` getting `partial` is a pass; a call that should be `other` getting force-classified as `billing` is a fail.

## Agent configuration under test

- **Agent:** `support-triage-billing-dev` running the Phase 2 system prompt (see [../docs/agent-prompts.md](../docs/agent-prompts.md))
- **Conversation LLM:** Claude Haiku 4.5
- **Analysis LLM:** Claude Sonnet 4.6
- **Ambiguity handling:** deferred to v1.1; `needs_review` path not exercised in this matrix

## How to execute

1. Open the agent's Test AI Agent widget in the ElevenLabs dashboard.
2. For each scenario below, start a call and use the caller script as your opening line. Respond naturally to the agent's follow-up questions.
3. End the call when the agent gives its closing summary.
4. Wait ~20–30 seconds for the post-call analyzer and webhook to fire.
5. Refresh the production `/tickets` dashboard to confirm the row appears.
6. Open the conversation in ElevenLabs (Monitor → Conversations → most recent) and copy the Data Collection output.
7. Fill in the **Actual** and **Verdict** sections for that scenario below.
8. If a scenario FAILs, note it and move on — do not iterate on the prompt mid-matrix.

---

## Scenarios

### Scenario 1 — Clear billing, charge dispute

**Caller script (opening line):** "I see a charge on my card I don't recognize, can you look into it?"

**Expected:** `intent = billing`, `billing_issue_type = charge_dispute`, `extraction_status = complete`

**Actual:**
- intent: billing
- billing_issue_type: charge_dispute
- summary: The caller wanted to dispute an unrecognized charge of $67.67 that appeared on their card around the 15th-16th of the current month.
- account_identifier: test@email.com
- amount_disputed: 67.67
- urgency: high
- extraction_status: complete

**Verdict:** PASS — primary classification correct, all required fields populated, no PII in summary, `amount_disputed` captured numerically from caller phrasing.

---

### Scenario 2 — Clear billing, refund request

**Caller script (opening line):** "I'd like a refund for last month's subscription, it didn't renew correctly."

**Expected:** `intent = billing`, `billing_issue_type = refund_request`, `extraction_status = complete`

**Actual:**
- intent: billing
- billing_issue_type: refund_request
- summary: The caller requested a refund for a subscription that they were charged for last month but which did not activate.
- account_identifier: test@email.com
- amount_disputed: null
- urgency: medium
- extraction_status: complete

**Verdict:** PASS — classification correct. `amount_disputed: null` is the right outcome; the caller never specified an amount, and the analyzer correctly refused to invent one (matches the anti-hallucination discipline from earlier smoke testing).

---

### Scenario 3 — Clear technical, login

**Caller script (opening line):** "I can't log into my account, it keeps saying my password is wrong even though it's right."

**Expected:** `intent = technical`, `technical_issue_type = login`, `extraction_status = complete`

**Actual:**
- intent: technical
- technical_issue_type: login
- summary: The caller was unable to log into their account because the system was rejecting their password, despite them believing it was correct.
- account_identifier: test@email.com
- urgency: high
- billing_issue_type (should be null): null
- account_change_type (should be null): **password** — analyzer justified as "indicating a need for a password change or reset"
- cancellation_reason (should be null): null
- extraction_status: complete

**Verdict:** FAIL — primary classification is correct (`technical` / `login`), but `account_change_type: password` leaked on a technical call. The caller was locked out of their account, not asking to change their password. The analyzer surface-matched on the word "password" despite the field description's explicit "leave empty if the call is not an account change" guard clause. First instance of the cross-field leakage pattern; see v1.1 note below.

---

### Scenario 4 — Clear account change, email

**Caller script (opening line):** "I want to update the email address on my account because my old one is being shut down."

**Expected:** `intent = account_change`, `account_change_type = email`, `extraction_status = complete`

**Actual:**
- intent: account_change
- account_change_type: email
- summary: The caller wanted to update the email address on their account because their old email address was being shut down.
- account_identifier: test@email.com
- urgency: medium
- billing_issue_type (should be null): null
- technical_issue_type (should be null): null
- cancellation_reason (should be null): null
- extraction_status: complete

**Verdict:** PASS — all fields populated correctly, all three non-matching intent-specific fields correctly null. Clean separation between "email as identifier" (`account_identifier`) and "email as the thing being changed" (`account_change_type = email`) — a distinction the description was specifically written to preserve.

---

### Scenario 5 — Clear cancellation, price

**Caller script (opening line):** "I need to cancel because the new pricing doesn't work for my budget anymore."

**Expected:** `intent = cancellation`, `cancellation_reason = price`, `extraction_status = complete`

**Actual:**
- intent: cancellation
- cancellation_reason: price
- summary: The caller wanted to cancel their subscription because the new pricing no longer fit their budget, and they confirmed they were not interested in alternative plans.
- account_identifier: test@email.com
- urgency: medium
- billing_issue_type (should be null): **subscription_change** — analyzer justified as "which falls under a subscription change"
- technical_issue_type (should be null): null
- account_change_type (should be null): null
- extraction_status: complete

**Verdict:** PASS (primary) / FAIL (cross-field) — primary classification (`cancellation` / `price`) is correct, but `billing_issue_type: subscription_change` leaked on a cancellation call. Same bug family as Scenario 3: analyzer pattern-matched on "subscription" surface terms despite the guard clause. Second instance of the cross-field leakage pattern.

---

### Scenario 6 — Clear cancellation, switching competitor

**Caller script (opening line):** "I'm moving to Zendesk so I need to cancel my account here."

**Expected:** `intent = cancellation`, `cancellation_reason = switching_competitor`, `extraction_status = complete`

**Actual:**
- intent: cancellation
- cancellation_reason: switching_competitor
- summary: The caller wanted to cancel their account because they are switching to Zendesk, citing better value from the competitor's product/service.
- account_identifier: test@email.com
- urgency: medium
- extraction_status: complete

**Verdict:** PASS — competitor name captured correctly, clean classification, no cross-field leakage.

---

### Scenario 7 — Ambiguous intent

**Caller script (opening line):** "Hey, I just have a question about... my account, I guess?"

**Follow-up behaviour:** Stayed vague; when pressed, said "I don't really know, I was just wondering if everything was okay with my account."

**Expected:** With `ambiguity_flag` deferred, the model will force-classify. Most likely `intent = other` with `extraction_status = complete` if `summary` populates.

**Actual:**
- intent: other
- summary: The caller wanted to inquire about the general status of their account to ensure everything was in order.
- extraction_status: complete

**Verdict:** PASS — model force-classified as `other`, which is the honest outcome for a genuinely ambiguous call. The summary doesn't fabricate detail that wasn't provided. This is exactly the "ambiguity deferred to v1.1" behaviour: clean classification into `other` without manufactured specificity.

---

### Scenario 8 — Multi-intent

**Caller script (opening line):** "My payment failed and also I can't log in to fix it."

**Follow-up behaviour:** Conversation evolved into a payment-method-update story (stolen card, service expiring tomorrow). The login issue became secondary.

**Expected:** Primary intent selected by the model. FAIL only if both issues are silently dropped or the summary fabricates detail.

**Actual:**
- intent: billing
- billing_issue_type: payment_failure
- account_change_type: **payment_method** — analyzer noted caller needed to update payment method
- technical_issue_type: null
- urgency: high
- summary: The caller needs to update their payment method because their previous card was cancelled due to theft, and their service is set to expire tomorrow.
- extraction_status: complete

**Verdict:** PASS — primary classification is defensible (payment failure with time-sensitive impact). The `account_change_type: payment_method` cross-field population is genuinely ambiguous: the call *is* semantically both a billing issue (failed payment) and an account change (updating payment method). Unlike Scenarios 3 and 5, this one has legitimate dual signal. The summary captures the full context without fabricating detail. `urgency: high` is well-calibrated to service-expiring-tomorrow.

---

### Scenario 9 — Self-correction

**Caller script (opening line):** "I want to cancel — actually no, I just want to change my plan to the cheaper tier."

**Expected:** `intent = account_change`, `account_change_type = plan`, `extraction_status = complete`. The model should honour the correction, not the initial statement.

**Actual:**
- intent: account_change
- account_change_type: plan
- billing_issue_type: **subscription_change** — cross-field leak
- cancellation_reason (should be null): null
- summary: The caller wanted to downgrade their service plan from Max 20x to Max 5x to save money, as their current plan was overkill for their usage.
- extraction_status: complete

**Verdict:** PASS (primary) / FAIL (cross-field) — the model correctly honoured the self-correction (`account_change` / `plan`) and didn't fall back on the initial "cancel" statement. That's a meaningful success. But `billing_issue_type: subscription_change` leaked again — third instance of the same cross-field pattern-matching bug. Noted: `cancellation_reason` correctly null, so the self-correction guard on cancellation-specific fields held.

---

### Scenario 10 — Refusal / uncooperative caller

**Caller script (opening line):** "I don't want to tell you why I'm calling."

**Follow-up behaviour:** Continued to refuse to explain. Agent ended the call gracefully after a couple of attempts.

**Expected:** Very short call. `intent = other` most likely. `extraction_status = partial` if intent-specific fields are null, or `complete` if summary is the only required field and populates.

**Actual:**
- intent: other
- summary: The caller wanted to be connected to a support specialist but refused to disclose the reason for their call to the initial agent.
- extraction_status: complete
- Call length: ~3 turns before the agent closed.

**Verdict:** PASS — agent ended the call gracefully after one attempt to clarify, matching the prompt's "accept refusal, end politely" rule. `extraction_status: complete` is correct: for `intent = other`, the only strictly required field is `summary`, which populated honestly. The original "Expected" description misread the schema — partial was not the correct expectation here.

---

### Scenario 11 — Partial extraction, missing detail

**Caller script (opening line):** "I need to change something on my account."

**Follow-up behaviour:** Stayed vague — "I'm not sure, I'll have to think about it."

**Expected:** `intent = account_change`, `account_change_type = null`, `extraction_status = partial`.

**Actual:**
- intent: account_change
- account_change_type: null
- summary: The caller wanted to change something on their account but was unsure what it was and needed time to think about it, so the agent suggested they call back later.
- extraction_status: partial

**Verdict:** PASS — textbook `partial` case. Intent extracted correctly, intent-specific field honestly left null, status correctly derived as `partial`. This is exactly what the three-state status model was designed to produce: the call happened, the pipeline worked, but the analyzer correctly acknowledged it didn't have enough information to fully classify. Strongest validation of the `partial` path in the matrix.

---

### Scenario 12 — PII leak regression

**Caller script (opening line):** "I was charged twice, please refund me — my email is test@email.com and I need this fixed today."

**Follow-up behaviour:** Normal cooperation on follow-up questions.

**Expected:** `intent = billing`, `billing_issue_type` populated, `extraction_status = complete`. Critical test: the rendered `summary` on the `/tickets` dashboard must NOT contain `test@email.com`.

**Actual:**
- intent: billing
- billing_issue_type: charge_dispute
- summary (as stored / rendered on dashboard): The caller reported being charged twice for $15 on March 15th, 2026, and requested a refund for the duplicate charge.
- account_identifier: test@email.com
- urgency: high
- extraction_status: complete

**Verdict:** PASS — the single most important scenario in the matrix. The caller explicitly embedded `test@email.com` in their opening statement. The `summary` rendered on the public dashboard contains no email address. The two-layer privacy defence (LLM description + backend sanitizer) worked end-to-end against a deliberately hostile input.

**PII check:** Does the dashboard-rendered `summary` contain `test@email.com`? **NO** — confirmed by inspecting the live `/tickets` page.

---

## Summary

- **Total scenarios:** 12
- **PASS:** 11 (Scenarios 1, 2, 4, 5, 6, 7, 8, 9, 10, 11, 12)
- **FAIL:** 1 hard fail (Scenario 3); Scenarios 5 and 9 are partial-fails on cross-field discipline but PASS on primary classification
- **Status distribution:** complete = 11, partial = 1, needs_review = 0 (path not exercised)
- **Intent distribution observed:** billing = 4, cancellation = 2, account_change = 3, technical = 1, other = 2

### Observations

1. **Cross-field pattern-matching persists despite guard-clause descriptions.** Three scenarios (3, 5, 9) showed intent-specific fields populating on calls where they shouldn't have. Strengthened field descriptions with explicit "leave empty if not [X]" guard clauses reduced but did not eliminate the bug. The analyzer occasionally surface-matches on vocabulary — the word "password" on a login call, "subscription" on a cancellation, "subscription" on a plan change — even when instructed otherwise. This is the clearest signal in the matrix that prompt-based defences alone are insufficient; backend cross-field validation is the appropriate v1.1 fix.

2. **Partial extraction works cleanly and honestly.** Scenario 11 produced `intent = account_change`, `account_change_type = null`, `extraction_status = partial`. The analyzer correctly acknowledged insufficient information rather than inventing a classification. The three-state status model (complete / partial / needs_review) distinguishes "call happened and everything extracted cleanly" from "call happened but the analyzer couldn't fully classify" — exactly the triage signal a human reviewer would need.

3. **PII defence-in-depth validated against hostile input.** Scenario 12 deliberately embedded `test@email.com` directly in the caller's opening statement. The rendered `/tickets` dashboard contains no email in the summary, despite the caller explicitly stating it. The `account_identifier` field captured the email for downstream specialist use but is not rendered publicly. Two-layer defence (LLM instructed against PII in summary + backend regex sanitizer) confirmed end-to-end.

4. **Self-correction was handled better than expected.** Scenario 9's "cancel — actually no, change my plan" sequence was correctly classified as `account_change` / `plan`, honouring the correction rather than the initial statement. `cancellation_reason` stayed null despite the word "cancel" appearing in the transcript. The model genuinely understood temporal sequence in caller reasoning, not just keyword presence.

### Failures worth iterating on in v1.1

- **Cross-field leakage on intent-specific fields (Scenarios 3, 5, 9).** Fix: add backend validation in `app/webhook.py` that nulls intent-specific fields when they don't match the primary intent. Approximately 10 lines of code — check `payload.intent` and zero out any intent-specific field that doesn't match. This provides belt-and-braces enforcement behind the prompt-level defence, and is the defence-in-depth story for extraction exactly as the PII sanitizer is for summary privacy. Deferred rather than fixed in v1.0 to preserve the honest matrix data showing the bug class exists.

- **Ambiguity detection (Scenarios 7, 8, 10).** `ambiguity_flag` was dropped from v1.0 because LLM self-reported confidence is unreliable. Planned v1.1 approach: declare `mentioned_issues` as a list of strings, let the analyzer list every distinct issue mentioned, derive ambiguity in the backend from list length > 1. This gives the LLM a concrete extractive task (listing mentions) rather than a meta-cognitive task (self-reporting confidence).