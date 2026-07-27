from datetime import date, timedelta
from decimal import Decimal

from app.engine import evaluate
from app.models import ConsumerOffer
from app.policy import load_policy
from app.state import CallState

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


def state():
    return CallState(call_id="test")


def test_full_payment_accepted_immediately():
    d = evaluate(state(), offer("1000.00", 1), POLICY, TODAY)
    assert d.decision == "accept"
    assert d.tier_id == "paid_in_full"


def test_settlement_not_available_on_first_turn():
    s = state()
    d = evaluate(s, offer("850.00", 3), POLICY, TODAY)
    assert d.decision == "counter"
    assert s.rung == 1


def test_ladder_advances_exactly_one_rung_per_improved_offer():
    s = state()
    evaluate(s, offer("850.00", 3), POLICY, TODAY)
    assert s.rung == 1
    evaluate(s, offer("900.00", 3), POLICY, TODAY)
    assert s.rung == 2


def test_settlement_accepted_once_that_rung_is_reached():
    s = state()
    evaluate(s, offer("850.00", 3), POLICY, TODAY)
    evaluate(s, offer("900.00", 3), POLICY, TODAY)
    d = evaluate(s, offer("800.00", 3), POLICY, TODAY)
    assert d.decision == "accept"
    assert d.tier_id == "settlement"


def test_repeating_the_same_offer_does_not_concede():
    s = state()
    evaluate(s, offer("850.00", 3), POLICY, TODAY)
    rung_after_first = s.rung
    evaluate(s, offer("850.00", 3), POLICY, TODAY)
    evaluate(s, offer("850.00", 3), POLICY, TODAY)
    assert s.rung == rung_after_first


def test_lowering_the_offer_does_not_concede():
    s = state()
    evaluate(s, offer("900.00", 3), POLICY, TODAY)
    rung = s.rung
    evaluate(s, offer("820.00", 3), POLICY, TODAY)
    assert s.rung == rung


def test_illegal_offer_is_rejected_and_costs_no_concession():
    s = state()
    d = evaluate(s, offer("1000.00", 6), POLICY, TODAY)
    assert d.decision == "reject"
    assert "exceeds_max_payments" in d.reason_codes
    assert s.rung == 0


def test_offer_below_maximum_discount_is_rejected():
    d = evaluate(state(), offer("400.00", 2), POLICY, TODAY)
    assert d.decision == "reject"
    assert "below_minimum_acceptable_total" in d.reason_codes


def test_better_terms_are_accepted_even_at_a_lower_rung():
    s = state()
    evaluate(s, offer("850.00", 3), POLICY, TODAY)
    evaluate(s, offer("900.00", 3), POLICY, TODAY)
    assert s.rung == 2
    d = evaluate(s, offer("1000.00", 1), POLICY, TODAY)
    assert d.decision == "accept"
    assert d.tier_id == "paid_in_full"


def test_rung_never_runs_past_the_end_of_the_ladder():
    s = state()
    for total in ("810.00", "820.00", "830.00", "840.00", "850.00", "860.00"):
        evaluate(s, offer(total, 4), POLICY, TODAY)
    assert s.rung == len(POLICY.ladder) - 1


def test_counter_schedule_always_sums_to_its_stated_total():
    s = state()
    d = evaluate(s, offer("850.00", 3), POLICY, TODAY)
    assert sum(i.amount for i in d.schedule) == d.total


def test_downpayment_counter_is_front_loaded():
    s = state()
    d = evaluate(s, offer("850.00", 3), POLICY, TODAY)
    assert d.tier_id == "downpayment_plus_one"
    assert d.schedule[0].amount == D("750.00")
    assert d.schedule[1].amount == D("250.00")