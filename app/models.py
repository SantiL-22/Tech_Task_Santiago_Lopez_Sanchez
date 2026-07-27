"""Data shapes exchanged between the agent, the API and the domain."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True) #What the consumer proposed, as parsed from the conversation. It's frozen so it cannot be mutated after creation.
class ConsumerOffer:
    total: Decimal
    num_payments: int
    cadence: str
    first_payment_date: date
