# Ticket Schema

Postgres table definition for the `tickets` table. Source of truth is [app/models.py](../app/models.py); this doc exists so the schema can be reviewed without reading SQLAlchemy.

## Rationale

Each ticket row is the post-call record for one ElevenLabs conversation. The row carries **both** normalized columns (for indexing, filtering, and dashboard rendering) and JSONB blobs (for resilience to payload evolution and for debugging). If ElevenLabs adds new Data Collection fields later, `extracted_data` captures them without requiring a migration; if ElevenLabs changes payload structure, `raw_payload` is the fallback source of truth.

## Columns

| Column | Type | Nullable | Notes |
| --- | --- | --- | --- |
| `id` | `UUID` | no | Primary key. Generated server-side via `uuid.uuid4`. |
| `conversation_id` | `TEXT` | no | **Unique**. Idempotency key - ElevenLabs webhook retries on non-200, so we upsert on this column with `ON CONFLICT DO UPDATE`. |
| `intent` | `ENUM(intent)` | no | One of: `billing`, `technical`, `account_change`, `cancellation`, `other`, `needs_review`. See intent-mapping rule in `PLAN.md` for the distinction between `other` and `needs_review`. |
| `extraction_status` | `ENUM(extraction_status)` | no | One of: `complete`, `partial`, `needs_review`. See derivation rules in `docs/data-collection-schema.md`. |
| `summary` | `TEXT` | yes | Analyzer-produced, sanitized before persistence for PII (emails, phone numbers, long numeric tokens). Public-facing; rendered on `/tickets`. |
| `created_at` | `TIMESTAMPTZ` | no | Server-set on insert. |
| `call_started_at` | `TIMESTAMPTZ` | yes | From webhook payload timestamps when present. |
| `call_ended_at` | `TIMESTAMPTZ` | yes | From webhook payload timestamps when present. |
| `extracted_data` | `JSONB` | no | Full `analysis.data_collection_results` block from the webhook. Never rendered publicly. |
| `raw_payload` | `JSONB` | no | Full webhook request body. Never rendered publicly; for debugging only. |

## Constraints

- Primary key: `id`.
- Unique: `conversation_id` (also indexed for upsert lookups).
- Enum types (`intent`, `extraction_status`) are created as native Postgres enums by SQLAlchemy.

## Migrations

Tables are created on app startup via `Base.metadata.create_all()` in [app/db.py](../app/db.py), called from the FastAPI `lifespan` hook in [app/main.py](../app/main.py). Alembic is intentionally deferred - for a single-model demo, `create_all` is sufficient and keeps the project surface small. See `PLAN.md` "Out of scope" section.

## Rendering discipline

The public `/tickets` dashboard renders only: `created_at`, `intent`, `extraction_status`, `summary`. `extracted_data` and `raw_payload` are **never** surfaced via any route, even in logs or error pages. This is a hard privacy rule, not a UI choice.
