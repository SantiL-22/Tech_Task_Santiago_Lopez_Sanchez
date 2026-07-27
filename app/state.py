"""Per-call negotiation state.

Deliberately tiny and explicit. Everything that determines the next decision
lives here, so a call can be replayed from its state and reproduce the same
outcome.
"""

from dataclasses import dataclass, field
from decimal import Decimal


@dataclass
class CallState:
    call_id: str

    # Index into policy.ladder. Starts at the most favourable terms and only
    # ever moves forward, one rung at a time.
    rung: int = 0

    # Highest total the consumer has offered so far. A concession is only
    # granted when they beat their own previous number, which is what stops
    # a consumer extracting the floor by repeating "no" without moving.
    best_offer_total: Decimal = Decimal("0.00")

    # Audit trail: every offer seen and what we decided.
    history: list[dict] = field(default_factory=list)

    def concede(self, max_rung: int) -> None:
        self.rung = min(self.rung + 1, max_rung)
    
    # Compliance rule ids triggered during this call.
    compliance_events: list[str] = field(default_factory=list)

    # Set when a statutory trigger fires. Once true, never reset.
    blocked: bool = False

    # Snapshot of the agreement the engine accepted. Serialisable by design:
    # storing a plain dict avoids a circular import with the engine and is
    # exactly what gets persisted.
    accepted: dict | None = None