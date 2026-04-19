from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_db
from .models import ExtractionStatus, Intent, Ticket

router = APIRouter()

_TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


@router.get("/")
def root() -> RedirectResponse:
    return RedirectResponse(url="/tickets", status_code=307)


@router.get("/tickets")
def tickets(
    request: Request,
    intent: str | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
):
    stmt = select(Ticket).order_by(Ticket.created_at.desc())

    intent_filter: Intent | None = None
    if intent:
        try:
            intent_filter = Intent(intent.lower())
            stmt = stmt.where(Ticket.intent == intent_filter)
        except ValueError:
            intent_filter = None

    status_filter: ExtractionStatus | None = None
    if status:
        try:
            status_filter = ExtractionStatus(status.lower())
            stmt = stmt.where(Ticket.extraction_status == status_filter)
        except ValueError:
            status_filter = None

    rows = db.execute(stmt.limit(200)).scalars().all()

    return templates.TemplateResponse(
        request,
        "tickets.html",
        {
            "tickets": rows,
            "intents": [i.value for i in Intent],
            "statuses": [s.value for s in ExtractionStatus],
            "active_intent": intent_filter.value if intent_filter else None,
            "active_status": status_filter.value if status_filter else None,
            "total": len(rows),
        },
    )
