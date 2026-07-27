"""Read-only operations dashboard.

Shows live tool-call activity, per-call negotiation state and finalized
agreements, and hosts a browser-based test call via the Vapi Web SDK. It
observes and never mutates: no route here can advance the ladder, unblock a
call or write an agreement. The web-call panel talks to Vapi directly from
the browser; this server only hands it the public key and assistant id.

Authentication is deliberately NOT handled here. In deployment the container
binds to localhost and nginx enforces HTTP basic auth on /dashboard before
anything reaches this router; locally the dashboard is as open as the rest of
the dev server.
"""

import os
from collections import deque
from datetime import datetime, timezone

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from app import agreements, store

# Ring buffer of recent tool calls. In-process, like the call store itself:
# with one worker there is exactly one of these, and it resets on redeploy.
EVENTS: deque = deque(maxlen=300)


def record(call_id: str, tool_name: str | None, result: dict) -> None:
    """Called by the HTTP layer after each tool call is handled."""
    EVENTS.append(
        {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "call_id": call_id,
            "tool": tool_name or "unknown",
            "decision": result.get("decision")
            or ("finalized" if result.get("finalized") else None)
            or ("clear" if result.get("clear") else None)
            or ("triggered" if result.get("triggered") else None),
            "tier": result.get("tier"),
            "say": result.get("say"),
            "reason_codes": result.get("reason_codes"),
            "agreement_id": result.get("agreement_id"),
        }
    )


def _serialise_call(state) -> dict:
    return {
        "call_id": state.call_id,
        "rung": state.rung,
        "best_offer_total": str(state.best_offer_total),
        "blocked": state.blocked,
        "compliance_events": state.compliance_events,
        "accepted": state.accepted,
        "history": [
            {
                "total": str(h["offer"].total),
                "num_payments": h["offer"].num_payments,
                "cadence": h["offer"].cadence,
                "decision": h["decision"],
            }
            for h in state.history
        ],
    }


router = APIRouter()


@router.get("/dashboard/data")
def dashboard_data():
    calls = [_serialise_call(s) for s in store._CALLS.values()]
    calls.reverse()  # newest call first
    return {
        "now": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "events": list(reversed(EVENTS)),
        "calls": calls,
        "agreements": agreements.recent(limit=25),
    }


@router.get("/dashboard/config")
def dashboard_config():
    """Vapi web-call wiring. The public key is designed for browser use."""
    return {
        "publicKey": os.getenv("VAPI_PUBLIC_KEY"),
        "assistantId": os.getenv("VAPI_ASSISTANT_ID"),
    }


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard_page():
    return _PAGE


_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Collections Agent - Live Operations</title>
<style>
  :root { --bg:#0e1116; --panel:#161b22; --line:#242c37; --text:#dbe2ea;
          --dim:#8a94a3; --accent:#4da3ff; --ok:#3fb96b; --warn:#e0b13f;
          --bad:#e05d5d; }
  * { box-sizing:border-box; margin:0; }
  body { background:var(--bg); color:var(--text);
         font:14px/1.5 ui-monospace, SFMono-Regular, Menlo, monospace; padding:20px; }
  h1 { font-size:16px; font-weight:600; }
  h1 span { color:var(--dim); font-weight:400; }
  h2 { font-size:12px; text-transform:uppercase; letter-spacing:.08em;
       color:var(--dim); margin-bottom:10px; }
  .grid { display:grid; grid-template-columns:1.2fr 1fr; gap:16px; margin-top:16px; }
  @media (max-width:900px){ .grid { grid-template-columns:1fr; } }
  .panel { background:var(--panel); border:1px solid var(--line);
           border-radius:8px; padding:14px; }
  .col { display:flex; flex-direction:column; gap:16px; min-width:0; }
  .ev { border-bottom:1px solid var(--line); padding:8px 0; }
  .ev:last-child { border-bottom:none; }
  .meta { color:var(--dim); font-size:12px; }
  .say { color:var(--dim); font-style:italic; margin-top:2px; }
  .tag { display:inline-block; padding:0 7px; border-radius:10px; font-size:12px;
         border:1px solid var(--line); margin-right:6px; }
  .t-accept,.t-finalized,.t-clear { color:var(--ok); border-color:var(--ok); }
  .t-counter { color:var(--warn); border-color:var(--warn); }
  .t-reject,.t-blocked,.t-triggered,.t-unparseable { color:var(--bad); border-color:var(--bad); }
  .call { border:1px solid var(--line); border-radius:6px; padding:10px; margin-bottom:10px; }
  .ladder { display:flex; gap:4px; margin:6px 0; }
  .rung { flex:1; text-align:center; font-size:11px; padding:2px 0;
          border:1px solid var(--line); border-radius:4px; color:var(--dim); }
  .rung.on { color:var(--accent); border-color:var(--accent); }
  table { width:100%; border-collapse:collapse; font-size:13px; }
  td,th { text-align:left; padding:4px 8px 4px 0; border-bottom:1px solid var(--line); }
  th { color:var(--dim); font-weight:400; }
  .empty { color:var(--dim); padding:8px 0; }
  #status { float:right; font-size:12px; color:var(--dim); }
  #callbtn { background:var(--accent); color:#08121f; border:none; border-radius:6px;
             padding:8px 18px; font:inherit; font-weight:600; cursor:pointer; }
  #callbtn.live { background:var(--bad); color:#fff; }
  #callbtn:disabled { opacity:.5; cursor:default; }
  #callstate { margin-left:10px; color:var(--dim); font-size:13px; }
  #transcript { margin-top:12px; max-height:340px; overflow-y:auto; }
  .line { margin:6px 0; }
  .line .who { font-size:11px; text-transform:uppercase; letter-spacing:.06em; }
  .line.agent .who { color:var(--accent); }
  .line.you .who { color:var(--ok); }
  .line.partial { opacity:.55; }
</style>
</head>
<body>
<h1>Collections Agent <span>&mdash; live operations</span><span id="status"></span></h1>
<div class="grid">
  <div class="col">
    <div class="panel">
      <h2>Talk to the agent</h2>
      <div>
        <button id="callbtn" disabled>Start call</button>
        <span id="callstate">loading&hellip;</span>
      </div>
      <div id="transcript"></div>
    </div>
    <div class="panel">
      <h2>Calls this session</h2>
      <div id="calls" class="empty">No calls yet.</div>
    </div>
  </div>
  <div class="col">
    <div class="panel">
      <h2>Tool call feed</h2>
      <div id="events" class="empty">Waiting for activity&hellip;</div>
    </div>
    <div class="panel">
      <h2>Finalized agreements</h2>
      <div id="agreements" class="empty">None yet.</div>
    </div>
  </div>
</div>
<script>
const LADDER = ["paid_in_full", "downpayment_plus_one", "settlement", "payment_plan"];
const esc = s => String(s ?? "").replace(/[&<>"]/g, c =>
  ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));

function tag(v) {
  return v ? `<span class="tag t-${esc(v)}">${esc(v)}</span>` : "";
}

function render(d) {
  const ev = document.getElementById("events");
  if (d.events.length) ev.outerHTML = `<div id="events">` + d.events.map(e => `
    <div class="ev">
      <div class="meta">${esc(e.ts.replace("T"," ").replace("+00:00"," UTC"))}
        &middot; call <b>${esc(e.call_id)}</b> &middot; ${esc(e.tool)}</div>
      <div>${tag(e.decision)}${e.tier ? "tier: <b>" + esc(e.tier) + "</b>" : ""}
        ${e.agreement_id ? " ref <b>" + esc(e.agreement_id) + "</b>" : ""}</div>
      ${e.say ? `<div class="say">&ldquo;${esc(e.say)}&rdquo;</div>` : ""}
    </div>`).join("") + `</div>`;

  const calls = document.getElementById("calls");
  if (d.calls.length) calls.outerHTML = `<div id="calls">` + d.calls.map(c => `
    <div class="call">
      <div><b>${esc(c.call_id)}</b>
        ${c.blocked ? tag("blocked") : ""}
        ${c.accepted ? tag("accept") : ""}
        <span class="meta">best offer $${esc(c.best_offer_total)}</span></div>
      <div class="ladder">${LADDER.map((r,i) =>
        `<div class="rung ${i === c.rung ? "on" : ""}">${r.replaceAll("_"," ")}</div>`).join("")}</div>
      ${c.history.length ? `<div class="meta">` + c.history.map(h =>
        `$${esc(h.total)}/${h.num_payments} ${esc(h.cadence)} &rarr; ${esc(h.decision)}`
        ).join(" &middot; ") + `</div>` : ""}
      ${c.compliance_events.length ?
        `<div class="meta">compliance: ${c.compliance_events.map(esc).join(", ")}</div>` : ""}
    </div>`).join("") + `</div>`;

  const ag = document.getElementById("agreements");
  if (d.agreements.length) ag.outerHTML = `<div id="agreements"><table>
    <tr><th>ref</th><th>total</th><th>payments</th><th>call</th><th>created (UTC)</th></tr>` +
    d.agreements.map(a => `
    <tr><td><b>${esc(a.id)}</b></td><td>$${esc(a.total)}</td>
      <td>${a.num_payments} ${esc(a.cadence)}</td><td>${esc(a.call_id)}</td>
      <td>${esc(a.created_at.slice(0,19).replace("T"," "))}</td></tr>`).join("") +
    `</table></div>`;

  document.getElementById("status").textContent =
    "live - updated " + new Date().toLocaleTimeString();
}

async function tick() {
  try {
    const r = await fetch("/dashboard/data", {cache: "no-store"});
    if (r.ok) render(await r.json());
  } catch (e) { /* keep polling */ }
}
tick();
setInterval(tick, 2000);

// ---- Web call via Vapi SDK ----
const btn = document.getElementById("callbtn");
const stateEl = document.getElementById("callstate");
const tEl = document.getElementById("transcript");
let vapi = null, live = false, lines = [], partial = null;

function drawTranscript() {
  const all = partial ? lines.concat([partial]) : lines;
  tEl.innerHTML = all.map(l => `
    <div class="line ${l.role === "assistant" ? "agent" : "you"} ${l.partial ? "partial" : ""}">
      <span class="who">${l.role === "assistant" ? "agent" : "you"}</span>
      <div>${esc(l.text)}</div>
    </div>`).join("");
  tEl.scrollTop = tEl.scrollHeight;
}

function setState(msg, isLive) {
  live = isLive;
  stateEl.textContent = msg;
  btn.textContent = isLive ? "End call" : "Start call";
  btn.classList.toggle("live", isLive);
}

async function initCall() {
  const cfg = await fetch("/dashboard/config").then(r => r.json()).catch(() => null);
  if (!cfg || !cfg.publicKey || !cfg.assistantId) {
    stateEl.textContent = "web call not configured";
    return;
  }
  try {
    const mod = await import("https://esm.sh/@vapi-ai/web");
    vapi = new (mod.default)(cfg.publicKey);
  } catch (e) {
    stateEl.textContent = "could not load Vapi SDK";
    return;
  }
  vapi.on("call-start", () => { lines = []; partial = null; drawTranscript();
                                setState("connected - the agent speaks first", true); });
  vapi.on("call-end", () => setState("call ended", false));
  vapi.on("error", e => {
    // When the AGENT hangs up (End Call tool) some SDK versions surface it
    // as an ejection/meeting-ended error instead of a call-end event.
    const blob = JSON.stringify(e || {});
    if (live && /eject|ended|end-?ed|hang|left/i.test(blob)) {
      setState("call ended", false);
    } else {
      setState("error: " + (e?.error?.message || e?.errorMsg || e?.message || "call failed"), false);
    }
  });
  vapi.on("message", m => {
    if (m.type === "status-update" && m.status === "ended") {
      setState("call ended", false);
      return;
    }
    if (m.type !== "transcript") return;
    if (m.transcriptType === "final") {
      partial = null;
      lines.push({ role: m.role, text: m.transcript });
    } else {
      partial = { role: m.role, text: m.transcript, partial: true };
    }
    drawTranscript();
  });
  btn.disabled = false;
  setState("ready - uses your microphone", false);
  btn.onclick = () => {
    if (live) { vapi.stop(); return; }
    setState("connecting…", false);
    vapi.start(cfg.assistantId);
  };
}
initCall();
</script>
</body>
</html>
"""
