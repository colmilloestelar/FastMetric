import json
import smtplib
from email.mime.text import MIMEText
from urllib.request import Request, urlopen

from .store import Store


class Notifier:
    def __init__(self):
        self.store = None

    def bind(self, store):
        self.store = store

    def get_store(self):
        if self.store is None:
            self.store = Store()
        return self.store

    def load_settings(self):
        s = self.get_store()
        return {
            "email_enabled": s.get_setting("email_enabled", "false") == "true",
            "email_to": s.get_setting("email_to", ""),
            "email_smtp": s.get_setting("email_smtp", ""),
            "email_user": s.get_setting("email_user", ""),
            "email_password": s.get_setting("email_password", ""),
            "webhooks": json.loads(s.get_setting("webhooks", "[]")),
        }

    def notify_alert(self, client_name, message, level, projects=None):
        text = f"[{level.upper()}] {client_name}: {message}"
        settings = self.load_settings()
        projects = projects or []
        project_cfgs = self.get_store().project_alerts()

        email_targets = []
        webhook_targets = []
        for p in projects:
            cfg = project_cfgs.get(p)
            if cfg:
                if cfg["email_to"]:
                    email_targets.append((p, cfg["email_to"], settings))
                for u in cfg["webhooks"]:
                    webhook_targets.append((p, u))

        if not projects or level == "critical":
            if settings["email_enabled"]:
                email_targets.append(("global", settings["email_to"], settings))
            webhook_targets.extend(("global", u) for u in settings["webhooks"])

        seen_email = set()
        seen_webhook = set()
        for kind, to, cfg in email_targets:
            if to in seen_email:
                continue
            seen_email.add(to)
            self._send_email(cfg, "FastMetric alert", text, to)
        for kind, url in webhook_targets:
            if url in seen_webhook:
                continue
            seen_webhook.add(url)
            self._send_webhook(url, text, level, client_name)

    def _send_email(self, settings, subject, body, to=None):
        if not settings["email_smtp"]:
            return
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = settings["email_user"] or settings["email_smtp"]
        msg["To"] = to if to is not None else settings["email_to"]
        try:
            smtp = smtplib.SMTP(settings["email_smtp"])
            smtp.starttls()
            if settings["email_user"] and settings["email_password"]:
                smtp.login(settings["email_user"], settings["email_password"])
            smtp.send_message(msg)
            smtp.quit()
        except Exception:
            pass

    def _send_webhook(self, url, text, level, client_name):
        payload = {
            "text": text,
            "level": level,
            "client": client_name,
        }
        try:
            req = Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(req, timeout=10):
                pass
        except Exception:
            pass

    def test_email(self):
        settings = self.load_settings()
        self._send_email(settings, "FastMetric test", "Test message from FastMetric")

    def test_project(self, project):
        cfg = self.get_store().project_alerts().get(project)
        if not cfg:
            return
        settings = self.load_settings()
        if cfg["email_to"] and settings["email_smtp"]:
            self._send_email(
                settings, "FastMetric test",
                f"Test message from FastMetric (project {project})", cfg["email_to"],
            )
        for url in cfg["webhooks"]:
            self._send_webhook(url, f"Test message from FastMetric (project {project})", "info", "test")

    def test_webhook(self, url):
        self._send_webhook(url, "Test message from FastMetric", "info", "test")