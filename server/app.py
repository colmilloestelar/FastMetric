import asyncio
import hashlib
import hmac
import json
import time

from contextlib import asynccontextmanager

from fastapi import Cookie, Depends, FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import config
from .diagnostics import diagnose
from .notify import Notifier
from .schemas import Ingest
from .store import Store

app = FastAPI(title="FastMetric", docs_url=None, redoc_url=None)

store = Store()
notifier = Notifier()
notifier.bind(store)

WEB_DIR = f"{config.BASE_DIR}/web"

ADMIN_COOKIE = "fm_admin"
SESSION_DAYS = 7

OFFLINE_WATCH_INTERVAL = 30


async def watch_offline():
    while True:
        await asyncio.sleep(OFFLINE_WATCH_INTERVAL)
        try:
            threshold = config.OFFLINE_AFTER_SECONDS
            for c in store.offline_unnotified(threshold):
                minutes = int(threshold // 60)
                message = f"no heartbeat received (offline for {minutes} min)"
                client_projects = store.projects_of(c["id"])
                store.add_event(c["id"], c["name"], "critical", message)
                notifier.notify_alert(c["name"], message, "critical", projects=client_projects)
                store.mark_offline_alerted(c["id"])
        except Exception:
            continue


@asynccontextmanager
async def lifespan(app_ctx):
    task = asyncio.create_task(watch_offline())
    try:
        yield
    finally:
        task.cancel()


app = FastAPI(title="FastMetric", docs_url=None, redoc_url=None, lifespan=lifespan)


def _admin_session():
    token = store.get_token().encode()
    value = str(int(time.time()) + SESSION_DAYS * 86400)
    sig = hmac.new(token, value.encode(), hashlib.sha256).hexdigest()
    return f"{value}.{sig}"


def _check_admin(cookie: str | None):
    if not cookie or "." not in cookie:
        return False
    expire, sig = cookie.split(".", 1)
    token = store.get_token().encode()
    expected = hmac.new(token, expire.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return False
    try:
        return int(expire) > time.time()
    except ValueError:
        return False


def require_admin(cookie: str | None = Cookie(alias=ADMIN_COOKIE, default="")):
    if not _check_admin(cookie):
        raise HTTPException(status_code=401, detail="admin required")


@app.post("/api/admin/login")
def admin_login(body: dict, response: Response):
    password = body.get("password", "")
    expected = config.ADMIN_PASSWORD or "admin"
    if not hmac.compare_digest(password, expected):
        raise HTTPException(status_code=401, detail="wrong password")
    response.set_cookie(
        ADMIN_COOKIE, _admin_session(), max_age=SESSION_DAYS * 86400,
        httponly=True, samesite="lax",
    )
    return {"ok": True}


@app.post("/api/admin/logout")
def admin_logout(response: Response):
    response.delete_cookie(ADMIN_COOKIE, samesite="lax")
    return {"ok": True}


@app.get("/api/admin/check")
def admin_check(cookie: str | None = Cookie(alias=ADMIN_COOKIE, default="")):
    return {"admin": _check_admin(cookie)}


def require_token(token: str):
    if token != store.get_token():
        raise HTTPException(status_code=401, detail="invalid token")


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/ingest")
def ingest(body: Ingest):
    require_token(body.token)
    payload = body.payload.model_dump()

    name = payload["hostname"] or payload["host_ip"]
    kind = payload["kind"]
    host_ip = payload["host_ip"] or name

    client_id, was_offline = store.upsert_client(name, kind, host_ip, body.token)

    if was_offline:
        client_projects = store.projects_of(client_id)
        store.add_event(client_id, name, "info", f"client back online: {name}")
        notifier.notify_alert(name, "client is reporting again (was offline)", "info", projects=client_projects)

    previous = store.latest_snapshot(client_id)
    store.record_snapshot(client_id, payload)

    report_interval = int(store.get_setting("report_interval_seconds", "300"))

    diag = diagnose(payload, store.get_thresholds())
    level = diag["level"]
    messages = diag["messages"]

    message = "; ".join(m["message"] for m in messages) if messages else "healthy"
    if previous is not None:
        prev_diag = diagnose(previous["payload"], store.get_thresholds())
        prev_level = prev_diag["level"]
        if level != prev_level:
            level_label = "ok" if level == "ok" else "warning" if level == "warning" else "critical"
            store.add_event(client_id, name, level_label, message)
            if level != "ok":
                client_projects = store.projects_of(client_id)
                notifier.notify_alert(name, message, level, projects=client_projects)
    else:
        store.add_event(client_id, name, "info", f"client registered: {name} ({kind})")

    store.prune()
    return {"accepted": True, "report_interval_seconds": report_interval}


@app.get("/api/clients")
def list_clients():
    trends = store.snapshot_trends(limit=120)
    out = []
    for c in store.clients():
        snap = c["snapshot"]
        snapshot = snap["payload"] if snap else {}
        diag = diagnose(snapshot, store.get_thresholds()) if snap else {"level": "offline", "messages": []}
        t = trends.get(c["id"], {"cpu": [], "mem": [], "disk": []})
        out.append(
            {
                "id": c["id"],
                "name": c["name"],
                "kind": c["kind"],
                "host_ip": c["host_ip"],
                "projects": c["projects"],
                "status": c["status"],
                "last_seen": c["last_seen"],
                "created_at": c["created_at"],
                "diagnosis": diag["level"],
                "diagnosis_messages": diag["messages"],
                "snapshot_ts": snap["ts"] if snap else None,
                "cpu_percent": snapshot.get("cpu_percent") if snap else None,
                "mem_percent": snapshot.get("mem_percent") if snap else None,
                "disks": snapshot.get("disks") if snap else [],
                "trend": {"cpu": t["cpu"], "mem": t["mem"], "disk": t["disk"]},
            }
        )
    return out


@app.get("/api/clients/{client_id}")
def client_detail(client_id: int):
    clients = store.clients()
    client = next((c for c in clients if c["id"] == client_id), None)
    if client is None:
        raise HTTPException(status_code=404, detail="client not found")
    snap = client["snapshot"]
    history = store.snapshot_history(client_id)
    events = store.events(client_id=client_id, limit=200)
    diag = diagnose(snap["payload"], store.get_thresholds()) if snap else {"level": "offline", "messages": []}
    return {
        "client": {k: v for k, v in client.items() if k != "snapshot"},
        "snapshot": snap,
        "history": history,
        "events": events,
        "diagnosis": diag,
    }


@app.delete("/api/clients/{client_id}")
def delete_client(client_id: int, confirm: str, response: Response, _: None = Depends(require_admin)):
    clients = store.clients()
    client = next((c for c in clients if c["id"] == client_id), None)
    if client is None:
        raise HTTPException(status_code=404, detail="client not found")
    if confirm != client["name"]:
        raise HTTPException(status_code=400, detail="confirmation text mismatch")
    client_name = client["name"]
    store.delete_client(client_id)
    store.add_event(client_id, client_name, "info", f"client removed: {client_name}")
    notifier.notify_alert(client_name, "client removed from monitoring", "info")
    return {"deleted": True}


@app.post("/api/clients/{client_id}/projects")
def set_projects(client_id: int, body: dict, _: None = Depends(require_admin)):
    clients = store.clients()
    client = next((c for c in clients if c["id"] == client_id), None)
    if client is None:
        raise HTTPException(status_code=404, detail="client not found")
    projects = [str(p).strip() for p in body.get("projects", []) if str(p).strip()]
    store.set_projects(client_id, projects)
    return {"saved": True, "projects": projects}


@app.get("/api/project-alerts")
def get_project_alerts():
    return store.project_alerts()


@app.post("/api/project-alerts/{project}")
def save_project_alert(project: str, body: dict, _: None = Depends(require_admin)):
    email_to = str(body.get("email_to", "")).strip()
    webhooks = [w.strip() for w in body.get("webhooks", []) if w.strip()]
    store.set_project_alert(project, email_to, webhooks)
    return {"saved": True}


@app.post("/api/project-alerts/{project}/test")
def test_project_alert(project: str, _: None = Depends(require_admin)):
    notifier.test_project(project)
    return {"sent": True}


@app.get("/api/events")
def list_events(level: str | None = None, limit: int = 500):
    return store.events(level=level, limit=limit)


@app.get("/api/settings")
def get_settings():
    return {
        "token": store.get_token(),
        "retention_days": config.RETENTION_DAYS,
        "offline_after_seconds": config.OFFLINE_AFTER_SECONDS,
        "report_interval_seconds": int(store.get_setting("report_interval_seconds", "300")),
        "bell_sound": config.BELL_SOUND,
        "thresholds": store.get_thresholds(),
        **notifier.load_settings(),
    }


@app.post("/api/settings/report-interval")
def save_report_interval(body: dict, _: None = Depends(require_admin)):
    val = max(int(body.get("report_interval_seconds", 300)), 10)
    store.set_setting("report_interval_seconds", str(val))
    return {"saved": True, "report_interval_seconds": val}


@app.post("/api/settings/thresholds")
def save_thresholds(body: dict, _: None = Depends(require_admin)):
    allow = {
        "disk_warning", "disk_critical",
        "cpu_warning", "cpu_critical",
        "mem_warning", "mem_critical",
    }
    values = {k: float(body[k]) for k in allow if k in body}
    if not values:
        raise HTTPException(status_code=400, detail="no thresholds provided")
    for k, v in values.items():
        if v < 0 or v > 100:
            raise HTTPException(status_code=400, detail=f"{k} must be between 0 and 100")
    store.set_thresholds(values)
    return {"saved": True, "thresholds": store.get_thresholds()}


@app.post("/api/settings/notify")
def save_notify_settings(body: dict, _: None = Depends(require_admin)):
    s = store
    s.set_setting("email_enabled", str(body.get("email_enabled", False)).lower())
    s.set_setting("email_to", body.get("email_to", ""))
    s.set_setting("email_smtp", body.get("email_smtp", ""))
    s.set_setting("email_user", body.get("email_user", ""))
    if body.get("email_password"):
        s.set_setting("email_password", body["email_password"])
    webhooks = [w for w in body.get("webhooks", []) if w.strip()]
    s.set_setting("webhooks", json.dumps(webhooks))
    return {"saved": True}


@app.post("/api/test/email")
def test_email(_: None = Depends(require_admin)):
    notifier.test_email()
    return {"sent": True}


@app.post("/api/test/webhook")
def test_webhook(body: dict, _: None = Depends(require_admin)):
    notifier.test_webhook(body.get("url", ""))
    return {"sent": True}


app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")