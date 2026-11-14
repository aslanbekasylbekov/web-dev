from typing import TypeVar

from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ValidationError
from sqlalchemy import Select, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..schemas import ErrorResponse

M = TypeVar("M", bound=BaseModel)


def not_found(description: str) -> dict:
    return {404: {"model": ErrorResponse, "description": description}}


def conflict(description: str) -> dict:
    return {409: {"model": ErrorResponse, "description": description}}


def get_or_404(db: Session, model, obj_id: int, name: str):
    obj = db.get(model, obj_id)
    if obj is None:
        raise HTTPException(status_code=404, detail=f"{name} {obj_id} not found")
    return obj


def validate_merged(schema: type[M], current: dict, changes: dict) -> M:
    """PATCH: apply the changes to the current values and validate the result with the full schema.

    Errors are returned exactly like FastAPI's own 422 body errors.
    """
    try:
        return schema(**(current | changes))
    except ValidationError as exc:
        errors = exc.errors(include_url=False)
        raise RequestValidationError([{**e, "loc": ("body", *e["loc"])} for e in errors])


def order_by(sort: str, allowed: dict, tie_breaker):
    """`sort=field` ascending, `sort=-field` descending. Unknown field -> 422."""
    field = sort.lstrip("-")
    if field not in allowed:
        raise HTTPException(status_code=422, detail=f"Cannot sort by '{field}'. Allowed: {sorted(allowed)}")
    column = allowed[field]
    direction = column.desc().nulls_last() if sort.startswith("-") else column.asc().nulls_last()
    return direction, tie_breaker


def paginate(db: Session, stmt: Select, order: tuple, limit: int, offset: int) -> dict:
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    items = db.scalars(stmt.order_by(*order).limit(limit).offset(offset)).unique().all()
    return {"items": items, "total": total, "limit": limit, "offset": offset}


def commit_or_409(db: Session, message: str) -> None:
    """Commit; a unique-index violation that slipped past the pre-check (race) becomes 409."""
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail=message)
