from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy import text

from . import models
from .config import settings
from .database import Base, engine
from .routers import subscriptions
from .schemas import ErrorResponse, HealthOut


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


DESCRIPTION = """
**SubTrack** keeps track of your paid subscriptions (Netflix, Spotify, iCloud, gym...)
and tells you how much they really cost and when the next charge is coming.

### Business rules
* `name` is unique, case-insensitive (`Netflix` = `netflix`) -> `409 Conflict`
* `price` > 0, at most 2 decimal places
* `cancelled_at` is only allowed when `active` is `false`, defaults to today, must not be earlier than `start_date`
* `next_payment_date` and `monthly_cost` are computed by the server, you cannot send them
"""

app = FastAPI(
    title=settings.app_name,
    description=DESCRIPTION,
    version="1.0.0",
    lifespan=lifespan,
    openapi_tags=[
        {"name": "subscriptions", "description": "CRUD, statistics and upcoming payments"},
        {"name": "system", "description": "Service health"},
    ],
)
app.include_router(subscriptions.router)


@app.get(
    "/health",
    tags=["system"],
    response_model=HealthOut,
    responses={503: {"model": ErrorResponse, "description": "Database is unreachable"}},
    summary="Health check",
    description="Returns 200 if the service is up and can reach the database.",
)
def health():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        raise HTTPException(status_code=503, detail="Database is unreachable")
    return {"status": "ok", "database": "up"}


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/docs")
