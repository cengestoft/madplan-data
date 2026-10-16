import datetime as dt, json, os, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import schedule_gate as sg

U = lambda s: dt.datetime.fromisoformat(s + "+00:00")
CRONS_UTC = ((6, 3), (7, 3), (8, 3))


class DecideTests(unittest.TestCase):
    def test_manual_run_always_goes(self):
        self.assertEqual(sg.decide("workflow_dispatch", U("2026-07-10T15:00:00"), dt.date(2026, 7, 10)), (True, "manuel"))

    def test_summer_first_cron_runs_at_0803_danish_time(self):
        self.assertEqual(sg.decide("schedule", U("2026-07-10T06:03:00"), dt.date(2026, 7, 9)), (True, "planlagt"))

    def test_summer_backup_cron_skips_when_already_fetched(self):
        self.assertEqual(sg.decide("schedule", U("2026-07-10T07:03:00"), dt.date(2026, 7, 10)), (False, "allerede_hentet"))
        self.assertEqual(sg.decide("schedule", U("2026-07-10T07:03:00"), dt.date(2026, 7, 9)), (True, "planlagt"))   # reserve, hvis første udeblev

    def test_summer_third_cron_is_outside_window(self):
        self.assertEqual(sg.decide("schedule", U("2026-07-10T08:03:00"), None), (False, "udenfor_tidsrum"))

    def test_winter_first_cron_is_too_early_second_runs(self):
        self.assertEqual(sg.decide("schedule", U("2026-01-12T06:03:00"), None), (False, "udenfor_tidsrum"))   # 07:03 dansk
        self.assertEqual(sg.decide("schedule", U("2026-01-12T07:03:00"), dt.date(2026, 1, 11)), (True, "planlagt"))   # 08:03 dansk
        self.assertEqual(sg.decide("schedule", U("2026-01-12T08:03:00"), dt.date(2026, 1, 12)), (False, "allerede_hentet"))

    def test_dst_switch_days(self):
        # 25. okt. 2026: sommer -> vinter (kl. 03 dansk). Kl. 06:03 UTC er nu 07:03 dansk.
        self.assertEqual(sg.decide("schedule", U("2026-10-25T06:03:00"), None)[0], False)
        self.assertEqual(sg.decide("schedule", U("2026-10-25T07:03:00"), None)[0], True)
        # 29. marts 2026: vinter -> sommer. Kl. 06:03 UTC er nu 08:03 dansk.
        self.assertEqual(sg.decide("schedule", U("2026-03-29T06:03:00"), None)[0], True)
        self.assertEqual(sg.decide("schedule", U("2026-03-28T06:03:00"), None)[0], False)

    def test_exactly_one_fetch_per_day_all_of_2026_and_2027_even_if_first_cron_runs(self):
        for n in range(730):
            day = dt.date(2026, 1, 1) + dt.timedelta(days=n)
            fetched, runs = None, []
            for h in (6, 7, 8):
                now = dt.datetime(day.year, day.month, day.day, h, 3, tzinfo=dt.timezone.utc)
                ok, _ = sg.decide("schedule", now, fetched)
                if ok:
                    runs.append(h); fetched = now.astimezone(sg.CPH).date()
            self.assertEqual(len(runs), 1, day)
            local = dt.datetime(day.year, day.month, day.day, runs[0], 3, tzinfo=dt.timezone.utc).astimezone(sg.CPH)
            self.assertEqual((local.hour, local.minute), (8, 3), day)

    def test_every_day_has_a_backup_attempt_if_first_one_is_missed(self):
        for n in range(730):
            day = dt.date(2026, 1, 1) + dt.timedelta(days=n)
            ok = [h for h in (6, 7, 8) if sg.decide("schedule", dt.datetime(day.year, day.month, day.day, h, 3, tzinfo=dt.timezone.utc), None)[0]]
            self.assertEqual(len(ok), 2, day)


class FileTests(unittest.TestCase):
    def test_last_fetch_date_uses_danish_date_and_tolerates_bad_files(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d, "o.json")
            self.assertIsNone(sg.last_fetch_date(p))
            for bad in ("", "ikke json", "[]", "{}", '{"generated_at": "nonsense"}', '{"generated_at": 5}'):
                p.write_text(bad); self.assertIsNone(sg.last_fetch_date(p), bad)
            p.write_text('{"generated_at": "2026-10-16T22:30:00Z"}')   # 00:30 dansk den 17.
            self.assertEqual(sg.last_fetch_date(p), dt.date(2026, 10, 17))

    def test_main_writes_github_output_with_fixed_vocabulary(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d, "gh.txt"); os.environ["GITHUB_OUTPUT"] = str(out)
            try:
                sg.main(["--event", "schedule", "--last", str(Path(d, "x.json"))], now=U("2026-07-10T06:03:00"))
            finally:
                del os.environ["GITHUB_OUTPUT"]
            self.assertEqual(out.read_text(), "run=yes\nreason=planlagt\n")


if __name__ == "__main__":
    unittest.main()
