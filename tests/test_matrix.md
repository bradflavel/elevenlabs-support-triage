# Extraction Test Matrix

Results from calling the deployed agent with a spread of scenarios. Each entry records the caller's prompt, the analyzer's output, and the resulting `extraction_status`. This matrix is the gate for declaring extraction quality acceptable.

The goal is not 100% `complete` - it is **correct** status assignment across the spectrum. A call that should be `partial` getting `partial` is a pass; a call that should be `needs_review` getting forced into `billing` is a bug.

## Scenarios

<!--
Filled after real calls are made against the deployed agent.

Template for each row:

### Scenario N - <one-line summary>

**Caller script:** <what was said / the prompt>

**Expected:** intent = <...>, extraction_status = <...>

**Actual:**
- intent: ...
- billing_issue_type / technical_issue_type / etc: ...
- summary: ...
- ambiguity_flag: ...
- extraction_status: ...

**Verdict:** PASS / FAIL - <why>

-->

### Planned scenarios

1. **Clear billing - charge dispute**: "I see a charge on my card I don't recognize, can you look into it?" -> expect `billing` / `charge_dispute` / `complete`.
2. **Clear billing - refund request**: "I'd like a refund for last month's subscription, it didn't renew correctly." -> expect `billing` / `refund_request` / `complete`.
3. **Clear technical - login**: "I can't log into my account, it keeps saying my password is wrong even though it's right." -> expect `technical` / `login` / `complete`.
4. **Clear account change - email**: "I want to update the email address on my account because my old one is being shut down." -> expect `account_change` / `email` / `complete`.
5. **Clear cancellation - price**: "I need to cancel because the new pricing doesn't work for my budget anymore." -> expect `cancellation` / `price` / `complete`.
6. **Clear cancellation - switching**: "I'm moving to <competitor> so I need to cancel my account here." -> expect `cancellation` / `switching_competitor` / `complete`.
7. **Ambiguous intent**: "Hey, I just have a question about... my account, I guess?" with no follow-up detail. -> expect `needs_review` / `needs_review`.
8. **Multi-intent**: "My payment failed and also I can't log in to fix it." -> expect `needs_review` or the primary intent with a note; verify `ambiguity_flag` behaviour.
9. **Self-correction**: "I want to cancel - actually no, I just want to change my plan to the cheaper tier." -> expect `account_change` / `plan`.
10. **Refusal / abuse**: caller refuses to explain issue or becomes abusive; agent ends call gracefully. -> expect short call, `needs_review` status, summary reflects lack of information.
11. **Partial extraction - missing detail**: caller gives intent but not the specific type (e.g. "I need to change something on my account" but doesn't say what). -> expect correct intent, `partial` status.
12. **Out-of-scope (Phase 1 only)**: caller asks about a technical problem to the billing-only Phase 1 agent. -> expect the agent to refuse politely; row either not created or flagged.

## How to execute

1. Make sure the agent is deployed with the Phase 2 system prompt (all five intents).
2. For each scenario above, start a call in the browser widget and follow the script.
3. After the call ends, wait for the webhook to fire (a few seconds).
4. Query the production Postgres or load `/tickets` to find the row.
5. Record the actual outputs in this file, in the Scenario section above.
6. Mark each scenario PASS or FAIL. Any FAIL drives a prompt iteration in [../docs/agent-prompts.md](../docs/agent-prompts.md).

## Summary

<!--
Totals once all scenarios are run:

- Total: N
- Pass: N
- Fail: N
- Status distribution: complete X, partial Y, needs_review Z
-->
