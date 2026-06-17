"""Unit tests for the parts that are easy to get subtly wrong: alarm evaluation,
edge-triggered firing, and the name store."""
import json

from gpumon import alarms, config, names, remote, vpn
from gpumon.poller import Poller


def gpu(idx, name, used, total, util, procs=None):
    return {"index": idx, "name": name, "mem_used": used, "mem_total": total,
            "util": util, "temp": 40, "procs": procs or []}


def host(name, gpus, reachable=True, error=None):
    return {"name": name, "reachable": reachable, "error": error, "gpus": gpus}


IDLE_H100 = gpu(0, "NVIDIA H100 80GB HBM3", 1, 81559, 0)
BUSY_A100 = gpu(0, "NVIDIA A100 80GB PCIe", 78000, 81920, 100,
                [{"pid": 1, "user": "alice", "mem": 78000, "elapsed": 60, "cmd": "x"}])


# ---------- evaluate ----------
def test_idle_match():
    snap = [host("Virgil", [IDLE_H100, BUSY_A100])]
    r = alarms.evaluate(snap, {"mode": "idle"})
    assert r["matched"] is True
    assert "H100" in r["message"]


def test_idle_no_match_when_all_busy():
    snap = [host("Brains", [BUSY_A100])]
    assert alarms.evaluate(snap, {"mode": "idle"})["matched"] is False


def test_vram_threshold():
    snap = [host("Brains", [gpu(0, "A100", 40000, 81920, 100)])]  # ~41GB free
    assert alarms.evaluate(snap, {"mode": "vram", "vram_gb": 40})["matched"] is True
    assert alarms.evaluate(snap, {"mode": "vram", "vram_gb": 60})["matched"] is False


def test_specific_counts():
    snap = [host("Virgil", [gpu(0, "H100", 1, 81559, 0), gpu(1, "H100", 1, 81559, 0)]),
            host("Brains", [gpu(0, "A100", 1, 81920, 0)])]
    cfg = {"mode": "specific", "specific": [{"type": "H100", "count": 2},
                                            {"type": "A100", "count": 1}]}
    assert alarms.evaluate(snap, cfg)["matched"] is True
    cfg["specific"][0]["count"] = 3
    assert alarms.evaluate(snap, cfg)["matched"] is False


def test_host_filter():
    snap = [host("Virgil", [IDLE_H100]), host("Brains", [BUSY_A100])]
    assert alarms.evaluate(snap, {"mode": "idle", "hosts": ["Brains"]})["matched"] is False
    assert alarms.evaluate(snap, {"mode": "idle", "hosts": ["Virgil"]})["matched"] is True


def test_unreachable_host_ignored():
    snap = [host("Virgil", [], reachable=False, error="timeout")]
    assert alarms.evaluate(snap, {"mode": "idle"})["matched"] is False


# ---------- edge-triggered firing ----------
def test_edge_firing(monkeypatch):
    calls = []
    monkeypatch.setattr(alarms, "notify",
                        lambda msg, sound="Glass": (calls.append(msg) or True))
    monkeypatch.setattr(vpn, "vpn_status",
                        lambda: {"state": "connected", "detail": ""})
    monkeypatch.setattr(alarms, "load_config",
                        lambda: {**alarms.DEFAULT, "enabled": True, "mode": "idle"})

    idle = [host("Virgil", [IDLE_H100])]
    busy = [host("Virgil", [BUSY_A100])]
    seq = {"v": idle}
    monkeypatch.setattr(remote, "fetch_all", lambda hosts=None: seq["v"])

    p = Poller()
    p.poll_once(); assert len(calls) == 1          # rising edge -> fire once
    p.poll_once(); assert len(calls) == 1          # still matched -> no refire
    seq["v"] = busy
    p.poll_once(); assert len(calls) == 1          # falls -> no fire
    seq["v"] = idle
    p.poll_once(); assert len(calls) == 2          # re-armed -> fires again


def test_no_fire_when_disabled(monkeypatch):
    calls = []
    monkeypatch.setattr(alarms, "notify",
                        lambda msg, sound="Glass": (calls.append(msg) or True))
    monkeypatch.setattr(vpn, "vpn_status",
                        lambda: {"state": "connected", "detail": ""})
    monkeypatch.setattr(remote, "fetch_all", lambda hosts=None: [host("Virgil", [IDLE_H100])])
    monkeypatch.setattr(alarms, "load_config",
                        lambda: {**alarms.DEFAULT, "enabled": False})
    p = Poller()
    p.poll_once()
    assert calls == []


def test_no_probe_when_vpn_down(monkeypatch):
    probed = {"n": 0}

    def boom(hosts=None):
        probed["n"] += 1
        return []
    monkeypatch.setattr(remote, "fetch_all", boom)
    monkeypatch.setattr(vpn, "vpn_status",
                        lambda: {"state": "disconnected", "detail": "off"})
    p = Poller()
    snap = p.poll_once()
    assert probed["n"] == 0                          # never SSH when VPN is down
    assert snap["hosts"] == []
    assert snap["vpn"]["state"] == "disconnected"


# ---------- name store ----------
def test_name_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STATE_DIR", tmp_path)
    monkeypatch.setattr(config, "NAMES_FILE", tmp_path / "names.json")
    assert names.load_names() == {}
    names.set_name("jdoe", "Jane Doe")
    assert names.load_names() == {"jdoe": "Jane Doe"}
    names.set_name("jdoe", "")                        # empty clears
    assert names.load_names() == {}
    on_disk = json.loads((tmp_path / "names.json").read_text())
    assert on_disk == {}
