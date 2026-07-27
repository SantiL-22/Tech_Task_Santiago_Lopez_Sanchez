"""Hard validations applied to any consumer offer.

These are absolute: no amount of negotiation, persuasion or model output
can bypass them. A failure here ends the offer immediately and does NOT
consume a concession step.

Every rejection returns a machine-readable reason code so the outcome can
be audited later without reading the transcript.
"""

from datetime import date

from app.models import ConsumerOffer
from app.policy import Policy
from app.schedule import build_schedule, smallest_payment, span_days


def validate_offer(offer: ConsumerOffer,policy: Policy,today: date) -> list[str]: #Return a list of violated rules. An empty list means the offer is legal.
    reasons: list[str] = []

    if offer.total <= 0: #Check if the total amount is positive
        reasons.append("non_positive_total")

    #Never collect more than is owed, even if the consumer offers it.
    if offer.total > policy.balance:#Check if the total amount exceeds the balance
        reasons.append("total_exceeds_balance")

    if offer.total < policy.min_acceptable_total:#Check if the total amount is below the minimum acceptable total
        reasons.append("below_minimum_acceptable_total")

    if offer.num_payments < 1:#Check if the number of payments is at least 1
        reasons.append("invalid_payment_count")

    if offer.num_payments > policy.max_payments:#Check if the number of payments does not exceed the maximum number of payments
        reasons.append("exceeds_max_payments")

    if offer.cadence not in policy.allowed_cadences:#Check if the cadence is supported
        reasons.append("unsupported_cadence")

    if offer.first_payment_date < today:#Check if the first payment date is not in the past
        reasons.append("first_payment_in_past")

    days_out = (offer.first_payment_date - today).days
    if days_out > policy.max_days_to_first_payment:#Check if the first payment date is not too far in the future
        reasons.append("first_payment_too_far_out")

    # The remaining checks need a concrete schedule, which we can only build
    # once the structural inputs above are known to be sane.
    structural_failures = {
        "non_positive_total",
        "invalid_payment_count",
        "exceeds_max_payments",
        "unsupported_cadence",
    }
    if not structural_failures.intersection(reasons):
        schedule = build_schedule(
            offer.total, offer.num_payments, offer.cadence, offer.first_payment_date
        )

        if smallest_payment(schedule) < offer.total * policy.min_payment_pct:
            reasons.append("payment_below_minimum_share")

        if span_days(schedule) > policy.max_span_days:
            reasons.append("exceeds_max_span")

    return reasons