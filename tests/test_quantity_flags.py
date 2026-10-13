import collections
import copy
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import tempfile
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
        aqf.load_flags()  # validates statuses and the fields required to lift a mark
        for f in self.flags["flags"]:
            self.assertIn(f["status"], ("unverified", "confirmed"))
            for field in ("store", "name", "checked_on", "as_delivered", "original_source", "not_confirmed_because", "needed_to_confirm"):
                self.assertTrue(f.get(field), field)

    def test_flagged_offers_keep_delivered_quantity_and_carry_the_mark(self):
        """Nothing is corrected by guessing: amounts stay exactly as delivered, the offer is only marked."""
        for f in self.flags["flags"]:
            o = self.by_id.get(f["offer_id"])
            if o is None or f["status"] != "unverified":
                continue  # expired and removed, or lifted after source confirmation
            for k, v in f["as_delivered"].items():
                self.assertEqual(o.get(k), v, f"{f['offer_id']} {k} changed without source confirmation")
            self.assertEqual(o.get("quantity_status"), "unverified", f"{f['offer_id']} lacks the mark; run scripts/apply_quantity_flags.py")
            self.assertEqual(o["store"], f["store"])

    def test_marks_are_in_step_with_the_registry(self):
        changed, problems = aqf.apply(write=False, today=dt.date.fromisoformat(load("current_offers.json")["generated_at"][:10]))
        self.assertEqual((changed, problems), ([], []), "run scripts/apply_quantity_flags.py to re-apply the marks")

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


TODAY = dt.date(2026, 10, 13)
FLAG_IDS = ("tilbudsugen-11335752", "tilbudsugen-11335755")


def offer(oid, **kw):
    o = {"id": oid, "name": "Coca Cola Cola 24 pk.", "store": "Dagli'Brugsen", "price_dkk": 79, "package_count": 24,
         "single_package_amount": 0.25, "package_amount": 6, "package_unit": "l", "valid_from": "2026-10-01", "valid_to": "2026-10-31"}
    o.update(kw)
    return o


def flag(oid, **kw):
    f = {"offer_id": oid, "status": "unverified"}
    f.update(kw)
    return f


CONFIRM = {"confirmed_by": "Casper", "confirmed_on": "2026-10-14", "confirmed_source": "Avis 40/2026 s. 25",
           "confirmed_quantity": {"package_count": 24, "single_package_amount": 0.25, "package_amount": 6, "package_unit": "l"}}


class ApplyRulesTest(unittest.TestCase):
    def test_mark_is_applied_to_active_offers_only_and_is_idempotent(self):
        active, expired = offer("a"), offer("b", valid_to="2026-10-12")
        flags = {"a": flag("a"), "b": flag("b")}
        n, probs = aqf.apply_to_offers([active, expired], flags, TODAY)
        self.assertEqual((n, probs), (1, []))
        self.assertEqual(active["quantity_status"], "unverified")
        self.assertNotIn("quantity_status", expired, "never (re)created on an expired offer")
        self.assertEqual(aqf.apply_to_offers([active, expired], flags, TODAY), (0, []))

    def test_missing_offers_are_never_created(self):
        offers = [offer("other")]
        self.assertEqual(aqf.apply_to_offers(offers, {"gone": flag("gone")}, TODAY), (0, []))
        self.assertEqual([o["id"] for o in offers], ["other"])
        self.assertNotIn("quantity_status", offers[0])

    def test_a_new_import_does_not_remove_the_mark_from_a_still_active_offer(self):
        flags = {"a": flag("a")}
        first = offer("a"); aqf.apply_to_offers([first], flags, TODAY)
        reimported = offer("a")  # the scan delivers the record again, without the mark
        self.assertNotIn("quantity_status", reimported)
        aqf.apply_to_offers([reimported], flags, TODAY)
        self.assertEqual(reimported["quantity_status"], "unverified")

    def test_only_the_two_mark_fields_change(self):
        o, before = offer("a", brand="Coca Cola", normalized_product_key="k"), None
        before = copy.deepcopy(o)
        aqf.apply_to_offers([o], {"a": flag("a")}, TODAY)
        for k in ("quantity_status", "quantity_note"):
            o.pop(k)
        self.assertEqual(o, before)

    def test_lifting_needs_reviewer_date_source_and_quantity(self):
        for missing in aqf.CONFIRM_FIELDS:
            with tempfile.TemporaryDirectory() as d:
                (Path(d) / "data_sources").mkdir()
                f = flag("a", status="confirmed", **{k: v for k, v in CONFIRM.items() if k != missing})
                (Path(d) / aqf.REGISTRY).write_text(json.dumps({"flags": [f]}))
                with self.assertRaises(aqf.FlagError):
                    aqf.load_flags(d)

    def test_lifting_removes_the_mark_only_when_amounts_match_the_source(self):
        flags = {"a": flag("a", status="confirmed", **CONFIRM)}
        ok = offer("a", quantity_status="unverified", quantity_note=aqf.NOTE)
        self.assertEqual(aqf.apply_to_offers([ok], flags, TODAY), (1, []))
        self.assertNotIn("quantity_status", ok)
        self.assertNotIn("quantity_note", ok)
        wrong = offer("a", quantity_status="unverified", quantity_note=aqf.NOTE, single_package_amount=0.33, package_amount=7.92)
        n, probs = aqf.apply_to_offers([wrong], flags, TODAY)
        self.assertEqual(n, 0)
        self.assertEqual(len(probs), 1)
        self.assertEqual(wrong["quantity_status"], "unverified", "mark stays until the data itself is corrected")
        self.assertEqual(wrong["package_amount"], 7.92, "amounts are never changed by the flag tool")

    def test_confirmed_flag_does_not_mark_anything(self):
        o = offer("a")
        self.assertEqual(aqf.apply_to_offers([o], {"a": flag("a", status="confirmed", **CONFIRM)}, TODAY), (0, []))
        self.assertNotIn("quantity_status", o)


class PipelineIntegrationTest(unittest.TestCase):
    """build_data_pipeline.py applies the registry after an import and before validation/publication."""
    NEEDED = ["current_offers.json", "next_week_offers.json", "import_status.json", "price_history.json", "monthly_price_history.json",
              "history_verification.json", "current_offers.previous.json"]

    def make_root(self, mutate=None, registry=None):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, True)
        for n in self.NEEDED:
            if (ROOT / n).exists():
                (d / n).symlink_to(ROOT / n) if n == "monthly_price_history.json" else shutil.copy(ROOT / n, d / n)
        (d / "stores").mkdir()
        for p in (ROOT / "stores").glob("*.json"):
            shutil.copy(p, d / "stores" / p.name)
        (d / "data_sources").mkdir()
        shutil.copy(ROOT / aqf.REGISTRY, d / aqf.REGISTRY)
        if registry:
            (d / aqf.REGISTRY).write_text(json.dumps(registry), encoding="utf-8")
        # simulate a fresh scan: records arrive WITHOUT the marks
        for path in [d / "current_offers.json", d / "stores/daglibrugsen.json"]:
            doc = json.loads(path.read_text(encoding="utf-8"))
            for o in doc["offers"]:
                o.pop("quantity_status", None); o.pop("quantity_note", None)
                if mutate:
                    mutate(path.name, o)
            path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return d

    def run_pipeline(self, root, today="2026-10-13"):
        env = dict(os.environ); env["PYTHONDONTWRITEBYTECODE"] = "1"
        return subprocess.run([sys.executable, str(ROOT / "scripts/build_data_pipeline.py"), "--root", str(root), "--write", "--today", today],
                              capture_output=True, text=True, env=env)

    def offers(self, root, name):
        return {o["id"]: o for o in json.loads((root / name).read_text(encoding="utf-8"))["offers"]}

    def test_fresh_import_gets_the_mark_back_on_still_active_offers(self):
        root = self.make_root()
        before = {k: v for k, v in self.offers(root, "current_offers.json").items() if k in FLAG_IDS}
        r = self.run_pipeline(root)
        self.assertEqual(r.returncode, 0, r.stderr[-400:])
        for name in ("current_offers.json", "stores/daglibrugsen.json"):
            got = self.offers(root, name)
            for oid in FLAG_IDS:
                self.assertEqual(got[oid]["quantity_status"], "unverified", (name, oid))
        after = self.offers(root, "current_offers.json")
        for oid in FLAG_IDS:  # amounts, prices and keys exactly as delivered
            for k, v in before[oid].items():
                self.assertEqual(after[oid][k], v, (oid, k))
        unmarked = [i for i, o in after.items() if o.get("quantity_status") and i not in FLAG_IDS]
        self.assertEqual(unmarked, [])

    def test_expired_offers_are_not_marked_again(self):
        def expire(name, o):
            if o["id"] in FLAG_IDS:
                o["valid_to"] = "2026-10-12"
        root = self.make_root(mutate=expire)
        r = self.run_pipeline(root)
        self.assertEqual(r.returncode, 0, r.stderr[-400:])
        self.assertTrue(set(FLAG_IDS).isdisjoint(self.offers(root, "current_offers.json")))
        stores = self.offers(root, "stores/daglibrugsen.json")
        for oid in FLAG_IDS:
            self.assertNotIn("quantity_status", stores.get(oid, {}))

    def test_confirmed_lift_with_mismatching_amounts_blocks_publication(self):
        reg = {"flags": [flag(FLAG_IDS[0], status="confirmed", **{**CONFIRM, "confirmed_quantity": {
            "package_count": 24, "single_package_amount": 0.33, "package_amount": 7.92, "package_unit": "l"}})]}
        root = self.make_root(registry=reg)
        before = (root / "current_offers.json").read_bytes()
        r = self.run_pipeline(root)
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual((root / "current_offers.json").read_bytes(), before, "nothing is written when the lift is inconsistent")


if __name__ == "__main__":
    unittest.main()
