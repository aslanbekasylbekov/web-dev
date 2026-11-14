from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    select,
    true,
)
from sqlalchemy.orm import Mapped, column_property, mapped_column, relationship

from . import billing
from .database import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class Category(TimestampMixin, Base):
    """A group of subscriptions (Streaming, Music, Cloud...). One category has many subscriptions."""

    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    subscriptions: Mapped[list["Subscription"]] = relationship(back_populates="category")


class Subscription(TimestampMixin, Base):
    """A paid subscription. Belongs to one category, has many payments."""

    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    category_id: Mapped[int] = mapped_column(
        ForeignKey("categories.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, index=True)
    billing_cycle: Mapped[str] = mapped_column(String(10), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    cancelled_at: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)

    category: Mapped[Category] = relationship(back_populates="subscriptions", lazy="joined")
    payments: Mapped[list["Payment"]] = relationship(
        back_populates="subscription",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
        order_by=lambda: [Payment.paid_at.desc(), Payment.id.desc()],
    )

    # ---- computed, read-only fields ----

    @property
    def category_name(self) -> str:
        return self.category.name

    @property
    def monthly_cost(self) -> Decimal:
        return billing.monthly_cost(self.price, self.billing_cycle)

    @property
    def next_payment_date(self) -> date | None:
        if not self.active:
            return None
        return billing.next_payment_date(self.start_date, self.billing_cycle, date.today())

    @property
    def payments_count(self) -> int:
        return len(self.payments)

    @property
    def total_paid(self) -> Decimal:
        return sum((p.amount for p in self.payments), Decimal("0.00"))

    @property
    def last_paid_at(self) -> date | None:
        return max((p.paid_at for p in self.payments), default=None)


class Payment(TimestampMixin, Base):
    """One real charge of a subscription. The currency is always the subscription's currency."""

    __tablename__ = "payments"
    __table_args__ = (UniqueConstraint("subscription_id", "paid_at", name="uq_payments_subscription_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    subscription_id: Mapped[int] = mapped_column(
        ForeignKey("subscriptions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    paid_at: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)

    subscription: Mapped[Subscription] = relationship(back_populates="payments", lazy="joined")

    @property
    def subscription_name(self) -> str:
        return self.subscription.name

    @property
    def currency(self) -> str:
        return self.subscription.currency


# Number of subscriptions in a category, loaded together with the category (one query, no N+1).
Category.subscription_count = column_property(
    select(func.count(Subscription.id))
    .where(Subscription.category_id == Category.id)
    .correlate_except(Subscription)
    .scalar_subquery()
)

Index("uq_categories_name_lower", func.lower(Category.name), unique=True)
Index("uq_subscriptions_name_lower", func.lower(Subscription.name), unique=True)
