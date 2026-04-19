from contextlib import asynccontextmanager

from fastapi import FastAPI

from .db import init_db
from .webhook import router as webhook_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Customer Support Triage", lifespan=lifespan)
app.include_router(webhook_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
