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
<title>Meridian Recovery Services - Operations</title>
<style>
  :root { --bg:#0d1218; --card:#151c26; --line:#242f3d; --text:#dbe3ed;
          --dim:#8a96a5; --head:#0a0f15; --accent:#4da3ff;
          --ok:#43d18e; --ok-bg:rgba(67,209,142,.12);
          --warn:#e8b64c; --warn-bg:rgba(232,182,76,.12);
          --bad:#f07a6a; --bad-bg:rgba(240,122,106,.12); }
  * { box-sizing:border-box; margin:0; }
  body { background:var(--bg); color:var(--text); padding:0 0 40px;
         font:14px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", Inter,
         Roboto, sans-serif; }
  header { background:var(--head); border-bottom:1px solid var(--line);
           color:#fff; padding:16px 28px;
           display:flex; align-items:baseline; gap:14px; }
  header .brand { font-size:17px; font-weight:700; letter-spacing:.2px; }
  header .sub { font-size:13px; color:var(--dim); }
  #status { margin-left:auto; font-size:12px; color:var(--dim); }
  #status::before { content:""; display:inline-block; width:8px; height:8px;
                    border-radius:50%; background:var(--ok); margin-right:6px; }
  .wrap { max-width:1200px; margin:22px auto 0; padding:0 20px; }
  .stats { display:grid; grid-template-columns:repeat(4,1fr); gap:18px;
           margin-bottom:18px; }
  @media (max-width:920px){ .stats { grid-template-columns:repeat(2,1fr); } }
  .kpi { background:var(--card); border:1px solid var(--line); border-radius:12px;
         padding:14px 18px; }
  .kpi .num { font-size:26px; font-weight:700; line-height:1.2; }
  .kpi .lbl { font-size:11px; text-transform:uppercase; letter-spacing:.09em;
              color:var(--dim); margin-top:2px; }
  .kpi.good .num { color:var(--ok); }
  .kpi.warn .num { color:var(--bad); }
  .grid { display:grid; grid-template-columns:1.15fr 1fr; gap:18px; }
  @media (max-width:920px){ .grid { grid-template-columns:1fr; } }
  .col { display:flex; flex-direction:column; gap:18px; min-width:0; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:12px;
          padding:18px 20px; }
  h2 { font-size:11px; text-transform:uppercase; letter-spacing:.1em;
       color:var(--dim); margin-bottom:12px; font-weight:600; }
  .empty { color:var(--dim); font-size:13px; padding:6px 0; }
  .meta { color:var(--dim); font-size:12px; }

  /* call panel */
  #callbtn { display:inline-flex; align-items:center; gap:8px;
             background:var(--accent); color:#08121f; border:none; border-radius:999px;
             padding:10px 22px; font:inherit; font-size:14px; font-weight:600;
             cursor:pointer; transition:background .15s; }
  #callbtn:hover { background:#71b7ff; }
  #callbtn.live { background:var(--bad); color:#1c0906; }
  #callbtn:disabled { opacity:.45; cursor:default; }
  #callstate { margin-left:12px; color:var(--dim); font-size:13px; }
  #transcript { margin-top:14px; max-height:380px; overflow-y:auto;
                display:flex; flex-direction:column; gap:8px; }
  .line { max-width:82%; padding:8px 12px; border-radius:12px; font-size:13.5px; }
  .line .who { display:block; font-size:10.5px; text-transform:uppercase;
               letter-spacing:.07em; color:var(--dim); margin-bottom:2px; }
  .line.agent { align-self:flex-start; background:#1c2532;
                border-bottom-left-radius:4px; }
  .line.you { align-self:flex-end; background:#1d3050;
              border-bottom-right-radius:4px; }
  .line.partial { opacity:.55; }

  /* feed */
  #events { max-height:520px; overflow-y:auto; }
  .ev { border-left:3px solid var(--line); padding:6px 0 6px 12px; margin:10px 0; }
  .ev.d-accept, .ev.d-finalized, .ev.d-clear { border-left-color:var(--ok); }
  .ev.d-counter { border-left-color:var(--warn); }
  .ev.d-reject, .ev.d-blocked, .ev.d-triggered, .ev.d-unparseable { border-left-color:var(--bad); }
  .say { color:var(--dim); font-style:italic; margin-top:3px; font-size:13px; }
  .tag { display:inline-block; padding:1px 9px; border-radius:999px; font-size:11.5px;
         font-weight:600; margin-right:6px; background:#212b38; color:var(--dim); }
  .t-accept,.t-finalized,.t-clear { color:var(--ok); background:var(--ok-bg); }
  .t-counter { color:var(--warn); background:var(--warn-bg); }
  .t-reject,.t-blocked,.t-triggered,.t-unparseable { color:var(--bad); background:var(--bad-bg); }

  /* negotiations */
  .call { border:1px solid var(--line); border-radius:10px; padding:12px 14px;
          margin-bottom:12px; }
  .call .cid { font-weight:600; font-size:13px; }
  .ladder { display:flex; align-items:center; margin:10px 0 6px; }
  .step { display:flex; align-items:center; gap:6px; font-size:11px; color:var(--dim);
          white-space:nowrap; }
  .step .dot { width:22px; height:22px; border-radius:50%; background:#212b38;
               color:var(--dim); display:flex; align-items:center; justify-content:center;
               font-size:11px; font-weight:600; }
  .step.done .dot { background:#24405f; color:#9cc4f0; }
  .step.on .dot { background:var(--accent); color:#06111d; }
  .step.on { color:var(--accent); font-weight:600; }
  .bar { flex:1; height:2px; background:var(--line); margin:0 6px; min-width:12px; }
  .bar.done { background:var(--accent); }

  /* agreements */
  table { width:100%; border-collapse:collapse; font-size:13px; }
  td,th { text-align:left; padding:7px 10px 7px 0; border-bottom:1px solid var(--line); }
  th { color:var(--dim); font-weight:600; font-size:11px; text-transform:uppercase;
       letter-spacing:.07em; }
  tr:last-child td { border-bottom:none; }
  .amount { font-weight:700; color:var(--accent); }
</style>
</head>
<body>
<header>
  <span class="brand">Meridian Recovery Services</span>
  <span class="sub">Collections agent &middot; operations console</span>
  <span id="status"></span>
</header>
<div class="wrap">
<div class="stats">
  <div class="kpi"><div class="num" id="k-calls">0</div>
    <div class="lbl">Negotiations</div></div>
  <div class="kpi good"><div class="num" id="k-agreements">0</div>
    <div class="lbl">Agreements</div></div>
  <div class="kpi good"><div class="num" id="k-collected">$0</div>
    <div class="lbl">Committed</div></div>
  <div class="kpi warn"><div class="num" id="k-blocked">0</div>
    <div class="lbl">Compliance holds</div></div>
</div>
<div class="grid">
  <div class="col">
    <div class="card">
      <h2>Talk to the agent</h2>
      <div>
        <button id="callbtn" disabled>
          <svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor"><path d="M6.6 10.8c1.4 2.8 3.8 5.1 6.6 6.6l2.2-2.2c.3-.3.7-.4 1-.2 1.1.4 2.3.6 3.6.6.6 0 1 .4 1 1V20c0 .6-.4 1-1 1C10.6 21 3 13.4 3 4c0-.6.4-1 1-1h3.5c.6 0 1 .4 1 1 0 1.2.2 2.4.6 3.6.1.3 0 .7-.2 1l-2.3 2.2z"/></svg>
          <span id="btnlabel">Start call</span>
        </button>
        <span id="callstate">loading&hellip;</span>
      </div>
      <div id="transcript"></div>
    </div>
    <div class="card">
      <h2>Negotiations this session</h2>
      <div id="calls" class="empty">No calls yet.</div>
    </div>
  </div>
  <div class="col">
    <div class="card">
      <h2>Engine activity</h2>
      <div id="events" class="empty">Waiting for activity&hellip;</div>
    </div>
    <div class="card">
      <h2>Finalized agreements</h2>
      <div id="agreements" class="empty">None yet.</div>
    </div>
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

function ladder(rung) {
  return `<div class="ladder">` + LADDER.map((r, i) => {
    const cls = i < rung ? "done" : (i === rung ? "on" : "");
    const mark = i < rung ? "&check;" : i + 1;
    return (i ? `<div class="bar ${i <= rung ? "done" : ""}"></div>` : "") +
      `<div class="step ${cls}"><span class="dot">${mark}</span>${r.replaceAll("_", " ")}</div>`;
  }).join("") + `</div>`;
}

function render(d) {
  const ev = document.getElementById("events");
  if (d.events.length) ev.outerHTML = `<div id="events">` + d.events.map(e => `
    <div class="ev d-${esc(e.decision || "")}">
      <div class="meta">${esc(e.ts.replace("T"," ").replace("+00:00",""))} UTC
        &middot; call ${esc(e.call_id)} &middot; ${esc(e.tool)}</div>
      <div>${tag(e.decision)}${e.tier ? "tier <b>" + esc(e.tier).replaceAll("_"," ") + "</b>" : ""}
        ${e.agreement_id ? " ref <b>" + esc(e.agreement_id) + "</b>" : ""}</div>
      ${e.say ? `<div class="say">&ldquo;${esc(e.say)}&rdquo;</div>` : ""}
    </div>`).join("") + `</div>`;

  const calls = document.getElementById("calls");
  if (d.calls.length) calls.outerHTML = `<div id="calls">` + d.calls.map(c => `
    <div class="call">
      <div><span class="cid">Call ${esc(c.call_id)}</span>
        ${c.blocked ? tag("blocked") : ""}
        ${c.accepted ? tag("accept") : ""}
        <span class="meta" style="float:right">best offer <b>$${esc(c.best_offer_total)}</b></span></div>
      ${ladder(c.rung)}
      ${c.history.length ? `<div class="meta">` + c.history.map(h =>
        `$${esc(h.total)} &times; ${h.num_payments} ${esc(h.cadence)} &rarr; ${esc(h.decision)}`
        ).join(" &nbsp;&middot;&nbsp; ") + `</div>` : ""}
      ${c.compliance_events.length ?
        `<div class="meta">compliance: ${c.compliance_events.map(esc).join(", ")}</div>` : ""}
    </div>`).join("") + `</div>`;

  const ag = document.getElementById("agreements");
  if (d.agreements.length) ag.outerHTML = `<div id="agreements"><table>
    <tr><th>Reference</th><th>Total</th><th>Payments</th><th>Call</th><th>Created (UTC)</th></tr>` +
    d.agreements.map(a => `
    <tr><td><b>${esc(a.id)}</b></td><td class="amount">$${esc(a.total)}</td>
      <td>${a.num_payments} ${esc(a.cadence)}</td><td>${esc(a.call_id)}</td>
      <td>${esc(a.created_at.slice(0,19).replace("T"," "))}</td></tr>`).join("") +
    `</table></div>`;

  document.getElementById("k-calls").textContent = d.calls.length;
  document.getElementById("k-agreements").textContent = d.agreements.length;
  document.getElementById("k-blocked").textContent =
    d.calls.filter(c => c.blocked).length;
  const collected = d.agreements.reduce((s, a) => s + parseFloat(a.total || 0), 0);
  document.getElementById("k-collected").textContent =
    "$" + collected.toLocaleString("en-US", {maximumFractionDigits: 0});

  document.getElementById("status").textContent =
    "live · " + new Date().toLocaleTimeString();
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
  document.getElementById("btnlabel").textContent = isLive ? "End call" : "Start call";
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
