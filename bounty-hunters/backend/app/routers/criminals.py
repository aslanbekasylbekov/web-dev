from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..database import get_db
from ..models import WantedCriminal
from ..schemas import CriminalDetailOut, CriminalOut

router = APIRouter(prefix="/api/criminals", tags=["criminals"])


@router.get("/", response_model=list[CriminalOut], summary="List wanted criminals")
def list_criminals(
    min_reward: int | None = Query(None, ge=0, description="Minimum bounty (inclusive)"),
    max_reward: int | None = Query(None, ge=0, description="Maximum bounty (inclusive)"),
    armed: bool | None = Query(None),
    has_crew: bool | None = Query(None),
    escape_master: bool | None = Query(None),
    sort: Literal["reward", "-reward"] | None = Query(
        None, description="`reward` = ascending, `-reward` = descending"
    ),
    db: Session = Depends(get_db),
):
    if min_reward is not None and max_reward is not None and min_reward > max_reward:
        raise HTTPException(status_code=400, detail="min_reward cannot be greater than max_reward")

    stmt = select(WantedCriminal)
    if min_reward is not None:
        stmt = stmt.where(WantedCriminal.reward >= min_reward)
    if max_reward is not None:
        stmt = stmt.where(WantedCriminal.reward <= max_reward)
    if armed is not None:
        stmt = stmt.where(WantedCriminal.armed == armed)
    if has_crew is not None:
        stmt = stmt.where(WantedCriminal.has_crew == has_crew)
    if escape_master is not None:
        stmt = stmt.where(WantedCriminal.escape_master == escape_master)

    if sort == "reward":
        stmt = stmt.order_by(WantedCriminal.reward.asc(), WantedCriminal.id)
    elif sort == "-reward":
        stmt = stmt.order_by(WantedCriminal.reward.desc(), WantedCriminal.id)
    else:
        stmt = stmt.order_by(WantedCriminal.id)

    return db.scalars(stmt).all()


@router.get(
    "/{criminal_id}/",
    response_model=CriminalDetailOut,
    summary="Criminal details with hunt history",
    responses={404: {"description": "Criminal not found"}},
)
def get_criminal(criminal_id: int = Path(gt=0), db: Session = Depends(get_db)):
    criminal = db.scalar(
        select(WantedCriminal)
        .options(selectinload(WantedCriminal.hunts))
        .where(WantedCriminal.id == criminal_id)
    )
    if criminal is None:
        raise HTTPException(status_code=404, detail=f"Criminal with id {criminal_id} not found")

    data = CriminalOut.model_validate(criminal).model_dump()
    return {
        **data,
        "hunts_count": len(criminal.hunts),
        "captured": any(h.success for h in criminal.hunts),
        "hunts": criminal.hunts,
    }
