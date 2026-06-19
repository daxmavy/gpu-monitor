"""Setup-wizard backend: write the user's config and test SSH reachability."""
from __future__ import annotations

import json
import subprocess

from . import config, presets


def current() -> dict:
    """Username + selected host ids derived from the existing saved config."""
    username, selected = "", []
    for h in config.HOSTS:
        ssh = h.get("ssh", "")
        host = ssh.split("@", 1)[1] if "@" in ssh else ssh
        if "@" in ssh and not username:
            username = ssh.split("@", 1)[0]
        for k in presets.KNOWN_HOSTS:
            if k["host"] == host or k["name"] == h.get("name"):
                selected.append(k["id"])
    return {"username": username, "selected": sorted(set(selected))}


def save_config(username: str, host_ids: list[str]) -> dict:
    """Write hosts (user@host for each selected server) + the VPN block."""
    username = (username or "").strip()
    hosts = [{"name": h["name"], "ssh": f"{username}@{h['host']}"}
             for h in presets.KNOWN_HOSTS if h["id"] in host_ids]
    data = {"hosts": hosts, "vpn": presets.KNOWN_VPN}
    config.CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    config.CONFIG_FILE.write_text(json.dumps(data, indent=2) + "\n")
    config.reload()
    return data


def test_ssh(ssh_target: str) -> dict:
    """Quick, non-hanging SSH reachability + key-auth test for one host."""
    if not ssh_target or "@" not in ssh_target:
        return {"ok": False, "error": "no SSH target"}
    try:
        r = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
             "-o", "StrictHostKeyChecking=accept-new", ssh_target,
             "echo gpumon-ok; nvidia-smi -L 2>/dev/null | head -1"],
            capture_output=True, text=True, timeout=15)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timed out — VPN off or host unreachable?"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)[:200]}
    if r.returncode == 0 and "gpumon-ok" in r.stdout:
        gpu = [ln for ln in r.stdout.splitlines()
               if ln.strip() and "gpumon-ok" not in ln]
        return {"ok": True, "detail": gpu[0][:80] if gpu else "connected"}
    return {"ok": False,
            "error": (r.stderr.strip() or r.stdout.strip()
                      or f"ssh exit {r.returncode}")[:200]}
