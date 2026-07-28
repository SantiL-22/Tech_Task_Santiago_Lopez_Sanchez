"""Property-based invariants over the deterministic core.

The case tests in the other files pin specific behaviours. These pin the
INVARIANTS that must hold for ANY input hypothesis can generate: exact cent
arithmetic, floors that cannot be crossed, a ladder that only moves forward,
and full determinism. If any of these ever fails, the negotiation engine is
not safe to put on a phone call, however many case tests pass.
"""

from datetime import date, timedelta
from decimal import Decimal

from hypothesis import given, strategies as st

from app.engine import evaluate
from app.models import ConsumerOffer
from app.policy import load_policy
from app.schedule import (
    CENT,
    build_schedule,
    smallest_payment,
    span_days,
    split_amounts,
    total_of,
)
from app.state import CallState
from app.validation import validate_offer

POLICY = load_policy()
# Fixed date: the properties must not depend on when the suite runs.
TODAY = date(2026, 7, 28)

# Amounts in exact cents, from 1 cent to 5,000.00: far beyond anything legal,
# so the strategies cover the envelope's outside as well as its inside.
cents = st.integers(min_value=1, max_value=500_000).map(
    lambda c: Decimal(c) / 100
)
payments = st.integers(min_value=1, max_value=8)
cadences = st.sampled_from(["weekly", "biweekly", "monthly"])
days_out = st.integers(min_value=0, max_value=10)


def _offer(total, num_payments, cadence, days):
    return ConsumerOffer(
        total=total,
        num_payments=num_payments,
        cadence=cadence,
        first_payment_date=TODAY + timedelta(days=days),
    )


offers = st.builds(_offer, cents, payments, cadences, days_out)
offer_sequences = st.lists(offers, min_size=1, max_size=8)


# --- Money arithmetic --------------------------------------------------------


@given(total=cents, n=payments)
def test_split_sums_to_the_total_exactly(total, n):
    amounts = split_amounts(total, n)
    assert sum(amounts) == total.quantize(CENT)
    assert all(a == a.quantize(CENT) for a in amounts)


@given(total=cents, raw_weights=st.lists(st.integers(1, 100), min_size=1, max_size=8))
def test_split_with_any_skew_still_sums_exactly(total, raw_weights):
    weight_sum = sum(raw_weights)
    skew = [Decimal(w) / weight_sum for w in raw_weights]
    amounts = split_amounts(total, len(raw_weights), skew)
    assert sum(amounts) == total.quantize(CENT)


@given(total=cents, n=payments, cadence=cadences, days=days_out)
def test_schedule_shape_is_always_sane(total, n, cadence, days):
    first = TODAY + timedelta(days=days)
    schedule = build_schedule(total, n, cadence, first)

    assert [i.seq for i in schedule] == list(range(1, n + 1))
    assert schedule[0].due_date == first
    dates = [i.due_date for i in schedule]
    assert dates == sorted(dates) and len(set(dates)) == len(dates)
    assert total_of(schedule) == total.quantize(CENT)


# --- Validation envelope -----------------------------------------------------


@given(offer=offers)
def test_any_offer_that_passes_validation_satisfies_every_limit(offer):
    if validate_offer(offer, POLICY, TODAY):
        return  # rejected offers are the envelope doing its job

    assert POLICY.min_acceptable_total <= offer.total <= POLICY.balance
    assert 1 <= offer.num_payments <= POLICY.max_payments
    assert offer.cadence in POLICY.allowed_cadences
    assert 0 <= (offer.first_payment_date - TODAY).days <= POLICY.max_days_to_first_payment

    schedule = build_schedule(
        offer.total, offer.num_payments, offer.cadence, offer.first_payment_date
    )
    assert smallest_payment(schedule) >= offer.total * POLICY.min_payment_pct
    assert span_days(schedule) <= POLICY.max_span_days


# --- Engine invariants over arbitrary negotiations ---------------------------


def _tier(tier_id):
    return next(t for t in POLICY.ladder if t.id == tier_id)


@given(sequence=offer_sequences)
def test_engine_invariants_hold_for_any_offer_sequence(sequence):
    state = CallState(call_id="prop")
    previous_best = Decimal("0.00")

    for offer in sequence:
        rung_before = state.rung
        decision = evaluate(state, offer, POLICY, TODAY)

        # The ladder only moves forward, at most one rung per offer.
        assert rung_before <= state.rung <= rung_before + 1
        # The consumer's best offer never goes backwards.
        assert state.best_offer_total >= previous_best
        previous_best = state.best_offer_total

        tier = _tier(decision.tier_id)

        if decision.decision == "accept":
            # The floor is never crossed and we never collect above balance.
            assert POLICY.min_acceptable_total <= offer.total <= POLICY.balance
            # Accepted terms are the consumer's, to the cent.
            assert total_of(decision.schedule) == offer.total
            assert smallest_payment(decision.schedule) >= offer.total * POLICY.min_payment_pct
            # Acceptance always maps to a tier already reached that the offer satisfies.
            assert POLICY.ladder.index(tier) <= state.rung
            assert offer.total >= tier.min_total
            assert offer.num_payments <= tier.max_payments
        else:
            # Counters and rejects only ever speak the current tier's terms.
            assert decision.total == tier.min_total
            assert total_of(decision.schedule) == tier.min_total
            assert len(decision.schedule) <= tier.max_payments

        if decision.decision == "reject":
            # Illegal offers cost no concession.
            assert state.rung == rung_before


@given(sequence=offer_sequences)
def test_engine_is_fully_deterministic(sequence):
    def run():
        state = CallState(call_id="prop")
        return [
            (
                d.decision,
                d.tier_id,
                str(d.total),
                [(str(i.amount), i.due_date.isoformat()) for i in d.schedule],
            )
            for d in (evaluate(state, offer, POLICY, TODAY) for offer in sequence)
        ]

    assert run() == run()
