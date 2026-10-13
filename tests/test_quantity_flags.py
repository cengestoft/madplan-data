import collections
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import apply_quantity_flags as aqf


def load(name):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


class QuantityFlagTest(unittest.TestCase):
    def setUp(self):
        self.flags = load("data_sources/offer_quantity_flags.json")
        self.offers = load("current_offers.json")["offers"]
        self.by_id = {o["id"]: o for o in self.offers}

    def test_registry_is_well_formed_and_holds_no_raw_data(self):
        self.assertIs(self.flags["raw_data_included"], False)
        ids = [f["offer_id"] for f in self.flags["flags"]]
        self.assertEqual(len(ids), len(set(ids)))
        for f in self.flags["flags"]:
            self.assertEqual(f["status"], "unverified")
            for field in ("store", "name", "checked_on", "as_delivered", "original_source", "not_confirmed_because", "needed_to_confirm"):
                self.assertTrue(f.get(field), field)

    def test_flagged_offers_keep_delivered_quantity_and_carry_the_mark(self):
        """Nothing is corrected by guessing: amounts stay exactly as delivered, the offer is only marked."""
        for f in self.flags["flags"]:
            o = self.by_id.get(f["offer_id"])
            if o is None:
                continue  # expired and removed
            for k, v in f["as_delivered"].items():
                self.assertEqual(o.get(k), v, f"{f['offer_id']} {k} changed without source confirmation")
            self.assertEqual(o.get("quantity_status"), "unverified", f"{f['offer_id']} lacks the mark; run scripts/apply_quantity_flags.py")
            self.assertEqual(o["store"], f["store"])

    def test_marks_are_in_step_with_the_registry(self):
        self.assertEqual(aqf.apply(write=False), [], "run scripts/apply_quantity_flags.py to re-apply the marks")

    def test_every_cross_chain_quantity_conflict_is_flagged(self):
        """Same product text and price in different chains with a different package amount must be flagged, never silent."""
        flagged = {f["offer_id"] for f in self.flags["flags"]}
        groups = collections.defaultdict(list)
        for o in self.offers:
            groups[(" ".join(str(o["name"]).lower().split()), o["price_dkk"])].append(o)
        for key, rows in groups.items():
            if len({r["store"] for r in rows}) < 2:
                continue
            if len({(r["package_amount"], r["package_unit"]) for r in rows}) > 1:
                minority = [r for r in rows if r["id"] in flagged]
                self.assertTrue(minority, f"unflagged quantity conflict: {key} {[(r['store'], r['package_amount']) for r in rows]}")

    def test_unverified_quantities_never_feed_super_deals(self):
        text = json.dumps(load("super_deals_current.json"), ensure_ascii=False)
        for f in self.flags["flags"]:
            self.assertNotIn(f["offer_id"], text)

    def test_coca_cola_history_identities_are_untouched(self):
        """The 24 x 25 cl and 24 x 33 cl keys stay in the identity registry; the flag never rewrites keys or history."""
        registry = load("data_sources/history_offer_identities.json")["keys"]
        for size in ("0-25l", "0-33l"):
            for variant in ("standard", "zero"):
                self.assertIn(f"brand=coca-cola|product=cola|variant={variant}|count=24|size={size}", registry)


if __name__ == "__main__":
    unittest.main()
