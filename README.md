# GPU Monitor

A macOS menu-bar app for the **Brains** and **Virgil** GPU servers. A small dot
sits in the menu bar; click it for a live, nvitop-style view of every GPU — type,
utilisation, memory, temperature, and who's running what — for both servers, with
no separate window to open.

## Install

1. **Download** `GPU-Monitor.dmg` and open it; drag **GPU Monitor** to Applications.
2. **First open** — because the app isn't signed by an Apple Developer account,
   macOS will block it the first time. **Right-click the app → Open → Open.**
   (Or remove the quarantine flag: `xattr -dr com.apple.quarantine "/Applications/GPU Monitor.app"`.)
3. The **first launch sets itself up** (~1 minute, needs internet once) and a
   **Setup window opens automatically**.
4. In Setup: enter your **username**, tick **which servers** you have access to
   (Brains / Virgil), connect the **VPN**, and **test SSH**. Each step has a
   *"🪄 Have Claude Code set this up for me"* button that copies a ready-to-paste
   prompt (e.g. to set up passwordless SSH) into a coding agent.
5. Done — a **● appears at the top-right of your menu bar.** Click it.

> **Stuck on the Gatekeeper step?** Paste this into Claude Code:
> *"macOS is blocking 'GPU Monitor.app' as unidentified. Remove its quarantine
> flag with `xattr -dr com.apple.quarantine "/Applications/GPU Monitor.app"` and
> open it."*

## What it does

- **Live GPU view** — one row of cards per server (no scrolling): GPU type, util
  + memory bars, temperature, and per-process **username**, **VRAM**, **runtime**,
  and command.
- **Rename people** — right-click a username in the popover and type their real
  name; it replaces that username everywhere from then on (stored locally).
- **Copy usernames** — the ⧉ button next to a name copies the raw username.
- **Availability alarms** — banner + sound when a GPU frees up: any idle GPU
  (default), free VRAM ≥ X GB, or specific types (e.g. 1×A100 + 2×H100).
- **Colour-coded icon** — 🟢 when a whole 80GB GPU is free, 🔴 when no GPU has
  >40GB free, 🟠 otherwise (⚪️ when the VPN is off). The number is idle-GPU count.
- **15-minute utilisation sparkline** on each GPU card.
- **Graceful VPN handling** — if the Oxford VPN is off, shows "VPN not on" with an
  Open-client button instead of hanging.

Right-click the menu-bar ● for **Setup…** (re-run the wizard) and **Quit**.

## Run from source (development)

Needs [`uv`](https://docs.astral.sh/uv/) and passwordless SSH to the servers.

```bash
uv sync
./start.sh            # menu-bar app (builds a dev .app and opens it)
./start.sh web        # web-only: serve the UI and open it in a browser
uv run pytest         # tests: alarm logic, edge-firing, VPN gate, name store
```

## Build the distributable

```bash
./package.sh          # -> dist/GPU Monitor.app  +  dist/GPU-Monitor.dmg
```
`package.sh` bundles the source + a copy of `uv`; the app bootstraps its own Python
environment on first launch, so the target Mac needs nothing preinstalled.

## Configuration

The setup wizard writes `~/.config/gpu-monitor/config.json`. You can also edit it by
hand or point elsewhere with `$GPUMON_CONFIG`; see `config.example.json` for the
schema (hosts as `user@host`, plus an optional `vpn` block). Tunables via env:
`GPUMON_POLL_FAST`, `GPUMON_POLL_SLOW`, `GPUMON_PORT`. Local state (renamed names,
alarm config) lives in `~/Library/Application Support/gpu-monitor/`.

## Architecture

- **`gpumon/`** — data + server: `probe.py` runs on each host via `ssh … python3 -`
  (stdlib only, nothing installed remotely); `remote.py` multiplexes SSH;
  `poller.py` polls adaptively (fast while open, slow when closed) and keeps the
  15-min history; `alarms.py`, `vpn.py`, `setup.py`, `presets.py`; `server.py`
  (FastAPI) serves the UI + a small JSON API.
- **`webui/`** — the popover UI (`index.html`) and the setup wizard (`setup.html`).
- **`macapp/menubar.py`** — PyObjC `NSStatusItem` + `NSPopover` + `WKWebView`,
  the auto-opening setup window, and the in-process server.
