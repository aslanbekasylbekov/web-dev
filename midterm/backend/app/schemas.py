from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, field_validator, model_validator

MoneyOut = Annotated[Decimal, PlainSerializer(float, return_type=float, when_used="json")]


class Category(str, Enum):
    streaming = "streaming"
    music = "music"
    cloud = "cloud"
    software = "software"
    gaming = "gaming"
    education = "education"
    news = "news"
    fitness = "fitness"
    other = "other"


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


EXAMPLE_IN = {
    "name": "Netflix",
    "category": "streaming",
    "price": 4990,
    "currency": "KZT",
    "billing_cycle": "monthly",
    "start_date": "2026-01-15",
    "active": True,
    "notes": "Family plan, shared with my brother",
}


class SubscriptionCreate(BaseModel):

    model_config = ConfigDict(extra="forbid", use_enum_values=True, json_schema_extra={"example": EXAMPLE_IN})

    name: str = Field(min_length=1, max_length=100, description="Service name, unique (case-insensitive)")
    category: Category
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

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name must not be blank")
        return value

    @model_validator(mode="after")
    def check_business_rules(self) -> "SubscriptionCreate":
        if self.active and self.cancelled_at is not None:
            raise ValueError("cancelled_at can only be set when active is false")
        if self.cancelled_at is not None and self.cancelled_at < self.start_date:
            raise ValueError("cancelled_at must not be earlier than start_date")
        return self


class SubscriptionPatch(BaseModel):

    model_config = ConfigDict(
        extra="forbid",
        use_enum_values=True,
        json_schema_extra={"example": {"active": False}},
    )

    name: str | None = Field(default=None, min_length=1, max_length=100)
    category: Category | None = None
    price: Decimal | None = Field(default=None, gt=0, max_digits=10, decimal_places=2)
    currency: Currency | None = None
    billing_cycle: BillingCycle | None = None
    start_date: date | None = None
    active: bool | None = None
    cancelled_at: date | None = None
    notes: str | None = Field(default=None, max_length=1000)


class SubscriptionOut(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": 1,
                **EXAMPLE_IN,
                "cancelled_at": None,
                "monthly_cost": 4990.0,
                "next_payment_date": "2026-11-15",
                "created_at": "2026-10-31T09:00:00Z",
                "updated_at": "2026-10-31T09:00:00Z",
            }
        },
    )

    id: int
    name: str
    category: Category
    price: MoneyOut
    currency: Currency
    billing_cycle: BillingCycle
    start_date: date
    active: bool
    cancelled_at: date | None
    notes: str | None
    monthly_cost: MoneyOut = Field(description="Average cost per month (computed)")
    next_payment_date: date | None = Field(description="Next charge date, null if cancelled (computed)")
    created_at: datetime
    updated_at: datetime


class SubscriptionList(BaseModel):
    items: list[SubscriptionOut]
    total: int = Field(description="Number of subscriptions matching the filters (ignores limit/offset)")
    limit: int
    offset: int


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
                "monthly_spend": {"KZT": 4990.0, "USD": 9.99},
                "yearly_spend": {"KZT": 59880.0, "USD": 119.88},
                "by_category": {"streaming": {"count": 1, "monthly_spend": {"KZT": 4990.0}}},
                "by_billing_cycle": {"monthly": 1, "yearly": 1},
                "next_payment": {"id": 1, "name": "Netflix", "date": "2026-11-15", "price": 4990.0, "currency": "KZT"},
            }
        }
    )

    total: int
    active: int
    cancelled: int
    monthly_spend: dict[str, MoneyOut] = Field(description="Active subscriptions only, per currency")
    yearly_spend: dict[str, MoneyOut] = Field(description="Active subscriptions only, per currency")
    by_category: dict[str, CategoryStat] = Field(description="Active subscriptions only")
    by_billing_cycle: dict[str, int] = Field(description="Active subscriptions only")
    next_payment: NextPayment | None = Field(description="The soonest upcoming charge, null if nothing is active")


class UpcomingItem(BaseModel):
    id: int
    name: str
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


class ErrorResponse(BaseModel):
    detail: str


class HealthOut(BaseModel):
    status: str
    database: str
