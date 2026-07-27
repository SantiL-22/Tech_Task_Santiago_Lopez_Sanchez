"""HTTP-level tests.

These exercise the full path a real tool call takes: Vapi payload shape,
authentication, argument coercion, engine decision and per-call state.
"""

from fastapi.testclient import TestClient

from app import store
from app.main import app

client = TestClient(app)
HEADERS = {"x-tool-secret": "dev-secret"}


def setup_function():
    """Each test starts from a clean registry of call states."""
    store.reset()


def _tool_payload(call_id: str, name: str, args: dict) -> dict:
    return {
        "message": {
            "type": "tool-calls",
            "call": {"id": call_id},
            "toolCallList": [{"id": "tc-1", "name": name, "arguments": args}],
        }
    }


def call_tool(call_id: str, args: dict) -> dict:
    response = client.post(
        "/vapi/tools", json=_tool_payload(call_id, "evaluate_offer", args), headers=HEADERS
    )
    return response.json()["results"][0]["result"]


def check(call_id: str, utterance: str) -> dict:
    response = client.post(
        "/vapi/tools",
        json=_tool_payload(call_id, "check_compliance", {"utterance": utterance}),
        headers=HEADERS,
    )
    return response.json()["results"][0]["result"]


# --- Service ----------------------------------------------------------------


def test_health():
    assert client.get("/health").json()["ok"] is True


def test_missing_secret_is_rejected():
    assert client.post("/vapi/tools", json={}).status_code == 401


def test_unknown_tool_is_reported_not_crashed():
    response = client.post(
        "/vapi/tools", json=_tool_payload("cX", "not_a_tool", {}), headers=HEADERS
    )
    assert "error" in response.json()["results"][0]["result"]


# --- Negotiation over HTTP --------------------------------------------------


def test_low_offer_returns_a_counter():
    result = call_tool("c1", {"total": "$850", "num_payments": "3"})
    assert result["decision"] == "counter"
    assert result["tier"] == "downpayment_plus_one"


def test_state_persists_across_calls_with_the_same_id():
    call_tool("c2", {"total": "850", "num_payments": "3"})
    result = call_tool("c2", {"total": "900", "num_payments": "3"})
    assert result["tier"] == "settlement"


def test_repeated_offer_does_not_advance_the_tier():
    call_tool("c3", {"total": "850", "num_payments": "3"})
    first = call_tool("c3", {"total": "850", "num_payments": "3"})
    second = call_tool("c3", {"total": "850", "num_payments": "3"})
    assert first["tier"] == second["tier"]


def test_separate_calls_do_not_share_state():
    call_tool("cA", {"total": "850", "num_payments": "3"})
    fresh = call_tool("cB", {"total": "850", "num_payments": "3"})
    assert fresh["tier"] == "downpayment_plus_one"


def test_unparseable_amount_asks_for_clarification():
    result = call_tool("c4", {"total": "whatever I can manage"})
    assert result["decision"] == "unparseable"


def test_spoken_amounts_are_parsed():
    result = call_tool("c5", {"total": "1,000.00", "num_payments": "one"})
    assert result["decision"] == "accept"


def test_serialised_schedule_sums_to_the_stated_total():
    from decimal import Decimal

    result = call_tool("c8", {"total": "850", "num_payments": "3"})
    total = sum(Decimal(i["amount"]) for i in result["schedule"])
    assert total == Decimal(result["total"])


# --- Compliance -------------------------------------------------------------


def test_compliance_trigger_blocks_further_negotiation():
    call_tool("c6", {"total": "850", "num_payments": "3"})
    result = check("c6", "stop calling me")
    assert result["ends_call"] is True

    after = call_tool("c6", {"total": "1000", "num_payments": "1"})
    assert after["decision"] == "blocked"


def test_clean_utterance_does_not_block():
    assert check("c7", "I could maybe do six hundred")["clear"] is True


def test_hostile_refusal_does_not_block():
    # An uncooperative consumer is not a statutory trigger. If this fired,
    # the agent would hang up before ever negotiating.
    assert check("c9", "I'm not paying you a damn thing")["clear"] is True
