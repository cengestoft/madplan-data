import datetime as dt
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from offer_schema import (canonicalize_offer, copenhagen_today, food_relevance_for, offer_status,
                          partition_offers, snapshot_date, unexplained_losses, unverifiable_missing)
from build_data_pipeline import (is_active_offer, reconcile_history_manifest, reconcile_import_status, store_organic_flags,
                                 validate_import)
from build_offer_feed import PAGE_LIMIT, _num as _num_for_test, build_feed, offer_line, paginate, render
from generate_acceptance_report import compare_reports
from check_freshness import freshness
from product_normalization import normalized_product_key
import check_super_deal_history as sdh


def load(name):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


D = dt.date


class ValiditySemantics(unittest.TestCase):
    def test_status_values(self):
        t = D(2026, 10, 9)
        self.assertEqual(offer_status({"valid_from": "2026-10-03", "valid_to": "2026-10-09"}, t), "active")
        self.assertEqual(offer_status({"valid_from": "2026-10-01", "valid_to": "2026-10-08"}, t), "expired")
        self.assertEqual(offer_status({"valid_from": "2026-10-11", "valid_to": None}, t), "future")
        self.assertEqual(offer_status({"valid_from": "2026-10-01", "valid_to": None}, t), "unknown_end")
        self.assertEqual(offer_status({}, t), "undated")

    def test_missing_end_date_is_never_active(self):
        self.assertFalse(is_active_offer({"valid_from": "2026-10-01", "valid_to": None}, D(2026, 10, 9)))

    def test_danish_date_not_utc(self):
        late_utc = dt.datetime(2026, 10, 8, 22, 30, tzinfo=dt.timezone.utc)  # already 9 Oct in Denmark
        self.assertEqual(copenhagen_today(late_utc), D(2026, 10, 9))

    def test_partition(self):
        offers = [{"id": 1, "valid_from": "2026-10-01", "valid_to": "2026-10-08"},
                  {"id": 2, "valid_from": "2026-10-09", "valid_to": "2026-10-09"},
                  {"id": 3, "valid_from": "2026-10-10", "valid_to": "2026-10-12"}]
        parts = partition_offers(offers, D(2026, 10, 9))
        self.assertEqual([len(parts[k]) for k in ("expired", "active", "future")], [1, 1, 1])


class ImportGuard(unittest.TestCase):
    def test_legitimate_expiry_is_not_data_loss(self):
        t = D(2026, 10, 9)
        previous = [{"id": i, "valid_from": "2026-10-01", "valid_to": "2026-10-08"} for i in range(80)] + \
                   [{"id": 100 + i, "valid_from": "2026-10-01", "valid_to": "2026-10-31"} for i in range(20)]
        incoming = [dict(o) for o in previous[80:]]  # only the expired ones are gone
        self.assertTrue(validate_import(incoming, previous, 0, today=t))

    def test_real_loss_is_blocked(self):
        t = D(2026, 10, 9)
        previous = [{"id": i, "valid_from": "2026-10-01", "valid_to": "2026-10-31"} for i in range(100)]
        with self.assertRaises(RuntimeError):
            validate_import(previous[:50], previous, 0, today=t)
        self.assertEqual(len(unexplained_losses(previous, previous[:50], t)), 50)

    def test_empty_import_still_blocked(self):
        with self.assertRaises(RuntimeError):
            validate_import([], [{"id": "x"}], 0, today=D(2026, 10, 9))


class Schema(unittest.TestCase):
    def test_canonicalize_keeps_values_and_does_not_guess_organic(self):
        o = canonicalize_offer({"package_size": 0.5, "member_required": True, "organic": None, "price_dkk": 69})
        self.assertEqual((o["package_amount"], o["member_only"], o["organic"], o["price_dkk"]), (0.5, True, None, 69))
        self.assertNotIn("package_size", o)
        self.assertIsNone(canonicalize_offer({"price_dkk": 1})["organic"])  # unknown, not False

    def test_food_relevance_is_deterministic(self):
        self.assertEqual(food_relevance_for("kød"), "high")
        self.assertEqual(food_relevance_for("husholdning"), "low")
        self.assertIsNone(food_relevance_for("snacks"))
        self.assertIsNone(food_relevance_for(None))

    def test_next_week_file_is_canonical(self):
        for o in load("next_week_offers.json")["offers"]:
            self.assertNotIn("package_size", o)
            self.assertNotIn("member_required", o)
            self.assertIn("package_amount", o)
            self.assertIn("member_only", o)

    def test_next_week_missing_end_dates_are_flagged(self):
        no_end = [o for o in load("next_week_offers.json")["offers"] if not o.get("valid_to")]
        flagged = [e for e in load("data_quality_errors.json")["errors"] if e.get("type") == "missing_valid_to"]
        self.assertEqual(len(no_end), len(flagged))


class RealData(unittest.TestCase):
    def test_no_expired_offers_in_current_index(self):
        cur = load("current_offers.json")
        parts = partition_offers(cur["offers"], snapshot_date(cur))
        self.assertEqual(len(parts["expired"]), 0, f"{len(parts['expired'])} expired offers in current_offers.json")
        self.assertEqual(len(parts["undated"]), 0)

    def test_import_status_matches_published_offers(self):
        cur, status = load("current_offers.json"), load("import_status.json")
        self.assertEqual(status["offer_count"], len(cur["offers"]))
        self.assertEqual(status["current_total"], len(cur["offers"]))
        self.assertEqual(sum(status["counts"].values()), len(cur["offers"]))

    def test_manifest_matches_monthly_history(self):
        monthly, manifest = load("monthly_price_history.json"), load("price_history.json")
        self.assertEqual(manifest["record_count"], len(monthly["records"]))
        self.assertEqual(monthly.get("record_count", len(monthly["records"])), len(monthly["records"]))
        self.assertEqual(reconcile_history_manifest(manifest, monthly)["record_count"], len(monthly["records"]))

    def test_current_keys_are_recomputed_identically(self):
        bad = [o["id"] for o in load("current_offers.json")["offers"]
               if o.get("normalized_product_key") != normalized_product_key(o)]
        self.assertEqual(bad, [], f"{len(bad)} offers with drifting normalized_product_key")

    def test_history_keys_present_and_well_formed(self):
        pattern = re.compile(r"^brand=.+\|product=.+\|variant=.+\|count=.+\|size=.+$")
        bad = [r for r in load("monthly_price_history.json")["records"]
               if not pattern.match(r.get("normalized_product_key") or "")]
        self.assertEqual(len(bad), 0)

    def test_history_is_aggregate_only_and_small(self):
        monthly = load("monthly_price_history.json")
        self.assertIs(monthly.get("raw_data_included"), False)
        self.assertEqual(monthly.get("aggregation"), "normalized_product_key + store + month")
        self.assertLess((ROOT / "monthly_price_history.json").stat().st_size, 12 * 1024 * 1024)

    def test_organic_is_boolean_or_unknown(self):
        for o in load("current_offers.json")["offers"]:
            self.assertIn(o.get("organic"), (True, False, None))

    def test_non_food_not_marked_high(self):
        for o in load("current_offers.json")["offers"]:
            if str(o.get("category")).lower() in ("husholdning", "dyrefoder"):
                self.assertNotEqual(o.get("food_relevance"), "high")


class SuperDeals(unittest.TestCase):
    def test_super_deals_are_active_and_graph_policy_holds(self):
        today = snapshot_date(load("super_deals_current.json"))
        report = sdh.build_report(str(ROOT / "super_deals_current.json"), str(ROOT / "monthly_price_history.json"), today)
        errors = {e["offer_id"] for e in load("data_quality_errors.json")["errors"] if e.get("type") == "super_deal_missing_history"}
        for row in report["offers"]:
            self.assertEqual(row["graph_allowed"], row["history_month_count"] >= 3)
            if not row["graph_allowed"]:
                self.assertIn(row["offer_id"], errors)
        stale = [o["id"] for o in load("super_deals_current.json")["offers"] if offer_status(o, today) != "active"]
        self.assertEqual(stale, [], "super_deals_current.json lists expired deals")


def _o(name, store="S", cat="mejeri", price=10, amount=1, unit="stk", oid=None, frm="2026-10-01", to="2026-10-31"):
    o = {"name": name, "store": store, "category": cat, "price_dkk": price, "package_amount": amount, "package_unit": unit,
         "valid_from": frm, "valid_to": to}
    if oid is not None: o["id"] = oid
    return o


class Feed(unittest.TestCase):
    def test_every_valid_priced_offer_appears_exactly_once_in_real_data(self):
        cur = load("current_offers.json"); today = snapshot_date(cur)
        valid = [o for o in cur["offers"] if offer_status(o, today) == "active" and o.get("price_dkk") and o.get("package_amount") is not None
                 and o.get("package_unit")]
        feed, excluded = build_feed(cur["offers"], today)
        self.assertEqual(sum(d["offer_count"] for d in feed.values()), len(valid))
        self.assertEqual(sum(excluded.values()), len(cur["offers"]) - len(valid))
        ids = [e["id"] for d in feed.values() for e in d["offers"]]
        self.assertEqual(sorted(ids), sorted(o["id"] for o in valid))  # exactly once, nothing lost, no duplicates
        self.assertEqual(len(set(ids)), len(ids))
        for d in feed.values():
            self.assertEqual(sum(len(p.split("\n")) for p in d["pages"]), d["offer_count"])

    def test_structured_record_keeps_full_name_price_package_and_validity(self):
        cur = load("current_offers.json"); today = snapshot_date(cur)
        src = {o["id"]: o for o in cur["offers"]}
        feed, _ = build_feed(cur["offers"], today)
        for d in feed.values():
            for e in d["offers"]:
                o = src[e["id"]]
                self.assertEqual((e["name"], e["price_dkk"], e["package_amount"], e["package_unit"], e["valid_from"], e["valid_to"]),
                                 (o["name"].strip(), o["price_dkk"], o["package_amount"], o["package_unit"], o["valid_from"], o["valid_to"]))

    def test_page_and_line_index_point_at_the_offers_own_line(self):
        cur = load("current_offers.json"); today = snapshot_date(cur)
        feed, _ = build_feed(cur["offers"], today)
        for d in feed.values():
            for e in d["offers"]:
                line = d["pages"][e["page"]].split("\n")[e["line"]]
                self.assertIn(f"{_num_for_test(e['price_dkk'])} kr. pr.", line)
                if not e["name_shortened_in_page_text"]:
                    self.assertTrue(line.startswith(e["name"]), line)

    def test_end_date_is_written_when_it_is_earlier_than_the_store_end(self):
        offers = [_o("Lang", to="2026-10-31"), _o("Kort", to="2026-10-12")]
        feed, _ = build_feed(offers, D(2026, 10, 9))
        lines = feed["S"]["pages"][0].split("\n")
        self.assertTrue(any(l.startswith("Kort") and l.endswith("til 12.10.") for l in lines))
        self.assertFalse(any(l.startswith("Lang") and " til " in l for l in lines))

    def test_non_food_is_kept_and_comes_last(self):
        offers = [_o("Vaskemiddel", cat="husholdning", unit="stk"), _o("Hundefoder", cat="dyrefoder"), _o("Mælk", cat="mejeri", unit="l"),
                  _o("Ukendt", cat="andet")]
        feed, _ = build_feed(offers, D(2026, 10, 9))
        lines = feed["S"]["pages"][0].split("\n")
        self.assertEqual(feed["S"]["offer_count"], 4)
        self.assertEqual(feed["S"]["non_food_count"], 2)
        self.assertTrue(lines[0].startswith("Mælk"))
        self.assertTrue(lines[1].startswith("Ukendt"))
        self.assertTrue({l.split(" - ")[0] for l in lines[2:]} == {"Vaskemiddel", "Hundefoder"})

    def test_food_only_filter_is_explicit(self):
        offers = [_o("Vaskemiddel", cat="husholdning"), _o("Mælk")]
        feed, excluded = build_feed(offers, D(2026, 10, 9), food_only=True)
        self.assertEqual(feed["S"]["offer_count"], 1)
        self.assertEqual(excluded["non_food_excluded_by_flag"], 1)
        self.assertEqual(build_feed(offers, D(2026, 10, 9))[0]["S"]["offer_count"], 2)

    def test_duplicate_ids_are_listed_once(self):
        offers = [_o("Mælk", oid="a"), _o("Mælk", oid="a"), _o("Smør", oid="b")]
        feed, excluded = build_feed(offers, D(2026, 10, 9))
        self.assertEqual(feed["S"]["offer_count"], 2)
        self.assertEqual(excluded["duplicate_id"], 1)

    def test_expired_future_and_unpriced_are_excluded_and_counted(self):
        offers = [_o("Gammel", to="2026-10-08"), _o("Fremtid", frm="2026-10-10"), _o("Ingen pris", price=None), _o("Ok")]
        feed, excluded = build_feed(offers, D(2026, 10, 9))
        self.assertEqual(feed["S"]["offer_count"], 1)
        self.assertEqual((excluded["not_active"], excluded["missing_price_or_package"]), (2, 1))

    def test_all_pages_within_limit_in_real_data(self):
        cur = load("current_offers.json")
        feed, _ = build_feed(cur["offers"], snapshot_date(cur))
        for store, doc in feed.items():
            for page in doc["pages"]:
                self.assertLessEqual(len(page), PAGE_LIMIT, store)
                self.assertLess(len(page), 6000, store)

    def test_single_oversized_line_is_truncated_with_trace_and_never_breaks_limit(self):
        long_line = "X" * 500
        pages, truncated = paginate(["kort", long_line, "kort2"], limit=100)
        self.assertTrue(all(len("\n".join(p)) <= 100 for p in pages))
        self.assertEqual(len(truncated), 1)
        self.assertEqual((truncated[0]["line_index"], truncated[0]["original_length"]), (1, 500))
        self.assertEqual(sum(len(p) for p in pages), 3)

    def test_pagination_never_exceeds_limit_for_many_lines(self):
        lines = [f"vare {i} " + "y" * (i % 37) for i in range(400)]
        pages, truncated = paginate(lines, limit=300)
        self.assertEqual(truncated, [])
        self.assertTrue(all(len("\n".join(p)) <= 300 for p in pages))
        self.assertEqual([l for p in pages for l in p], lines)

    def test_oversized_offer_keeps_price_package_dates_and_full_text(self):
        long_name = "N" * 400
        o = _o(long_name, oid=1, price=12.5, amount=0.5, unit="kg", to="2026-10-12")
        o2 = _o("Anden", oid=2, to="2026-10-31")
        feed, _ = build_feed([o, o2], D(2026, 10, 9), limit=100)
        doc = feed["S"]
        line = next(l for p in doc["pages"] for l in p.split("\n") if l.startswith("N"))
        self.assertLessEqual(len(line), 100)
        self.assertTrue(line.endswith("- 12,5 kr. pr. 0,5 kg - til 12.10."), line)  # price, package and end date survive
        self.assertEqual(len(doc["truncated_lines"]), 1)
        self.assertEqual(doc["truncated_lines"][0]["full_text"], long_name + " - 12,5 kr. pr. 0,5 kg - til 12.10.")
        entry = next(e for e in doc["offers"] if e["id"] == 1)
        self.assertEqual((entry["name"], entry["price_dkk"], entry["valid_to"], entry["name_shortened_in_page_text"]),
                         (long_name, 12.5, "2026-10-12", True))
        self.assertTrue(all(len(p) <= 100 for p in doc["pages"]))

    def test_committed_feed_files_match_fresh_build_and_index_is_consistent(self):
        cur = load("current_offers.json"); today = snapshot_date(cur)
        feed, excluded = build_feed(cur["offers"], today)
        for name, text in render(feed, excluded, today).items():
            raw = (ROOT / "feed" / name).read_bytes()
            self.assertEqual(raw.decode("utf-8"), text, name)  # valid utf-8 and identical to a fresh build
        index = load("feed/index.json")
        self.assertEqual((index["schema_version"], index["valid_on"], index["encoding"]), (1, str(today), "utf-8"))
        for store, meta in index["stores"].items():
            doc = load("feed/" + meta["file"])
            self.assertEqual((doc["offer_count"], doc["page_count"]), (meta["offer_count"], meta["page_count"]))
            self.assertEqual(len(doc["pages"]), doc["page_count"])


class UnknownEnd(unittest.TestCase):
    T = D(2026, 10, 9)

    def test_unknown_end_is_not_active_and_not_counted_as_verified_loss(self):
        previous = [{"id": "u", "valid_from": "2026-10-01", "valid_to": None},
                    {"id": "a", "valid_from": "2026-10-01", "valid_to": "2026-10-31"}]
        incoming = [previous[1]]
        self.assertEqual(offer_status(previous[0], self.T), "unknown_end")
        self.assertEqual(unexplained_losses(previous, incoming, self.T), [])
        self.assertEqual(unverifiable_missing(previous, incoming, self.T), ["u"])

    def test_missing_verified_offers_are_still_loss_and_future_counts(self):
        previous = [{"id": "a", "valid_from": "2026-10-01", "valid_to": "2026-10-31"},
                    {"id": "f", "valid_from": "2026-10-12", "valid_to": "2026-10-18"}]
        self.assertEqual(unexplained_losses(previous, [], self.T), ["a", "f"])

    def test_many_unknown_end_offers_disappearing_does_not_block_import(self):
        previous = [{"id": i, "valid_from": "2026-10-01", "valid_to": None} for i in range(50)] + \
                   [{"id": 100 + i, "valid_from": "2026-10-01", "valid_to": "2026-10-31"} for i in range(50)]
        self.assertTrue(validate_import(previous[50:], previous, 0, today=self.T))

    def test_loss_of_verified_offers_still_blocks(self):
        previous = [{"id": i, "valid_from": "2026-10-01", "valid_to": "2026-10-31"} for i in range(100)] + \
                   [{"id": 500 + i, "valid_from": "2026-10-01", "valid_to": None} for i in range(100)]
        with self.assertRaises(RuntimeError):
            validate_import(previous[50:], previous, 0, today=self.T)


class AcceptanceReportCheck(unittest.TestCase):
    BASE = {"valid_on": "2026-10-09", "passed": 2, "total": 2, "all_pass": True,
            "results": [{"id": 1, "name": "A", "status": "PASS", "detail": "5 of 10"},
                        {"id": 2, "name": "B", "status": "PASS", "detail": "ok"}]}

    def clone(self):
        return json.loads(json.dumps(self.BASE))

    def test_identical_reports_match(self):
        self.assertEqual(compare_reports(self.BASE, self.clone()), [])

    def test_changed_count_with_unchanged_pass_fail_is_detected(self):
        new = self.clone(); new["results"][0]["detail"] = "6 of 10"
        self.assertTrue(compare_reports(self.BASE, new))

    def test_changed_valid_on_name_and_row_count_are_detected(self):
        for mutate in (lambda r: r.update(valid_on="2026-10-10"), lambda r: r["results"][1].update(name="C"),
                       lambda r: r["results"].pop(), lambda r: r.update(total=3)):
            new = self.clone(); mutate(new)
            self.assertTrue(compare_reports(self.BASE, new))

    def test_generated_at_alone_does_not_cause_a_difference(self):
        old, new = self.clone(), self.clone()
        old["generated_at"], new["generated_at"] = "x", "y"
        self.assertEqual(compare_reports(old, new), [])

    def test_committed_report_describes_the_committed_snapshot_date(self):
        self.assertEqual(load("acceptance_report.json")["valid_on"], str(snapshot_date(load("current_offers.json"))))


class SnapshotVersusFreshness(unittest.TestCase):
    def test_snapshot_date_is_danish_date_of_generated_at(self):
        self.assertEqual(snapshot_date({"generated_at": "2026-10-08T22:30:00+00:00"}), D(2026, 10, 9))
        with self.assertRaises(ValueError): snapshot_date({})

    def test_stale_live_data_is_flagged_but_fresh_is_not(self):
        cur = {"generated_at": "2026-10-09T06:40:00+00:00",
               "offers": [{"valid_from": "2026-10-01", "valid_to": "2026-10-12"}]}
        self.assertFalse(freshness(cur, D(2026, 10, 9))["stale"])
        self.assertTrue(freshness(cur, D(2026, 10, 13))["stale"])  # offer expired and snapshot old
        self.assertTrue(freshness(cur, D(2026, 10, 12 + 4))["stale"])

    def test_snapshot_tests_do_not_read_the_clock(self):
        import re
        no_arg_clock_call = re.compile(r"copenhagen_today" + r"\(\s*\)")
        for path in (ROOT / "tests").glob("test_*.py"):
            hits = no_arg_clock_call.findall(path.read_text(encoding="utf-8"))
            self.assertEqual(hits, [], f"{path.name} reads today's date in a snapshot test")


class PipelineSnapshotMode(unittest.TestCase):
    def test_snapshot_mode_validates_on_snapshot_date_and_cannot_write(self):
        import subprocess
        cur = load("current_offers.json")
        out = subprocess.run([sys.executable, str(ROOT / "scripts" / "build_data_pipeline.py"), "--snapshot-date"],
                             capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(json.loads(out.stdout.strip().splitlines()[-1])["date"], str(snapshot_date(cur)))
        bad = subprocess.run([sys.executable, str(ROOT / "scripts" / "build_data_pipeline.py"), "--snapshot-date", "--write"],
                             capture_output=True, text=True, cwd=ROOT)
        self.assertNotEqual(bad.returncode, 0)

    def test_ci_runs_the_pipeline_in_snapshot_mode(self):
        text = (ROOT / ".github" / "workflows" / "data-quality.yml").read_text(encoding="utf-8")
        self.assertIn("build_data_pipeline.py --snapshot-date", text)


class Organic(unittest.TestCase):
    def test_real_data_organic_matches_documented_store_value_by_id(self):
        flags = store_organic_flags(ROOT)
        for o in load("current_offers.json")["offers"]:
            documented = flags.get(o["id"])
            if o.get("organic") is False or o.get("organic") is True:
                self.assertEqual(o["organic"], documented, o["id"])  # bool only where the source documents it
            else:
                self.assertIsNone(o.get("organic"))

    def test_conflicting_documented_values_become_unknown(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "stores").mkdir()
            (Path(tmp) / "stores" / "a.json").write_text(json.dumps({"offers": [{"id": "x", "organic": True}, {"id": "y", "organic": False}]}))
            (Path(tmp) / "stores" / "b.json").write_text(json.dumps({"offers": [{"id": "x", "organic": False}, {"id": "z", "organic": None}]}))
            conflicts = []
            flags = store_organic_flags(Path(tmp), conflicts)
        self.assertEqual(conflicts, ["x"])
        self.assertNotIn("x", flags)
        self.assertEqual(flags, {"y": False})  # None in source stays unknown, never False

    def test_missing_source_value_is_never_false(self):
        from build_data_pipeline import enrich_offer
        self.assertIsNone(enrich_offer({"id": 1, "name": "x"}, {})["organic"])


class HistoryRights(unittest.TestCase):
    def test_written_permission_is_recorded_and_conditions_hold(self):
        manifest = load("data_sources/dagligepriser_manifest.json")
        self.assertEqual(manifest.get("redistribution_status"), "permitted_aggregated_only")
        hist = load("monthly_price_history.json")
        self.assertIs(hist.get("raw_data_included"), False)
        self.assertEqual(hist.get("source"), "dagligepriser.dk")
        self.assertTrue(hist.get("credit") and hist.get("source_url"), "visible credit with source is required")
        allowed = {"normalized_product_key", "store", "month", "observation_count", "median_price_dkk", "min_price_dkk",
                   "avg_price_dkk", "max_price_dkk", "source"}
        for r in hist["records"][:5000]:
            self.assertLessEqual(set(r), allowed, "history rows must stay aggregated (no daily/raw fields)")
            self.assertRegex(r["month"], r"^\d{4}-\d{2}$")


class WorkflowSafety(unittest.TestCase):
    def test_no_workflow_can_write_or_publish(self):
        for wf in (ROOT / ".github" / "workflows").glob("*.yml"):
            text = wf.read_text(encoding="utf-8")
            self.assertNotIn("contents: write", text, wf.name)
            self.assertNotIn("git push", text, wf.name)
            self.assertNotIn("git commit", text, wf.name)
            self.assertNotIn("--allow-public-output", text, wf.name)
            self.assertNotRegex(text, r"(?m)^\s*branches:\s*\[main\]", wf.name)
            self.assertIn("contents: read", text, wf.name)
            self.assertNotRegex(text, r"(?i)(gh pr merge|gh api .*-X (POST|PUT|PATCH|DELETE)|git (merge|tag)|--write\b|actions/(create|upload)-release|peaceiris|stefanzweifel)", wf.name)
            self.assertNotRegex(text, r"(?i)secrets\.", wf.name)
            self.assertNotRegex(text, r"(?m)^\s*schedule:", wf.name)

    def test_workflows_do_not_run_the_pipeline_in_write_mode(self):
        for wf in (ROOT / ".github" / "workflows").glob("*.yml"):
            for line in wf.read_text(encoding="utf-8").splitlines():
                if "build_data_pipeline.py" in line and line.strip().startswith("run:"):
                    self.assertNotIn("--write", line, wf.name)


if __name__ == "__main__":
    unittest.main()
