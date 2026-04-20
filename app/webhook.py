import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

from elevenlabs.client import ElevenLabs
from fastapi import APIRouter, Header, HTTPException, Request, status
from pydantic import ValidationError
from sqlalchemy.dialects.postgresql import insert as pg_insert

from .config import get_settings
from .db import SessionLocal
from .enums import ALLOWED_INTENT_SPECIFIC_VALUES, INTENT_REQUIRED_FIELD, PUBLIC_INTENTS
from .models import ExtractionStatus, Intent, Ticket
from .schemas import WebhookPayload

logger = logging.getLogger(__name__)
router = APIRouter()

# Instantiated once at module load. The api_key is not used by
# construct_event; only API calls would need a real key. We pass a
# placeholder so the WebhooksClient has a valid client_wrapper.
_webhooks_verifier = ElevenLabs(api_key="webhook-verify-only").webhooks


# Precompiled redaction patterns. `summary` is shown on a public dashboard,
# so these run before persistence. See docs/ticket-schema.md privacy note.
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
_PHONE_RE = re.compile(r"\b\+?\d[\d\s().-]{7,}\d\b")
_ACCOUNT_ID_RE = re.compile(r"\b\d{6,}\b")
_REDACTED_PLACEHOLDER = "Caller described a support issue; details withheld for privacy."


def sanitize_summary(text: str | None) -> str | None:
    """Strip emails, phone numbers, and long numeric tokens from summary text.

    If the redacted text is empty or contains only redaction markers, return
    a privacy-safe fallback rather than a meaningless string of tags.
    """
    if not text:
        return text
    out = _EMAIL_RE.sub("[redacted email]", text)
    out = _PHONE_RE.sub("[redacted phone]", out)
    out = _ACCOUNT_ID_RE.sub("[redacted id]", out)
    residue = re.sub(r"\[redacted [a-z]+\]", "", out).strip()
    if not residue or len(residue) < 5:
        return _REDACTED_PLACEHOLDER
    return out


def _extract_value(raw: Any) -> Any:
    # Data Collection results can arrive either as bare values or as
    # objects like {"value": ..., "rationale": "..."}. Handle both.
    if isinstance(raw, dict) and "value" in raw:
        return raw["value"]
    return raw


def _normalized_text(raw: Any) -> str | None:
    if not isinstance(raw, str):
        return None
    value = raw.strip().lower()
    return value or None


def _resolve_intent(data_collection: dict[str, Any]) -> tuple[Intent | None, bool]:
    normalized = _normalized_text(_extract_value(data_collection.get("intent")))
    if normalized is None:
        return None, False
    if normalized == Intent.NEEDS_REVIEW.value:
        return None, True

    public_values = {intent.value for intent in PUBLIC_INTENTS}
    if normalized not in public_values:
        return None, False

    return Intent(normalized), False


def derive_intent_and_status(
    data_collection: dict[str, Any],
) -> tuple[Intent | None, ExtractionStatus]:
    """Apply the locked intent-mapping rule from PLAN.md:

    - missing / unparseable intent -> partial with intent set to null
    - ambiguity flag or legacy intent="needs_review" -> needs_review
    - missing summary or missing / invalid intent-specific required field -> partial
    - everything present and valid -> complete
    """
    intent, legacy_needs_review = _resolve_intent(data_collection)
    if _extract_value(data_collection.get("ambiguity_flag")) is True or legacy_needs_review:
        return intent, ExtractionStatus.NEEDS_REVIEW

    if intent is None:
        return None, ExtractionStatus.PARTIAL

    summary = _extract_value(data_collection.get("summary"))
    if not isinstance(summary, str) or not summary.strip():
        return intent, ExtractionStatus.PARTIAL

    required_field = INTENT_REQUIRED_FIELD.get(intent)
    if required_field is not None:
        normalized_value = _normalized_text(_extract_value(data_collection.get(required_field)))
        if normalized_value is None:
            return intent, ExtractionStatus.PARTIAL
        allowed_values = ALLOWED_INTENT_SPECIFIC_VALUES[required_field]
        if normalized_value not in allowed_values:
            return intent, ExtractionStatus.PARTIAL

    return intent, ExtractionStatus.COMPLETE


def _call_timestamps(metadata) -> tuple[datetime | None, datetime | None]:
    if metadata is None or metadata.start_time_unix_secs is None:
        return None, None
    start = datetime.fromtimestamp(metadata.start_time_unix_secs, tz=timezone.utc)
    end = None
    if metadata.call_duration_secs is not None:
        end = datetime.fromtimestamp(
            metadata.start_time_unix_secs + metadata.call_duration_secs,
            tz=timezone.utc,
        )
    return start, end


@router.post("/webhooks/elevenlabs")
async def elevenlabs_webhook(
    request: Request,
    elevenlabs_signature: str | None = Header(default=None, alias="elevenlabs-signature"),
) -> dict[str, str]:
    secret = get_settings().elevenlabs_webhook_secret
    raw_bytes = await request.body()

    try:
        raw_str = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Body is not valid UTF-8")

    # construct_event:
    #   - raises BadRequestError on missing/bad signature, stale timestamp
    #   - raises ValueError (from int(timestamp)) on malformed signature header
    #   - raises json.JSONDecodeError if rawBody isn't valid JSON
    try:
        event = _webhooks_verifier.construct_event(raw_str, elevenlabs_signature or "", secret)
    except json.JSONDecodeError:
        logger.warning("Webhook body is signed but not valid JSON")
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Body is not valid JSON")
    except Exception as exc:
        logger.warning("Webhook signature verification failed: %s", exc)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook signature")

    try:
        payload = WebhookPayload.model_validate(event)
    except ValidationError as ve:
        logger.warning("Webhook payload failed transport validation: %s", ve)
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Missing required transport-level fields",
        )

    data = payload.data
    dc = data.analysis.data_collection_results

    intent, extraction_status = derive_intent_and_status(dc)

    raw_summary = _extract_value(dc.get("summary"))
    summary = sanitize_summary(raw_summary if isinstance(raw_summary, str) else None)

    call_started_at, call_ended_at = _call_timestamps(data.metadata)

    db = None
    try:
        db = SessionLocal()
        stmt = pg_insert(Ticket).values(
            conversation_id=data.conversation_id,
            intent=intent.value if intent is not None else None,
            extraction_status=extraction_status.value,
            summary=summary,
            call_started_at=call_started_at,
            call_ended_at=call_ended_at,
            extracted_data=dc,
            raw_payload=event,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["conversation_id"],
            set_={
                "intent": stmt.excluded.intent,
                "extraction_status": stmt.excluded.extraction_status,
                "summary": stmt.excluded.summary,
                "call_started_at": stmt.excluded.call_started_at,
                "call_ended_at": stmt.excluded.call_ended_at,
                "extracted_data": stmt.excluded.extracted_data,
                "raw_payload": stmt.excluded.raw_payload,
            },
        )
        db.execute(stmt)
        db.commit()
    except Exception:
        if db is not None:
            db.rollback()
        logger.exception(
            "Failed to persist ticket for conversation_id=%s", data.conversation_id
        )
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Persistence failed"
        )
    finally:
        if db is not None:
            db.close()

    return {"status": "ok"}
