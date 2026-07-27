from datetime import date
from decimal import Decimal

from app.schedule import (
    build_schedule,
    smallest_payment,
    span_days,
    split_amounts,
    total_of,
)

D = Decimal


def test_split_sums_exactly_to_total():
    assert sum(split_amounts(D("1000.00"), 3)) == D("1000.00")


def test_rounding_remainder_lands_on_first_payment():
    assert split_amounts(D("1000.00"), 3) == [D("333.34"), D("333.33"), D("333.33")]


def test_skew_produces_downpayment_heavy_split():
    amounts = split_amounts(D("1000.00"), 2, skew=[D("0.75"), D("0.25")])
    assert amounts == [D("750.00"), D("250.00")]


def test_weekly_dates_advance_by_seven_days():
    schedule = build_schedule(D("1000.00"), 4, "weekly", date(2026, 8, 3))
    assert [i.due_date for i in schedule] == [
        date(2026, 8, 3),
        date(2026, 8, 10),
        date(2026, 8, 17),
        date(2026, 8, 24),
    ]


def test_monthly_clamps_to_last_valid_day_without_drift():
    schedule = build_schedule(D("900.00"), 3, "monthly", date(2026, 1, 31))
    assert [i.due_date for i in schedule] == [
        date(2026, 1, 31),
        date(2026, 2, 28),
        date(2026, 3, 31),
    ]


def test_four_weekly_payments_span_three_weeks():
    schedule = build_schedule(D("1000.00"), 4, "weekly", date(2026, 8, 3))
    assert span_days(schedule) == 21


def test_helpers_report_total_and_smallest():
    schedule = build_schedule(
        D("1000.00"), 2, "monthly", date(2026, 8, 3), skew=[D("0.75"), D("0.25")]
    )
    assert total_of(schedule) == D("1000.00")
    assert smallest_payment(schedule) == D("250.00")