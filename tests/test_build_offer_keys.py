import json, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import build_offer_keys as k
from build_super_deals import to_app_offer
from product_normalization import normalize_record

NOW = "2026-10-17T06:00:00+00:00"


def x(i, name, price, qraw, qtype, utype="pk.", brand=""):
    return {"id": i, "name": name, "brand": brand, "price_dkk": price, "unit_price_dkk": None, "quantity_raw": qraw, "quantity_type": qtype,
            "unit_type": utype, "valid_from": "2026-10-12", "valid_to": "2026-10-25", "long_validity": False}


def key_of(row, slug="netto"):
    return normalize_record(to_app_offer(slug, row))[0]["normalized_product_key"]


def ver(*keys, status="verified"):
    return {"generated_at": "v", "keys": {kk: {"status": status} for kk in keys}}


def run(rows, verification, store="netto"):
    return k.build({"generated_at": "g", "stores": {store: {"offers": rows}}}, verification, NOW)


class OfferKeys(unittest.TestCase):
    def test_eksakt_verificeret_nøgle_gemmes_pr_tilbuds_id(self):
        row = x(11, "Letmælk", 10.0, "1", "ltr.")
        d = run([row], ver(key_of(row)))
        self.assertEqual(d["keys"], {"11": key_of(row)})
        self.assertEqual((d["exact_verified"], d["scanned"]), (1, 1))
        self.assertEqual(d["offers_file_generated_at"], "g")

    def test_ikke_verificeret_nøgle_bruges_ikke(self):
        row = x(11, "Letmælk", 10.0, "1", "ltr.")
        for st in ("review_required", "rejected", "no_candidate"):
            self.assertEqual(run([row], ver(key_of(row), status=st))["keys"], {})

    def test_anden_pakning_tælles_men_gemmes_ikke(self):
        a, b = x(1, "Letmælk", 10.0, "1", "ltr."), x(2, "Letmælk", 8.0, "0.5", "ltr.")
        d = run([b], ver(key_of(a)))
        self.assertEqual((d["keys"], d["similar_pack"]), ({}, 1))

    def test_uden_pris_eller_id_eller_ukendt_butik_ignoreres(self):
        row = x(11, "Letmælk", 10.0, "1", "ltr.")
        v = ver(key_of(row))
        self.assertEqual(run([dict(row, price_dkk=None)], v)["keys"], {})
        self.assertEqual(run([dict(row, id=None)], v)["keys"], {})
        self.assertEqual(run([row], v, store="ukendt")["scanned"], 0)

    def test_tomme_og_manglende_input(self):
        self.assertEqual(k.build({}, {}, NOW)["keys"], {})
        self.assertEqual(k.verified_keys({"keys": {"a": "x", "b": {"status": "verified"}}}), {"b"})

    def test_main_skriver_fil_uden_rå_data(self):
        row = x(11, "Letmælk", 10.0, "1", "ltr.")
        with tempfile.TemporaryDirectory() as t:
            p, v, q = Path(t, "in.json"), Path(t, "v.json"), Path(t, "out.json")
            p.write_text(json.dumps({"generated_at": "g", "stores": {"netto": {"offers": [row]}}}))
            v.write_text(json.dumps(ver(key_of(row))))
            k.main(["--in", str(p), "--verification", str(v), "--out", str(q)])
            out = json.loads(q.read_text())
            self.assertEqual(sorted(out["keys"]), ["11"])
            self.assertNotIn("Letmælk", q.read_text())
            self.assertFalse(Path(str(q) + ".tmp").exists())


if __name__ == "__main__":
    unittest.main()
