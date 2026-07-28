# Decisions

Notes behind the design, kept for the recording and follow-up questions.
The three headline decisions come first; the rest is supporting record.

## 1. The money logic lives outside the model

The language model never decides an amount. Every figure the consumer says is
sent to a deterministic engine (`app/engine.py`) that validates it against a
policy envelope and a four-rung concession ladder (`config/policy.yaml`), and
returns the decision plus the exact sentence the agent may speak (`say`).

Why: a model can be persuaded, confused, or prompt-injected into inventing a
discount. The engine cannot. The model is never told where the floors are, so
they cannot be extracted socially: it cannot reveal what it does not know.

Two rules do the anti-manipulation work:

- A concession is granted only when the consumer beats their own previous
  offer. Repeating a number, or repeating "no", never moves the ladder.
- Invalid offers (below the $800 floor, too many payments, too far out) are
  rejected outright and cost no concession.

Observed working during testing: a call that opened at $700 (rejected as
below the floor), then offered $875, then tried to drop back to $800 never
reached the settlement tier. The engine cannot be walked down.

## 2. Compliance is enforced server-side, not requested from the model

Six rules with the statutory basis kept next to each one (FDCPA 1692b/c/g,
11 U.S.C. 362, two-party consent). Two detection paths into the same rules:

- Cooperative: the `check_compliance` tool, which returns a fixed script the
  agent must read verbatim.
- Enforcement: Vapi streams every transcribed consumer utterance to
  `POST /vapi/events`; the server scans each one with the same detector. A
  trigger freezes the negotiation server-side, so even if the model never
  calls the tool, the next `evaluate_offer` returns `blocked` regardless of
  how good the offer is. No offer reopens a blocked call.

The cease script also notifies that the balance remains on the account. That
is deliberate wording: FDCPA 1692c(c) permits notifying that efforts are
terminated, and the balance statement is on the approved-consequences list.
Nothing beyond the script is spoken after a trigger.

## 3. The model cannot record terms that were not approved

`finalize_agreement` takes no monetary arguments. It persists the terms the
engine wrote into call state at the moment of acceptance. Even if the model
hallucinated "$200 in 12 payments", what lands in SQLite is what the engine
authorised, together with the full offer history and compliance events for
audit.

## Policy interpretation

The brief's outcome ladder maps one-to-one to `config/policy.yaml`. Two
derivations worth defending:

- "Highest-amount downpayment + one more payment": with the 25% minimum
  payment rule, the most aggressive split available is 75/25, so that skew is
  configured rather than invented.
- "Smallest payment never less than 25%": interpreted as 25% of the agreed
  total. Both readings (of the total vs of the $1,000 balance) converge on
  the brief's own caps: max 3 payments at the $800 settlement, max 4 on the
  full-balance plan, so the configuration is consistent under either.

## Deployment decisions

- Single uvicorn worker, on purpose: per-call negotiation state is a
  process-local dict. A second worker would split a call across processes and
  reset the ladder mid-negotiation. Scaling out requires a Redis-backed
  store first; documented as a known limitation instead of built.
- Docker on a VPS behind nginx with Let's Encrypt. Container binds to
  localhost only; `restart: unless-stopped` and a healthcheck keep it up with
  no scale-to-zero (a cold start during a live call is audible silence).
- The service refuses to boot in a container without a real `TOOL_SECRET`.
  An unset secret would mean an open endpoint that settles debts.
- SQLite on a mounted volume. One writer, one file, auditable with any
  client; the brief does not evaluate the destination system.

## Voice and conversation tuning (Vapi)

- Transcriber: Deepgram nova-3 with keyword boosting for proper nouns.
  Krisp denoising on: cleaner input helps both the transcriber and the
  compliance regexes, which run on transcribed text.
- LiveKit smart endpointing: consumers hesitate mid-number ("I could do...
  maybe 700"); turn-based endpointing would jump in during the pause.
- stopSpeakingPlan numWords=1: any consumer speech yields the floor
  immediately. The tradeoff is accepted knowingly: a bare "yeah" during the
  schedule read also stops the agent, but an uncooperative caller being
  talked over reads far worse than an agent that pauses and resumes.
- Tool request-start messages ("Let me check that") cover engine latency so
  it reads as a person checking a system, not dead air.
- Background office ambience for phone realism.
- Neutral end-call wording; anything warmer ("thank you for trusting us")
  reads wrong after a cease request or a wrong-number call.
- First message identifies agent and company (Meridian Recovery Services)
  and asks for the account holder by name; the FDCPA mini-Miranda is spoken
  only after identity is confirmed, per the prompt.

## Prompt lessons from live testing

Two failures found by calling the agent, both fixed in the prompt, not in
code:

- The model did not know that a consumer saying yes to a counter must be
  re-submitted through `evaluate_offer` to be approved; finalize then found
  no agreement and the agent improvised a "technical issue". The loop and the
  recovery path are now spelled out.
- Enabling the end-call tool is not enough; the prompt now states the three
  legitimate reasons to hang up, and that hostility is never one of them.

## What was tested

- 58 unit tests over the pure domain: ladder progression, validation,
  schedule cent-arithmetic, compliance triggers, and the adversarial case of
  a model attempting to record unapproved terms.
- Production smoke tests: per-call state surviving across HTTP requests,
  repeated offers not advancing the ladder, a transcript trigger blocking a
  subsequent perfect offer, and the full voice flow closing a settlement at
  $800 with a persisted reference.
