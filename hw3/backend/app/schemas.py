from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Annotated, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, field_validator, model_validator

MoneyOut = Annotated[Decimal, PlainSerializer(float, return_type=float, when_used="json")]

T = TypeVar("T")


# ---------------------------------------------------------------- enums

class Currency(str, Enum):
    KZT = "KZT"
    USD = "USD"
    EUR = "EUR"
    RUB = "RUB"


class BillingCycle(str, Enum):
    weekly = "weekly"
    monthly = "monthly"
    quarterly = "quarterly"
    yearly = "yearly"


# ---------------------------------------------------------------- helpers

def _strip_required(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("must not be blank")
    return value


def _strip_optional(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int = Field(description="Number of records matching the filters (ignores limit/offset)")
    limit: int
    offset: int


class ErrorResponse(BaseModel):
    detail: str


class HealthOut(BaseModel):
    status: str
    database: str


# ---------------------------------------------------------------- categories

CATEGORY_EXAMPLE = {"name": "Streaming", "description": "Video and TV services"}


class CategoryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"example": CATEGORY_EXAMPLE})

    name: str = Field(min_length=1, max_length=50, description="Unique (case-insensitive)")
    description: str | None = Field(default=None, max_length=500)

    _name = field_validator("name")(_strip_required)
    _description = field_validator("description")(_strip_optional)


class CategoryPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"example": {"description": "Movies and series"}})

    name: str | None = None
    description: str | None = None


class CategoryOut(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": 1, **CATEGORY_EXAMPLE, "subscription_count": 2,
                "created_at": "2026-11-17T09:00:00Z", "updated_at": "2026-11-17T09:00:00Z",
            }
        },
    )

    id: int
    name: str
    description: str | None
    subscription_count: int = Field(description="How many subscriptions are in the category (computed)")
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------- subscriptions

SUBSCRIPTION_EXAMPLE = {
    "category_id": 1,
    "name": "Netflix",
    "price": 4990,
    "currency": "KZT",
    "billing_cycle": "monthly",
    "start_date": "2026-01-15",
    "active": True,
    "notes": "Family plan, shared with my brother",
}


class SubscriptionCreate(BaseModel):

    model_config = ConfigDict(extra="forbid", use_enum_values=True, json_schema_extra={"example": SUBSCRIPTION_EXAMPLE})

    category_id: int = Field(gt=0, description="ID of an existing category")
    name: str = Field(min_length=1, max_length=100, description="Service name, unique (case-insensitive)")
    price: Decimal = Field(gt=0, max_digits=10, decimal_places=2, description="Price for one billing period")
    currency: Currency
    billing_cycle: BillingCycle
    start_date: date = Field(description="Date of the first payment")
    active: bool = Field(default=True, description="false = the subscription is cancelled")
    cancelled_at: date | None = Field(
        default=None,
        description="Only allowed when active is false. Defaults to today. Must not be earlier than start_date",
    )
    notes: str | None = Field(default=None, max_length=1000)

    _name = field_validator("name")(_strip_required)

    @model_validator(mode="after")
    def check_business_rules(self) -> "SubscriptionCreate":
        if self.active and self.cancelled_at is not None:
            raise ValueError("cancelled_at can only be set when active is false")
        if self.cancelled_at is not None and self.cancelled_at < self.start_date:
            raise ValueError("cancelled_at must not be earlier than start_date")
        return self


class SubscriptionPatch(BaseModel):

    model_config = ConfigDict(extra="forbid", json_schema_extra={"example": {"active": False}})

    category_id: int | None = None
    name: str | None = None
    price: Decimal | None = None
    currency: str | None = None
    billing_cycle: str | None = None
    start_date: date | None = None
    active: bool | None = None
    cancelled_at: date | None = None
    notes: str | None = None


class SubscriptionOut(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": 1,
                **SUBSCRIPTION_EXAMPLE,
                "category_name": "Streaming",
                "cancelled_at": None,
                "monthly_cost": 4990.0,
                "next_payment_date": "2026-12-15",
                "payments_count": 2,
                "total_paid": 9980.0,
                "last_paid_at": "2026-11-15",
                "created_at": "2026-11-17T09:00:00Z",
                "updated_at": "2026-11-17T09:00:00Z",
            }
        },
    )

    id: int
    category_id: int
    category_name: str
    name: str
    price: MoneyOut
    currency: Currency
    billing_cycle: BillingCycle
    start_date: date
    active: bool
    cancelled_at: date | None
    notes: str | None
    monthly_cost: MoneyOut = Field(description="Average cost per month (computed)")
    next_payment_date: date | None = Field(description="Next charge date, null if cancelled (computed)")
    payments_count: int = Field(description="Number of recorded payments (computed)")
    total_paid: MoneyOut = Field(description="Sum of recorded payments, in the subscription's currency (computed)")
    last_paid_at: date | None = Field(description="Date of the latest recorded payment (computed)")
    created_at: datetime
    updated_at: datetime


class CategoryStat(BaseModel):
    count: int
    monthly_spend: dict[str, MoneyOut]


class NextPayment(BaseModel):
    id: int
    name: str
    date: date
    price: MoneyOut
    currency: Currency


class StatsOut(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "total": 3,
                "active": 2,
                "cancelled": 1,
                "monthly_spend": {"KZT": 4990.0, "USD": 2.5},
                "yearly_spend": {"KZT": 59880.0, "USD": 29.99},
                "by_category": {"Streaming": {"count": 1, "monthly_spend": {"KZT": 4990.0}}},
                "by_billing_cycle": {"monthly": 1, "yearly": 1},
                "next_payment": {"id": 1, "name": "Netflix", "date": "2026-12-15", "price": 4990.0, "currency": "KZT"},
                "total_paid": {"KZT": 9980.0, "USD": 29.99},
                "payments_count": 3,
            }
        }
    )

    total: int
    active: int
    cancelled: int
    monthly_spend: dict[str, MoneyOut] = Field(description="Active subscriptions only, per currency")
    yearly_spend: dict[str, MoneyOut] = Field(description="Active subscriptions only, per currency")
    by_category: dict[str, CategoryStat] = Field(description="Active subscriptions only, keyed by category name")
    by_billing_cycle: dict[str, int] = Field(description="Active subscriptions only")
    next_payment: NextPayment | None = Field(description="The soonest upcoming charge, null if nothing is active")
    total_paid: dict[str, MoneyOut] = Field(description="All recorded payments (any subscription), per currency")
    payments_count: int = Field(description="All recorded payments")


class UpcomingItem(BaseModel):
    id: int
    name: str
    category_name: str
    price: MoneyOut
    currency: Currency
    billing_cycle: BillingCycle
    next_payment_date: date
    days_left: int


class UpcomingOut(BaseModel):
    days: int
    date_from: date
    date_to: date
    items: list[UpcomingItem]
    total_due: dict[str, MoneyOut] = Field(description="Sum of upcoming charges per currency")


# ---------------------------------------------------------------- payments

PAYMENT_EXAMPLE = {"paid_at": "2026-11-15", "amount": 4990, "note": "Kaspi Gold"}


class PaymentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"example": PAYMENT_EXAMPLE})

    paid_at: date = Field(
        description="Not in the future, not before the subscription's start_date, not after its cancelled_at. "
                    "One payment per subscription per day",
    )
    amount: Decimal | None = Field(
        default=None, gt=0, max_digits=10, decimal_places=2,
        description="Defaults to the subscription's current price. Currency = the subscription's currency",
    )
    note: str | None = Field(default=None, max_length=500)

    _note = field_validator("note")(_strip_optional)

    @field_validator("paid_at")
    @classmethod
    def not_in_future(cls, value: date) -> date:
        if value > date.today():
            raise ValueError("paid_at must not be in the future")
        return value


class PaymentUpdate(PaymentCreate):
    """Full payment after a PATCH is applied: amount is required here."""

    amount: Decimal = Field(gt=0, max_digits=10, decimal_places=2)


class PaymentPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"example": {"amount": 5490}})

    paid_at: date | None = None
    amount: Decimal | None = None
    note: str | None = None


class PaymentOut(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": 1, "subscription_id": 1, "subscription_name": "Netflix",
                "paid_at": "2026-11-15", "amount": 4990.0, "currency": "KZT", "note": "Kaspi Gold",
                "created_at": "2026-11-17T09:00:00Z", "updated_at": "2026-11-17T09:00:00Z",
            }
        },
    )

    id: int
    subscription_id: int
    subscription_name: str
    paid_at: date
    amount: MoneyOut
    currency: Currency
    note: str | None
    created_at: datetime
    updated_at: datetime
