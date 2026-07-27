"""Payment Schedule Function"""
"""Description : Given a total amount of debt and a number of payments it will return the total of payments and the amount of each payment"""
"""Less amount in each payment with a max of 4 payments -> minimum_payment ≥ 0.25 × total   →   total/n ≥ 0.25 × total   →   n ≤ 4"""

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

# All monetary values are quantized to cents. We use Decimal rather than
# float because binary floats cannot represent 0.01 exactly, and a payment
# agreement that is off by a cent is a defect in a collections context.
CENT = Decimal("0.01")

CADENCE_DAYS = {
    "weekly": 7,
    "biweekly": 14,
}

@dataclass(frozen=True)#One scheduled payment. Frozen so it cannot be mutated after creation.
class Installment:
    

    seq: int
    amount: Decimal
    due_date: date

def _days_in_month(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]

def _add_months(start: date, months: int) -> date:#Add whole months, clamping to the last valid day of the target month.

    month_index = start.month - 1 + months #months from 0-11 (0=January, 11=December)
    year = start.year + month_index // 12 #number of years to add
    month = month_index % 12 + 1 #month of the year
    day = min(start.day, _days_in_month(year, month)) #day of the month
    return date(year, month, day)

def _due_date(first: date, cadence: str, index: int) -> date: #Due date of payment number `index` (0-based).

   #Every date is computed from `first`, never from the previous payment,
   #so month-end clamping cannot accumulate drift across the schedule.
    if cadence == "monthly":
        return _add_months(first, index)
    return first + timedelta(days=CADENCE_DAYS[cadence] * index)

def split_amounts(total: Decimal, num_payments: int, skew: list[Decimal] | None = None) -> list[Decimal]:
    """In case you have to split `total` into `num_payments` amounts that sum to it exactly.

    `skew` optionally provides per-payment weights, e.g. [0.75, 0.25] for a
    downpayment-heavy plan. Without it the split is even.

    Any rounding remainder is applied to the FIRST payment, never the last.
    Collecting the odd cent up front is marginally better for recovery and
    leaves the final payment a round, easy-to-communicate number.
    """
    if num_payments < 1:
        raise ValueError("num_payments must be >= 1")

    total = total.quantize(CENT, rounding=ROUND_HALF_UP)

    if skew is not None:
        if len(skew) != num_payments:
            raise ValueError("skew length must match num_payments")
        amounts = [(total * w).quantize(CENT, rounding=ROUND_HALF_UP) for w in skew]
    else:
        base = (total / num_payments).quantize(CENT, rounding=ROUND_HALF_UP)
        amounts = [base] * num_payments

    # Absorb the rounding difference so the schedule sums to the total.
    amounts[0] += total - sum(amounts)
    return amounts


def build_schedule( #Function to build the payment schedule
    total: Decimal,
    num_payments: int,
    cadence: str,
    first_payment_date: date,
    skew: list[Decimal] | None = None,
) -> list[Installment]:
    """Build the full payment schedule."""
    if cadence not in ("weekly", "biweekly", "monthly"):
        raise ValueError(f"unsupported cadence: {cadence}")

    amounts = split_amounts(total, num_payments, skew)
    return [
        Installment(
            seq=i + 1,
            amount=amount,
            due_date=_due_date(first_payment_date, cadence, i),
        )
        for i, amount in enumerate(amounts)
    ]


# --- Helpers used by the negotiation engine in the next step -----------------


def total_of(schedule: list[Installment]) -> Decimal: #Returns the total amount of the schedule
    return sum((i.amount for i in schedule), Decimal("0.00"))


def smallest_payment(schedule: list[Installment]) -> Decimal: #Returns the smallest payment in the schedule
    return min(i.amount for i in schedule)


def span_days(schedule: list[Installment]) -> int: #Returns the number of days between the first and last payment
    return (schedule[-1].due_date - schedule[0].due_date).days