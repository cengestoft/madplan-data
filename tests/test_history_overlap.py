import json
import sys
import unittest
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from offer_schema import snapshot_date
from history_identity import verified_overlap, history_integrity


def load(name, default=None):
    path = ROOT / name
    if not path.exists():
        return default
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


class HistoryOverlapTest(unittest.TestCase):
    def test_overlap_is_reported_as_quality_target_not_blocking(self):
        """30 % verified overlap is a QUALITY TARGET (Casper, 13 Oct 2026): the real numbers are reported, a shortfall never fails the suite."""
        current, verification = load("current_offers.json"), load("history_verification.json")
        r = verified_overlap(current, verification, snapshot_date(current))
        self.assertEqual(r["verified"] + r["review_required"] + r["rejected"] + r["no_candidate"], r["active_food_keys"])
        self.assertLessEqual(r["verified"], r["active_food_keys"])
        if r["overlap"] < r["required"]:
            warnings.warn(f"verified history overlap {r['overlap']:.1%} is below the 30% quality target "
                          f"({r['verified']} of {r['active_food_keys']}; {r['additional_verified_needed']} more verified keys needed)")

    def test_history_rows_come_only_from_verified_keys(self):
        r = history_integrity(load("monthly_price_history.json"), load("history_verification.json"))
        self.assertTrue(r["verification_file_present"], "history_verification.json is required next to the history")
        self.assertEqual(r["rows_unverified"], 0, f"{r['rows_unverified']} history rows without verified status")

    def test_verified_status_requires_actual_history(self):
        r = history_integrity(load("monthly_price_history.json"), load("history_verification.json"))
        self.assertEqual(r["verified_without_history"], [], "verified keys without history rows or months")
        self.assertEqual(r["verified_without_raw"], [], "verified keys without a verified raw product")

    def test_history_file_contains_only_verified_history(self):
        hist = load("monthly_price_history.json")
        self.assertIs(hist.get("verified_only"), True, "monthly_price_history.json must be rebuilt with the identity check (verified_only)")
        verification = load("history_verification.json")
        self.assertIsNotNone(verification, "history_verification.json is required next to the history")
        keys = verification["keys"]
        bad = sorted({r["normalized_product_key"] for r in hist["records"]
                      if (keys.get(r["normalized_product_key"]) or {}).get("status") != "verified"})
        self.assertEqual(bad, [], f"{len(bad)} history keys without verified status")

    def test_review_decisions_are_well_formed_and_hash_only(self):
        doc = load("data_sources/history_review_decisions.json")
        if doc is None:
            self.skipTest("no decisions yet")
        self.assertIs(doc.get("raw_data_included"), False)
        seen = set()
        for d in doc["decisions"]:
            self.assertIn(d["decision"], ("verified", "rejected"))
            self.assertRegex(d["raw_id_hash"], r"^[0-9a-f]{16}$")
            self.assertTrue(d.get("reviewed_by") and d.get("reviewed_on"), "decision without reviewer/date is ignored by the importer")
            self.assertTrue(d["normalized_product_key"].startswith("brand="))
            self.assertNotIn((d["normalized_product_key"], d["raw_id_hash"]), seen, "duplicate decision")
            seen.add((d["normalized_product_key"], d["raw_id_hash"]))
            self.assertLessEqual(set(d), {"normalized_product_key", "raw_id_hash", "decision", "reviewed_by", "reviewed_on", "note"})

    def test_every_history_key_is_in_the_identity_registry(self):
        """The next import keeps verified history for every key in the registry, so no existing history key may be missing there."""
        hist, registry = load("monthly_price_history.json"), load("data_sources/history_offer_identities.json")
        self.assertIsNotNone(registry, "identity registry is required so verified history survives expired offers")
        self.assertIs(registry.get("raw_data_included"), False)
        missing = sorted({r["normalized_product_key"] for r in hist["records"]} - set(registry["keys"]))
        self.assertEqual(missing, [], f"{len(missing)} history keys would be dropped by the next import")

    def test_verification_file_holds_no_raw_text(self):
        verification = load("history_verification.json")
        if verification is None:
            self.skipTest("no verification file yet")
        self.assertIs(verification.get("raw_data_included"), False)
        allowed = {"active", "status", "offer_names", "raw_products", "methods", "conflict_fields", "missing_fields", "manual_decisions", "manual_decisions_blocked", "months", "carried_over"}
        for k, v in verification["keys"].items():
            self.assertLessEqual(set(v), allowed, k)


if __name__ == "__main__":
    unittest.main()
