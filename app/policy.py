"""Loads negotiation authority from config/policy.yaml."""

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import yaml

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "policy.yaml"


@dataclass(frozen=True)
class Tier:
    """One rung of the concession ladder.

    Tiers are STRICTER than the global validation envelope. The envelope says
    what is never acceptable; a tier says what we are authorised to agree to at
    this point in the negotiation.
    """

    id: str
    min_total: Decimal
    max_payments: int
    allowed_cadences: tuple[str, ...]
    # Optional per-instalment weights, e.g. (0.75, 0.25) to front-load.
    skew: tuple[Decimal, ...] | None = None


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
    ladder: tuple[Tier, ...]


def _decimal(value) -> Decimal:
    """PyYAML parses numbers as floats. Going through str() keeps the exact
    decimal value: Decimal("0.25") is exact, Decimal(0.25) is not."""
    return Decimal(str(value))


def load_policy(path: Path = CONFIG_PATH) -> Policy:
    raw = yaml.safe_load(path.read_text())
    limits = raw["limits"]

    ladder = tuple(
        Tier(
            id=rung["id"],
            min_total=_decimal(rung["min_total"]),
            max_payments=int(rung["max_payments"]),
            allowed_cadences=tuple(rung["allowed_cadences"]),
            skew=tuple(_decimal(w) for w in rung["skew"]) if rung.get("skew") else None,
        )
        for rung in raw["ladder"]
    )

    return Policy(
        balance=_decimal(raw["balance"]),
        currency=raw["currency"],
        min_payment_pct=_decimal(limits["min_payment_pct"]),
        max_payments=int(limits["max_payments"]),
        max_span_days=int(limits["max_span_days"]),
        max_days_to_first_payment=int(limits["max_days_to_first_payment"]),
        allowed_cadences=tuple(limits["allowed_cadences"]),
        min_acceptable_total=_decimal(limits["min_acceptable_total"]),
        ladder=ladder,
    )