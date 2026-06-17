"""Persistent username -> real-name map (small, <300 entries). JSON on disk."""
from __future__ import annotations

import json
import threading

from . import config

_lock = threading.Lock()


def load_names() -> dict[str, str]:
    try:
        with open(config.NAMES_FILE) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def set_name(username: str, real: str | None) -> dict[str, str]:
    """Set (or clear, if `real` is empty/None) the display name for a username."""
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    with _lock:
        d = load_names()
        if real and real.strip():
            d[username] = real.strip()
        else:
            d.pop(username, None)
        tmp = config.NAMES_FILE.with_suffix(".json.tmp")
        with open(tmp, "w") as f:
            json.dump(d, f, indent=2, sort_keys=True)
        tmp.replace(config.NAMES_FILE)
    return d
