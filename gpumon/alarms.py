"""Alarm configuration, evaluation against a snapshot, and macOS notification.

Three trigger modes:
  - "idle":     any GPU on a watched host becomes fully idle (no process, ~0 mem,
                ~0 util).  [default]
  - "vram":     any GPU has >= `vram_gb` GB of FREE VRAM (even if lightly shared).
  - "specific": enough fully-idle GPUs of each requested kind, e.g. 1×A100 + 2×H100.

Firing is edge-triggered by the poller: a single banner+sound when the condition
becomes true, re-armed once it goes false again.
"""
from __future__ import annotations

import json
import subprocess
import threading

from . import config

_lock = threading.Lock()

DEFAULT = {
    "enabled": False,
    "mode": "idle",          # idle | vram | specific
    "vram_gb": 40,
    "specific": [],          # [{"type": "A100", "count": 1}, ...]
    "hosts": [],             # [] = all hosts
    "sound": "Glass",
}

# A GPU is "fully idle" if nothing is running on it. Tolerances catch
# containerised jobs whose processes don't appear in nvidia-smi's list.
IDLE_MEM_MIB = 1500
IDLE_UTIL_PCT = 5


def load_config() -> dict:
    try:
        with open(config.ALARMS_FILE) as f:
            data = json.load(f)
        return {**DEFAULT, **data} if isinstance(data, dict) else dict(DEFAULT)
    except (OSError, json.JSONDecodeError):
        return dict(DEFAULT)


def save_config(cfg: dict) -> dict:
    merged = {**DEFAULT, **(cfg or {})}
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    with _lock:
        tmp = config.ALARMS_FILE.with_suffix(".json.tmp")
        with open(tmp, "w") as f:
            json.dump(merged, f, indent=2)
        tmp.replace(config.ALARMS_FILE)
    return merged


def gpu_type(name: str) -> str:
    """Short label for a GPU model: A100 / L40S / H100 / ... ."""
    n = (name or "").upper()
    for tag in ("A100", "L40S", "H100", "A40", "A6000", "V100", "L4", "RTX"):
        if tag in n:
            return tag
    return (name or "GPU").replace("NVIDIA ", "").split()[0]


def is_idle(g: dict) -> bool:
    if g.get("procs"):
        return False
    return (g.get("mem_used") or 0) <= IDLE_MEM_MIB \
        and (g.get("util") or 0) <= IDLE_UTIL_PCT


def free_mib(g: dict) -> int:
    return (g.get("mem_total") or 0) - (g.get("mem_used") or 0)


# Menu-bar icon thresholds (MiB). An 80GB-class GPU is >= BIG_GPU_MIB total;
# "more than 40GB available" is free > GREEN/ORANGE/RED cutoffs.
BIG_GPU_MIB = 80000
RED_FREE_MIB = 40 * 1024


def availability_badge(snapshot: list[dict], vpn_state: str) -> dict:
    """Colour for the menu-bar icon:
      green  — at least one 80GB-class GPU is completely free,
      red    — no GPU has more than 40GB free,
      orange — otherwise.
    Returns {color, vpn, idle, free_max_gb}."""
    if vpn_state != "connected":
        return {"color": "gray", "vpn": False, "idle": 0, "free_max_gb": 0}
    gpus = [g for h in snapshot if h.get("reachable") for g in h.get("gpus", [])]
    if not gpus:
        return {"color": "gray", "vpn": True, "idle": 0, "free_max_gb": 0}
    idle = sum(1 for g in gpus if is_idle(g))
    free_max = max(free_mib(g) for g in gpus)
    big_free = any(is_idle(g) and (g.get("mem_total") or 0) >= BIG_GPU_MIB
                   for g in gpus)
    if big_free:
        color = "green"
    elif free_max <= RED_FREE_MIB:
        color = "red"
    else:
        color = "orange"
    return {"color": color, "vpn": True, "idle": idle,
            "free_max_gb": round(free_max / 1024, 1)}


def _watched_gpus(snapshot: list[dict], cfg: dict):
    """Yield (host_name, gpu) for hosts the alarm watches (reachable only)."""
    want = set(cfg.get("hosts") or [])
    for h in snapshot:
        if not h.get("reachable"):
            continue
        if want and h["name"] not in want:
            continue
        for g in h.get("gpus", []):
            yield h["name"], g


def evaluate(snapshot: list[dict], cfg: dict) -> dict:
    """Return {"matched": bool, "message": str, "gpus": [labels]}."""
    cfg = {**DEFAULT, **(cfg or {})}
    mode = cfg.get("mode", "idle")
    pairs = list(_watched_gpus(snapshot, cfg))

    if mode == "vram":
        thresh = int(cfg.get("vram_gb", 40)) * 1024
        hits = [(hn, g) for hn, g in pairs if free_mib(g) >= thresh]
        labels = [f"{hn} GPU{g['index']} ({free_mib(g)//1024}GB free)"
                  for hn, g in hits]
        return {
            "matched": bool(hits),
            "message": (f"{len(hits)} GPU(s) with ≥{cfg['vram_gb']}GB free: "
                        + ", ".join(labels)) if hits else "",
            "gpus": labels,
        }

    idle = [(hn, g) for hn, g in pairs if is_idle(g)]

    if mode == "specific":
        rules = cfg.get("specific") or []
        by_type: dict[str, int] = {}
        for _hn, g in idle:
            by_type[gpu_type(g["name"])] = by_type.get(gpu_type(g["name"]), 0) + 1
        ok = bool(rules) and all(
            by_type.get(r["type"].upper(), 0) >= int(r.get("count", 1))
            for r in rules)
        want = " + ".join(f"{r.get('count', 1)}×{r['type']}" for r in rules)
        have = ", ".join(f"{v}×{k}" for k, v in sorted(by_type.items())) or "none"
        return {
            "matched": ok,
            "message": f"Requested {want} now free (idle: {have})" if ok else "",
            "gpus": [f"{hn} GPU{g['index']} {gpu_type(g['name'])}"
                     for hn, g in idle],
        }

    # default: idle
    labels = [f"{hn} GPU{g['index']} {gpu_type(g['name'])}" for hn, g in idle]
    return {
        "matched": bool(idle),
        "message": (f"{len(idle)} GPU(s) now fully idle: " + ", ".join(labels))
                   if idle else "",
        "gpus": labels,
    }


def notify(message: str, title: str = "GPU Monitor", sound: str = "Glass") -> bool:
    """Fire a macOS notification banner (+ sound). Returns True on success."""
    def esc(s: str) -> str:
        return s.replace("\\", "\\\\").replace('"', '\\"')
    script = (f'display notification "{esc(message)}" with title "{esc(title)}"'
              f' sound name "{esc(sound or "Glass")}"')
    try:
        subprocess.run(["osascript", "-e", script], check=True,
                       capture_output=True, text=True, timeout=10)
        return True
    except Exception:  # noqa: BLE001
        return False
