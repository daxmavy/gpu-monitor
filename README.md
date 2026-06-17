# GPU Monitor

A macOS menu-bar monitor for your **remote GPU servers**. A small item sits in the
menu bar; clicking it opens a popover with nvitop-style live state — no separate
app to open. You point it at your own hosts (over SSH); it ships with no servers
baked in.

## Setup

> **You must add your own hosts and username** — nothing is hardcoded.

1. **Requirements**: macOS, [`uv`](https://docs.astral.sh/uv/), and **passwordless
   SSH** (key-based) to each GPU server. The servers just need `nvidia-smi` and
   `python3` (stdlib only — nothing is installed on them).
2. **Install deps**: `uv sync`
3. **Configure your hosts** — copy the example and edit it:
   ```bash
   mkdir -p ~/.config/gpu-monitor
   cp config.example.json ~/.config/gpu-monitor/config.json
   # edit it: set each host's "ssh" to your own user@host
   ```
   ```json
   {
     "hosts": [
       { "name": "Server1", "ssh": "yourusername@gpu1.example.edu" },
       { "name": "Server2", "ssh": "yourusername@gpu2.example.edu" }
     ]
   }
   ```
   The config is searched at `$GPUMON_CONFIG`, then `./gpu-monitor.json` (gitignored),
   then `~/.config/gpu-monitor/config.json`. You can instead set
   `GPUMON_HOSTS="Server1=you@gpu1.example.edu,Server2=you@gpu2.example.edu"`.
4. **Run**: `./start.sh`

If the servers sit behind a VPN, add an optional `"vpn"` block (see
`config.example.json`); only Cisco Secure Client is supported. With no `"vpn"`
block the tool never blocks on a VPN.

## Run

```bash
./start.sh            # menu-bar app (default) — a "● N" item appears top-right
./start.sh web        # web-only: serve the UI and open it in a browser
```

The menu-bar app starts its own local server (`127.0.0.1:8765`), so `./start.sh`
is all you need. Left-click the menu-bar item to open the popover; right-click for
a Quit menu.

> The menu-bar item must run in the GUI session — `start.sh` launches it as
> `dist/GPU Monitor.app` via `open` (built by `build_app.sh`). To start it at
> login, see [`macapp/gpumonitor.plist.template`](macapp/gpumonitor.plist.template).

## Features

- **Live feed from your servers** over SSH: GPU type (A100 / L40S / H100 / …),
  utilisation, memory used/free, temperature, and per-process **username**,
  **VRAM**, **runtime**, and command. Hosts are probed concurrently and laid out
  one row of GPU cards per host (no scrolling).
- **15-minute utilisation history** as a tiny sparkline on each GPU card.
- **Colour-coded menu-bar icon**: 🟢 when an 80GB-class GPU is completely free,
  🔴 when no GPU has more than 40GB free, 🟠 otherwise (⚪️ grey when a configured
  VPN is off). The number is the count of idle GPUs.
- **Usernames**: each process shows the owner. A **copy** button copies the raw
  username. **Right-click a name** to type/paste the person's real name — it
  replaces the username everywhere from then on (stored locally in `names.json`).
- **Optional VPN gate**: if configured and the VPN is off, shows "VPN not on" with
  an **Open VPN client** button, instead of hanging trying to reach the servers.
- **Alarms** (macOS banner + sound, fired once on the rising edge):
  - **any GPU becomes fully idle** (default),
  - **free VRAM ≥ X GB**,
  - **specific GPUs become idle** (e.g. 1×A100 + 2×H100),
  - scoped to any host or all.

## Performance (low latency, low background cost)

- **Instant open**: the popover's webview stays warm and the server **embeds the
  latest snapshot into the HTML** (`window.__INITIAL_STATE__`), so the UI paints
  with data on open — no fetch wait, no spinner. The popover auto-sizes to content.
- **Warm SSH**: a detached connection-multiplexing master per host means each
  probe reuses one connection (~0.2s) instead of a fresh ~1.5s handshake.
- **Adaptive polling**: fast (2s) only while the popover is open; slow (15s) when
  closed. So the background cost is one light SSH probe per host every 15s plus a
  couple of idle multiplex sockets. Tunable via `GPUMON_POLL_FAST` / `GPUMON_POLL_SLOW`.

## Architecture

**Data (`gpumon/`)**
- `probe.py` — runs *on* a server via `ssh <host> python3 -` (stdlib only); emits
  one JSON snapshot of GPUs + processes. Owner/runtime come from `/proc` so
  containerised jobs are attributed correctly.
- `remote.py` — pipes the probe over SSH to all hosts concurrently (multiplexed);
  failures become `reachable:false` instead of hanging.
- `config.py` — loads hosts + optional VPN from your JSON config.
- `vpn.py` — optional VPN-state check (+ routing-table fallback); opens the client.
- `alarms.py` — alarm config, evaluation, and `osascript` notification.
- `poller.py` — background loop: VPN → probe → evaluate alarms (edge-triggered) →
  cache snapshot + 15-min history.
- `server.py` — FastAPI: serves the web UI and a small JSON API.

**UI (`webui/`)** — single HTML/CSS/JS app styled as a menu-bar dropdown.

**Native wrapper (`macapp/menubar.py`)** — PyObjC `NSStatusItem` + `NSPopover` +
`WKWebView` hosting the same web UI.

Local state (renamed names, alarm config) lives in
`~/Library/Application Support/gpu-monitor/`.

## Tests

```bash
uv run pytest        # alarm evaluation, edge-triggered firing, VPN gate, name store
```
