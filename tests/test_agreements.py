"""Agreement finalization and persistence.

The property under test throughout: the model cannot record terms the engine
did not approve, because finalize_agreement reads from call state and not from
its own arguments.
"""

import json
from decimal import Decimal

from fastapi.testclient import TestClient

from app import agreements, store
from app.main import app

client = TestClient(app)
HEADERS = {"x-tool-secret": "dev-secret"}


def setup_function():
    store.reset()


def _tool(call_id, name, args):
    payload = {
        "message": {
            "call": {"id": call_id},
            "toolCallList": [{"id": "tc-1", "name": name, "arguments": args}],
        }
    }
    return client.post("/vapi/tools", json=payload, headers=HEADERS).json()[
        "results"
    ][0]["result"]


def test_cannot_finalize_without_an_approved_agreement():
    result = _tool("f1", "finalize_agreement", {"consumer_confirmed": True})
    assert result["finalized"] is False
    assert result["reason"] == "no_approved_agreement"


def test_finalize_persists_the_approved_terms():
    _tool("f2", "evaluate_offer", {"total": "1000", "num_payments": "1"})
    result = _tool("f2", "finalize_agreement", {"consumer_confirmed": True})

    assert result["finalized"] is True
    assert result["agreement_id"].startswith("AG-")

    stored = agreements.get(result["agreement_id"])
    assert stored["total"] == "1000.00"
    assert stored["tier_id"] == "paid_in_full"
    assert stored["consumer_confirmed"] == 1


def test_finalize_ignores_amounts_supplied_by_the_model():
    # The model attempts to record terms that were never approved.
    _tool("f3", "evaluate_offer", {"total": "1000", "num_payments": "1"})
    result = _tool(
        "f3",
        "finalize_agreement",
        {"consumer_confirmed": True, "total": "200.00", "num_payments": 12},
    )

    stored = agreements.get(result["agreement_id"])
    assert stored["total"] == "1000.00"
    assert stored["num_payments"] == 1


def test_compliance_hold_prevents_finalizing():
    _tool("f4", "evaluate_offer", {"total": "1000", "num_payments": "1"})
    _tool("f4", "check_compliance", {"utterance": "stop calling me"})
    result = _tool("f4", "finalize_agreement", {"consumer_confirmed": True})
    assert result["finalized"] is False
    assert result["reason"] == "compliance_hold"


def test_persisted_schedule_sums_to_the_total():
    # Two payments live on rung 1, so the ladder has to advance first.
    _tool("f5", "evaluate_offer", {"total": "850", "num_payments": "3"})
    _tool("f5", "evaluate_offer", {"total": "1000", "num_payments": "2"})
    result = _tool("f5", "finalize_agreement", {"consumer_confirmed": True})

    assert result["finalized"] is True
    stored = agreements.get(result["agreement_id"])
    schedule = json.loads(stored["schedule_json"])
    assert sum(Decimal(p["amount"]) for p in schedule) == Decimal(stored["total"])


def test_accepted_offer_preserves_the_consumer_structure():
    # The 75/25 skew is a counter-offer anchor, not something imposed on terms
    # the consumer proposed themselves. A consumer who offers the full balance
    # in two payments gets the split they asked for.
    _tool("f6", "evaluate_offer", {"total": "850", "num_payments": "3"})
    _tool("f6", "evaluate_offer", {"total": "1000", "num_payments": "2"})
    result = _tool("f6", "finalize_agreement", {"consumer_confirmed": True})

    stored = agreements.get(result["agreement_id"])
    schedule = json.loads(stored["schedule_json"])
    assert len(schedule) == 2
    assert sum(Decimal(p["amount"]) for p in schedule) == Decimal("1000.00")


def test_compliance_events_are_recorded_on_the_agreement():
    _tool("f7", "evaluate_offer", {"total": "1000", "num_payments": "1"})
    _tool("f7", "check_compliance", {"utterance": "just so you know, I'm recording this"})
    result = _tool("f7", "finalize_agreement", {"consumer_confirmed": True})

    stored = agreements.get(result["agreement_id"])
    assert "recording_notice" in json.loads(stored["compliance_events"])
