"""Regression tests (19 Oct 2026): multipack identities must describe the same as the full offer, and documented rejections must not vanish."""
import json, subprocess, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from history_identity import REJECTED, carry_over_rejections, compare, describe  # noqa: E402
from history_import_guard import check  # noqa: E402
from import_dagligepriser_history import identity_record, merge_registry  # noqa: E402

COLA = {"standard25": "brand=coca-cola|product=cola|variant=standard|count=24|size=0-25l",
        "zero25": "brand=coca-cola|product=cola|variant=zero|count=24|size=0-25l",
        "zero33": "brand=coca-cola|product=cola|variant=zero|count=24|size=0-33l"}
FAXE = "brand=faxe-kondi|product=sportssodavand-24-pk|variant=standard|count=24|size=0-33l"


def load(name):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


class MultipackIdentity(unittest.TestCase):
    def test_registry_identity_describes_like_full_offer_for_all_multipack_offers(self):
        offers = load("current_offers.json")["offers"]
        reg = load("data_sources/history_offer_identities.json")["keys"]
        ident = lambda r: (r.get("name"), r.get("brand"), r.get("package_amount"), r.get("package_unit"), r.get("package_count"))
        checked = 0
        for o in offers:
            k = o.get("normalized_product_key")
            if not k or float(o.get("package_count") or 1) <= 1:
                continue
            match = [r for r in reg.get(k, []) if ident(r) == ident(o)]
            self.assertTrue(match, f"multipack offer without registry identity: {k}")
            for r in match:
                self.assertEqual(describe(r)["pack_value"], describe(o)["pack_value"], k)
                self.assertEqual(describe(r)["pack_family"], describe(o)["pack_family"], k)
            checked += 1
        self.assertGreaterEqual(checked, 40)  # the 45 multipack offers examined on 19 Oct 2026

    def test_no_double_multiplication(self):
        offer = {"name": "Coca Cola Cola 24 pk.", "brand": "Coca Cola", "package_count": 24, "package_amount": 6, "package_unit": "l",
                 "single_package_amount": 0.25, "single_package_unit": "l", "category": "drikkevarer", "normalized_product_key": COLA["standard25"]}
        full, ident = describe(offer), describe(identity_record(offer))
        self.assertEqual(full["pack_value"], 6.0)
        self.assertEqual(ident["pack_value"], 6.0)

    def test_old_identity_without_single_amount_is_enriched_additively(self):
        offer = {"name": "Coca Cola Cola 24 pk.", "brand": "Coca Cola", "package_count": 24, "package_amount": 6, "package_unit": "l",
                 "single_package_amount": 0.25, "single_package_unit": "l", "category": "drikkevarer", "normalized_product_key": COLA["standard25"]}
        old = {"name": "Coca Cola Cola 24 pk.", "brand": "Coca Cola", "package_count": 24, "package_amount": 6, "package_unit": "l",
               "category": "drikkevarer", "normalized_product_key": COLA["standard25"]}
        out = merge_registry({COLA["standard25"]: [dict(old)]}, [offer])
        self.assertEqual(len(out[COLA["standard25"]]), 1)
        r = out[COLA["standard25"]][0]
        self.assertEqual((r["single_package_amount"], r["single_package_unit"]), (0.25, "l"))
        for f, v in old.items():
            self.assertEqual(r[f], v)  # nothing overwritten

    def test_single_packs_do_not_get_extra_fields(self):
        o = {"name": "KiMs Chips", "brand": "KiMs", "package_count": 1, "package_amount": 150, "package_unit": "g",
             "single_package_amount": 150, "single_package_unit": "g", "normalized_product_key": "k"}
        self.assertNotIn("single_package_amount", identity_record(o))

    def test_coca_cola_keys_have_no_pack_size_conflict_against_matching_raw(self):
        reg = load("data_sources/history_offer_identities.json")["keys"]
        raws = {"standard25": "Coca-Cola 24 x 25 cl", "zero25": "Coca-Cola Zero 24 x 25 cl", "zero33": "Coca-Cola Zero 24 x 33 cl"}
        for name, key in COLA.items():
            raw = {"name": raws[name], "brand": None, "package_amount": None, "package_unit": None, "package_count": None}
            for ident in reg[key]:
                v = compare(describe(raw), describe(ident))
                self.assertNotIn("pack_size", v["conflicts"], f"{key}: {v}")


class RejectionCarryOver(unittest.TestCase):
    def info(self, status="no_candidate", **rp):
        return {"status": status, "raw_products": {"verified": 0, "review_required": 0, "rejected": 0, **rp}}

    def test_rejected_with_zero_raw_matches_stays_rejected(self):
        ki = {FAXE: self.info()}
        kept = carry_over_rejections(ki, {FAXE: {"status": "rejected"}})
        self.assertEqual(kept, [FAXE]); self.assertEqual(ki[FAXE]["status"], REJECTED); self.assertTrue(ki[FAXE]["carried_over"])

    def test_new_evidence_is_judged_normally(self):
        ki = {FAXE: self.info("review_required", review_required=2)}
        self.assertEqual(carry_over_rejections(ki, {FAXE: {"status": "rejected"}}), [])
        self.assertEqual(ki[FAXE]["status"], "review_required"); self.assertNotIn("carried_over", ki[FAXE])

    def test_other_statuses_untouched(self):
        ki = {"a": self.info(), "b": self.info("verified", verified=1)}
        self.assertEqual(carry_over_rejections(ki, {"a": {"status": "review_required"}, "b": {"status": "rejected"}}), [])
        self.assertEqual((ki["a"]["status"], ki["b"]["status"]), ("no_candidate", "verified"))

    def test_guard_blocks_lost_rejection_without_evidence(self):
        before = {"keys": {FAXE: {"status": "rejected", "raw_products": {"rejected": 4}}, "v": {"status": "verified"}}}
        after_ok = {"keys": {FAXE: {"status": "rejected", "carried_over": True, "raw_products": {"verified": 0, "review_required": 0, "rejected": 0}},
                             "v": {"status": "verified"}}, "raw_data_included": False}
        after_bad = {"keys": {FAXE: {"status": "no_candidate", "raw_products": {"verified": 0, "review_required": 0, "rejected": 0}},
                              "v": {"status": "verified"}}, "raw_data_included": False}
        hist = {"records": [{"normalized_product_key": "v", "month": "2026-01", "source": "dagligepriser.dk"}], "verified_only": True,
                "raw_data_included": False, "credit": "dagligepriser.dk"}
        bad = lambda after: [p for p in check(hist, before, hist, after, 1000, {}, {}) if "rejection" in p]
        self.assertEqual(bad(after_ok), [])
        self.assertEqual(len(bad(after_bad)), 1)


class ImporterKeepsRejection(unittest.TestCase):
    def test_end_to_end_previous_rejection_survives_zero_raw(self):
        tmp = Path(tempfile.mkdtemp())
        offer = {"id": "o1", "store": "Netto", "category": "drikkevarer", "price_dkk": 80, "package_amount": 7.92, "package_unit": "l", "package_count": 24,
                 "single_package_amount": 0.33, "single_package_unit": "l", "name": "Faxe Kondi Sportssodavand 24 pk.", "brand": "Faxe Kondi",
                 "valid_from": "2026-10-05", "valid_to": "2026-10-12"}
        from product_normalization import normalized_product_key
        offer["normalized_product_key"] = normalized_product_key(offer)
        (tmp / "current.json").write_text(json.dumps({"generated_at": "2026-10-09T08:00:00+02:00", "offers": [offer]}), encoding="utf-8")
        (tmp / "raw.json").write_text("[]", encoding="utf-8")
        (tmp / "prev.json").write_text(json.dumps({"keys": {offer["normalized_product_key"]: {"status": "rejected"}}}), encoding="utf-8")
        out = subprocess.run([sys.executable, str(ROOT / "scripts" / "import_dagligepriser_history.py"), "--source-file", str(tmp / "raw.json"),
                              "--current-offers", str(tmp / "current.json"), "--output", str(tmp / "monthly.json"), "--decisions", str(tmp / "d.json"),
                              "--identities", str(tmp / "id.json"), "--previous-verification", str(tmp / "prev.json")], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        line = json.loads(out.stdout.strip().splitlines()[0])  # the Actions log prints the numeric fields of this line
        self.assertEqual((line["previous_verification_keys"], line["carried_over_rejections"]), (1, 1))
        ver = json.loads((tmp / "history_verification.json").read_text(encoding="utf-8"))
        v = ver["keys"][offer["normalized_product_key"]]
        self.assertEqual(v["status"], "rejected"); self.assertTrue(v["carried_over"])
        reg = json.loads((tmp / "id.json").read_text(encoding="utf-8"))["keys"][offer["normalized_product_key"]][0]
        self.assertEqual(reg["single_package_amount"], 0.33)


if __name__ == "__main__":
    unittest.main()


class HistoricalMultipack(unittest.TestCase):
    def test_every_multipack_identity_has_a_single_size_that_matches_its_key(self):
        from history_identity import single_from_key
        reg = load("data_sources/history_offer_identities.json")["keys"]
        n = 0
        for k, recs in reg.items():
            for r in recs:
                if float(r.get("package_count") or 1) > 1:
                    n += 1
                    self.assertIsNotNone(r.get("single_package_amount"), k)
                    self.assertAlmostEqual(float(r["package_count"]) * float(r["single_package_amount"]), float(r["package_amount"]), places=6, msg=k)
                    self.assertEqual(describe(r)["pack_value"], round(float(r["package_amount"]), 6), k)
        self.assertGreaterEqual(n, 28)

    def test_single_from_key_never_guesses(self):
        from history_identity import single_from_key
        base = {"normalized_product_key": "brand=x|product=oel-18-pk|variant=standard|count=18|size=0-33l", "package_count": 18, "package_amount": 5.94, "package_unit": "l"}
        self.assertEqual(single_from_key(base), (0.33, "l"))
        self.assertIsNone(single_from_key(dict(base, package_amount=6)))          # total does not match count x size
        self.assertIsNone(single_from_key(dict(base, package_unit="kg")))         # unit differs
        self.assertIsNone(single_from_key(dict(base, normalized_product_key="brand=x|product=y")))  # no size in key
