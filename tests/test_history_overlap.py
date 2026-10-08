import json
import unittest


class HistoryOverlapTest(unittest.TestCase):
    def test_history_overlap(self):
        current=json.load(open("current_offers.json",encoding="utf-8"))
        history=json.load(open("monthly_price_history.json",encoding="utf-8"))

        # Use the same grocery scope as the raw-history builder. Household and
        # pet-food offers are intentionally outside the published food history.
        current_keys={
            x.get("normalized_product_key")
            for x in current.get("offers",[])
            if x.get("normalized_product_key")
            and str(x.get("category") or "").lower() not in {"husholdning","dyrefoder"}
        }
        history_keys={
            x.get("normalized_product_key")
            for x in history.get("records",[])
            if x.get("normalized_product_key")
        }
        overlap=len(current_keys & history_keys)/max(1,len(current_keys))
        self.assertGreaterEqual(
            overlap,0.30,
            f"history overlap below 30% in grocery scope: {overlap:.1%}"
        )


if __name__=="__main__":
    unittest.main()
