import json
import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from apply_super_deals import annotate
from build_data_pipeline import calculate_unit_price,deal_score,find_duplicates,is_active_offer,validate_import
from product_normalization import normalize_record,normalized_product_key

class AcceptanceTests(unittest.TestCase):
    def test_01_regular_coke_24_pack_is_superdeal(self):
        o={"name":"Coca-Cola 24 x 33 cl","brand":"Coca-Cola","category":"drikkevarer",
           "source_category":"Sodavand","container":"can","package_count":24,"price_dkk":59}
        self.assertTrue(annotate(o,"test")); self.assertEqual(o["super_deal_rule"],"cola_24_cans")
    def test_02_corny_is_not_cola(self):
        o={"name":"Corny Chocolate 24 stk","brand":"Corny","category":"snacks",
           "source_category":"Snacks","container":"box","package_count":24,"price_dkk":59}
        self.assertFalse(annotate(o,"test"))
    def test_03_whipping_cream_category(self):
        out,errs=normalize_record({"id":"x","name":"Thise Piskefløde 38% 500 ml","brand":"Thise","category":"snacks","price_dkk":12})
        self.assertEqual(out["category"],"mejeri"); self.assertEqual(out["product_type"],"whipping_cream")
        self.assertFalse([e for e in errs if e["type"]=="category_uncertain"])
    def test_04_abc_is_videbaek(self):
        prefs=json.loads((ROOT/"store_preferences.json").read_text(encoding="utf-8"))
        abc=prefs["preferred_store_locations"]["ABC Lavpris"]
        location=abc.get("city") if isinstance(abc,dict) else abc
        self.assertEqual(location,"Videbæk")
    def test_05_expired_offer_not_active(self):
        import datetime as dt
        self.assertFalse(is_active_offer({"valid_from":"2025-01-01","valid_to":"2025-01-07"},dt.date(2026,10,5)))
    def test_06_duplicates_are_detected(self):
        a={"id":"1","store":"Netto","name":"Mælk","price_dkk":10,"valid_from":"2026-10-01","valid_to":"2026-10-07"}
        b=dict(a,id="2"); a["normalized_product_key"]=normalized_product_key(a); b["normalized_product_key"]=normalized_product_key(b)
        self.assertEqual(len(find_duplicates([a,b])),1)
    def test_07_import_status_matches_current(self):
        cur=json.loads((ROOT/"current_offers.json").read_text(encoding="utf-8"))
        status=json.loads((ROOT/"import_status.json").read_text(encoding="utf-8"))
        self.assertEqual(cur["offer_count"],len(cur["offers"]))
        self.assertEqual(status["offer_count"],len(cur["offers"]))
        self.assertEqual(status["current_total"],len(cur["offers"]))
    def test_08_unit_price(self):
        p=calculate_unit_price(59,24,33,"cl")
        self.assertEqual(p["unit"],"l"); self.assertAlmostEqual(p["value"],59/7.92,places=3)
    def test_09_deal_score_rewards_historic_low(self):
        self.assertGreaterEqual(deal_score(10,[10,15,20,25]),90)
        self.assertGreater(deal_score(10,[10,15,20,25]),deal_score(25,[10,15,20,25]))
    def test_10_bad_import_blocked(self):
        with self.assertRaises(RuntimeError): validate_import([], [{"id":"old"}],0)
        with self.assertRaises(RuntimeError): validate_import([{"id":"x"}]*70,[{"id":str(i)} for i in range(100)],0)
        with self.assertRaises(RuntimeError): validate_import([{"id":str(i)} for i in range(100)],None,11)
    def test_same_key_current_and_history_shape(self):
        cur={"name":"Coca-Cola 24 x 33 cl","brand":"Coca-Cola","package_count":24,"single_package_amount":33,"single_package_unit":"cl"}
        hist={"name":"Coca-Cola 24x33 cl","package_count":24,"package_amount":33,"package_unit":"cl"}
        self.assertEqual(normalized_product_key(cur),normalized_product_key(hist))

if __name__=="__main__": unittest.main()
