"""In-memory registry of live call states."""

from app.state import CallState

# One CallState per phone call, keyed by the id Vapi assigns to the call.
# A plain module-level dict is enough because the service runs a single
# worker: every request for a given call lands in this same process.
_CALLS: dict[str, CallState] = {}


def get_or_create(call_id: str) -> CallState:
    # The first tool call of a conversation creates the state; every later
    # one picks up where it left off. No expiry needed: calls are short and
    # the dict resets with the process.
    if call_id not in _CALLS:
        _CALLS[call_id] = CallState(call_id=call_id)
    return _CALLS[call_id]


def reset() -> None:
    """Test helper. Never called in production paths."""
    _CALLS.clear()
