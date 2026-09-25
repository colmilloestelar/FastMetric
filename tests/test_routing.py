import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server.notify import Notifier
from server.store import Store


class RoutingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.store = Store(path=os.path.join(self.tmp, "test.db"))

        self.notifier = Notifier()
        self.notifier.bind(self.store)

        self.emails = []
        self.hooks = []
        self.notifier._send_email = self._fake_email
        self.notifier._send_webhook = self._fake_hook

        self.store.set_setting("email_enabled", "true")
        self.store.set_setting("email_smtp", "smtp.global:587")
        self.store.set_setting("email_to", "sre@corp.com")
        self.store.set_setting("webhooks", json.dumps(["https://wh.global/sre"]))

        self.store.set_project_alert("WebTeam", "web@corp.com", ["https://wh.web"])
        self.store.set_project_alert("Payments", "pay@corp.com", ["https://wh.pay"])

    def _fake_email(self, settings, subject, body, to=None):
        self.emails.append(to or settings["email_to"])

    def _fake_hook(self, url, text, level, client_name):
        self.hooks.append(url)

    def assert_sent(self, emails, hooks):
        self.assertEqual(sorted(self.emails), sorted(emails))
        self.assertEqual(sorted(self.hooks), sorted(hooks))

    def test_warning_single_project_only_project_channel(self):
        self.notifier.notify_alert("web-01", "CPU at 91%", "warning", projects=["WebTeam"])
        self.assert_sent(["web@corp.com"], ["https://wh.web"])

    def test_critical_single_project_also_global(self):
        self.notifier.notify_alert("web-01", "CPU at 96%", "critical", projects=["WebTeam"])
        self.assert_sent(
            ["web@corp.com", "sre@corp.com"],
            ["https://wh.web", "https://wh.global/sre"],
        )

    def test_warning_no_project_only_global(self):
        self.notifier.notify_alert("db-01", "disk full", "warning", projects=None)
        self.assert_sent(["sre@corp.com"], ["https://wh.global/sre"])

    def test_warning_multi_project_sends_to_all_members(self):
        self.notifier.notify_alert(
            "shared-01", "mem at 92%", "warning", projects=["WebTeam", "Payments"]
        )
        self.assert_sent(
            ["web@corp.com", "pay@corp.com"],
            ["https://wh.web", "https://wh.pay"],
        )

    def test_critical_multi_project_sends_all_plus_global(self):
        self.notifier.notify_alert(
            "shared-01", "mem at 98%", "critical", projects=["WebTeam", "Payments"]
        )
        self.assert_sent(
            ["web@corp.com", "pay@corp.com", "sre@corp.com"],
            ["https://wh.web", "https://wh.pay", "https://wh.global/sre"],
        )

    def test_multi_project_duplicate_destination_deduped(self):
        self.store.set_project_alert(
            "WebTeam", "shared@corp.com", ["https://wh.shared"]
        )
        self.store.set_project_alert(
            "Payments", "shared@corp.com", ["https://wh.shared"]
        )
        self.notifier.notify_alert(
            "shared-01", "disk at 95%", "warning", projects=["WebTeam", "Payments"]
        )
        self.assert_sent(["shared@corp.com"], ["https://wh.shared"])

    def test_everything_disabled_sends_nothing(self):
        self.store.set_setting("email_enabled", "false")
        self.store.set_setting("webhooks", "[]")
        self.store.set_project_alert("WebTeam", "", [])
        self.notifier.notify_alert("x", "boom", "critical", projects=["WebTeam"])
        self.assert_sent([], [])

    def test_project_email_independent_of_global_flag(self):
        self.store.set_setting("email_enabled", "false")
        self.store.set_setting("webhooks", "[]")
        self.notifier.notify_alert("web-01", "CPU at 95%", "warning", projects=["WebTeam"])
        self.assert_sent(["web@corp.com"], ["https://wh.web"])


if __name__ == "__main__":
    unittest.main()