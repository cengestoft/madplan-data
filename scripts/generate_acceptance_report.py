#!/usr/bin/env python3
"""Generate acceptance_report.json from REAL test and data results.

Nothing is hard-coded as PASS: every row is computed from the data files or from
the unittest run. `--check` recomputes and fails if the committed report differs.
"""
from __future__ import annotations
import argparse, datetime as dt, io, json, sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from offer_schema import partition_offers, snapshot_date
from product_normalization import normalized_product_key

def load(name): return json.loads((ROOT / name).read_text(encoding="utf-8"))

def run_unittests():
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"))
    result = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(suite)
    failed = {t.id() for t, _ in result.failures + result.errors}
    return result.testsRun, sorted(failed)

GROCERY_EXCLUDED = {"husholdning", "dyrefoder"}
MIN_OVERLAP = 0.30  # quality target (non-blocking, decided by Casper 13 Oct 2026); integrity checks stay blocking

def history_overlap(cur, hist, verification=None, today=None):
    """Active food keys with VERIFIED history (unverified matches never count). Returns (verified, total)."""
    from history_identity import verified_overlap
    r = verified_overlap(cur, verification, today or snapshot_date(cur), MIN_OVERLAP)
    return r["verified"], r["active_food_keys"], r

def compare_reports(old, new):
    """Differences between a committed and a fresh report. Everything except generated_at counts."""
    diffs = []
    for key in ("valid_on", "passed", "total", "all_pass"):
        if old.get(key) != new.get(key): diffs.append(f"{key}: {old.get(key)!r} -> {new.get(key)!r}")
    if old.get("quality_targets") != new.get("quality_targets"): diffs.append("quality_targets differ")
    o_rows, n_rows = old.get("results", []), new.get("results", [])
    if len(o_rows) != len(n_rows): diffs.append(f"results: {len(o_rows)} rows -> {len(n_rows)} rows")
    for a, b in zip(o_rows, n_rows):
        for field in ("id", "name", "status", "detail"):
            if a.get(field) != b.get(field): diffs.append(f"result {b.get('id')} {field}: {a.get(field)!r} -> {b.get(field)!r}")
    return diffs

def compute(today=None):
    cur_doc = load("current_offers.json")
    today = today or snapshot_date(cur_doc)  # snapshot date, not the day the check happens to run
    cur, status, hist, manifest = load("current_offers.json"), load("import_status.json"), load("monthly_price_history.json"), load("price_history.json")
    nxt, quality = load("next_week_offers.json"), load("data_quality_errors.json")
    parts = partition_offers(cur["offers"], today)
    bad_keys = sum(1 for o in cur["offers"] if o.get("normalized_product_key") != normalized_product_key(o))
    hist_missing = sum(1 for r in hist["records"] if not r.get("normalized_product_key"))
    size = (ROOT / "monthly_price_history.json").stat().st_size
    verification = load("history_verification.json") if (ROOT / "history_verification.json").exists() else None
    matched, total_keys, ov = history_overlap(cur, hist, verification, today)
    overlap = matched / max(1, total_keys)
    from history_identity import history_integrity
    integ = history_integrity(hist, verification)
    tests_run, failed = run_unittests()
    nxt_noncanon = sum(1 for o in nxt["offers"] if "package_size" in o or "member_required" in o)
    nxt_no_end = sum(1 for o in nxt["offers"] if not o.get("valid_to"))
    rows = [
        ("No expired offers in current index (Danish date)", len(parts["expired"]) == 0,
         f"{len(parts['expired'])} expired, {len(parts['active'])} active, {len(parts['future'])} future, {len(parts['unknown_end'])} without end date on {today}."),
        ("import_status matches active offers", status.get("offer_count") == status.get("current_total") == len(cur["offers"]) == cur.get("offer_count"),
         f"index {len(cur['offers'])}; status offer_count {status.get('offer_count')}, current_total {status.get('current_total')}."),
        ("price_history.json manifest matches monthly history", manifest.get("record_count") == len(hist["records"]),
         f"manifest {manifest.get('record_count')} vs actual {len(hist['records'])} records."),
        ("All current rows have a recomputed-identical normalized_product_key", bad_keys == 0, f"{bad_keys} mismatching of {len(cur['offers'])}."),
        ("All history rows have normalized_product_key", hist_missing == 0, f"{hist_missing} missing of {len(hist['records'])}."),
        ("History is aggregate-only and under 12 MiB", hist.get("raw_data_included") is False and size < 12 * 1024 * 1024,
         f"{size} bytes; raw_data_included={hist.get('raw_data_included')}."),
        ("next_week_offers.json uses canonical schema", nxt_noncanon == 0, f"{nxt_noncanon} offers with alias field names."),
        ("Future offers without end date are flagged, not treated as unlimited", nxt_no_end == sum(1 for e in quality["errors"] if e.get("type") == "missing_valid_to"),
         f"{nxt_no_end} offers without valid_to; {sum(1 for e in quality['errors'] if e.get('type') == 'missing_valid_to')} flagged."),
        ("No hard data-quality errors", quality.get("hard_error_count") == 0, f"hard_error_count={quality.get('hard_error_count')}."),
        ("History rows come only from verified products (verified_only, every row key has status verified)",
         integ["verification_file_present"] and integ["verified_only_flag"] and integ["rows_unverified"] == 0,
         f"{integ['rows_total']} rows over {integ['history_keys']} keys; {integ['rows_unverified']} rows without verified status; "
         f"verified_only={integ['verified_only_flag']}; verification file present={integ['verification_file_present']}."),
        ("Verified status is only given to keys with actual verified history",
         integ["verification_file_present"] and not integ["verified_without_history"] and not integ["verified_without_raw"],
         f"{integ['verified_keys']} verified keys; {len(integ['verified_without_history'])} without history rows; "
         f"{len(integ['verified_without_raw'])} without verified raw product."),
        (f"Unit test suite ({tests_run} tests)", not failed, "all passed" if not failed else "failed: " + ", ".join(failed)),
    ]
    quality = [{"name": f"Verified history overlap on active food keys (target {MIN_OVERLAP:.0%}, non-blocking)",
                "status": "MET" if overlap >= MIN_OVERLAP else "BELOW_TARGET", "blocking": False,
                "verified": matched, "active_food_keys": total_keys, "overlap": round(overlap, 4),
                "review_required": ov["review_required"], "rejected": ov["rejected"], "no_candidate": ov["no_candidate"],
                "additional_verified_needed": ov["additional_verified_needed"]}]
    results = [{"id": i + 1, "name": n, "status": "PASS" if ok else "FAIL", "detail": d} for i, (n, ok, d) in enumerate(rows)]
    passed = sum(r["status"] == "PASS" for r in results)
    return {"valid_on": str(today), "passed": passed, "total": len(results), "all_pass": passed == len(results), "results": results,
            "quality_targets": quality}

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--check", action="store_true"); ap.add_argument("--today")
    a = ap.parse_args()
    rep = compute(dt.date.fromisoformat(a.today) if a.today else None)
    path = ROOT / "acceptance_report.json"
    if a.check:
        old = json.loads(path.read_text(encoding="utf-8"))
        diffs = compare_reports(old, rep)
        print(json.dumps({"committed_all_pass": old.get("all_pass"), "fresh_all_pass": rep["all_pass"], "match": not diffs,
                          "differences": diffs}, ensure_ascii=False))
        sys.exit(0 if not diffs and rep["all_pass"] else 1)
    rep = {"generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"), "branch": "claude-kodekontrol-2026-10-09", **rep,
           "automation": {"workflow": ".github/workflows/data-quality.yml", "behavior": "Validation only; CI does not write or commit data."},
           "note": "Generated by scripts/generate_acceptance_report.py from real data and test results."}
    path.write_text(json.dumps(rep, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: rep[k] for k in ("passed", "total", "all_pass")}))
    sys.exit(0 if rep["all_pass"] else 1)

if __name__ == "__main__": main()
