"""In-memory registry of live call states."""

from app.state import CallState

_CALLS: dict[str, CallState] = {}


def get_or_create(call_id: str) -> CallState:
    if call_id not in _CALLS:
        _CALLS[call_id] = CallState(call_id=call_id)
    return _CALLS[call_id]


def reset() -> None:
    """Test helper. Never called in production paths."""
    _CALLS.clear()