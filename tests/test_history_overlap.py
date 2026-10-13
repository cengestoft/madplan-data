import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from offer_schema import offer_status, snapshot_date


def load(name):
    with open(ROOT / name, encoding="utf-8") as fh:
        return json.load(fh)


class HistoryOverlapTest(unittest.TestCase):
    def test_history_overlap(self):
        """At least 30 % of the ACTIVE grocery offer keys must have exact history. Never lower this threshold."""
        current, history = load("current_offers.json"), load("monthly_price_history.json")
        today = snapshot_date(current)
        # Same grocery scope as the raw-history builder: household and pet food are outside the food history.
        current_keys = {
            x.get("normalized_product_key")
            for x in current.get("offers", [])
            if x.get("normalized_product_key")
            and offer_status(x, today) == "active"
            and str(x.get("category") or "").lower() not in {"husholdning", "dyrefoder"}
        }
        history_keys = {x.get("normalized_product_key") for x in history.get("records", []) if x.get("normalized_product_key")}
        overlap = len(current_keys & history_keys) / max(1, len(current_keys))
        self.assertGreaterEqual(
            overlap, 0.30,
            f"history overlap below 30% on active grocery offers: {overlap:.1%} "
            f"({len(current_keys & history_keys)} of {len(current_keys)} keys)"
        )


if __name__ == "__main__":
    unittest.main()
