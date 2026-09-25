import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server.store import Store


class OfflineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.store = Store(path=os.path.join(self.tmp, "test.db"))

    def test_offline_unnotified_flags_and_clears(self):
        cid, _ = self.store.upsert_client(
            "web-01", "vm", "10.0.0.1", "tok"
        )
        self.assertFalse(self.store.offline_unnotified(10))

        old = time.time() - 120
        with self.store.connect() as con:
            con.execute(
                "UPDATE clients SET last_seen=? WHERE id=?",
                (old, cid),
            )
        found = self.store.offline_unnotified(60)
        self.assertEqual([f["name"] for f in found], ["web-01"])

        self.store.mark_offline_alerted(cid)
        self.assertEqual(self.store.offline_unnotified(60), [])

        cid2, was = self.store.upsert_client(
            "web-01", "vm", "10.0.0.1", "tok"
        )
        self.assertEqual(cid2, cid)
        self.assertTrue(was)
        self.assertEqual(self.store.offline_unnotified(60), [])

    def test_never_reported_not_in_unnotified_until_window(self):
        cid, _ = self.store.upsert_client(
            "fresh", "vm", "10.0.0.2", "tok"
        )
        self.assertEqual(self.store.offline_unnotified(300), [])


if __name__ == "__main__":
    unittest.main()