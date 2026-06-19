"""Background poller.

Design goals: instant-feeling UI and low background cost.
- **Adaptive cadence**: polls fast while the popover is open (`active`), slow when
  closed. The menu-bar app flips `active` on show/hide. A wake Event lets an
  open-event poll immediately instead of waiting out the slow sleep.
- **History**: a 15-minute ring buffer of per-GPU utilisation (coarse ~10s
  resolution, time-stamped) so the sparklines are ready the instant the UI opens.
- Probing is skipped entirely when the VPN is down.
"""
from __future__ import annotations

import json
import threading
import time
from collections import deque

from . import alarms, config, remote, vpn


def _read_db_status() -> dict:
    """Read the thesis results-DB backup status JSON (cheap, local, no SSH)."""
    try:
        return json.loads(config.DB_STATUS_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return {}

FAST = config.POLL_FAST
SLOW = config.POLL_SLOW
HISTORY_WINDOW = 900      # seconds kept (15 min)
HISTORY_DT = 10           # min seconds between stored points (bounds size)


class Poller:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._latest: dict = {
            "ts": 0, "vpn": {"state": "undetermined", "detail": "starting…"},
            "hosts": [], "alarm": {"matched": False, "message": "", "enabled": False},
            "badge": {"color": "gray", "vpn": False, "idle": 0, "free_max_gb": 0},
            "backup": {},
        }
        self._prev_matched = False
        self._active = False
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._history: dict[str, deque] = {}

    # -- state access --
    def latest(self) -> dict:
        with self._lock:
            return dict(self._latest)

    def badge(self) -> dict:
        with self._lock:
            return dict(self._latest.get("badge") or {})

    def backup_status(self) -> dict:
        with self._lock:
            return dict(self._latest.get("backup") or {})

    def rearm(self) -> None:
        self._prev_matched = False

    def set_active(self, on: bool) -> None:
        """Called when the popover opens (True) / closes (False). Opening wakes
        the loop so it refreshes immediately."""
        self._active = bool(on)
        if on:
            self._wake.set()

    # -- lifecycle --
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="gpumon-poller",
                                        daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    # -- history --
    def _record_history(self, hosts: list[dict], now: float) -> None:
        for h in hosts:
            if not h.get("reachable"):
                continue
            for g in h.get("gpus", []):
                key = f"{h['name']}\x00{g['index']}"
                dq = self._history.setdefault(key, deque())
                if not dq or (now - dq[-1][0]) >= HISTORY_DT:
                    dq.append((round(now), int(g.get("util") or 0)))
                while dq and now - dq[0][0] > HISTORY_WINDOW:
                    dq.popleft()
                g["util_history"] = [list(p) for p in dq]

    # -- one poll --
    def poll_once(self) -> dict:
        v = vpn.vpn_status()
        connected = v["state"] == "connected"
        hosts = remote.fetch_all() if connected else []
        now = time.time()
        if connected:
            self._record_history(hosts, now)
        cfg = alarms.load_config()

        if connected and cfg.get("enabled"):
            ev = alarms.evaluate(hosts, cfg)
        else:
            ev = {"matched": False, "message": "", "gpus": []}

        fired = False
        if cfg.get("enabled") and ev["matched"] and not self._prev_matched:
            fired = alarms.notify(ev["message"], sound=cfg.get("sound", "Glass"))
        self._prev_matched = ev["matched"]

        snap = {
            "ts": now,
            "vpn": v,
            "hosts": hosts,
            "alarm": {**ev, "enabled": bool(cfg.get("enabled")),
                      "mode": cfg.get("mode"), "fired": fired},
            "badge": alarms.availability_badge(hosts, v["state"]),
            "backup": _read_db_status(),
            "active": self._active,
        }
        with self._lock:
            self._latest = snap
        return snap

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.poll_once()
            except Exception as e:  # noqa: BLE001
                with self._lock:
                    self._latest = {**self._latest, "ts": time.time(),
                                    "error": str(e)}
            interval = FAST if self._active else SLOW
            self._wake.wait(interval)
            self._wake.clear()


poller = Poller()
