import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts.audit_snapshot_chain import audit


class SnapshotAuditTests(unittest.TestCase):
    def test_stale_does_not_change_files(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for name in ("current_offers.json", "next_week_offers.json"):
                (root / name).write_text(json.dumps({"generated_at": "2026-10-13T21:22:29+02:00", "offers": []}))
            before = {p.name: p.read_bytes() for p in root.iterdir()}
            result = audit(root, dt.datetime(2026, 11, 1, 8, tzinfo=ZoneInfo("Europe/Copenhagen")))
            self.assertFalse(result["safe_to_import"])
            self.assertEqual(before, {p.name: p.read_bytes() for p in root.iterdir()})

    def test_fresh(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for name in ("current_offers.json", "next_week_offers.json"):
                (root / name).write_text(json.dumps({"generated_at": "2026-11-01T07:00:00+01:00"}))
            result = audit(root, dt.datetime(2026, 11, 1, 8, tzinfo=ZoneInfo("Europe/Copenhagen")))
            self.assertTrue(result["safe_to_import"])
