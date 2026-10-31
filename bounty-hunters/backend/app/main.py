from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy import text

from . import models
from .config import settings
from .database import Base, engine
from .routers import criminals, hunts


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title=settings.app_name,
    description="REST API for space bounty hunters: wanted criminals and a hunting journal.",
    version="1.0.0",
    lifespan=lifespan,
)
app.include_router(criminals.router)
app.include_router(hunts.router)


@app.get("/health", tags=["system"], summary="Health check")
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
