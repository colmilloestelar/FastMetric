import json
import os
import secrets
import sqlite3
import time
from contextlib import contextmanager

from . import config
from .diagnostics import DEFAULT_THRESHOLDS


class Store:
    def __init__(self, path=None):
        self.path = path or config.DB_PATH
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self._init()

    def connect(self):
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")
        return con

    def _init(self):
        with self.connect() as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS clients (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    host_ip TEXT NOT NULL,
                    token TEXT NOT NULL,
                    project TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    last_seen REAL,
                    last_error TEXT,
                    created_at REAL,
                    offline_alerted INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            con.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_clients_status ON clients(status)
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    client_id INTEGER,
                    client_name TEXT,
                    ts REAL,
                    level TEXT,
                    message TEXT
                )
                """
            )
            con.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts)
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    client_id INTEGER,
                    ts REAL,
                    payload TEXT
                )
                """
            )
            con.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_snapshots_client ON snapshots(client_id, ts)
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS project_alerts (
                    project TEXT PRIMARY KEY,
                    email_to TEXT NOT NULL DEFAULT '',
                    webhooks TEXT NOT NULL DEFAULT '[]'
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS client_projects (
                    client_id INTEGER NOT NULL,
                    project TEXT NOT NULL,
                    PRIMARY KEY (client_id, project)
                )
                """
            )
            con.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_client_projects_project ON client_projects(project)
                """
            )
            con.execute(
                """
                INSERT OR IGNORE INTO client_projects(client_id, project)
                SELECT id, project FROM clients WHERE project != ''
                """
            )

        with self.connect() as con:
            cols = [r["name"] for r in con.execute("PRAGMA table_info(clients)").fetchall()]
            if "project" not in cols:
                con.execute("ALTER TABLE clients ADD COLUMN project TEXT NOT NULL DEFAULT ''")
            if "offline_alerted" not in cols:
                con.execute("ALTER TABLE clients ADD COLUMN offline_alerted INTEGER NOT NULL DEFAULT 0")

    def get_setting(self, key, default=None):
        with self.connect() as con:
            row = con.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        if row is None:
            return default
        return row["value"]

    def set_setting(self, key, value):
        with self.connect() as con:
            con.execute(
                "INSERT INTO settings(key,value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, str(value)),
            )

    def get_thresholds(self):
        out = dict(DEFAULT_THRESHOLDS)
        for key in DEFAULT_THRESHOLDS:
            v = self.get_setting(key)
            if v is not None:
                try:
                    out[key] = float(v)
                except ValueError:
                    pass
        return out

    def set_thresholds(self, values):
        for key in DEFAULT_THRESHOLDS:
            if key in values:
                try:
                    v = float(values[key])
                except (TypeError, ValueError):
                    continue
                self.set_setting(key, v)

    def get_token(self):
        token = self.get_setting("server_token")
        if not token:
            token = config.TOKEN_ENV or secrets.token_urlsafe(24)
            self.set_setting("server_token", token)
        return token

    def upsert_client(self, name, kind, host_ip, token):
        now = time.time()
        with self.connect() as con:
            row = con.execute(
                "SELECT id, offline_alerted FROM clients WHERE name=?", (name,)
            ).fetchone()
            if row:
                con.execute(
                    "UPDATE clients SET token=?, host_ip=?, status=?, last_seen=?, "
                    "offline_alerted=0 WHERE id=?",
                    (token, host_ip, "online", now, row["id"]),
                )
                return row["id"], bool(row["offline_alerted"])
            con.execute(
                "INSERT INTO clients(name,kind,host_ip,token,project,status,last_seen,created_at) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (name, kind, host_ip, token, "", "online", now, now),
            )
            return con.execute("SELECT last_insert_rowid()").fetchone()[0], False

    def set_projects(self, client_id, projects):
        with self.connect() as con:
            con.execute("DELETE FROM client_projects WHERE client_id=?", (client_id,))
            for p in projects:
                con.execute(
                    "INSERT INTO client_projects(client_id,project) VALUES(?,?)",
                    (client_id, p),
                )

    def projects_of(self, client_id):
        with self.connect() as con:
            rows = con.execute(
                "SELECT project FROM client_projects WHERE client_id=? ORDER BY project",
                (client_id,),
            ).fetchall()
        return [r["project"] for r in rows]

    def mark_offline_alerted(self, client_id):
        with self.connect() as con:
            con.execute(
                "UPDATE clients SET offline_alerted=1 WHERE id=?", (client_id,)
            )

    def clear_offline_alerted(self, client_id):
        with self.connect() as con:
            con.execute(
                "UPDATE clients SET offline_alerted=0 WHERE id=?", (client_id,)
            )

    def offline_unnotified(self, threshold_seconds):
        cutoff = time.time() - threshold_seconds
        with self.connect() as con:
            rows = con.execute(
                "SELECT id, name FROM clients "
                "WHERE offline_alerted=0 AND (last_seen IS NULL OR last_seen < ?)",
                (cutoff,),
            ).fetchall()
        return [{"id": r["id"], "name": r["name"]} for r in rows]

    def set_project(self, client_id, project):
        with self.connect() as con:
            con.execute(
                "UPDATE clients SET project=? WHERE id=?", (project, client_id)
            )

    def project_of(self, client_id):
        with self.connect() as con:
            row = con.execute(
                "SELECT project FROM clients WHERE id=?", (client_id,)
            ).fetchone()
        return row["project"] if row else ""

    def project_alerts(self):
        with self.connect() as con:
            rows = con.execute("SELECT * FROM project_alerts").fetchall()
        out = {}
        for r in rows:
            d = dict(r)
            out[d["project"]] = {
                "email_to": d["email_to"],
                "webhooks": json.loads(d["webhooks"]),
            }
        return out

    def set_project_alert(self, project, email_to, webhooks):
        with self.connect() as con:
            con.execute(
                "INSERT INTO project_alerts(project,email_to,webhooks) VALUES(?,?,?) "
                "ON CONFLICT(project) DO UPDATE SET "
                "email_to=excluded.email_to, webhooks=excluded.webhooks",
                (project, email_to, json.dumps(webhooks)),
            )

    def clients(self):
        now = time.time()
        offline_after = config.OFFLINE_AFTER_SECONDS
        with self.connect() as con:
            rows = con.execute("SELECT * FROM clients").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["snapshot"] = self.latest_snapshot(d["id"])
            d["projects"] = self.projects_of(d["id"])
            if d["last_seen"] is None:
                d["status"] = "offline"
            elif now - d["last_seen"] > offline_after:
                d["status"] = "offline"
            out.append(d)
        return out

    def latest_snapshot(self, client_id):
        with self.connect() as con:
            row = con.execute(
                "SELECT payload, ts FROM snapshots WHERE client_id=? ORDER BY ts DESC LIMIT 1",
                (client_id,),
            ).fetchone()
        if row is None:
            return None
        return {"payload": json.loads(row["payload"]), "ts": row["ts"]}

    def snapshot_trends(self, limit=120):
        now = time.time()
        cutoff = now - config.RETENTION_DAYS * 86400
        with self.connect() as con:
            rows = con.execute(
                "SELECT client_id, payload, ts FROM snapshots "
                "WHERE ts>=? ORDER BY client_id, ts",
                (cutoff,),
            ).fetchall()
        out = {}
        for r in rows:
            p = json.loads(r["payload"])
            series = out.setdefault(r["client_id"], {"cpu": [], "mem": [], "disk": []})
            cpu = p.get("cpu_percent")
            mem = p.get("mem_percent")
            disk = 0.0
            for d in p.get("disks") or []:
                disk = max(disk, float(d.get("percent", 0)) or 0)
            series["cpu"].append(cpu if cpu is not None else None)
            series["mem"].append(mem if mem is not None else None)
            series["disk"].append(disk)
            for k in ("cpu", "mem", "disk"):
                if len(series[k]) > limit:
                    series[k].pop(0)
        return out

    def snapshot_history(self, client_id, limit=300):
        with self.connect() as con:
            rows = con.execute(
                "SELECT payload, ts FROM snapshots WHERE client_id=? ORDER BY ts DESC LIMIT ?",
                (client_id, limit),
            ).fetchall()
        return [{"payload": json.loads(r["payload"]), "ts": r["ts"]} for r in rows]

    def add_event(self, client_id, client_name, level, message):
        now = time.time()
        with self.connect() as con:
            con.execute(
                "INSERT INTO events(client_id,client_name,ts,level,message) VALUES(?,?,?,?,?)",
                (client_id, client_name, now, level, message),
            )

    def events(self, client_id=None, level=None, limit=500, since=None):
        sql = "SELECT * FROM events"
        conds = []
        args = []
        if client_id is not None:
            conds.append("client_id=?")
            args.append(client_id)
        if level:
            conds.append("level=?")
            args.append(level)
        if since is not None:
            conds.append("ts>=?")
            args.append(since)
        if conds:
            sql += " WHERE " + " AND ".join(conds)
        sql += " ORDER BY ts DESC LIMIT ?"
        args.append(limit)
        with self.connect() as con:
            rows = con.execute(sql, args).fetchall()
        return [dict(r) for r in rows]

    def delete_client(self, client_id):
        with self.connect() as con:
            con.execute("DELETE FROM clients WHERE id=?", (client_id,))
            con.execute("DELETE FROM client_projects WHERE client_id=?", (client_id,))
            con.execute("DELETE FROM snapshots WHERE client_id=?", (client_id,))
            con.execute("DELETE FROM events WHERE client_id=?", (client_id,))

    def prune(self):
        keep_period = config.RETENTION_DAYS * 86400
        cutoff = time.time() - keep_period
        with self.connect() as con:
            con.execute("DELETE FROM events WHERE ts<?", (cutoff,))
            con.execute("DELETE FROM snapshots WHERE ts<?", (cutoff,))

    def record_snapshot(self, client_id, payload):
        now = time.time()
        with self.connect() as con:
            con.execute(
                "INSERT INTO snapshots(client_id,ts,payload) VALUES(?,?,?)",
                (client_id, now, json.dumps(payload)),
            )