"""HTTP surface for the collections agent.

This layer is intentionally thin: it parses, delegates to the domain, and
serialises. No negotiation logic lives here.
"""

import logging
import os
from datetime import date

from fastapi import FastAPI, Header, HTTPException

from app import store
from app.engine import evaluate
from app.parsing import ParseError, parse_offer
from app.policy import load_policy
from app import compliance
from app import agreements
from app import dashboard

logger = logging.getLogger("collector")

app = FastAPI(title="AI Collector - Tool API")

POLICY = load_policy()

# An unset secret means an open endpoint that settles debts. The dev fallback
# exists only for local runs; the Dockerfile sets REQUIRE_TOOL_SECRET=1 so a
# deployed container refuses to boot without a real secret.
_secret = os.getenv("TOOL_SECRET")
if _secret is None:
    if os.getenv("REQUIRE_TOOL_SECRET") == "1":
        raise RuntimeError(
            "TOOL_SECRET is not set. Refusing to start with the dev-secret "
            "fallback outside local development. Set TOOL_SECRET in the "
            "environment."
        )
    logger.warning(
        "TOOL_SECRET is not set; using the dev-secret fallback. "
        "Never deploy in this state."
    )
TOOL_SECRET = _secret or "dev-secret"


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

def _handle_finalize_agreement(call_id: str, args: dict) -> dict:
    """Persist the agreement the engine approved.

    Takes NO monetary arguments. The terms come from call state, written there
    by the engine at the moment of acceptance. There is therefore no parameter
    through which the model could record terms that were never authorised.
    """
    state = store.get_or_create(call_id)

    if state.blocked:
        return {
            "finalized": False,
            "reason": "compliance_hold",
            "say": "I'm not able to set anything up on this account right now.",
        }

    if state.accepted is None:
        return {
            "finalized": False,
            "reason": "no_approved_agreement",
            "say": "We haven't settled on terms yet. What amount can you commit to?",
        }

    # The agent is instructed to read the terms back and obtain an explicit
    # yes before calling this. The flag is recorded rather than trusted: the
    # binding protection is that the amounts come from state, not from args.
    confirmed = bool(args.get("consumer_confirmed", False))

    agreement_id = agreements.save(
        call_id=call_id,
        accepted=state.accepted,
        currency=POLICY.currency,
        consumer_confirmed=confirmed,
        compliance_events=state.compliance_events,
        offer_history=state.history,
    )

    schedule = state.accepted["schedule"]
    lines = ", then ".join(f"${p['amount']} on {p['due_date']}" for p in schedule)

    return {
        "finalized": True,
        "agreement_id": agreement_id,
        "total": state.accepted["total"],
        "schedule": schedule,
        "say": (
            f"You're all set. That's {lines}. "
            f"Your reference number is {agreement_id}. "
            "You'll get written confirmation of these terms."
        ),
    }

TOOL_HANDLERS = {
    "evaluate_offer": _handle_evaluate_offer,
    "check_compliance": _handle_check_compliance,
    "finalize_agreement": _handle_finalize_agreement,
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
        dashboard.record(call_id, name, result)
        results.append({"toolCallId": tool_call.get("id"), "result": result})

    return {"results": results}


@app.post("/vapi/events")
async def vapi_events(
    payload: dict,
    x_tool_secret: str | None = Header(default=None),
    x_vapi_secret: str | None = Header(default=None),
):
    """Server-side compliance monitor over live transcripts.

    Vapi streams every transcribed utterance here during the call. Each final
    consumer utterance is run through the same detector the check_compliance
    tool uses, so a statutory trigger freezes the negotiation even if the
    model never calls the tool. This is the enforcement path; the tool is the
    cooperative path that also gives the model a script to read.

    Vapi's assistant-level server config sends its secret as x-vapi-secret;
    the tool header is accepted too so the endpoint can be exercised by hand.
    """
    _require_secret(x_vapi_secret or x_tool_secret)

    message = payload.get("message", {})
    if message.get("type") != "transcript":
        return {}
    if message.get("role") != "user" or message.get("transcriptType") != "final":
        return {}

    utterance = str(message.get("transcript", ""))
    triggered = compliance.detect(utterance)
    if not triggered:
        return {}

    call_id = message.get("call", {}).get("id", "unknown-call")
    state = store.get_or_create(call_id)
    state.compliance_events.extend(
        t for t in triggered if t not in state.compliance_events
    )
    rule = compliance.most_severe(triggered)
    if rule.blocks_negotiation:
        state.blocked = True

    dashboard.record(
        call_id,
        "transcript_monitor",
        {"decision": "triggered", "reason_codes": triggered, "say": rule.script},
    )
    return {}


app.include_router(dashboard.router)