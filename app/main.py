"""HTTP surface for the collections agent.

This layer is intentionally thin: it parses, delegates to the domain, and
serialises. No negotiation logic lives here.
"""

import os
from datetime import date

from fastapi import FastAPI, Header, HTTPException

from app import store
from app.engine import evaluate
from app.parsing import ParseError, parse_offer
from app.policy import load_policy
from app import compliance

app = FastAPI(title="AI Collector - Tool API")

POLICY = load_policy()
TOOL_SECRET = os.getenv("TOOL_SECRET", "dev-secret")


@app.get("/health")
def health():
    return {"ok": True, "service": "collector-tools"}


def _require_secret(provided: str | None) -> None:
    """An endpoint that settles debts cannot be anonymous."""
    if provided != TOOL_SECRET:
        raise HTTPException(status_code=401, detail="unauthorized")


def _serialise(decision) -> dict:
    return {
        "decision": decision.decision,
        "tier": decision.tier_id,
        "total": str(decision.total),
        "reason_codes": decision.reason_codes,
        "schedule": [
            {
                "seq": i.seq,
                "amount": str(i.amount),
                "due_date": i.due_date.isoformat(),
            }
            for i in decision.schedule
        ],
        # The only field the agent is allowed to speak from.
        "say": decision.spoken_summary,
    }


def _handle_evaluate_offer(call_id: str, args: dict) -> dict:
    state = store.get_or_create(call_id)

    # A compliance trigger overrides everything. Once the call is blocked it
    # stays blocked: no offer, however good, reopens the negotiation. This
    # check runs before parsing so a blocked call never even reads an amount.
    if state.blocked:
        return {
            "decision": "blocked",
            "reason_codes": ["compliance_hold"],
            "say": "I'm not able to continue with this account on this call.",
        }

    today = date.today()

    try:
        offer = parse_offer(args, today)
    except ParseError as exc:
        # Never guess a number. Ask the consumer to restate it.
        return {
            "decision": "unparseable",
            "reason_codes": [str(exc)],
            "say": "I didn't catch that amount. Could you say it again?",
        }

    return _serialise(evaluate(state, offer, POLICY, today))

def _handle_check_compliance(call_id: str, args: dict) -> dict:
    """Scan a consumer utterance for statutory triggers.

    The assistant is instructed to call this on every consumer turn, but the
    same function is also applied server-side to transcript events, so a
    trigger is caught even if the model fails to call it.
    """
    utterance = str(args.get("utterance", ""))
    triggered = compliance.detect(utterance)
    rule = compliance.most_severe(triggered)

    if rule is None:
        return {"triggered": [], "clear": True}

    state = store.get_or_create(call_id)
    state.compliance_events.extend(triggered)
    if rule.blocks_negotiation:
        state.blocked = True

    return {
        "triggered": triggered,
        "clear": False,
        "basis": rule.basis,
        "ends_call": rule.ends_call,
        # Read verbatim. This is not a suggestion to paraphrase.
        "say": rule.script,
    }

TOOL_HANDLERS = {
    "evaluate_offer": _handle_evaluate_offer,
    "check_compliance": _handle_check_compliance,
}


@app.post("/vapi/tools")
async def vapi_tools(payload: dict, x_tool_secret: str | None = Header(default=None)):
    """Webhook target for every tool the assistant can call.

    Vapi batches tool calls into a single request, so we dispatch by name and
    return one result per call id.
    """
    _require_secret(x_tool_secret)

    message = payload.get("message", {})
    call_id = message.get("call", {}).get("id", "unknown-call")
    tool_calls = message.get("toolCallList") or message.get("toolCalls") or []

    results = []
    for tool_call in tool_calls:
        name = tool_call.get("name") or tool_call.get("function", {}).get("name")
        args = tool_call.get("arguments") or tool_call.get("function", {}).get("arguments") or {}

        handler = TOOL_HANDLERS.get(name)
        result = (
            handler(call_id, args)
            if handler
            else {"error": f"unknown tool: {name}"}
        )
        results.append({"toolCallId": tool_call.get("id"), "result": result})

    return {"results": results}