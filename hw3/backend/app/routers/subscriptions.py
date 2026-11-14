from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .. import billing
from ..database import get_db
from ..models import Category, Payment, Subscription
from ..schemas import (
    BillingCycle,
    Currency,
    Page,
    PaymentCreate,
    PaymentOut,
    StatsOut,
    SubscriptionCreate,
    SubscriptionOut,
    SubscriptionPatch,
    UpcomingOut,
)
from .common import commit_or_409, conflict, get_or_404, not_found, order_by, paginate, validate_merged

router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])

WRITABLE_FIELDS = tuple(SubscriptionCreate.model_fields)
SUBSCRIPTION_SORT = {
    "id": Subscription.id,
    "name": Subscription.name,
    "price": Subscription.price,
    "start_date": Subscription.start_date,
    "created_at": Subscription.created_at,
    "currency": Subscription.currency,
    "billing_cycle": Subscription.billing_cycle,
    "category_id": Subscription.category_id,
}
PAYMENT_SORT = {
    "id": Payment.id,
    "paid_at": Payment.paid_at,
    "amount": Payment.amount,
    "created_at": Payment.created_at,
}
SUBSCRIPTION_SORT_DESCRIPTION = "Sort field, prefix with '-' for descending. Allowed: " + ", ".join(sorted(SUBSCRIPTION_SORT))
PAYMENT_SORT_DESCRIPTION = "Sort field, prefix with '-' for descending. Allowed: " + ", ".join(sorted(PAYMENT_SORT))

SUB_404 = not_found("Subscription (or the category in the body) not found")
NAME_409 = conflict("A subscription with this name already exists, or its currency cannot change")


# ---------------------------------------------------------------- shared helpers (also used by other routers)

def subscription_list_query(
    *,
    category_id: int | None = None,
    currency: Currency | None = None,
    billing_cycle: BillingCycle | None = None,
    active: bool | None = None,
    min_price: Decimal | None = None,
    max_price: Decimal | None = None,
    q: str | None = None,
):
    if min_price is not None and max_price is not None and min_price > max_price:
        raise HTTPException(status_code=422, detail="min_price must not be greater than max_price")

    stmt = select(Subscription)
    if category_id is not None:
        stmt = stmt.where(Subscription.category_id == category_id)
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
    return stmt


def check_payment_date(sub: Subscription, paid_at: date) -> None:
    """A payment must lie between the subscription's start_date and (if cancelled) its cancelled_at."""
    if paid_at < sub.start_date:
        raise HTTPException(
            status_code=422,
            detail=f"paid_at must not be earlier than the subscription's start_date ({sub.start_date.isoformat()})",
        )
    if sub.cancelled_at is not None and paid_at > sub.cancelled_at:
        raise HTTPException(
            status_code=422,
            detail=f"paid_at must not be later than the subscription's cancelled_at ({sub.cancelled_at.isoformat()})",
        )


def ensure_one_payment_per_day(db: Session, sub_id: int, paid_at: date, exclude_id: int | None) -> None:
    stmt = select(Payment.id).where(Payment.subscription_id == sub_id, Payment.paid_at == paid_at)
    if exclude_id is not None:
        stmt = stmt.where(Payment.id != exclude_id)
    if db.scalar(stmt) is not None:
        raise HTTPException(
            status_code=409, detail=f"Subscription {sub_id} already has a payment on {paid_at.isoformat()}"
        )


def _ensure_unique_name(db: Session, name: str, exclude_id: int | None) -> None:
    stmt = select(Subscription.id).where(func.lower(Subscription.name) == name.lower())
    if exclude_id is not None:
        stmt = stmt.where(Subscription.id != exclude_id)
    if db.scalar(stmt) is not None:
        raise HTTPException(status_code=409, detail=f"Subscription '{name}' already exists")


def _check_payments_still_fit(sub: Subscription, data: dict) -> None:
    """Changing a subscription must not leave its recorded payments inconsistent."""
    if not sub.payments:
        return
    if data["currency"] != sub.currency:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot change currency: the subscription has {len(sub.payments)} payment(s) in {sub.currency}",
        )
    first = min(p.paid_at for p in sub.payments)
    last = max(p.paid_at for p in sub.payments)
    if data["start_date"] > first:
        raise HTTPException(
            status_code=422, detail=f"start_date must not be later than the first payment ({first.isoformat()})"
        )
    if data["cancelled_at"] is not None and data["cancelled_at"] < last:
        raise HTTPException(
            status_code=422, detail=f"cancelled_at must not be earlier than the last payment ({last.isoformat()})"
        )


def _apply(db: Session, sub: Subscription, payload: SubscriptionCreate) -> Subscription:
    get_or_404(db, Category, payload.category_id, "Category")
    _ensure_unique_name(db, payload.name, exclude_id=sub.id)
    data = payload.model_dump()

    if data["active"]:
        data["cancelled_at"] = None
    elif data["cancelled_at"] is None:
        old = sub.cancelled_at
        data["cancelled_at"] = old if old and old >= data["start_date"] else max(date.today(), data["start_date"])

    if sub.id is not None:
        _check_payments_still_fit(sub, data)

    for key, value in data.items():
        setattr(sub, key, value)

    db.add(sub)
    commit_or_409(db, f"Subscription '{payload.name}' already exists")
    db.refresh(sub)
    return sub


def _add(totals: dict, currency: str, amount: Decimal) -> None:
    totals[currency] = totals.get(currency, Decimal("0")) + amount


# ---------------------------------------------------------------- reports

@router.get(
    "/stats",
    response_model=StatsOut,
    summary="Spending statistics",
    description="Totals and spend per currency. Spend numbers include only active subscriptions; "
                "`total_paid` sums all recorded payments.",
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

    for sub in db.scalars(select(Subscription).where(Subscription.active.is_(True))).unique().all():
        _add(monthly, sub.currency, sub.monthly_cost)
        _add(yearly, sub.currency, billing.yearly_cost(sub.price, sub.billing_cycle))

        cat = by_category.setdefault(sub.category_name, {"count": 0, "monthly_spend": {}})
        cat["count"] += 1
        _add(cat["monthly_spend"], sub.currency, sub.monthly_cost)

        by_cycle[sub.billing_cycle] += 1

        if next_payment is None or sub.next_payment_date < next_payment["date"]:
            next_payment = {
                "id": sub.id, "name": sub.name, "date": sub.next_payment_date,
                "price": sub.price, "currency": sub.currency,
            }

    total_paid: dict[str, Decimal] = {}
    payments_count = 0
    rows = db.execute(
        select(Subscription.currency, func.sum(Payment.amount), func.count(Payment.id))
        .select_from(Payment)
        .join(Payment.subscription)
        .group_by(Subscription.currency)
    ).all()
    for currency, amount, count in rows:
        total_paid[currency] = amount
        payments_count += count

    return {
        "total": total,
        "active": active,
        "cancelled": total - active,
        "monthly_spend": monthly,
        "yearly_spend": yearly,
        "by_category": by_category,
        "by_billing_cycle": dict(by_cycle),
        "next_payment": next_payment,
        "total_paid": total_paid,
        "payments_count": payments_count,
    }


@router.get(
    "/upcoming",
    response_model=UpcomingOut,
    summary="Upcoming payments",
    description="Active subscriptions that will charge you within the next `days` days (today included).",
)
def upcoming_payments(
    days: int = Query(7, ge=0, le=365, description="How many days ahead to look"),
    category_id: int | None = Query(None, gt=0, description="Only this category"),
    db: Session = Depends(get_db),
):
    today = date.today()
    until = today + timedelta(days=days)

    stmt = select(Subscription).where(Subscription.active.is_(True))
    if category_id is not None:
        stmt = stmt.where(Subscription.category_id == category_id)

    items = []
    total_due: dict[str, Decimal] = {}
    for sub in db.scalars(stmt).unique().all():
        pay_date = sub.next_payment_date
        if pay_date <= until:
            items.append({
                "id": sub.id, "name": sub.name, "category_name": sub.category_name,
                "price": sub.price, "currency": sub.currency,
                "billing_cycle": sub.billing_cycle, "next_payment_date": pay_date,
                "days_left": (pay_date - today).days,
            })
            _add(total_due, sub.currency, sub.price)

    items.sort(key=lambda item: (item["next_payment_date"], item["name"].lower()))
    return {"days": days, "date_from": today, "date_to": until, "items": items, "total_due": total_due}


# ---------------------------------------------------------------- CRUD

@router.get(
    "",
    response_model=Page[SubscriptionOut],
    summary="List subscriptions",
    description="Returns a page of subscriptions with optional filters, search and sorting.",
)
def list_subscriptions(
    category_id: int | None = Query(None, gt=0, description="Filter by category"),
    currency: Currency | None = Query(None, description="Filter by currency"),
    billing_cycle: BillingCycle | None = Query(None, description="Filter by billing cycle"),
    active: bool | None = Query(None, description="true = active, false = cancelled"),
    min_price: Decimal | None = Query(None, ge=0, description="Price per period >= this value"),
    max_price: Decimal | None = Query(None, ge=0, description="Price per period <= this value"),
    q: str | None = Query(None, min_length=1, description="Case-insensitive search in name and notes"),
    sort: str = Query("name", description=SUBSCRIPTION_SORT_DESCRIPTION),
    limit: int = Query(20, ge=1, le=100, description="Page size"),
    offset: int = Query(0, ge=0, description="Number of items to skip"),
    db: Session = Depends(get_db),
):
    stmt = subscription_list_query(
        category_id=category_id, currency=currency, billing_cycle=billing_cycle, active=active,
        min_price=min_price, max_price=max_price, q=q,
    )
    return paginate(db, stmt, order_by(sort, SUBSCRIPTION_SORT, Subscription.id), limit, offset)


@router.get("/{sub_id}", response_model=SubscriptionOut, responses=SUB_404, summary="Get a subscription by ID")
def get_subscription(sub_id: int, db: Session = Depends(get_db)):
    return get_or_404(db, Subscription, sub_id, "Subscription")


@router.post(
    "",
    response_model=SubscriptionOut,
    status_code=status.HTTP_201_CREATED,
    responses={**not_found("Category not found"), **conflict("A subscription with this name already exists")},
    summary="Create a subscription",
    description=(
        "Creates a new subscription in an existing category (`category_id`, otherwise `404`).\n\n"
        "Rules: `name` must be unique (case-insensitive); `cancelled_at` is only allowed when `active` is false "
        "and must not be earlier than `start_date`. If `active` is false and `cancelled_at` is omitted, it is set to today."
    ),
)
def create_subscription(payload: SubscriptionCreate, db: Session = Depends(get_db)):
    return _apply(db, Subscription(), payload)


@router.put(
    "/{sub_id}",
    response_model=SubscriptionOut,
    responses={**SUB_404, **NAME_409},
    summary="Replace a subscription (full update)",
    description=(
        "Send the full object, same body as POST. Optional fields that are omitted get their default values.\n\n"
        "If the subscription has payments: `currency` cannot change (`409`), `start_date` must not be later than the "
        "first payment and `cancelled_at` not earlier than the last one (`422`)."
    ),
)
def replace_subscription(sub_id: int, payload: SubscriptionCreate, db: Session = Depends(get_db)):
    sub = get_or_404(db, Subscription, sub_id, "Subscription")
    return _apply(db, sub, payload)


@router.patch(
    "/{sub_id}",
    response_model=SubscriptionOut,
    responses={**SUB_404, **NAME_409},
    summary="Update a subscription (partial)",
    description=(
        "Send only the fields you want to change; everything else keeps its current value. Same rules as PUT.\n\n"
        "Example: `{\"active\": false}` cancels the subscription today, `{\"active\": true}` resumes it, "
        "`{\"category_id\": 2}` moves it to another category."
    ),
)
def update_subscription(sub_id: int, payload: SubscriptionPatch, db: Session = Depends(get_db)):
    sub = get_or_404(db, Subscription, sub_id, "Subscription")
    changes = payload.model_dump(exclude_unset=True)

    current = {field: getattr(sub, field) for field in WRITABLE_FIELDS}
    if (changes.get("active", current["active"])) and "cancelled_at" not in changes:
        changes["cancelled_at"] = None

    return _apply(db, sub, validate_merged(SubscriptionCreate, current, changes))


@router.delete(
    "/{sub_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=SUB_404,
    summary="Delete a subscription",
    description="Deletes the subscription **and all its payments** (cascade).",
)
def delete_subscription(sub_id: int, db: Session = Depends(get_db)):
    sub = get_or_404(db, Subscription, sub_id, "Subscription")
    db.delete(sub)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------- related data: payments of a subscription

@router.get(
    "/{sub_id}/payments",
    response_model=Page[PaymentOut],
    responses=not_found("Subscription not found"),
    summary="Payment history of a subscription",
    description="Newest first by default.",
)
def list_subscription_payments(
    sub_id: int,
    date_from: date | None = Query(None, description="paid_at >= this date"),
    date_to: date | None = Query(None, description="paid_at <= this date"),
    sort: str = Query("-paid_at", description=PAYMENT_SORT_DESCRIPTION),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    get_or_404(db, Subscription, sub_id, "Subscription")
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status_code=422, detail="date_from must not be later than date_to")
    stmt = select(Payment).where(Payment.subscription_id == sub_id)
    if date_from:
        stmt = stmt.where(Payment.paid_at >= date_from)
    if date_to:
        stmt = stmt.where(Payment.paid_at <= date_to)
    return paginate(db, stmt, order_by(sort, PAYMENT_SORT, Payment.id.desc()), limit, offset)


@router.post(
    "/{sub_id}/payments",
    response_model=PaymentOut,
    status_code=status.HTTP_201_CREATED,
    responses={**not_found("Subscription not found"), **conflict("There is already a payment on this date")},
    summary="Record a payment of a subscription",
    description=(
        "Rules: `paid_at` not in the future, not before `start_date`, not after `cancelled_at` (`422`); "
        "one payment per subscription per day (`409`). `amount` defaults to the subscription's price; "
        "the currency is always the subscription's currency."
    ),
)
def create_payment(sub_id: int, payload: PaymentCreate, db: Session = Depends(get_db)):
    sub = get_or_404(db, Subscription, sub_id, "Subscription")
    check_payment_date(sub, payload.paid_at)
    ensure_one_payment_per_day(db, sub.id, payload.paid_at, exclude_id=None)

    payment = Payment(paid_at=payload.paid_at, amount=payload.amount or sub.price, note=payload.note)
    sub.payments.append(payment)
    commit_or_409(db, f"Subscription {sub.id} already has a payment on {payload.paid_at.isoformat()}")
    db.refresh(payment)
    return payment
