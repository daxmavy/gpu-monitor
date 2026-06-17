"""Optional VPN-state detection — independent of the GPU servers (never contacts
them), so "VPN is off" stays distinct from "server unreachable".

Active only when a VPN is configured (``config.VPN``). Schema::

    "vpn": {
        "type": "cisco",                                   # only type supported
        "binary": "/opt/cisco/secureclient/bin/vpn",       # client CLI (status)
        "app": "/Applications/Cisco/Cisco Secure Client.app",  # launched by button
        "network": "10.0",                                 # internal prefix (route fallback)
        "label": "Cisco Secure Client"                     # button label
    }

With no VPN configured the tool never blocks on a VPN (always "connected").
"""
from __future__ import annotations

import os
import subprocess

from . import config


def vpn_status() -> dict:
    """Return {"state": connected|disconnected|connecting|undetermined, "detail"}."""
    vpn = config.VPN
    if not vpn:
        return {"state": "connected", "detail": "no VPN configured"}
    if vpn.get("type", "cisco") == "cisco":
        return _cisco_status(vpn)
    return {"state": "connected", "detail": f"unknown VPN type: {vpn.get('type')}"}


def _cisco_status(vpn: dict) -> dict:
    bin_ = vpn.get("binary", "/opt/cisco/secureclient/bin/vpn")
    if os.path.exists(bin_) and os.access(bin_, os.X_OK):
        try:
            out = subprocess.run([bin_, "status"], capture_output=True,
                                 text=True, timeout=8).stdout
        except Exception:  # noqa: BLE001
            out = ""
        notice, state = "", ""
        for line in out.splitlines():
            low = line.lower()
            i = low.find("notice:")
            if i != -1:
                notice = line[i + len("notice:"):].strip()
            i = low.find("state:")
            if i != -1 and "unknown" not in low:
                state = line[i + len("state:"):].strip()
        s = state.lower()
        if s.startswith("connected"):
            return {"state": "connected", "detail": notice or "connected"}
        if s.startswith("connecting") or s.startswith("reconnecting"):
            return {"state": "connecting", "detail": notice or "in progress"}
        if s.startswith("disconnected"):
            return {"state": "disconnected", "detail": notice or "not connected"}

    # Fallback: a live VPN installs a route into the internal range via utun.
    net = vpn.get("network")
    if net:
        try:
            rt = subprocess.run(["netstat", "-rn", "-f", "inet"],
                                capture_output=True, text=True, timeout=5).stdout
            for line in rt.splitlines():
                parts = line.split()
                if parts and parts[0].startswith(net + ".") \
                        and parts[-1].startswith("utun"):
                    return {"state": "connected", "detail": f"route via {parts[-1]}"}
        except Exception:  # noqa: BLE001
            pass
    return {"state": "undetermined", "detail": "cannot determine VPN state"}


def open_vpn_client() -> dict:
    """Launch the configured VPN client app so the user can connect."""
    app = (config.VPN or {}).get("app")
    if not app:
        return {"ok": False, "error": "no VPN client configured"}
    try:
        subprocess.run(["open", app], check=True, capture_output=True,
                       text=True, timeout=10)
        return {"ok": True}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}
