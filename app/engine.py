"""Negotiation engine.

The only component authorised to accept an agreement. The language model calls
this and reports the result; it never decides an amount itself and is never told
where the floors are.

Order of operations matters:
  1. Hard validation. Illegal offers are rejected and cost no concession.
  2. Acceptance check against every tier at or above the current rung.
  3. Concession, granted only if the consumer improved their own offer.
  4. Counter built deterministically from the resulting tier.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from app.models import ConsumerOffer
from app.policy import Policy, Tier
from app.schedule import Installment, build_schedule
from app.state import CallState
from app.validation import validate_offer

# Used when the consumer has not proposed a workable first payment date.
DEFAULT_DAYS_TO_FIRST_PAYMENT = 3


@dataclass(frozen=True)
class Decision:
    decision: str  # "accept" | "counter" | "reject"
    tier_id: str
    total: Decimal
    schedule: list[Installment]
    reason_codes: list[str]
    spoken_summary: str


def _offer_matches_tier(offer: ConsumerOffer, tier: Tier) -> bool:
    return (
        offer.total >= tier.min_total
        and offer.num_payments <= tier.max_payments
        and offer.cadence in tier.allowed_cadences
    )


def _counter_first_date(offer: ConsumerOffer, policy: Policy, today: date) -> date:
    """Honour the consumer's proposed start date when it is workable.

    Keeping their date where possible makes the counter feel like a response to
    them rather than a script, and costs nothing.
    """
    days_out = (offer.first_payment_date - today).days
    if 0 <= days_out <= policy.max_days_to_first_payment:
        return offer.first_payment_date
    return today + timedelta(days=DEFAULT_DAYS_TO_FIRST_PAYMENT)


def _build_counter(
    tier: Tier, offer: ConsumerOffer, policy: Policy, today: date
) -> list[Installment]:
    cadence = (
        offer.cadence if offer.cadence in tier.allowed_cadences else "monthly"
    )
    skew = list(tier.skew) if tier.skew else None
    return build_schedule(
        total=tier.min_total,
        num_payments=tier.max_payments,
        cadence=cadence,
        first_payment_date=_counter_first_date(offer, policy, today),
        skew=skew,
    )


def _describe(schedule: list[Installment]) -> str:
    """Plain, factual rendering of a schedule.
    The agent paraphrases this. It never composes the numbers itself.
    """
    if len(schedule) == 1:
        i = schedule[0]
        return f"a single payment of ${i.amount} on {i.due_date:%B %-d}"
    parts = [f"${i.amount} on {i.due_date:%B %-d}" for i in schedule]
    return ", then ".join(parts)


def evaluate(
    state: CallState,
    offer: ConsumerOffer,
    policy: Policy,
    today: date,
) -> Decision:
    current_tier = policy.ladder[state.rung]

    # 1. Hard validation
    reasons = validate_offer(offer, policy, today)
    if reasons:
        counter = _build_counter(current_tier, offer, policy, today)
        decision = Decision(
            decision="reject",
            tier_id=current_tier.id,
            total=current_tier.min_total,
            schedule=counter,
            reason_codes=reasons,
            spoken_summary=f"That arrangement is not available. What I can do is {_describe(counter)}.",
        )
        state.history.append({"offer": offer, "decision": decision.decision})
        return decision

    # 2. Acceptance 
    # An offer is acceptable if it satisfies any tier we have already reached.
    # Checking earlier tiers too means a consumer who suddenly offers better
    # terms is accepted immediately rather than negotiated back down.
    for tier in policy.ladder[: state.rung + 1]:
        if _offer_matches_tier(offer, tier):
            schedule = build_schedule(
                offer.total, offer.num_payments, offer.cadence, offer.first_payment_date
            )
            decision = Decision(
                decision="accept",
                tier_id=tier.id,
                total=offer.total,
                schedule=schedule,
                reason_codes=[],
                spoken_summary=f"Agreed: {_describe(schedule)}.",
            )
            state.best_offer_total = max(state.best_offer_total, offer.total)
            # Record what was approved. finalize_agreement reads from here and
            # never from tool arguments, so the model cannot persist terms the
            # engine did not authorise.
            state.accepted = {
                "tier_id": tier.id,
                "total": str(offer.total),
                "num_payments": offer.num_payments,
                "cadence": offer.cadence,
                "schedule": [
                    {
                        "seq": i.seq,
                        "amount": str(i.amount),
                        "due_date": i.due_date.isoformat(),
                    }
                    for i in schedule
                ],
            }
            state.history.append({"offer": offer, "decision": decision.decision})
            return decision

    # 3. Concession
    if offer.total > state.best_offer_total:
        state.concede(max_rung=len(policy.ladder) - 1)
        state.best_offer_total = offer.total

    # 4. Counter
    tier = policy.ladder[state.rung]
    counter = _build_counter(tier, offer, policy, today)
    decision = Decision(
        decision="counter",
        tier_id=tier.id,
        total=tier.min_total,
        schedule=counter,
        reason_codes=["below_current_authority"],
        spoken_summary=f"I can't approve that. What I can approve is {_describe(counter)}.",
    )
    state.history.append({"offer": offer, "decision": decision.decision})
    return decision