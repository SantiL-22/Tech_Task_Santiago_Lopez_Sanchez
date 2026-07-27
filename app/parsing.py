"""Normalises tool arguments coming from the language model.

The model transcribes speech, so arguments arrive loosely typed: "$850.00",
"850", "three". This layer coerces them into exact types and rejects anything
it cannot interpret, rather than guessing. A guess here becomes a wrong number
in a binding agreement.
"""

import re
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from app.models import ConsumerOffer

DEFAULT_DAYS_TO_FIRST_PAYMENT = 3

WORD_NUMBERS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}

CADENCE_ALIASES = {
    "weekly": "weekly", "week": "weekly", "every week": "weekly",
    "biweekly": "biweekly", "bi-weekly": "biweekly", "fortnightly": "biweekly",
    "every two weeks": "biweekly", "twice a month": "biweekly",
    "monthly": "monthly", "month": "monthly", "every month": "monthly",
    "once": "monthly", "one time": "monthly", "lump sum": "monthly",
}


class ParseError(ValueError):
    """Raised when an argument cannot be interpreted with certainty."""


def parse_money(value) -> Decimal:
    if isinstance(value, Decimal):
        return value
    text = str(value).strip()
    # Strip currency symbols, thousands separators and stray words.
    cleaned = re.sub(r"[^\d.,-]", "", text).replace(",", "")
    try:
        return Decimal(cleaned)
    except (InvalidOperation, ValueError):
        raise ParseError(f"unparseable amount: {value!r}")


def parse_count(value) -> int:
    text = str(value).strip().lower()
    if text in WORD_NUMBERS:
        return WORD_NUMBERS[text]
    digits = re.sub(r"[^\d]", "", text)
    if not digits:
        raise ParseError(f"unparseable payment count: {value!r}")
    return int(digits)


def parse_cadence(value) -> str:
    text = str(value).strip().lower()
    if text in CADENCE_ALIASES:
        return CADENCE_ALIASES[text]
    for alias, canonical in CADENCE_ALIASES.items():
        if alias in text:
            return canonical
    raise ParseError(f"unrecognised cadence: {value!r}")


def parse_date(value, today: date) -> date:
    """Accept an ISO date, or fall back to a near-term default.

    We deliberately do NOT attempt to resolve phrases like "next Friday". The
    agent is instructed to confirm a concrete date and pass it as ISO; anything
    else defaults to a few days out, which validation will then check.
    """
    if value in (None, "", "unknown"):
        return today + timedelta(days=DEFAULT_DAYS_TO_FIRST_PAYMENT)
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except ValueError:
        return today + timedelta(days=DEFAULT_DAYS_TO_FIRST_PAYMENT)


def parse_offer(args: dict, today: date) -> ConsumerOffer:
    """Build a ConsumerOffer from raw tool arguments."""
    if "total" not in args:
        raise ParseError("missing required argument: total")

    num_payments = parse_count(args["num_payments"]) if args.get("num_payments") else 1

    return ConsumerOffer(
        total=parse_money(args["total"]),
        num_payments=num_payments,
        cadence=parse_cadence(args.get("cadence") or "monthly"),
        first_payment_date=parse_date(args.get("first_payment_date"), today),
    )