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


def test_settlement_offer_is_accepted_when_it_reaches_that_rung():
    # Climbing to the settlement rung with a legal offer accepts it there and
    # then, at the consumer's own number — not countered back to the floor.
    s = state()
    evaluate(s, offer("850.00", 3), POLICY, TODAY)  # reaches downpayment rung
    d = evaluate(s, offer("900.00", 3), POLICY, TODAY)  # improves -> settlement
    assert d.decision == "accept"
    assert d.tier_id == "settlement"
    assert d.total == D("900.00")  # accepted at the offer, not the $850 floor


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
    # Four-payment offers never match the top three tiers, so improving legal
    # offers climb all the way to the last rung and stall there.
    s = state()
    for total in ("850.00", "870.00", "890.00", "910.00", "930.00"):
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
    # Skew is 60/40 on the $1,000 balance.
    assert d.schedule[0].amount == D("600.00")
    assert d.schedule[1].amount == D("400.00")


# --- Ceiling deadlock: full-balance offers must be able to reach the tier that
# --- fits their structure, because paying in full is never a discount. ---


def test_full_balance_offer_reaches_a_three_payment_tier():
    # The consumer offers the whole $1,000 but wants three installments. The
    # old ladder froze at downpayment (max 2 payments) because nothing can beat
    # a $1,000 best-offer. It must now advance to a tier that grants 3 payments
    # and accept at the full balance.
    s = state()
    evaluate(s, offer("1000.00", 3), POLICY, TODAY)      # counters, concedes to rung 1
    d = evaluate(s, offer("1000.00", 3), POLICY, TODAY)  # was deadlocked, now accepts
    assert d.decision == "accept"
    assert d.total == D("1000.00")
    assert len(d.schedule) == 3


def test_full_balance_offer_reaches_the_payment_plan():
    s = state()
    evaluate(s, offer("1000.00", 4), POLICY, TODAY)
    d = evaluate(s, offer("1000.00", 4), POLICY, TODAY)
    assert d.decision == "accept"
    assert d.tier_id == "payment_plan"
    assert d.total == D("1000.00")
    assert len(d.schedule) == 4


def test_full_balance_move_does_not_leak_a_discount():
    # Reaching settlement via a full-balance offer must NOT let a later
    # sub-balance offer be accepted at the discount floor. The monotonic accept
    # guard (never accept below the best offer seen) closes that path.
    s = state()
    evaluate(s, offer("1000.00", 4), POLICY, TODAY)
    evaluate(s, offer("1000.00", 4), POLICY, TODAY)  # walks down to payment_plan
    d = evaluate(s, offer("850.00", 3), POLICY, TODAY)
    assert d.decision != "accept"  # 850 < the $1,000 already offered


def test_offer_that_triggers_a_concession_is_captured_not_undercut():
    # A consumer at the downpayment rung who offers full balance in 3 payments
    # is accepted for the full $1,000 — the engine does not counter them down
    # to the settlement floor and leave money on the table.
    s = state()
    evaluate(s, offer("900.00", 2), POLICY, TODAY)       # reaches downpayment rung
    d = evaluate(s, offer("1000.00", 3), POLICY, TODAY)  # concede + capture
    assert d.decision == "accept"
    assert d.total == D("1000.00")