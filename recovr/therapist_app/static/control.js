// Therapist control page -- plain fetch + polling, no framework.
//
// The page never holds "truth": it POSTs config/commands and then renders
// whatever GET /api/state returns. Same reconcile model as the Pygame client.

"use strict";

const POLL_MS = window.RECOVR_POLL_MS || 300;

const $ = (id) => document.getElementById(id);

async function postJSON(path, body) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  let data = null;
  try { data = await res.json(); } catch (_) {}
  return { ok: res.ok, status: res.status, data };
}

// --- Configuration form -------------------------------------------------
$("config-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  const body = Object.fromEntries(fd.entries());
  body.duration_sec = parseInt(body.duration_sec, 10) || 60;
  const { ok } = await postJSON("/api/session/config", body);
  setMsg(ok ? "Configuration applied." : "Failed to apply configuration.", ok ? "ok" : "err");
});

// --- Command buttons --------------------------------------------------
document.querySelectorAll("button.cmd").forEach((btn) => {
  btn.addEventListener("click", async () => {
    const command = btn.dataset.cmd;
    const { ok, data } = await postJSON("/api/command", { command });
    const message = (data && data.message) || (ok ? "ok" : "rejected");
    setMsg(`${command}: ${message}`, ok ? "ok" : "err");
  });
});

$("reset-btn").addEventListener("click", async () => {
  await postJSON("/api/reset", {});
  setMsg("Session reset.", "ok");
});

function setMsg(text, kind) {
  const el = $("cmd-msg");
  el.textContent = text;
  el.className = "msg " + (kind || "");
}

// --- Live polling ---------------------------------------------------
function fmt(v, digits) {
  if (v === undefined || v === null || v === "") return "—";
  return typeof v === "number" ? v.toFixed(digits ?? 0) : String(v);
}

function render(state) {
  const cfg = state.config || {};
  const tel = state.telemetry || {};

  $("s-status").textContent = state.status || "—";
  $("s-sid").textContent = cfg.session_id || "—";
  $("s-patient").textContent = cfg.patient_name
    ? `${cfg.patient_name}${cfg.patient_id ? " (" + cfg.patient_id + ")" : ""}`
    : "—";
  $("s-game").textContent = cfg.selected_game || "—";
  $("s-diff").textContent = cfg.difficulty || "—";
  $("s-cseq").textContent = state.command_seq ?? 0;
  $("s-gseq").textContent = state.game_seq ?? 0;
  $("s-pending").textContent = state.pending_action || "—";

  $("t-score").textContent = fmt(tel.score);
  $("t-remaining").textContent = tel.remaining_sec !== undefined ? fmt(tel.remaining_sec, 1) + "s" : "—";
  $("t-elapsed").textContent = tel.elapsed_sec !== undefined ? fmt(tel.elapsed_sec, 1) + "s" : "—";
  $("t-accuracy").textContent = tel.accuracy !== undefined ? fmt(tel.accuracy * 100, 0) + "%" : "—";
  $("t-reps").textContent = fmt(tel.reps);
  $("t-rt").textContent = fmt(tel.reaction_time_ms);

  $("raw").textContent = JSON.stringify(state, null, 2);
}

function setConn(ok) {
  const el = $("conn");
  el.textContent = ok ? "connected" : "server unreachable";
  el.className = "pill " + (ok ? "pill-ok" : "pill-bad");
}

async function poll() {
  try {
    const res = await fetch("/api/state");
    const state = await res.json();
    setConn(true);
    render(state);
  } catch (_) {
    setConn(false);
  }
}

poll();
setInterval(poll, POLL_MS);
