# Vapi assistant configuration

The assistant lives in the Vapi dashboard; this file records its full
configuration so the setup is reproducible. The tool definitions it uses are
in `vapi/tools/` (create them with `vapi/create_tools.sh` or by hand).

## Model

- System prompt: the exact contents of `prompts/system.md` (or
  `prompts/system.es.md` for a Spanish demo, switching transcriber and voice
  language accordingly). The repo copy is the source of truth; if the prompt
  is edited in the dashboard, mirror the change here.
- Provider/model: any strong instruction-following model. Tested with a
  low temperature (~0.3). Avoid small models: the prompt depends on strict
  tool discipline.

## First message

```
Hello this is Santi from Meridian Recovery Services, may I speak with Jordan Rivera?
```

The consumer identity (Jordan Rivera) is fictional. The required FDCPA
mini-Miranda is spoken after identity is confirmed, per the system prompt.

## Tools

Attach the three function tools from `vapi/tools/`:

- `evaluate_offer`
- `check_compliance`
- `finalize_agreement`

All three post to `https://collections.santils.dev/vapi/tools` with the
`x-tool-secret` header and run synchronously (`async: false`) so the agent
waits for the engine's verdict before speaking.

Also enable the built-in **End Call** tool so the agent can actually hang up
after reading a compliance script whose rule ends the call (cease request,
attorney, dispute, wrong party, bankruptcy). Without it the agent can only
go silent.

## Server messages (compliance enforcement and live mirror)

Configured via the API (the dashboard UI did not persist these reliably):

```
PATCH /assistant/{id}
{
  "server": {"url": "https://collections.santils.dev/vapi/events",
             "secret": "<TOOL_SECRET>"},
  "serverMessages": ["transcript", "status-update", "end-of-call-report"]
}
```

This streams every transcribed utterance to the service, which does two
things with it and stores neither:

- Scans consumer turns with the same detector as `check_compliance`. A
  statutory trigger freezes the negotiation server-side even if the model
  never calls the tool.
- Mirrors the conversation to the dashboard's live view so phone calls are
  visible in real time. Text is held in process memory only while the call
  is active; `status-update: ended` / `end-of-call-report` delete it.

## Transcriber and voice

- Transcriber: Deepgram, `nova-2` or newer, language `en`.
- Voice: any; not load-bearing.

## Dashboard web-call wiring

The live dashboard's "Talk to the agent" button needs two values in the
service environment (see `.env.example`): `VAPI_PUBLIC_KEY` (the public key,
safe for browsers) and `VAPI_ASSISTANT_ID`.
