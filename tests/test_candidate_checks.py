import copy, json, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from candidate_checks import COLA_KEYS, EXPECTED_FILES, FAXE_KEY, PROVISIONAL, report, run_checks  # noqa: E402

V = "brand=a|product=verified|variant=standard|count=1|size=1kg"


def ver(keys):
    return {"schema_version": 1, "raw_data_included": False, "keys": keys}


def k(status, **kw):
    base = {"status": status, "offer_names": ["Eget Tilbud"], "raw_products": {"verified": 0, "review_required": 0, "rejected": 0}, "methods": {}, "conflict_fields": {},
            "missing_fields": {}, "manual_decisions": 0, "months": 0}
    base.update(kw)
    return base


def write(d, name, obj):
    p = Path(d) / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj), encoding="utf-8" if isinstance(obj, (dict, list)) else None)


class Fixture(unittest.TestCase):
    def setUp(self):
        self.b, self.a = Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp())
        rows = [{"normalized_product_key": V, "store": "Netto", "month": f"2026-0{m}", "observation_count": 2, "median_price_dkk": 10.0, "min_price_dkk": 9.0, "source": "dagligepriser.dk"} for m in (1, 2, 3)]
        hist = {"raw_data_included": False, "verified_only": True, "records": rows}
        bkeys = {V: k("verified", months=3), FAXE_KEY: k("rejected", raw_products={"verified": 0, "review_required": 0, "rejected": 4}),
                 **{c: k("review_required", raw_products={"verified": 0, "review_required": 3, "rejected": 0}) for c in COLA_KEYS}}
        write(self.b, "monthly_price_history.json", hist)
        write(self.b, "history_verification.json", ver(bkeys))
        write(self.b, "current_offers.json", {"offers": [{"name": "Eget Tilbud"}]})
        write(self.b, "data_sources/history_offer_identities.json", {"keys": {}})
        self.dec = {"status": PROVISIONAL, "decisions": [{"decision": "verified", "normalized_product_key": V, "raw_id_hash": "h"}]}
        write(self.b, "data_sources/history_review_decisions.json", self.dec)
        self.hist = hist
        akeys = copy.deepcopy(bkeys)
        akeys[FAXE_KEY] = k("rejected", carried_over=True)
        akeys[V]["manual_decisions"] = 1
        for name in EXPECTED_FILES:
            write(self.a, name, {})
        write(self.a, "monthly_price_history.json", copy.deepcopy(hist))
        write(self.a, "history_verification.json", ver(akeys))
        (self.a / "report.md").write_text("ok", encoding="utf-8")
        self.akeys = akeys

    def run_(self):
        res, notes = run_checks(self.b, self.a, None)
        return res

    def save(self):
        write(self.a, "history_verification.json", ver(self.akeys))


class Checks(Fixture):
    def test_all_pass(self):
        res = self.run_()
        self.assertEqual({n: v[0] for n, v in res.items()}, {n: "PASS" for n in range(1, 8)}, res)
        self.assertTrue(report(res, [])[1])

    def test_changed_row_fails_1(self):
        h = copy.deepcopy(self.hist); h["records"][0]["median_price_dkk"] = 11.0
        write(self.a, "monthly_price_history.json", h)
        self.assertEqual(self.run_()[1][0], "FAIL")

    def test_lost_verified_fails_2(self):
        self.akeys[V]["status"] = "review_required"; self.save()
        self.assertEqual(self.run_()[2][0], "FAIL")

    def test_cola_pack_size_conflict_fails_3_and_rejected_for_other_reason_fails_3(self):
        self.akeys[COLA_KEYS[0]]["conflict_fields"] = {"pack_size": 3}; self.save()
        self.assertEqual(self.run_()[3][0], "FAIL")
        self.akeys[COLA_KEYS[0]]["conflict_fields"] = {}; self.akeys[COLA_KEYS[0]]["status"] = "rejected"; self.save()
        self.assertEqual(self.run_()[3][0], "FAIL")

    def test_faxe_lost_fails_4(self):
        self.akeys[FAXE_KEY] = k("no_candidate"); self.save()
        self.assertEqual(self.run_()[4][0], "FAIL")

    def test_new_approvals_fail_5_and_changed_status_fails_6(self):
        self.akeys[FAXE_KEY]["manual_decisions"] = 1; self.save()  # approval on a key that has no decision in the file
        self.assertEqual(self.run_()[5][0], "FAIL")
        self.dec["status"] = "final"; write(self.b, "data_sources/history_review_decisions.json", self.dec)
        self.assertEqual(self.run_()[6][0], "FAIL")

    def test_leaks_fail_7(self):
        write(self.a, "extra.txt", {}); self.assertEqual(self.run_()[7][0], "FAIL"); (self.a / "extra.txt").unlink()
        (self.a / "report.md").write_text("token sl." + "A" * 30, encoding="utf-8"); self.assertEqual(self.run_()[7][0], "FAIL")
        (self.a / "report.md").write_text("ok", encoding="utf-8")
        self.akeys[V]["raw_examples"] = [{"raw_name": "x"}]; self.save(); self.assertEqual(self.run_()[7][0], "FAIL")
        del self.akeys[V]["raw_examples"]; self.akeys[V]["offer_names"] = ["Rå produktnavn fra Dropbox"]; self.save()
        self.assertEqual(self.run_()[7][0], "FAIL")


if __name__ == "__main__":
    unittest.main()
