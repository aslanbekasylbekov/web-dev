from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import billing
from ..database import get_db
from ..models import Subscription
from ..schemas import (
    BillingCycle,
    Category,
    Currency,
    ErrorResponse,
    StatsOut,
    SubscriptionCreate,
    SubscriptionList,
    SubscriptionOut,
    SubscriptionPatch,
    UpcomingOut,
)

router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])

WRITABLE_FIELDS = (
    "name", "category", "price", "currency", "billing_cycle", "start_date", "active", "cancelled_at", "notes",
)
SORT_FIELDS = {"id", "name", "price", "start_date", "created_at", "category", "currency", "billing_cycle"}

NOT_FOUND = {404: {"model": ErrorResponse, "description": "Subscription not found"}}
CONFLICT = {409: {"model": ErrorResponse, "description": "A subscription with this name already exists"}}


def _get_or_404(db: Session, sub_id: int) -> Subscription:
    sub = db.get(Subscription, sub_id)
    if sub is None:
        raise HTTPException(status_code=404, detail=f"Subscription {sub_id} not found")
    return sub


def _ensure_unique_name(db: Session, name: str, exclude_id: int | None) -> None:
    stmt = select(Subscription.id).where(func.lower(Subscription.name) == name.lower())
    if exclude_id is not None:
        stmt = stmt.where(Subscription.id != exclude_id)
    if db.scalar(stmt) is not None:
        raise HTTPException(status_code=409, detail=f"Subscription '{name}' already exists")


def _apply(db: Session, sub: Subscription, payload: SubscriptionCreate) -> Subscription:
    _ensure_unique_name(db, payload.name, exclude_id=sub.id)
    data = payload.model_dump()

    if data["active"]:
        data["cancelled_at"] = None
    elif data["cancelled_at"] is None:
        old = sub.cancelled_at
        data["cancelled_at"] = old if old and old >= data["start_date"] else max(date.today(), data["start_date"])

    for key, value in data.items():
        setattr(sub, key, value)

    db.add(sub)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail=f"Subscription '{payload.name}' already exists")
    db.refresh(sub)
    return sub


def _add(totals: dict, currency: str, amount: Decimal) -> None:
    totals[currency] = totals.get(currency, Decimal("0")) + amount


@router.get(
    "/stats",
    response_model=StatsOut,
    summary="Spending statistics",
    description="Totals and spend per currency. Spend numbers include only active subscriptions.",
)
def subscription_stats(db: Session = Depends(get_db)):
    total, active = db.execute(
        select(func.count(Subscription.id), func.count(Subscription.id).filter(Subscription.active.is_(True)))
    ).one()

    monthly: dict[str, Decimal] = {}
    yearly: dict[str, Decimal] = {}
    by_category: dict[str, dict] = {}
    by_cycle: dict[str, int] = defaultdict(int)
    next_payment = None

    for sub in db.scalars(select(Subscription).where(Subscription.active.is_(True))).all():
        _add(monthly, sub.currency, sub.monthly_cost)
        _add(yearly, sub.currency, billing.yearly_cost(sub.price, sub.billing_cycle))

        cat = by_category.setdefault(sub.category, {"count": 0, "monthly_spend": {}})
        cat["count"] += 1
        _add(cat["monthly_spend"], sub.currency, sub.monthly_cost)

        by_cycle[sub.billing_cycle] += 1

        if next_payment is None or sub.next_payment_date < next_payment["date"]:
            next_payment = {
                "id": sub.id, "name": sub.name, "date": sub.next_payment_date,
                "price": sub.price, "currency": sub.currency,
            }

    return {
        "total": total,
        "active": active,
        "cancelled": total - active,
        "monthly_spend": monthly,
        "yearly_spend": yearly,
        "by_category": by_category,
        "by_billing_cycle": dict(by_cycle),
        "next_payment": next_payment,
    }


@router.get(
    "/upcoming",
    response_model=UpcomingOut,
    summary="Upcoming payments",
    description="Active subscriptions that will charge you within the next `days` days (today included).",
)
def upcoming_payments(
    days: int = Query(7, ge=0, le=365, description="How many days ahead to look"),
    db: Session = Depends(get_db),
):
    today = date.today()
    until = today + timedelta(days=days)

    items = []
    total_due: dict[str, Decimal] = {}
    for sub in db.scalars(select(Subscription).where(Subscription.active.is_(True))).all():
        pay_date = sub.next_payment_date
        if pay_date <= until:
            items.append({
                "id": sub.id, "name": sub.name, "price": sub.price, "currency": sub.currency,
                "billing_cycle": sub.billing_cycle, "next_payment_date": pay_date,
                "days_left": (pay_date - today).days,
            })
            _add(total_due, sub.currency, sub.price)

    items.sort(key=lambda item: (item["next_payment_date"], item["name"].lower()))
    return {"days": days, "date_from": today, "date_to": until, "items": items, "total_due": total_due}


@router.get(
    "",
    response_model=SubscriptionList,
    summary="List subscriptions",
    description=(
        "Returns a page of subscriptions with optional filters.\n\n"
        "**Sorting:** `sort=<field>` ascending or `sort=-<field>` descending. "
        f"Allowed fields: {', '.join(sorted(SORT_FIELDS))}."
    ),
)
def list_subscriptions(
    category: Category | None = Query(None, description="Filter by category"),
    currency: Currency | None = Query(None, description="Filter by currency"),
    billing_cycle: BillingCycle | None = Query(None, description="Filter by billing cycle"),
    active: bool | None = Query(None, description="true = active, false = cancelled"),
    min_price: Decimal | None = Query(None, ge=0, description="Price per period >= this value"),
    max_price: Decimal | None = Query(None, ge=0, description="Price per period <= this value"),
    q: str | None = Query(None, min_length=1, description="Case-insensitive search in name and notes"),
    sort: str = Query("name", description="Sort field, prefix with '-' for descending"),
    limit: int = Query(20, ge=1, le=100, description="Page size"),
    offset: int = Query(0, ge=0, description="Number of items to skip"),
    db: Session = Depends(get_db),
):
    field = sort.lstrip("-")
    if field not in SORT_FIELDS:
        raise HTTPException(status_code=422, detail=f"Cannot sort by '{field}'. Allowed: {sorted(SORT_FIELDS)}")
    if min_price is not None and max_price is not None and min_price > max_price:
        raise HTTPException(status_code=422, detail="min_price must not be greater than max_price")

    stmt = select(Subscription)
    if category:
        stmt = stmt.where(Subscription.category == category.value)
    if currency:
        stmt = stmt.where(Subscription.currency == currency.value)
    if billing_cycle:
        stmt = stmt.where(Subscription.billing_cycle == billing_cycle.value)
    if active is not None:
        stmt = stmt.where(Subscription.active.is_(active))
    if min_price is not None:
        stmt = stmt.where(Subscription.price >= min_price)
    if max_price is not None:
        stmt = stmt.where(Subscription.price <= max_price)
    if q:
        pattern = f"%{q}%"
        stmt = stmt.where(or_(Subscription.name.ilike(pattern), Subscription.notes.ilike(pattern)))

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    column = getattr(Subscription, field)
    order = column.desc() if sort.startswith("-") else column.asc()
    items = db.scalars(stmt.order_by(order, Subscription.id).limit(limit).offset(offset)).all()
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/{sub_id}", response_model=SubscriptionOut, responses=NOT_FOUND, summary="Get a subscription by ID")
def get_subscription(sub_id: int, db: Session = Depends(get_db)):
    return _get_or_404(db, sub_id)


@router.post(
    "",
    response_model=SubscriptionOut,
    status_code=status.HTTP_201_CREATED,
    responses=CONFLICT,
    summary="Create a subscription",
    description=(
        "Creates a new subscription.\n\n"
        "Rules: `name` must be unique (case-insensitive); `cancelled_at` is only allowed when `active` is false "
        "and must not be earlier than `start_date`. If `active` is false and `cancelled_at` is omitted, it is set to today."
    ),
)
def create_subscription(payload: SubscriptionCreate, db: Session = Depends(get_db)):
    return _apply(db, Subscription(), payload)


@router.put(
    "/{sub_id}",
    response_model=SubscriptionOut,
    responses={**NOT_FOUND, **CONFLICT},
    summary="Replace a subscription (full update)",
    description="Send the full object, same body as POST. Optional fields that are omitted get their default values.",
)
def replace_subscription(sub_id: int, payload: SubscriptionCreate, db: Session = Depends(get_db)):
    sub = _get_or_404(db, sub_id)
    return _apply(db, sub, payload)


@router.patch(
    "/{sub_id}",
    response_model=SubscriptionOut,
    responses={**NOT_FOUND, **CONFLICT},
    summary="Update a subscription (partial)",
    description=(
        "Send only the fields you want to change; everything else keeps its current value.\n\n"
        "Example: `{\"active\": false}` cancels the subscription today, `{\"active\": true}` resumes it."
    ),
)
def update_subscription(sub_id: int, payload: SubscriptionPatch, db: Session = Depends(get_db)):
    sub = _get_or_404(db, sub_id)
    changes = payload.model_dump(exclude_unset=True)

    merged = {field: getattr(sub, field) for field in WRITABLE_FIELDS} | changes
    if merged["active"] and "cancelled_at" not in changes:
        merged["cancelled_at"] = None

    try:
        full = SubscriptionCreate(**merged)
    except ValidationError as exc:
        errors = exc.errors(include_url=False)
        raise RequestValidationError([{**e, "loc": ("body", *e["loc"])} for e in errors])

    return _apply(db, sub, full)


@router.delete(
    "/{sub_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=NOT_FOUND,
    summary="Delete a subscription",
)
def delete_subscription(sub_id: int, db: Session = Depends(get_db)):
    sub = _get_or_404(db, sub_id)
    db.delete(sub)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
