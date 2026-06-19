"use strict";
const $ = (s) => document.querySelector(s);
let INFO = null, username = "", selectedIds = [];

async function load() {
  INFO = await (await fetch("/api/setup/info")).json();
  $("#username").value = INFO.username || "";

  const wrap = $("#servers"); wrap.innerHTML = "";
  for (const h of INFO.hosts) {
    const checked = (INFO.selected || []).includes(h.id);
    const lab = document.createElement("label");
    lab.className = "server";
    lab.innerHTML = `<input type="checkbox" value="${h.id}" ${checked ? "checked" : ""}>
      <b>${h.name}</b> <span class="gpus">${h.gpus}</span>`;
    wrap.appendChild(lab);
  }

  const vpn = INFO.vpn || {};
  if (vpn.label) {
    $("#vpn-desc").textContent =
      `The servers are only reachable on the ${vpn.gateway || "university"} VPN (${vpn.label}).`;
    $("#open-vpn").textContent = "Open " + vpn.label;
  }

  if (INFO.configured) { $("#step-servers").classList.add("done"); applySelection(); unlock(); }
}

const currentSelection = () =>
  [...document.querySelectorAll("#servers input:checked")].map((i) => i.value);
const selectedHosts = () => INFO.hosts.filter((h) => selectedIds.includes(h.id));

function applySelection() {
  username = $("#username").value.trim();
  selectedIds = currentSelection();
  buildPrompts();
  buildSshRows();
}

function unlock() {
  ["step-vpn", "step-ssh", "step-done"].forEach((id) => $("#" + id).classList.remove("locked"));
}

async function save() {
  username = $("#username").value.trim();
  selectedIds = currentSelection();
  const st = $("#save-status");
  if (!username) { st.className = "status bad"; st.textContent = "Enter your username first."; return; }
  if (!selectedIds.length) { st.className = "status bad"; st.textContent = "Pick at least one server."; return; }
  st.className = "status"; st.textContent = "Saving…";
  try {
    await fetch("/api/setup/save", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, hosts: selectedIds }),
    });
    st.className = "status ok"; st.textContent = "Saved ✓";
    $("#step-servers").classList.add("done");
    applySelection(); unlock();
  } catch (e) { st.className = "status bad"; st.textContent = "Save failed: " + e; }
}

function buildPrompts() {
  const vpn = INFO.vpn || {};
  const hosts = selectedHosts();
  const targets = hosts.map((h) => `${username}@${h.host}`);
  $("#prompt-vpn").textContent =
`I'm on macOS and need to connect to the ${vpn.gateway || "university"} VPN before I can reach my GPU servers (${hosts.map((h) => h.host).join(", ")}). The VPN client is ${vpn.label || "Cisco Secure Client"} (Cisco AnyConnect), gateway ${vpn.gateway || "the university VPN"}. Please:
1. Check whether ${vpn.label || "Cisco Secure Client"} is installed (look in /Applications/Cisco).
2. If it's missing, help me download and install it (Oxford users: register.it.ox.ac.uk).
3. Connect it to ${vpn.gateway || "the gateway"} using my university SSO login.
4. Confirm the VPN shows as connected.`;

  $("#prompt-ssh").textContent =
`Set up passwordless (key-based) SSH from this Mac so a tool can run nvidia-smi over SSH with no password prompt. Targets: ${targets.join(", ")}.
Please:
1. If ~/.ssh/id_ed25519 doesn't exist, create a key:
   ssh-keygen -t ed25519 -C "$(whoami)@$(hostname)" -N "" -f ~/.ssh/id_ed25519
2. Authorise it on each server (I'll type my password once each):
   ${targets.map((t) => "ssh-copy-id " + t).join("\n   ")}
3. Verify each works with NO password prompt:
   ${targets.map((t) => "ssh -o BatchMode=yes " + t + " nvidia-smi -L").join("\n   ")}
I must be on the VPN first. If anything fails, diagnose, fix it, and re-verify.`;
}

function buildSshRows() {
  const wrap = $("#ssh-hosts"); wrap.innerHTML = "";
  for (const h of selectedHosts()) {
    const target = `${username}@${h.host}`;
    const row = document.createElement("div");
    row.className = "ssh-host";
    row.innerHTML = `<b>${h.name}</b> <span class="tgt">${target}</span>
      <button class="ghost small test-ssh" data-target="${target}">Test</button>
      <span class="res" data-res></span>`;
    wrap.appendChild(row);
  }
}

async function testSsh(btn) {
  const res = btn.parentElement.querySelector("[data-res]");
  res.className = "res"; res.textContent = "testing…"; btn.disabled = true;
  try {
    const d = await (await fetch("/api/setup/ssh", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ target: btn.dataset.target }),
    })).json();
    res.className = "res " + (d.ok ? "ok" : "bad");
    res.textContent = (d.ok ? "✓ " + (d.detail || "connected") : "✗ " + (d.error || "failed"));
  } catch (e) { res.className = "res bad"; res.textContent = "✗ " + e; }
  btn.disabled = false;
}

async function checkVpn() {
  const st = $("#vpn-status"); st.className = "status"; st.textContent = "checking…";
  try {
    const d = await (await fetch("/api/setup/vpn")).json();
    const cls = d.state === "connected" ? "ok" : d.state === "connecting" ? "warn" : "bad";
    const mark = d.state === "connected" ? "✓ " : d.state === "connecting" ? "… " : "✗ ";
    st.className = "status " + cls; st.textContent = mark + (d.detail || d.state);
  } catch (e) { st.className = "status bad"; st.textContent = "✗ " + e; }
}

function copyPrompt(btn) {
  const txt = $("#" + btn.dataset.target).textContent;
  const done = () => { const o = btn.textContent; btn.textContent = "Copied ✓"; btn.classList.add("copied");
    setTimeout(() => { btn.textContent = o; btn.classList.remove("copied"); }, 1400); };
  navigator.clipboard.writeText(txt).then(done).catch(() => {
    const ta = document.createElement("textarea"); ta.value = txt; document.body.appendChild(ta);
    ta.select(); try { document.execCommand("copy"); } catch (_) {} ta.remove(); done();
  });
}

function finish() {
  const mh = window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.setup;
  if (mh) mh.postMessage("done");
  else $("#finish-hint").textContent =
    "You can close this window — click the ● near the top-right of your menu bar to open GPU Monitor.";
}

$("#save").addEventListener("click", save);
$("#check-vpn").addEventListener("click", checkVpn);
$("#open-vpn").addEventListener("click", () => fetch("/api/vpn/open", { method: "POST" }));
$("#finish").addEventListener("click", finish);
$("#username").addEventListener("input", () => { if (!$("#step-ssh").classList.contains("locked")) applySelection(); });
$("#servers").addEventListener("change", () => { if (!$("#step-ssh").classList.contains("locked")) applySelection(); });
document.addEventListener("click", (e) => {
  if (e.target.classList.contains("copy-prompt")) copyPrompt(e.target);
  if (e.target.classList.contains("test-ssh")) testSsh(e.target);
});

load();
