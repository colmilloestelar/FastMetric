DEFAULT_THRESHOLDS = {
    "disk_warning": 90,
    "disk_critical": 98,
    "cpu_warning": 90,
    "cpu_critical": 95,
    "mem_warning": 90,
    "mem_critical": 95,
}


def _disks(payload):
    return payload.get("disks", []) or []


def _dict_get(d, keys, default=0):
    for k in keys:
        if isinstance(d, dict) and k in d:
            return d.get(k)
    return default


def check_disk(payload, t):
    level = "ok"
    message = None
    for d in _disks(payload):
        pct = _dict_get(d, ["percent", "usage_percent", "used_percent"], 0)
        mount = d.get("mount", d.get("device", "?"))
        if pct >= t["disk_critical"]:
            level = "critical"
            message = f"disk {mount} at {pct}% (critical threshold {t['disk_critical']}%)"
            break
        if pct >= t["disk_warning"]:
            level = "warning"
            message = f"disk {mount} at {pct}% (threshold {t['disk_warning']}%)"
            break
    return level, message


def check_cpu(payload, t):
    pct = _dict_get(payload, ["cpu_percent", "cpu"], 0)
    if pct >= t["cpu_critical"]:
        return "critical", f"CPU at {pct}% (critical threshold {t['cpu_critical']}%)"
    if pct >= t["cpu_warning"]:
        return "warning", f"CPU at {pct}% (threshold {t['cpu_warning']}%)"
    return "ok", None


def check_mem(payload, t):
    pct = _dict_get(payload, ["mem_percent", "memory_percent"], 0)
    if pct >= t["mem_critical"]:
        return "critical", f"memory at {pct}% (critical threshold {t['mem_critical']}%)"
    if pct >= t["mem_warning"]:
        return "warning", f"memory at {pct}% (threshold {t['mem_warning']}%)"
    return "ok", None


def diagnose(payload, thresholds=None):
    t = thresholds or DEFAULT_THRESHOLDS
    results = []
    for check in (check_disk, check_cpu, check_mem):
        level, message = check(payload, t)
        if message:
            results.append({"level": level, "message": message})
    if not results:
        return {"level": "ok", "messages": []}
    worst = max(r["level"] for r in results)
    return {"level": worst, "messages": results}