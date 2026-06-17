"use strict";

const $ = (s) => document.querySelector(s);
const VISIBLE_MS = 2000;
const HIDDEN_MS = 20000;
const EMBED = location.search.indexOf("embed") !== -1;  // hosted in the menu-bar popover
const DEFAULT_TYPES = ["A100", "L40S", "H100"];

let state = { hosts: [], vpn: {}, alarm: {}, names: {}, alarm_config: {} };
let editingUser = null;   // suppress content re-render while renaming
let alarmOpen = false;

/* ---------- helpers ---------- */
function fmtDur(s) {
  if (s == null) return "—";
  s = Math.floor(s);
  const d = Math.floor(s / 86400); s %= 86400;
  const h = Math.floor(s / 3600); s %= 3600;
  const m = Math.floor(s / 60);
  if (d) return `${d}d${h}h`;
  if (h) return `${h}h${m}m`;
  if (m) return `${m}m`;
  return `${s}s`;
}
const gb = (mib) => (mib == null ? "?" : (mib / 1024).toFixed(1));
function gpuType(name) {
  const n = (name || "").toUpperCase();
  for (const t of ["A100", "L40S", "H100", "A40", "A6000", "V100", "L4"]) if (n.includes(t)) return t;
  return (name || "GPU").replace("NVIDIA ", "").split(" ")[0];
}
function isIdle(g) {
  if (g.procs && g.procs.length) return false;
  return (g.mem_used || 0) <= 1500 && (g.util || 0) <= 5;
}
function displayName(u) { return state.names[u] || u; }
function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// Tiny utilisation sparkline (last 15 min) as an inline SVG.
function sparkline(hist, tsNow) {
  const W = 70, H = 16, win = 900;
  hist = hist || [];
  const t0 = (tsNow || Date.now() / 1000) - win;
  const pts = hist.filter((p) => p[0] >= t0);
  const empty = `<svg class="sparksvg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}"></svg>`;
  if (pts.length < 2) return empty;
  const X = (t) => Math.max(0, Math.min(W, ((t - t0) / win) * W));
  const Y = (u) => (H - 1) - (Math.max(0, Math.min(100, u)) / 100) * (H - 2);
  const line = pts.map((p, i) => `${i ? "L" : "M"}${X(p[0]).toFixed(1)} ${Y(p[1]).toFixed(1)}`).join(" ");
  const area = `M${X(pts[0][0]).toFixed(1)} ${H} `
    + pts.map((p) => `L${X(p[0]).toFixed(1)} ${Y(p[1]).toFixed(1)}`).join(" ")
    + ` L${X(pts[pts.length - 1][0]).toFixed(1)} ${H} Z`;
  return `<svg class="sparksvg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">`
    + `<path class="sparkarea" d="${area}"/><path class="sparkline" d="${line}"/></svg>`;
}

async function copyText(t) {
  try { await navigator.clipboard.writeText(t); return true; }
  catch (e) {
    const ta = document.createElement("textarea");
    ta.value = t; ta.style.position = "fixed"; ta.style.opacity = "0";
    document.body.appendChild(ta); ta.select();
    let ok = false; try { ok = document.execCommand("copy"); } catch (_) {}
    ta.remove(); return ok;
  }
}

/* ---------- data ---------- */
async function poll() {
  try {
    const r = await fetch("/api/state");
    state = await r.json();
    render();
  } catch (e) {
    $("#updated").textContent = "backend unreachable…";
    $("#live-dot").classList.remove("live");
  }
}

/* ---------- render ---------- */
function render() {
  const v = state.vpn || {};
  const pill = $("#vpn-pill");
  const connected = v.state === "connected";
  pill.className = "pill " + (connected ? "ok" : v.state === "connecting" ? "warn" : "bad");
  pill.textContent = connected ? "VPN on" : v.state === "connecting" ? "VPN…" : "VPN off";
  pill.classList.toggle("hidden", state.vpn_configured === false);  // no pill if no VPN gate

  $("#live-dot").classList.toggle("live", connected);
  if (state.ts) {
    const ago = Math.max(0, Math.round(Date.now() / 1000 - state.ts));
    $("#updated").textContent = `updated ${ago}s ago`;
  }

  // alarm chip
  const a = state.alarm || {};
  const chip = $("#alarm-chip");
  if (a.enabled) {
    chip.classList.remove("hidden");
    chip.classList.toggle("met", !!a.matched);
    chip.textContent = a.matched ? "🔔 MET" : "🔔 armed";
    chip.title = a.matched ? (a.message || "") : `mode: ${a.mode || "idle"}`;
  } else {
    chip.classList.add("hidden");
  }

  const vpnDown = $("#vpn-down");
  const content = $("#content");
  if (alarmOpen) {                       // settings view replaces the GPU list
    vpnDown.classList.add("hidden");
    content.classList.add("hidden");
    return;
  }
  content.classList.remove("hidden");
  if (!connected) {
    vpnDown.classList.remove("hidden");
    content.innerHTML = "";
    $("#vpn-sub").textContent = v.detail || "";
    $("#open-vpn").textContent = "Open " + (state.vpn_label || "VPN client");
    return;
  }
  vpnDown.classList.add("hidden");
  if (!editingUser) renderContent();
}

function renderContent() {
  const content = $("#content");
  const hosts = state.hosts || [];
  if (!hosts.length) {
    content.innerHTML = state.configured === false
      ? `<div class="notice">No GPU hosts configured.<br>Edit <code>${esc(state.config_file || "config.json")}</code> (copy <code>config.example.json</code>) and add your hosts with your <b>username</b> — e.g. <code>"ssh": "you@gpu.example.edu"</code>.</div>`
      : `<div class="host"><div class="no-proc">no host data yet…</div></div>`;
    return;
  }

  let html = "";
  for (const h of hosts) {
    html += `<section class="host">`;
    if (!h.reachable) {
      html += `<div class="host-head"><span class="host-name">${esc(h.name)}</span>
               <span class="host-err">unreachable: ${esc(h.error || "?")}</span></div></section>`;
      continue;
    }
    const gpus = h.gpus || [];
    const idleN = gpus.filter(isIdle).length;
    html += `<div class="host-head"><span class="host-name">${esc(h.name)}</span>
             <span class="host-meta">${idleN}/${gpus.length} idle</span></div>`;
    html += `<div class="gpus">` + gpus.map(gpuCard).join("") + `</div>`;
    html += `</section>`;
  }
  content.innerHTML = html;
  wireRows();
}

function gpuCard(g) {
  const t = gpuType(g.name);
  const idle = isIdle(g);
  const memPct = g.mem_total ? Math.round(100 * g.mem_used / g.mem_total) : 0;
  const util = g.util || 0;
  const free = (g.mem_total || 0) - (g.mem_used || 0);
  const temp = g.temp != null ? `${g.temp}°C` : "";

  const hist = g.util_history || [];
  const spark = hist.length >= 2
    ? `<div class="spark" title="utilisation · last 15 min">${sparkline(hist, state.ts)}</div>` : "";

  let procs = "";
  if (g.procs && g.procs.length) {
    procs = `<div class="procs">` + g.procs.map((p) => procRow(p)).join("") + `</div>`;
  } else if (idle) {
    procs = `<div class="procs"><div class="no-proc">free — no processes</div></div>`;
  }

  return `
  <div class="gpu ${idle ? "idle" : ""}">
    <div class="gpu-top">
      <span class="badge ${t}">${esc(t)}</span>
      <span class="gpu-id">GPU${g.index}</span>
      ${idle ? `<span class="idle-tag">IDLE</span>` : ""}
      <span class="gpu-temp">${temp}</span>
    </div>
    <span class="bar mem"><span style="width:${memPct}%"></span></span>
    <div class="mval">${gb(g.mem_used)} / ${gb(g.mem_total)} GB</div>
    <div class="mval free">${gb(free)} GB free</div>
    <span class="bar util"><span style="width:${util}%"></span></span>
    <div class="mval">${util}% util</div>
    ${spark}
    ${procs}
  </div>`;
}

function procRow(p) {
  const mapped = state.names[p.user] && state.names[p.user] !== p.user;
  return `
  <div class="proc" data-user="${esc(p.user)}">
    <div class="who">
      <span class="name" title="right-click to rename · ${esc(p.user)}">${esc(displayName(p.user))}${mapped ? `<span class="uname">${esc(p.user)}</span>` : ""}</span>
      <button class="copy" title="copy username">⧉</button>
    </div>
    <div class="pmeta">${gb(p.mem)} GB · ${fmtDur(p.elapsed)}</div>
    ${p.cmd ? `<div class="pcmd">${esc(p.cmd)}</div>` : ""}
  </div>`;
}

/* ---------- row interactions ---------- */
function wireRows() {
  document.querySelectorAll(".proc").forEach((row) => {
    const user = row.dataset.user;
    const nameEl = row.querySelector(".name");
    const copyEl = row.querySelector(".copy");
    copyEl.addEventListener("click", async () => {
      const ok = await copyText(user);
      if (ok) { copyEl.classList.add("done"); copyEl.textContent = "✓";
        setTimeout(() => { copyEl.classList.remove("done"); copyEl.textContent = "⧉"; }, 1200); }
    });
    nameEl.addEventListener("contextmenu", (e) => { e.preventDefault(); startEdit(nameEl, user); });
  });
}

function startEdit(nameEl, user) {
  editingUser = user;
  const cur = state.names[user] || "";
  const input = document.createElement("input");
  input.className = "name-input";
  input.value = cur;
  input.placeholder = user;
  nameEl.replaceWith(input);
  input.focus(); input.select();
  let done = false;
  const finish = async (save) => {
    if (done) return; done = true;
    if (save) {
      try {
        const r = await fetch("/api/names", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ username: user, name: input.value }),
        });
        state.names = (await r.json()).names || state.names;
      } catch (_) {}
    }
    editingUser = null;
    renderContent();
  };
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") finish(true);
    else if (e.key === "Escape") finish(false);
  });
  input.addEventListener("blur", () => finish(true));
}

/* ---------- alarm panel ---------- */
function observedTypes() {
  const set = new Set();
  for (const h of state.hosts || []) for (const g of h.gpus || []) set.add(gpuType(g.name));
  return set.size ? [...set] : DEFAULT_TYPES;
}
function hostNames() {
  return (state.hosts || []).map((h) => h.name);
}

function openAlarmPanel() {
  alarmOpen = true;
  const c = state.alarm_config || {};
  $("#al-enabled").checked = !!c.enabled;
  $("#al-vram").value = c.vram_gb || 40;
  const mode = c.mode || "idle";
  document.querySelectorAll('input[name="al-mode"]').forEach((r) => { r.checked = r.value === mode; });

  // specific rules
  const wrap = $("#al-specific"); wrap.innerHTML = "";
  const rules = (c.specific && c.specific.length) ? c.specific : [{ type: observedTypes()[0], count: 1 }];
  rules.forEach(addRuleRow);

  // hosts
  const watch = new Set(c.hosts || []);
  const hostsWrap = $("#al-hosts"); hostsWrap.innerHTML = "";
  hostNames().forEach((n) => {
    const checked = watch.size === 0 || watch.has(n);
    const lab = document.createElement("label");
    lab.innerHTML = `<input type="checkbox" value="${esc(n)}" ${checked ? "checked" : ""}> ${esc(n)}`;
    hostsWrap.appendChild(lab);
  });

  $("#al-savestatus").textContent = "";
  $("#alarm-panel").classList.remove("hidden");
  $("#content").classList.add("hidden");
  $("#vpn-down").classList.add("hidden");
}

function closeAlarmPanel() {
  alarmOpen = false;
  $("#alarm-panel").classList.add("hidden");
  render();
}

function addRuleRow(rule) {
  const wrap = $("#al-specific");
  const types = observedTypes();
  const row = document.createElement("div");
  row.className = "rule";
  const opts = types.map((t) => `<option value="${esc(t)}" ${rule && rule.type === t ? "selected" : ""}>${esc(t)}</option>`).join("");
  row.innerHTML = `<input type="number" class="num count" min="1" max="8" value="${rule ? rule.count : 1}">
    <span>×</span><select class="type">${opts}</select>
    <button class="rm" title="remove">✕</button>`;
  row.querySelector(".rm").addEventListener("click", () => row.remove());
  wrap.appendChild(row);
}

function readAlarmForm() {
  const mode = document.querySelector('input[name="al-mode"]:checked')?.value || "idle";
  const specific = [...document.querySelectorAll("#al-specific .rule")].map((r) => ({
    type: r.querySelector(".type").value,
    count: Math.max(1, parseInt(r.querySelector(".count").value, 10) || 1),
  }));
  const hosts = [...document.querySelectorAll("#al-hosts input:checked")].map((c) => c.value);
  const allHosts = document.querySelectorAll("#al-hosts input").length;
  return {
    enabled: $("#al-enabled").checked,
    mode,
    vram_gb: Math.max(1, parseInt($("#al-vram").value, 10) || 40),
    specific,
    hosts: hosts.length === allHosts ? [] : hosts,  // [] == all
  };
}

async function saveAlarm() {
  const cfg = readAlarmForm();
  const r = await fetch("/api/alarms", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(cfg),
  });
  state.alarm_config = await r.json();
  $("#al-savestatus").textContent = "saved ✓";
  setTimeout(() => { $("#al-savestatus").textContent = ""; }, 1800);
}

/* ---------- wiring ---------- */
$("#refresh-btn").addEventListener("click", () => fetch("/api/refresh", { method: "POST" }).then(poll));
$("#open-vpn").addEventListener("click", () => fetch("/api/vpn/open", { method: "POST" }));
$("#alarm-btn").addEventListener("click", () => { alarmOpen ? closeAlarmPanel() : openAlarmPanel(); });
$("#alarm-close").addEventListener("click", closeAlarmPanel);
$("#al-add-rule").addEventListener("click", () => addRuleRow(null));
$("#al-save").addEventListener("click", saveAlarm);
$("#al-test").addEventListener("click", () => fetch("/api/alarm/test", { method: "POST" }));

// Visibility-aware polling: fast when on screen, slow when hidden, immediate on
// reappear. In a browser tab we also tell the server to switch cadence; in the
// menu-bar popover the native app owns that signal (avoids fighting it).
let pollTimer = null;
function setActive(on) {
  if (EMBED) return;
  fetch("/api/active?on=" + (on ? 1 : 0), { method: "POST" }).catch(() => {});
}
async function tickLoop() {
  await poll();
  pollTimer = setTimeout(tickLoop, document.hidden ? HIDDEN_MS : VISIBLE_MS);
}
document.addEventListener("visibilitychange", () => {
  setActive(!document.hidden);
  if (!document.hidden) {
    clearTimeout(pollTimer);
    poll();
    pollTimer = setTimeout(tickLoop, VISIBLE_MS);
  }
});

// In the popover, report content height to the native app so it can size the
// popover to fit exactly (no scroll, no empty space).
function postHeight() {
  const mh = window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.resize;
  if (mh) mh.postMessage(Math.ceil(document.body.scrollHeight));
}

// Instant first paint from server-embedded state, then start polling.
if (EMBED) {
  document.body.classList.add("embed");
  if (window.ResizeObserver) new ResizeObserver(postHeight).observe(document.body);
}
if (window.__INITIAL_STATE__) { state = window.__INITIAL_STATE__; render(); }
setActive(!document.hidden);
tickLoop();
