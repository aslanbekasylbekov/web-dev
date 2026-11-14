from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy import text

from . import models  # noqa: F401  (registers the tables)
from .config import settings
from .database import Base, engine
from .routers import categories, payments, subscriptions
from .schemas import ErrorResponse, HealthOut


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


DESCRIPTION = """
**SubTrack** keeps track of your paid subscriptions (Netflix, Spotify, iCloud, gym...),
tells you how much they really cost and when the next charge is coming, and stores the history of real payments.

### Data model
* **Category** (Streaming, Music, Cloud...) — has many **Subscriptions** (one-to-many)
* **Subscription** (Netflix) — belongs to one Category, has many **Payments** (one-to-many)
* **Payment** — one real charge of one Subscription

### Business rules
* Category `name` and subscription `name` are unique, case-insensitive -> `409`
* A category that still has subscriptions cannot be deleted -> `409`. Deleting a subscription deletes its payments
* `price` > 0, at most 2 decimal places; `cancelled_at` only when `active` is false, not earlier than `start_date`
* A payment lies between `start_date` and `cancelled_at` (or today) -> `422`; one payment per subscription per day -> `409`
* The currency of a subscription with payments cannot change -> `409`
* `monthly_cost`, `next_payment_date`, `total_paid`... are computed by the server, you cannot send them
"""

app = FastAPI(
    title=settings.app_name,
    description=DESCRIPTION,
    version="2.0.0",
    lifespan=lifespan,
    openapi_tags=[
        {"name": "categories", "description": "Categories and their subscriptions"},
        {"name": "subscriptions", "description": "CRUD, statistics, upcoming charges and payment history"},
        {"name": "payments", "description": "Recorded payments"},
        {"name": "system", "description": "Service health"},
    ],
)
app.include_router(categories.router)
app.include_router(subscriptions.router)
app.include_router(payments.router)


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
