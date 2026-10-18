import contextlib, io, json, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import check_freshness as cf


def run(argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = cf.main(argv)
    return code, out.getvalue()


class Freshness(unittest.TestCase):
    def test_gammelt_snapshot_er_kun_en_note_med_informational(self):
        code, out = run(["--today", "2030-01-01", "--informational"])
        self.assertEqual(code, 0)
        self.assertIn("::notice::", out)
        self.assertIn("Intern snapshot", out)
        self.assertNotIn("::warning::", out)

    def test_uden_flag_er_gammelt_snapshot_stadig_en_advarsel_og_fejl(self):
        code, out = run(["--today", "2030-01-01"])
        self.assertEqual(code, 1)
        self.assertIn("::warning::", out)

    def test_friskt_snapshot_giver_ingen_besked(self):
        snap = json.loads((Path(cf.__file__).resolve().parents[1] / "current_offers.json").read_text(encoding="utf-8"))
        day = cf.snapshot_date(snap).isoformat()
        for extra in ([], ["--informational"]):
            code, out = run(["--today", day, "--max-age-days", "400"] + extra)
            self.assertEqual(code, 0)
            self.assertNotIn("::", out)


if __name__ == "__main__":
    unittest.main()
