"""Configuration.

Hosts and the (optional) VPN gate come from a JSON config file so the tool is
generic — **each user supplies their own SSH targets, including their username**
(``user@host``). Nothing site-specific is baked into the code.

Config file search order:
  1. ``$GPUMON_CONFIG``
  2. ``gpu-monitor.json`` in the repo root (gitignored)
  3. ``~/.config/gpu-monitor/config.json``

See ``config.example.json``. You MUST set your own hosts; without a config the
UI shows a "configure your hosts" message instead of GPU data.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

APP_NAME = "gpu-monitor"


def _config_file() -> Path:
    if os.environ.get("GPUMON_CONFIG"):
        return Path(os.environ["GPUMON_CONFIG"]).expanduser()
    local = Path(__file__).resolve().parent.parent / "gpu-monitor.json"
    if local.exists():
        return local
    return Path.home() / ".config" / APP_NAME / "config.json"


CONFIG_FILE = _config_file()


def _load() -> dict:
    try:
        return json.loads(CONFIG_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


_CFG = _load()


def _hosts_from_env() -> list[dict]:
    """Parse GPUMON_HOSTS="Name=user@host,Name2=user@host2" (name optional)."""
    out = []
    for part in os.environ.get("GPUMON_HOSTS", "").split(","):
        part = part.strip()
        if not part:
            continue
        if "=" in part:
            name, ssh = part.split("=", 1)
        else:
            ssh, name = part, part.split("@")[-1].split(".")[0]
        out.append({"name": name.strip(), "ssh": ssh.strip()})
    return out


# Remote GPU hosts: [{"name": "...", "ssh": "user@host"}]. From the config file,
# else the GPUMON_HOSTS env var. Empty until the user configures their own.
HOSTS = _CFG.get("hosts") or _hosts_from_env()
CONFIGURED = bool(HOSTS)

# Optional VPN gate (e.g. a corporate/university VPN required to reach the hosts).
# None -> the tool never blocks on a VPN. See vpn.py for the schema.
VPN = _CFG.get("vpn") or None

# Adaptive polling cadence (seconds): fast while the popover is open, slow when
# closed (keeps background cost low). The menu-bar app flips the active flag.
POLL_FAST = float(os.environ.get("GPUMON_POLL_FAST", "2"))
POLL_SLOW = float(os.environ.get("GPUMON_POLL_SLOW", "15"))

# SSH probe timeout (seconds) per host.
SSH_TIMEOUT = float(os.environ.get("GPUMON_SSH_TIMEOUT", "25"))

# Local HTTP bind.
HOST = os.environ.get("GPUMON_HOST", "127.0.0.1")
PORT = int(os.environ.get("GPUMON_PORT", "8765"))

# Local persistent state (username->real-name map, alarm config).
STATE_DIR = Path(os.environ.get(
    "GPUMON_STATE_DIR",
    Path.home() / "Library" / "Application Support" / APP_NAME))
NAMES_FILE = STATE_DIR / "names.json"
ALARMS_FILE = STATE_DIR / "alarms.json"

WEBUI_DIR = Path(__file__).resolve().parent.parent / "webui"
