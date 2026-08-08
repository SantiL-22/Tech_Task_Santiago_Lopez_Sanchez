from datetime import date, timedelta
from decimal import Decimal

from app.models import ConsumerOffer
from app.policy import load_policy
from app.validation import validate_offer

D = Decimal
POLICY = load_policy()
TODAY = date(2026, 8, 1)


def offer(total, n, cadence="monthly", days_out=2):
    return ConsumerOffer(
        total=D(total),
        num_payments=n,
        cadence=cadence,
        first_payment_date=TODAY + timedelta(days=days_out),
    )


def test_full_payment_is_valid():
    assert validate_offer(offer("1000.00", 1), POLICY, TODAY) == []


def test_max_settlement_is_valid():
    # The settlement floor is $850 (max 15% off the $1,000 balance).
    assert validate_offer(offer("850.00", 3), POLICY, TODAY) == []


def test_below_settlement_floor_is_rejected():
    assert "below_minimum_acceptable_total" in validate_offer(
        offer("800.00", 3), POLICY, TODAY
    )


def test_overpayment_is_rejected():
    assert "total_exceeds_balance" in validate_offer(offer("1200.00", 1), POLICY, TODAY)


def test_below_max_discount_is_rejected():
    reasons = validate_offer(offer("500.00", 2), POLICY, TODAY)
    assert "below_minimum_acceptable_total" in reasons


def test_five_payments_is_rejected():
    assert "exceeds_max_payments" in validate_offer(offer("1000.00", 5), POLICY, TODAY)


def test_four_weekly_payments_are_valid():
    assert validate_offer(offer("1000.00", 4, "weekly"), POLICY, TODAY) == []


def test_first_payment_in_the_past_is_rejected():
    assert "first_payment_in_past" in validate_offer(
        offer("1000.00", 1, days_out=-1), POLICY, TODAY
    )


def test_first_payment_a_month_out_is_rejected():
    assert "first_payment_too_far_out" in validate_offer(
        offer("1000.00", 1, days_out=30), POLICY, TODAY
    )


def test_unknown_cadence_is_rejected():
    assert "unsupported_cadence" in validate_offer(
        offer("1000.00", 2, "daily"), POLICY, TODAY
    )