"""Loads negotiation authority from config/policy.yaml."""

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import yaml

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "policy.yaml"


@dataclass(frozen=True)
class Policy:
    balance: Decimal
    currency: str
    min_payment_pct: Decimal
    max_payments: int
    max_span_days: int
    max_days_to_first_payment: int
    allowed_cadences: tuple[str, ...]
    min_acceptable_total: Decimal


def load_policy(path: Path = CONFIG_PATH) -> Policy:
    raw = yaml.safe_load(path.read_text())
    limits = raw["limits"]

    # Monetary and ratio values go through str() before Decimal because
    # PyYAML parses them as floats, and Decimal(float) inherits binary
    # representation error. Decimal("0.25") is exact; Decimal(0.25) is not.
    return Policy(
        balance=Decimal(str(raw["balance"])),
        currency=raw["currency"],
        min_payment_pct=Decimal(str(limits["min_payment_pct"])),
        max_payments=int(limits["max_payments"]),
        max_span_days=int(limits["max_span_days"]),
        max_days_to_first_payment=int(limits["max_days_to_first_payment"]),
        allowed_cadences=tuple(limits["allowed_cadences"]),
        min_acceptable_total=Decimal(str(limits["min_acceptable_total"])),
    )