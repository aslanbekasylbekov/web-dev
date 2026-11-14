import calendar
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")

CYCLE_MONTHS = {"monthly": 1, "quarterly": 3, "yearly": 12}

PAYMENTS_PER_YEAR = {"weekly": 52, "monthly": 12, "quarterly": 4, "yearly": 1}


def add_months(day: date, months: int) -> date:
    index = day.month - 1 + months
    year = day.year + index // 12
    month = index % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(day.day, last_day))


def nth_payment(start: date, cycle: str, n: int) -> date:
    if cycle == "weekly":
        return start + timedelta(weeks=n)
    return add_months(start, CYCLE_MONTHS[cycle] * n)


def next_payment_date(start: date, cycle: str, today: date) -> date:
    if start >= today:
        return start
    if cycle == "weekly":
        n = (today - start).days // 7
    else:
        months_passed = (today.year - start.year) * 12 + today.month - start.month
        n = months_passed // CYCLE_MONTHS[cycle]
    while nth_payment(start, cycle, n) < today:
        n += 1
    return nth_payment(start, cycle, n)


def yearly_cost(price: Decimal, cycle: str) -> Decimal:
    return (Decimal(price) * PAYMENTS_PER_YEAR[cycle]).quantize(CENT, ROUND_HALF_UP)


def monthly_cost(price: Decimal, cycle: str) -> Decimal:
    return (Decimal(price) * PAYMENTS_PER_YEAR[cycle] / 12).quantize(CENT, ROUND_HALF_UP)
