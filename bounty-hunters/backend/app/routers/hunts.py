from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import HuntLog, WantedCriminal
from ..schemas import HuntCreate, HuntOut, HuntUpdate

router = APIRouter(prefix="/api/hunts", tags=["hunts"])


def _get_hunt_or_404(db: Session, hunt_id: int) -> HuntLog:
    hunt = db.get(HuntLog, hunt_id)
    if hunt is None:
        raise HTTPException(status_code=404, detail=f"Hunt log with id {hunt_id} not found")
    return hunt


@router.get("/", response_model=list[HuntOut], summary="List hunt logs")
def list_hunts(
    criminal_id: int | None = Query(None, gt=0, description="Only hunts for this criminal"),
    db: Session = Depends(get_db),
):
    stmt = select(HuntLog).order_by(HuntLog.id)
    if criminal_id is not None:
        if db.get(WantedCriminal, criminal_id) is None:
            raise HTTPException(status_code=404, detail=f"Criminal with id {criminal_id} not found")
        stmt = stmt.where(HuntLog.criminal_id == criminal_id)
    return db.scalars(stmt).all()


@router.get(
    "/{hunt_id}/",
    response_model=HuntOut,
    summary="Get one hunt log",
    responses={404: {"description": "Hunt log not found"}},
)
def get_hunt(hunt_id: int = Path(gt=0), db: Session = Depends(get_db)):
    return _get_hunt_or_404(db, hunt_id)


@router.post(
    "/",
    response_model=HuntOut,
    status_code=201,
    summary="Record a capture attempt",
    responses={422: {"description": "Invalid body or criminal does not exist"}},
)
def create_hunt(payload: HuntCreate, response: Response, db: Session = Depends(get_db)):
    if db.get(WantedCriminal, payload.criminal_id) is None:
        raise HTTPException(
            status_code=422,
            detail=f"criminal_id {payload.criminal_id} does not reference an existing criminal",
        )
    hunt = HuntLog(**payload.model_dump())
    db.add(hunt)
    db.commit()
    db.refresh(hunt)
    response.headers["Location"] = f"/api/hunts/{hunt.id}/"
    return hunt


@router.patch(
    "/{hunt_id}/",
    response_model=HuntOut,
    summary="Update success and/or notes",
    responses={404: {"description": "Hunt log not found"}},
)
def update_hunt(payload: HuntUpdate, hunt_id: int = Path(gt=0), db: Session = Depends(get_db)):
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=422, detail="Provide at least one of: success, notes")
    if "success" in changes and changes["success"] is None:
        raise HTTPException(status_code=422, detail="success cannot be null")
    if "notes" in changes and changes["notes"] is None:
        raise HTTPException(status_code=422, detail="notes cannot be null")

    hunt = _get_hunt_or_404(db, hunt_id)
    for field, value in changes.items():
        setattr(hunt, field, value)
    db.commit()
    db.refresh(hunt)
    return hunt


@router.delete(
    "/{hunt_id}/",
    status_code=204,
    summary="Delete a hunt log",
    responses={404: {"description": "Hunt log not found"}},
)
def delete_hunt(hunt_id: int = Path(gt=0), db: Session = Depends(get_db)):
    hunt = _get_hunt_or_404(db, hunt_id)
    db.delete(hunt)
    db.commit()
    return Response(status_code=204)
