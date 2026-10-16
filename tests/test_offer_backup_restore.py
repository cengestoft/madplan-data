import datetime as dt, json, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_offers as fo
import offer_guard as og
import restore_offers as ro
import test_fetch_offers as tf

TODAY = dt.date(2026, 10, 17)
NOW = dt.datetime(2026, 10, 17, 6, 0, tzinfo=dt.timezone.utc)


def o(i, a="2026-10-12", b="2026-10-25"):
    return {"id": i, "name": "Vare %s" % i, "price_dkk": 10.0, "valid_from": a, "valid_to": b}


def doc(stores):
    return {"generated_at": "2026-10-16T03:30:00Z", "stores": {s: {"chain": "T", "offers": offs, "accepted": len(offs)} for s, offs in stores.items()}}


class BackupTests(unittest.TestCase):
    def test_backup_created_with_previous_valid_file_before_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            out = str(Path(d, "data", "offers.json"))
            self.assertEqual(fo.main(tf.FakeSite(40, True).get, lambda s: None, argv=["--out", out]), 0)
            self.assertFalse(Path(d, "data", "offers.previous.json").exists())   # første kørsel: intet at gemme
            first = Path(out).read_text()
            self.assertEqual(fo.main(tf.FakeSite(40, True).get, lambda s: None, argv=["--out", out]), 0)
            self.assertEqual(Path(d, "data", "offers.previous.json").read_text(), first)

    def test_blocked_run_leaves_file_and_backup_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            out = str(Path(d, "offers.json"))
            fo.main(tf.FakeSite(40, True).get, lambda s: None, argv=["--out", out])
            fo.main(tf.FakeSite(40, True).get, lambda s: None, argv=["--out", out])
            a, b = Path(out).read_text(), Path(d, "offers.previous.json").read_text()
            self.assertEqual(fo.main(lambda u: (500, b""), lambda s: None, argv=["--out", out]), 1)
            self.assertEqual((Path(out).read_text(), Path(d, "offers.previous.json").read_text()), (a, b))

    def test_invalid_current_file_never_overwrites_good_backup(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d, "offers.json")
            good = doc({"a": [o(1)]})
            og.write_atomic(Path(d, "offers.previous.json"), good)
            for bad in ("ikke json", "{}", '{"stores": {}}', json.dumps(doc({"a": []}))):
                out.write_text(bad)
                self.assertFalse(og.backup_previous(out, og.load_previous(out)))
                self.assertEqual(json.loads(Path(d, "offers.previous.json").read_text()), good)

    def test_no_tmp_files_left(self):
        with tempfile.TemporaryDirectory() as d:
            og.backup_previous(Path(d, "offers.json"), doc({"a": [o(1)]}))
            self.assertEqual(sorted(p.name for p in Path(d).iterdir()), ["offers.previous.json"])


class RestoreTests(unittest.TestCase):
    def test_restore_drops_expired_and_keeps_current_and_upcoming(self):
        b = doc({"a": [o(1, b="2026-10-16"), o(2, b="2026-10-17"), o(3, a="2026-10-20", b="2026-10-27")], "b": [o(4, b="2026-10-10")]})
        res, rep = og.restore_doc(b, TODAY, NOW)
        self.assertEqual([x["id"] for x in res["stores"]["a"]["offers"]], [2, 3])
        self.assertNotIn("b", res["stores"])                       # alt udløbet -> butikken tages ikke med
        self.assertEqual(rep["dropped_expired"], 2)
        self.assertEqual(res["generated_at"], "2026-10-16T03:30:00Z")   # alder bevares
        self.assertEqual(res["restored"]["at"], "2026-10-17T06:00:00Z")
        self.assertEqual(res["stores"]["a"]["status"], "restored")
        self.assertTrue(res["import_report"]["restored"])

    def test_expired_offers_never_come_back_even_from_old_backup(self):
        b = doc({"a": [o(i, b="2026-09-30") for i in range(50)]})
        res, rep = og.restore_doc(b, TODAY, NOW)
        self.assertIsNone(res)
        self.assertEqual(rep["reason"], "nothing_still_valid")

    def test_refuses_invalid_backup(self):
        for bad in (None, {}, {"stores": {}}, doc({"a": []})):
            res, rep = og.restore_doc(bad, TODAY, NOW)
            self.assertIsNone(res); self.assertEqual(rep["reason"], "backup_invalid")

    def test_cli_writes_atomically_and_refuses_without_touching_target(self):
        with tempfile.TemporaryDirectory() as d:
            src, dst = Path(d, "offers.previous.json"), Path(d, "offers.json")
            dst.write_text("NUVAERENDE")
            self.assertEqual(ro.main(["--from", str(src), "--to", str(dst)], now=NOW), 1)   # backup findes ikke
            self.assertEqual(dst.read_text(), "NUVAERENDE")
            og.write_atomic(src, doc({"a": [o(1, b="2026-10-01")]}))
            self.assertEqual(ro.main(["--from", str(src), "--to", str(dst)], now=NOW), 1)   # kun udløbet
            self.assertEqual(dst.read_text(), "NUVAERENDE")
            og.write_atomic(src, doc({"a": [o(1), o(2, b="2026-10-01")]}))
            self.assertEqual(ro.main(["--from", str(src), "--to", str(dst)], now=NOW), 0)
            r = json.loads(dst.read_text())
            self.assertEqual([x["id"] for x in r["stores"]["a"]["offers"]], [1])
            self.assertFalse(dst.with_name("offers.json.tmp").exists())

    def test_restored_file_is_valid_input_for_next_import(self):
        with tempfile.TemporaryDirectory() as d:
            src, dst = Path(d, "offers.previous.json"), Path(d, "offers.json")
            og.write_atomic(src, doc({"a": [o(1)]}))
            ro.main(["--from", str(src), "--to", str(dst)], now=NOW)
            self.assertIsNotNone(og.load_previous(dst))
            self.assertTrue(og.valid_backup(og.load_previous(dst)))


if __name__ == "__main__":
    unittest.main()
