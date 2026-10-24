import datetime as dt
import json, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import build_super_deals as b

NOW = "2026-10-17T06:00:00+00:00"
TODAY = "2026-10-17"


def x(name, price, qraw, qtype, utype, unit_price=None, brand="", a="2026-10-12", z="2026-10-25"):
    return {"id": name[:6], "name": name, "brand": brand, "price_dkk": price, "unit_price_dkk": unit_price, "quantity_raw": qraw,
            "quantity_type": qtype, "unit_type": utype, "valid_from": a, "valid_to": z, "long_validity": False}


def run(*offers, store="netto"):
    return b.build({"generated_at": "g", "stores": {store: {"offers": list(offers)}}}, TODAY, NOW)


class SuperDeals(unittest.TestCase):
    def test_cola_24_dåser_udledes_fra_liter(self):
        d = run(x("Coca Cola 24 dåser", 65.0, "7.92", "ltr.", "ds.", 8.2, "Coca Cola"))
        self.assertEqual([o["super_deal_rule"] for o in d["offers"]], ["cola_24_cans"])
        self.assertIn("package_count_fra_liter_og_33cl", d["offers"][0]["derived"])

    def test_cola_24_for_dyr_matcher_ikke(self):
        self.assertEqual(run(x("Coca Cola", 69.0, "7.92", "ltr.", "ds.", 8.7, "Coca Cola"))["super_deal_count"], 0)

    def test_antal_der_ikke_går_op_gættes_ikke(self):
        self.assertEqual(run(x("Coca Cola", 20.0, "7.5", "ltr.", "ds.", 2.7, "Coca Cola"))["super_deal_count"], 0)

    def test_zero_og_pepsi_matcher_ikke(self):
        self.assertEqual(run(x("Coca Cola Zero", 50.0, "7.92", "ltr.", "ds.", 6.3, "Coca Cola Zero"),
                              x("Pepsi Max", 50.0, "7.92", "ltr.", "ds.", 6.3, "Pepsi Max"))["super_deal_count"], 0)

    def test_cola_24_med_stykstørrelse_pr_dåse_og_antal_i_navnet(self):
        # Rigtigt format fra Tilbudsugen 24. okt.: 0,330 l er PR. dåse, antallet står i navnet
        d = run(x("Cola 24 pk.", 65.0, "0.330", "ltr.", "ds.", 8.21, "Coca Cola"))
        self.assertEqual([o["super_deal_rule"] for o in d["offers"]], ["cola_24_cans"])
        o = d["offers"][0]
        self.assertEqual((o["container"], o["package_count"]), ("can", 24))
        self.assertIn("package_count_fra_navn_og_daasestoerrelse", o["derived"])

    def test_cola_24_pr_dåse_grænse_zero_pepsi_og_flasker(self):
        self.assertEqual(run(x("Cola 24 pk.", 69.0, "0.330", "ltr.", "ds.", 8.71, "Coca Cola"))["super_deal_count"], 0)       # ikke under 69
        self.assertEqual(run(x("Cola 24 pk.", 65.0, "0.330", "ltr.", "ds.", 8.21, "Coca Cola Zero"))["super_deal_count"], 0)
        self.assertEqual(run(x("Cola 24 pk.", 65.0, "0.330", "ltr.", "ds.", 8.21, "Pepsi Max"))["super_deal_count"], 0)
        self.assertEqual(run(x("Cola 24 pk.", 65.0, "0.330", "ltr.", "fl.", 8.21, "Coca Cola"))["super_deal_count"], 0)        # flaske, ikke dåse

    def test_cola_24_pr_dåse_gætter_ikke(self):
        self.assertEqual(run(x("Cola", 65.0, "0.330", "ltr.", "ds.", 8.21, "Coca Cola"))["super_deal_count"], 0)              # intet antal i navnet
        self.assertEqual(run(x("Cola 24 pk.", 65.0, "0.330", "ltr.", "ds.", 20.0, "Coca Cola"))["super_deal_count"], 0)       # enhedspris passer ikke
        self.assertEqual(run(x("Cola 24 pk.", 65.0, "0.400", "ltr.", "ds.", 6.8, "Coca Cola"))["super_deal_count"], 0)         # ukendt dåsestørrelse
        self.assertEqual(run(x("Cola 2 pk.", 10.0, "0.330", "ltr.", "ds.", 15.2, "Coca Cola"))["super_deal_count"], 0)          # for få

    def test_cola_24_pr_dåse_25_cl(self):
        d = run(x("Cola 24 pk.", 60.0, "0.250", "ltr.", "ds.", 10.0, "Coca Cola"))
        self.assertEqual([o["package_count"] for o in d["offers"]], [24])

    def test_stor_flaske_under_11_kr_pr_liter(self):
        d = run(x("Coca Cola", 18.0, "1.5", "ltr.", "fl.", 10.0, "Coca Cola"))
        self.assertEqual([o["super_deal_rule"] for o in d["offers"]], ["cola_large_bottle"])
        self.assertEqual(run(x("Coca Cola", 18.0, "0.5", "ltr.", "fl.", 10.0, "Coca Cola"))["super_deal_count"], 0)

    def test_smør_men_ikke_smørbar(self):
        self.assertEqual(run(x("Smør", 20.0, "0.5", "kg.", "pk.", 40.0))["super_deal_count"], 1)
        self.assertEqual(run(x("Smørbar", 15.0, "0.5", "kg.", "pk.", 30.0))["super_deal_count"], 0)

    def test_udløbne_og_uden_pris_ignoreres(self):
        d = run(x("Smør", 20.0, "0.5", "kg.", "pk.", 40.0, z="2026-10-16"), x("Smør", None, "0.5", "kg.", "pk.", 40.0))
        self.assertEqual(d["super_deal_count"], 0)
        self.assertEqual(d["scanned"], 2)

    def test_ukendt_butik_ignoreres_og_kun_kilde_og_tal_i_output(self):
        d = run(x("Smør", 20.0, "0.5", "kg.", "pk.", 40.0), store="ukendt")
        self.assertEqual((d["scanned"], d["super_deal_count"]), (0, 0))
        self.assertEqual(d["source"], "Tilbudsugen.dk")

    def test_main_skriver_atomisk_fil(self):
        with tempfile.TemporaryDirectory() as t:
            p, q = Path(t, "in.json"), Path(t, "out.json")
            p.write_text(json.dumps({"stores": {"netto": {"offers": [x("Smør", 20.0, "0.5", "kg.", "pk.", 40.0)]}}}))
            b.main(["--in", str(p), "--out", str(q)], now=dt.datetime.fromisoformat(NOW))
            self.assertEqual(json.loads(q.read_text())["super_deal_count"], 1)
            self.assertFalse(Path(str(q) + ".tmp").exists())


if __name__ == "__main__":
    unittest.main()
