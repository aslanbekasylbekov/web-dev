from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Payment, Subscription
from ..schemas import Currency, Page, PaymentOut, PaymentPatch, PaymentUpdate
from .common import commit_or_409, conflict, get_or_404, not_found, order_by, paginate, validate_merged
from .subscriptions import PAYMENT_SORT, PAYMENT_SORT_DESCRIPTION, check_payment_date, ensure_one_payment_per_day

router = APIRouter(prefix="/payments", tags=["payments"])

WRITABLE_FIELDS = tuple(PaymentUpdate.model_fields)
PAYMENT_404 = not_found("Payment not found")


@router.get(
    "",
    response_model=Page[PaymentOut],
    summary="List payments",
    description="All recorded payments across subscriptions. Newest first by default.",
)
def list_payments(
    subscription_id: int | None = Query(None, gt=0, description="Only this subscription"),
    category_id: int | None = Query(None, gt=0, description="Only subscriptions of this category"),
    currency: Currency | None = Query(None, description="Only subscriptions in this currency"),
    date_from: date | None = Query(None, description="paid_at >= this date"),
    date_to: date | None = Query(None, description="paid_at <= this date"),
    min_amount: Decimal | None = Query(None, ge=0, description="amount >= this value"),
    sort: str = Query("-paid_at", description=PAYMENT_SORT_DESCRIPTION),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status_code=422, detail="date_from must not be later than date_to")

    stmt = select(Payment)
    if subscription_id is not None:
        stmt = stmt.where(Payment.subscription_id == subscription_id)
    if category_id is not None or currency is not None:
        subs = select(Subscription.id)
        if category_id is not None:
            subs = subs.where(Subscription.category_id == category_id)
        if currency is not None:
            subs = subs.where(Subscription.currency == currency.value)
        stmt = stmt.where(Payment.subscription_id.in_(subs))
    if date_from:
        stmt = stmt.where(Payment.paid_at >= date_from)
    if date_to:
        stmt = stmt.where(Payment.paid_at <= date_to)
    if min_amount is not None:
        stmt = stmt.where(Payment.amount >= min_amount)
    return paginate(db, stmt, order_by(sort, PAYMENT_SORT, Payment.id.desc()), limit, offset)


@router.get("/{payment_id}", response_model=PaymentOut, responses=PAYMENT_404, summary="Get a payment")
def get_payment(payment_id: int, db: Session = Depends(get_db)):
    return get_or_404(db, Payment, payment_id, "Payment")


@router.patch(
    "/{payment_id}",
    response_model=PaymentOut,
    responses={**PAYMENT_404, **conflict("There is already a payment on this date")},
    summary="Update a payment (partial)",
    description="Fix a payment record: send only the fields to change. Same rules as when it was recorded. "
                "The subscription of a payment cannot be changed.",
)
def update_payment(payment_id: int, payload: PaymentPatch, db: Session = Depends(get_db)):
    payment = get_or_404(db, Payment, payment_id, "Payment")
    current = {field: getattr(payment, field) for field in WRITABLE_FIELDS}
    full = validate_merged(PaymentUpdate, current, payload.model_dump(exclude_unset=True))

    check_payment_date(payment.subscription, full.paid_at)
    ensure_one_payment_per_day(db, payment.subscription_id, full.paid_at, exclude_id=payment.id)

    for key, value in full.model_dump().items():
        setattr(payment, key, value)
    commit_or_409(db, f"Subscription {payment.subscription_id} already has a payment on {full.paid_at.isoformat()}")
    db.refresh(payment)
    return payment


@router.delete(
    "/{payment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=PAYMENT_404,
    summary="Delete a payment",
)
def delete_payment(payment_id: int, db: Session = Depends(get_db)):
    payment = get_or_404(db, Payment, payment_id, "Payment")
    db.delete(payment)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
