# Data Collection Schema

This is the product spec for what the ElevenLabs Data Collection analyzer should extract from each conversation. Fields declared here are configured in the agent's Data Collection settings in the ElevenLabs dashboard; the names below are the exact identifiers the webhook payload will return under `analysis.data_collection_results`.

The schema is versioned by phase. Phase 1 fields must be stable before Phase 2 fields are added - don't change Phase 1 names after calls have been recorded against them.

---

## Phase 1 - billing only

Agent scope: handle inbound billing questions only. System prompt refuses other intents and says the user will be transferred.

### Required (non-null for `extraction_status = complete`)

| Field | Type | Description (given to the analyzer) |
| --- | --- | --- |
| `intent` | string enum: `billing` | Always `billing` in Phase 1; field still declared so the Phase 2 schema is a superset, not a migration. |
| `billing_issue_type` | string enum: `charge_dispute`, `payment_failure`, `subscription_change`, `refund_request`, `invoice_question`, `other` | Which category of billing issue the caller described. Use `other` only when the issue is clearly billing but doesn't fit the other categories. |
| `summary` | string, <= 240 chars | One-sentence plain-language summary of what the caller wanted. Written as if describing the call to a human colleague. Do not include names, email addresses, phone numbers, account identifiers, or other personal identifiers. |

### Optional (may be null; presence does not affect `extraction_status`)

| Field | Type | Description |
| --- | --- | --- |
| `account_identifier` | string | Account number, username, email-as-login, or other account ID the caller gave. Null if not provided. |
| `amount_disputed` | number | If the caller mentioned a specific amount in dispute, the numeric value. Null otherwise. |
| `urgency` | string enum: `low`, `medium`, `high` | Analyzer's read of how urgent the caller framed the issue. `medium` if not obviously either extreme. |

### Extraction status derivation

- `complete` -> all three required fields are non-null **and** `intent == billing` **and** `billing_issue_type` is one of the enum values.
- `partial` -> at least one required field is null or `billing_issue_type` is outside the enum.
- `needs_review` -> analyzer returned an intent the agent shouldn't have accepted (non-billing) **or** returned ambiguous / multi-intent output. In Phase 1 this should be rare because the agent refuses off-topic calls.

---

## Phase 2 - all intents

Adds four intent-specific fields. The Phase 1 `intent` enum widens; no Phase 1 field is removed or renamed.

### Required (non-null for `extraction_status = complete`)

| Field | Type | Description |
| --- | --- | --- |
| `intent` | string enum: `billing`, `technical`, `account_change`, `cancellation`, `other` | The caller's primary intent. `other` means the call was clearly a support request but doesn't fit the four main categories. Ambiguous or multi-intent cases are **not** `other` - the webhook handler maps those to `needs_review` based on a separate analyzer signal (see `ambiguity_flag` below). |
| `summary` | string, <= 240 chars | Same as Phase 1: keep it plain-language and do not include names, email addresses, phone numbers, account identifiers, or other personal identifiers. |

### Conditionally required

Exactly one of the following must be non-null, depending on `intent`. If `intent == other`, none of these need to be filled.

| Field | Type | Required when | Description |
| --- | --- | --- | --- |
| `billing_issue_type` | string enum (see Phase 1) | `intent == billing` | |
| `technical_issue_type` | string enum: `login`, `outage`, `feature_not_working`, `performance`, `data_loss`, `other` | `intent == technical` | |
| `account_change_type` | string enum: `email`, `password`, `plan`, `payment_method`, `personal_info`, `other` | `intent == account_change` | |
| `cancellation_reason` | string enum: `price`, `not_using`, `missing_feature`, `switching_competitor`, `temporary`, `other` | `intent == cancellation` | Why the caller wants to cancel, in their words. |

### Optional

| Field | Type | Description |
| --- | --- | --- |
| `account_identifier` | string | As in Phase 1. |
| `urgency` | string enum: `low`, `medium`, `high` | As in Phase 1. |
| `ambiguity_flag` | boolean | `true` if the analyzer had low confidence in the intent classification or detected multiple conflicting intents. Drives `extraction_status = needs_review`. |
| `amount_disputed` | number | As in Phase 1. |

### Phase 2 extraction status derivation

- `complete` -> `intent` and `summary` non-null; the conditionally required field for that intent is non-null and within its enum; `ambiguity_flag` is false or null.
- `partial` -> `intent` and `summary` are set, but the conditionally required field is null or out-of-enum. Persist and surface in the dashboard.
- `needs_review` -> `ambiguity_flag == true` **or** `intent` itself was returned as a multi-value / free-text string. Distinct from `other`: `other` is a confident classification that doesn't match a supported type; `needs_review` is low-confidence or multi-intent.

---

## Field naming conventions

- `snake_case` for field identifiers.
- String enums listed explicitly in the analyzer description so the LLM is biased toward them. The webhook handler still validates the returned value against the enum - out-of-enum values trigger `partial`.
- No PII is a declared field. `account_identifier` is optional and stored, but never rendered on the public dashboard (see `PLAN.md` privacy discipline).
- Summaries are instructed to avoid including names, emails, phone numbers, or account identifiers; the dashboard surfaces `summary` publicly, so the analyzer prompt must enforce this.
- The backend sanitizes `summary` again before persistence/rendering. Analyzer instructions reduce risk; they do not replace backend privacy filtering.
