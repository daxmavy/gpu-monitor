"""Fetch GPU snapshots from remote hosts by piping probe.py over SSH.

No agent/install on the server: `ssh <host> python3 -` reads the probe script on
stdin and prints JSON. Hosts are probed concurrently so one slow/unreachable box
never holds up the other.

Latency: a persistent, **detached** multiplex master is opened per host so each
probe reuses one warm connection (~0.2s instead of a ~1.5s handshake). The master
is detached (its own DEVNULL streams) and the per-probe `ssh` commands carry NO
ControlPersist — otherwise a backgrounded master inherits the captured stdout
pipe and `subprocess.run` blocks until the persist timeout.
"""
from __future__ import annotations

import concurrent.futures
import json
import os
import subprocess
import threading
import time
from pathlib import Path

from . import config

PROBE = Path(__file__).resolve().parent / "probe.py"

SSH_BASE = ["-o", "ConnectTimeout=10", "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=accept-new"]
_CM_PATH = os.path.expanduser("~/.ssh/gpumon-cm-%h")
CM_OPTS = ["-o", "ControlMaster=auto", "-o", f"ControlPath={_CM_PATH}"]
_master_lock = threading.Lock()


def _probe_script() -> str:
    return PROBE.read_text()


def _master_alive(target: str) -> bool:
    try:
        return subprocess.run(["ssh", *SSH_BASE, *CM_OPTS, "-O", "check", target],
                              capture_output=True, timeout=5).returncode == 0
    except Exception:  # noqa: BLE001
        return False


def ensure_master(target: str) -> None:
    """Best-effort: open a persistent, detached multiplex master for `target` so
    later probes reuse it. Detached streams (DEVNULL) keep it from ever holding a
    captured pipe. Failures are ignored — probes then just connect per-poll."""
    with _master_lock:
        if _master_alive(target):
            return
        try:
            subprocess.Popen(
                ["ssh", *SSH_BASE, *CM_OPTS, "-o", "ControlPersist=180",
                 "-N", "-f", target],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL)
        except Exception:  # noqa: BLE001
            return
        for _ in range(15):                 # wait up to ~3s for the socket
            if _master_alive(target):
                return
            time.sleep(0.2)


def fetch_host(host: dict) -> dict:
    """Probe one host. Always returns a dict; failures become `reachable=False`."""
    base = {"name": host["name"], "ssh": host["ssh"], "gpus": []}
    ensure_master(host["ssh"])
    try:
        r = subprocess.run(
            ["ssh", *SSH_BASE, *CM_OPTS, host["ssh"], "python3 -"],
            input=_probe_script(), capture_output=True, text=True,
            timeout=config.SSH_TIMEOUT)
    except subprocess.TimeoutExpired:
        return {**base, "reachable": False, "error": "ssh timeout"}
    except Exception as e:  # noqa: BLE001
        return {**base, "reachable": False, "error": str(e)[:300]}
    if r.returncode != 0:
        msg = (r.stderr.strip() or f"ssh exit {r.returncode}")[:300]
        return {**base, "reachable": False, "error": msg}
    try:
        data = json.loads(r.stdout)
    except json.JSONDecodeError:
        return {**base, "reachable": False,
                "error": ("bad probe output: " + r.stdout.strip()[:200])}
    data.update(name=host["name"], ssh=host["ssh"], reachable=True)
    data.setdefault("gpus", [])
    return data


def fetch_all(hosts: list[dict] | None = None) -> list[dict]:
    hosts = hosts or config.HOSTS
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(hosts))) as ex:
        return list(ex.map(fetch_host, hosts))
