#!/usr/bin/env python3
"""FastMetric test agent. Sends synthetic, configurable health payloads.

Environment:
    MS_SERVER_URL   server endpoint (required)
    MS_TOKEN        server token (required)
    MS_NAME         client name (default "sim-host")
    MS_KIND         pc, vm, container (default container)
    MS_INTERVAL     seconds between reports (default 10)
    MS_DISK_PCT     disk usage to fake, 0..100 (default 50)
    MS_CPU_PCT      cpu usage to fake, 0..100 (default 5)
    MS_MEM_PCT      memory usage to fake, 0..100 (default 30)
"""
import json
import os
import socket
import time
import urllib.request

SERVER_URL = os.getenv("MS_SERVER_URL", "").rstrip("/")
TOKEN = os.getenv("MS_TOKEN", "")
NAME = os.getenv("MS_NAME", "sim-host")
KIND = os.getenv("MS_KIND", "container")
INTERVAL = int(os.getenv("MS_INTERVAL", "10"))
DISK_PCT = float(os.getenv("MS_DISK_PCT", "50"))
CPU_PCT = float(os.getenv("MS_CPU_PCT", "5"))
MEM_PCT = float(os.getenv("MS_MEM_PCT", "30"))


def host_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "0.0.0.0"


def payload():
    return {
        "ts": time.time(),
        "hostname": NAME,
        "kind": KIND,
        "host_ip": host_ip(),
        "cpu_percent": CPU_PCT,
        "mem_percent": MEM_PCT,
        "uptime_seconds": 86400 * 5,
        "disks": [
            {
                "mount": "/",
                "total_bytes": 100 * 1024**3,
                "used_bytes": int(100 * 1024**3 * DISK_PCT / 100),
                "percent": DISK_PCT,
            }
        ],
    }


def main():
    if not SERVER_URL or not TOKEN:
        print("sim agent: MS_SERVER_URL and MS_TOKEN required")
        raise SystemExit(1)
    print(f"sim agent '{NAME}' reporting to {SERVER_URL} every {INTERVAL}s (disk {DISK_PCT}%, cpu {CPU_PCT}%)")
    while True:
        try:
            data = json.dumps({"token": TOKEN, "payload": payload()}).encode()
            req = urllib.request.Request(
                f"{SERVER_URL}/api/ingest",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10):
                pass
        except Exception as e:
            print(f"report failed: {e}")
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()