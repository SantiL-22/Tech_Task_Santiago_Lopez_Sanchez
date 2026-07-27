# AI Voice Collections Agent

An AI voice agent that negotiates payment of a past-due account over a live
phone call. A Vapi assistant handles the conversation; during the call it
invokes tool endpoints on this FastAPI service, which owns every decision about
money and compliance. The account under negotiation is a fixed $1,000 balance
defined in `config/policy.yaml`.

## Design: the model never decides amounts

The system is split into three layers:

1. **Pure domain** (`app/engine.py`, `app/validation.py`, `app/schedule.py`,
   `app/compliance.py`): deterministic negotiation and compliance logic. No
   HTTP, no I/O, fully covered by tests.
2. **Thin HTTP surface** (`app/main.py`): parses Vapi's webhook payload,
   delegates to the domain, serialises the result. No negotiation logic lives
   here.
3. **Agent prompt** (`prompts/system.md`, `prompts/system.es.md`): instructs
   the model to report tool results and forbids it from inventing figures.

The money logic sits outside the model on purpose. A language model can be
persuaded, confused, or prompted into inventing a discount; a deterministic
engine cannot. The model is never told where the floors are, so there is
nothing for a hostile caller to extract. The same principle protects
persistence: `finalize_agreement` takes no monetary arguments, so the model
has no parameter through which it could record terms the engine did not
approve.

## Call flow

```
Caller <-> Vapi assistant (LLM + STT/TTS)
              |
              | POST /vapi/tools  (x-tool-secret header)
              v
        FastAPI service
              |
   +----------+-----------+
   |          |           |
evaluate   check       finalize
_offer   _compliance  _agreement
   |          |           |
engine.py  compliance.py  agreements.py
(ladder,   (statutory     (SQLite record)
 policy)    triggers)
```

Per-call negotiation state (current ladder rung, best offer so far, compliance
holds, the accepted terms) lives in `app/store.py`, keyed by the Vapi call id.

## The tools

**`evaluate_offer`** takes the consumer's proposed total, number of payments,
cadence and optional first payment date. The engine validates it against the
policy envelope, checks it against every ladder tier already reached, and
returns one of `accept`, `counter` or `reject`, plus a payment schedule and a
`say` field. Concessions are only granted when the consumer improves their own
offer; repeating the same offer does not advance the ladder. Unparseable
amounts return `decision: unparseable` and a request to restate, never a
guess.

**`check_compliance`** scans a consumer utterance for statutory triggers
(cease request, attorney representation, dispute, wrong party, bankruptcy,
recording notice). On a match it returns the fixed script to read, whether the
call must end, and blocks further negotiation on that call. The assistant is
instructed to call it every turn, but the same detector can be applied
server-side to transcript events, so a trigger is caught even if the model
fails to call the tool.

**`finalize_agreement`** persists the agreement to SQLite and returns a
reference number. It reads the terms from call state, written there by the
engine at the moment of acceptance, and accepts no amounts from the model.

All three arrive on a single webhook, `POST /vapi/tools`, authenticated by the
`x-tool-secret` header. `GET /health` is an unauthenticated liveness check.

`GET /dashboard` serves a read-only live operations view: the tool-call feed,
each call's position on the concession ladder, and finalized agreements. It
observes and never mutates. In deployment nginx enforces HTTP basic auth in
front of it; credentials are provided separately.

Every tool response includes a `say` field: the only text the agent is allowed
to speak from, so numbers reaching the caller always originate in the engine.

## Negotiation policy

`config/policy.yaml` defines a global envelope (minimum acceptable total $800,
at most 4 payments, no installment below 25% of the total, everything inside
92 days, first payment within 7 days) and a concession ladder in order of
business preference: paid in full, downpayment plus one, settlement at up to
20% off, full-balance payment plan. Each rung is stricter than the envelope;
the envelope is the outer safety net. Policy lives in config, not code, so
limits can be tuned per portfolio without a redeploy and audited in one place.

## Compliance guardrails

Defined in `app/compliance.py` with the statutory basis kept next to each
rule. Detection is regex-based, deliberately conservative, and biased toward
false positives: ending a call unnecessarily costs one contact attempt,
continuing after a cease request is a violation. Once a call is blocked it
stays blocked; no later offer reopens it.

| Trigger | Basis | Effect |
| --- | --- | --- |
| Cease request | FDCPA 15 U.S.C. 1692c(c) | Script, end call, block |
| Attorney representation | FDCPA 15 U.S.C. 1692c(a)(2) | Script, end call, block |
| Dispute | FDCPA 15 U.S.C. 1692g(b) | Script, end call, block |
| Wrong party | FDCPA 15 U.S.C. 1692b | Script, end call, block |
| Bankruptcy | 11 U.S.C. 362 (automatic stay) | Script, end call, block |
| Recording notice | State two-party consent statutes | Acknowledge, continue |

The agent may state only the approved consequences of non-payment listed in
`config/approved_consequences.yaml`; the prompt forbids everything else
(legal action, garnishment, invented urgency). The scripts are illustrative;
production wording would be reviewed by counsel per jurisdiction.

## Running locally

Requires Python 3.12+.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload   # http://localhost:8000
```

Without `TOOL_SECRET` set, the service logs a warning and falls back to
`dev-secret`. This is for local development only.

Tests:

```bash
pytest   # 58 tests
```

## Deployment

The live instance runs at `https://collections.santils.dev` on a VPS: the
container binds to localhost only, nginx terminates TLS (Let's Encrypt,
auto-renewed) and reverse-proxies to it, and `restart: unless-stopped` plus a
Docker healthcheck keep it up without scale-to-zero.

The service ships as a single container. Build and run:

```bash
docker build -t collections-agent .
docker run -d -p 8000:8000 \
  -e TOOL_SECRET="$(openssl rand -hex 32)" \
  -v agreements-data:/data \
  collections-agent
```

Environment variables (see `.env.example`):

| Variable | Required | Default | Purpose |
| --- | --- | --- | --- |
| `TOOL_SECRET` | in production | `dev-secret` (local only) | Shared secret for `/vapi/tools` |
| `DB_PATH` | no | `./agreements.db` local, `/data/agreements.db` in container | SQLite location |
| `PORT` | no | `8000` | Listen port |
| `REQUIRE_TOOL_SECRET` | no | set to `1` by the Dockerfile | Refuse to start without a real secret |

The container sets `REQUIRE_TOOL_SECRET=1`, so a deployment with no
`TOOL_SECRET` fails at startup rather than running with an open endpoint that
settles debts. It runs as a non-root user, exposes a Docker `HEALTHCHECK`
against `GET /health`, and writes agreements to `/data`, which should be a
mounted volume so records survive redeploys.

The service must run behind HTTPS with exactly one uvicorn worker and must not
scale to zero: a cold start during a live call is audible silence to the
caller.

## Known limitations

- **In-memory call state.** Negotiation state lives in a process-local dict.
  A restart mid-call resets the ladder for calls in progress. Finalized
  agreements are unaffected; they are on disk.
- **Single worker, single instance.** A direct consequence of the above: a
  second worker or replica would split a call's requests across processes and
  reset the concession ladder mid-negotiation. Scaling out requires moving
  `app/store.py` to a shared store such as Redis first.
- **SQLite.** One writer, one file. Fine for an auditable record at this
  volume; not a multi-instance database.
- **No outbound dialing.** The service answers tool calls; campaign and call
  initiation live in Vapi.
