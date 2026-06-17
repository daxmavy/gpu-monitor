#!/usr/bin/env python3
"""Runs ON a remote GPU host. Emits one JSON snapshot of GPU +
per-process state to stdout. Pure stdlib so it can be piped over
`ssh <host> python3 - < probe.py` with nothing installed on the server.

Process owner + start time are read from /proc (not `ps`) so containerised /
namespaced GPU jobs are attributed correctly — same source nvitop/psutil use.
"""
import json, os, pwd, subprocess, sys, time

CMD_MAX = 200  # cap command line length kept in the payload


def smi(qtype, fields):
    r = subprocess.run(
        ["nvidia-smi", f"--query-{qtype}={fields}", "--format=csv,noheader,nounits"],
        capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"nvidia-smi failed: {r.stderr.strip()}")
    return [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]


def num(v, cast=int):
    try:
        return cast(v)
    except (ValueError, TypeError):
        return None


def clk_tck():
    try:
        return os.sysconf("SC_CLK_TCK")
    except (ValueError, OSError):
        return 100


def boot_time():
    try:
        with open("/proc/stat") as f:
            for line in f:
                if line.startswith("btime"):
                    return int(line.split()[1])
    except OSError:
        pass
    return None


def proc_info(pid, btime, tck):
    """(user, start_epoch, cmd) for a pid via /proc. Robust to namespaced jobs."""
    user = "?"
    try:
        uid = os.stat(f"/proc/{pid}").st_uid
        try:
            user = pwd.getpwuid(uid).pw_name
        except KeyError:
            user = f"uid:{uid}"
    except OSError:
        return user, None, ""
    start_epoch = None
    try:
        with open(f"/proc/{pid}/stat") as f:
            data = f.read()
        # comm (field 2) may contain spaces/parens; everything after the last ')'
        # is space-separated. starttime is field 22 -> index 19 of that tail.
        tail = data[data.rfind(")") + 2:].split()
        starttime_ticks = int(tail[19])
        if btime is not None:
            start_epoch = btime + starttime_ticks / tck
    except (OSError, ValueError, IndexError):
        pass
    cmd = ""
    try:
        with open(f"/proc/{pid}/cmdline") as f:
            cmd = f.read().replace("\x00", " ").strip()
    except OSError:
        pass
    if not cmd:
        try:
            with open(f"/proc/{pid}/comm") as f:
                cmd = f.read().strip()
        except OSError:
            pass
    return user, start_epoch, cmd[:CMD_MAX]


def main():
    now = time.time()
    out = {"host": os.uname().nodename, "ts": now, "gpus": [], "error": None}
    try:
        btime, tck = boot_time(), clk_tck()
        gpus = {}
        for ln in smi("gpu", "index,name,memory.used,memory.total,"
                             "utilization.gpu,temperature.gpu,power.draw,power.limit"):
            p = [x.strip() for x in ln.split(",")]
            idx = int(p[0])
            gpus[idx] = {
                "index": idx, "name": p[1],
                "mem_used": num(p[2]), "mem_total": num(p[3]),
                "util": num(p[4]), "temp": num(p[5]),
                "power": num(p[6], float), "power_limit": num(p[7], float),
                "procs": [],
            }
        uuid2idx = {}
        for ln in smi("gpu", "index,uuid"):
            i, u = [x.strip() for x in ln.split(",")]
            uuid2idx[u] = int(i)
        for ln in smi("compute-apps", "gpu_uuid,pid,used_gpu_memory"):
            p = [x.strip() for x in ln.split(",")]
            if len(p) < 3 or p[0] not in uuid2idx:
                continue
            try:
                idx, pid, mem = uuid2idx[p[0]], int(p[1]), int(p[2])
            except (ValueError, KeyError):
                continue
            user, start_epoch, cmd = proc_info(pid, btime, tck)
            gpus[idx]["procs"].append({
                "pid": pid, "user": user, "mem": mem,
                "elapsed": (now - start_epoch) if start_epoch else None,
                "cmd": cmd,
            })
        out["gpus"] = [gpus[i] for i in sorted(gpus)]
    except Exception as e:  # noqa: BLE001 - report any failure as data, never crash
        out["error"] = str(e)
    sys.stdout.write(json.dumps(out))


if __name__ == "__main__":
    main()
