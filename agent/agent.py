#!/usr/bin/env python3
"""FastMetric agent.

Reports machine health to a FastMetric endpoint on Linux and Windows.
Uses only the Python standard library.

Configuration (env or agent.conf file next to this script):
    MS_SERVER_URL   e.g. http://10.0.0.5:8456
    MS_TOKEN        the server token
    MS_INTERVAL     seconds between reports (default 300)
    MS_KIND         pc, vm, container, other (default pc)
"""
import json
import os
import platform
import subprocess
import sys
import time
import urllib.request

MYDIR = os.path.dirname(os.path.abspath(__file__))
IS_WINDOWS = platform.system() == "Windows"


def load_config_file():
    path = os.path.join(MYDIR, "agent.conf")
    cfg = {}
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    cfg[k.strip()] = v.strip()
    return cfg


CFG = load_config_file()


def env_or_cfg(key, default=None):
    return os.getenv(key) or CFG.get(key) or default


SERVER_URL = env_or_cfg("MS_SERVER_URL", "").rstrip("/")
TOKEN = env_or_cfg("MS_TOKEN", "")
INTERVAL = int(env_or_cfg("MS_INTERVAL", "300"))
KIND = env_or_cfg("MS_KIND", "pc")


def _run(cmd):
    try:
        return subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
        ).stdout
    except Exception:
        return ""


def _linux_cpu():
    try:
        with open("/proc/stat") as f:
            first = f.readline().split()[1:]
        time.sleep(0.3)
        with open("/proc/stat") as f:
            second = f.readline().split()[1:]
        n1 = [int(x) for x in first]
        n2 = [int(x) for x in second]
        d_idle = n2[3] - n1[3]
        d_total = sum(n2) - sum(n1)
        if d_total <= 0:
            return 0.0
        return round((1 - d_idle / d_total) * 100, 1)
    except Exception:
        return 0.0


def _linux_mem():
    try:
        with open("/proc/meminfo") as f:
            vals = {}
            for line in f.read().splitlines():
                parts = line.split(":")
                if len(parts) == 2:
                    vals[parts[0]] = int(parts[1].strip().split()[0])
        total = vals.get("MemTotal", 0)
        free = vals.get("MemFree", 0) + vals.get("Buffers", 0) + vals.get("Cached", 0)
        used = total - free
        return round(used / total * 100, 1) if total else 0.0
    except Exception:
        return 0.0


def _linux_uptime():
    try:
        with open("/proc/uptime") as f:
            return int(float(f.read().split()[0]))
    except Exception:
        return int(time.time())


def _windows_cpu():
    out = _run("powershell -NoProfile -Command \"(Get-CimInstance Win32_Processor).LoadPercentage\"")
    try:
        return round(float(out.strip().splitlines()[-1]), 1)
    except Exception:
        return 0.0


def _windows_mem():
    out = _run(
        "powershell -NoProfile -Command \"$m=Get-CimInstance Win32_OperatingSystem; "
        "[math]::Round(($m.TotalVisibleMemorySize-$m.FreePhysicalMemory)/$m.TotalVisibleMemorySize*100,1)."
        "ToString([System.Globalization.CultureInfo]::InvariantCulture)\""
    )
    try:
        return round(float(out.strip().splitlines()[-1]), 1)
    except Exception:
        return 0.0


def _windows_uptime():
    out = _run(
        "powershell -NoProfile -Command \"$m=Get-CimInstance Win32_OperatingSystem; "
        "[int](($m.LocalDateTime)-($m.LastBootUpTime)).TotalSeconds\""
    )
    try:
        return int(float(out.strip().splitlines()[-1]))
    except Exception:
        return 0


def _linux_disks():
    out = []
    try:
        import shutil

        mounts = []
        try:
            for l in _run("df -P").splitlines()[1:]:
                mounts.append(l.split()[5])
        except Exception:
            mounts = ["/", "/home", "/var", "/tmp"]
        for p in mounts[:6]:
            try:
                usage = shutil.disk_usage(p)
                out.append(
                    {
                        "mount": p,
                        "total_bytes": usage.total,
                        "used_bytes": usage.used,
                        "percent": round(usage.used / usage.total * 100, 1) if usage.total else 0,
                    }
                )
            except Exception:
                pass
    except Exception:
        pass
    return out


def _windows_disks():
    out = _run(
        "powershell -NoProfile -Command \"Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=3' | "
        "ForEach-Object { Write-Output ($_.DeviceID+'|'+$_.Size+'|'+$_.FreeSpace) }\""
    )
    disks = []
    for line in out.splitlines():
        parts = line.strip().split("|")
        if len(parts) != 3:
            continue
        try:
            dev, size, free = parts[0], int(parts[1]), int(parts[2])
        except Exception:
            continue
        total = size or 1
        used = total - free
        disks.append(
            {
                "mount": dev,
                "total_bytes": total,
                "used_bytes": used,
                "percent": round(used / total * 100, 1),
            }
        )
    return disks


def host_ip():
    try:
        import socket

        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return ""


def hostname():
    return os.environ.get("COMPUTERNAME") or getattr(platform, "node", lambda: "unknown")()


def collect_payload():
    if IS_WINDOWS:
        return {
            "ts": time.time(),
            "hostname": hostname(),
            "kind": KIND,
            "host_ip": host_ip(),
            "cpu_percent": _windows_cpu(),
            "mem_percent": _windows_mem(),
            "uptime_seconds": _windows_uptime(),
            "disks": _windows_disks(),
        }
    return {
        "ts": time.time(),
        "hostname": hostname(),
        "kind": KIND,
        "host_ip": host_ip(),
        "cpu_percent": _linux_cpu(),
        "mem_percent": _linux_mem(),
        "uptime_seconds": _linux_uptime(),
        "disks": _linux_disks(),
    }


def send(payload):
    url = f"{SERVER_URL}/api/ingest"
    data = json.dumps({"token": TOKEN, "payload": payload}).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        body = resp.read()
    try:
        return float(json.loads(body).get("report_interval_seconds", INTERVAL))
    except Exception:
        return INTERVAL


def main():
    global INTERVAL
    if not SERVER_URL or not TOKEN:
        print("FastMetric agent error: MS_SERVER_URL and MS_TOKEN are required")
        sys.exit(1)
    once = "--once" in sys.argv or os.getenv("MS_ONCE") == "1"
    if once:
        try:
            payload = collect_payload()
            send(payload)
        except Exception as e:
            print(f"FastMetric agent report failed: {e}")
            sys.exit(2)
        return
    print(f"FastMetric agent started. Reporting to {SERVER_URL} every {INTERVAL}s")
    while True:
        try:
            payload = collect_payload()
            interval = send(payload)
            if interval and interval != INTERVAL:
                INTERVAL = interval
                print(f"FastMetric agent interval updated to {INTERVAL}s")
        except Exception as e:
            print(f"FastMetric agent report failed: {e}")
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()