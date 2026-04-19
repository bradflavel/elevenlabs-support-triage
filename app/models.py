import uuid
from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import Enum as SQLEnum, Text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    pass


class Intent(str, Enum):
    BILLING = "billing"
    TECHNICAL = "technical"
    ACCOUNT_CHANGE = "account_change"
    CANCELLATION = "cancellation"
    OTHER = "other"
    NEEDS_REVIEW = "needs_review"


class ExtractionStatus(str, Enum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    NEEDS_REVIEW = "needs_review"


class Ticket(Base):
    __tablename__ = "tickets"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    conversation_id: Mapped[str] = mapped_column(
        Text, unique=True, nullable=False, index=True
    )
    intent: Mapped[Intent] = mapped_column(
        SQLEnum(Intent, name="intent", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    extraction_status: Mapped[ExtractionStatus] = mapped_column(
        SQLEnum(
            ExtractionStatus,
            name="extraction_status",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
    )
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    call_started_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    call_ended_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    extracted_data: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    raw_payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
