import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from promote_future_offers import promote

TODAY = dt.date(2026, 10, 13)


def offer(name, vf, vt, price=10):
    return {"store": "Lidl", "name": name, "category": "kolonial", "price_dkk": price, "package_amount": 250, "package_unit": "g",
            "valid_from": vf, "valid_to": vt, "member_only": True, "organic": None}


class PromoteFutureOffers(unittest.TestCase):
    def run_promote(self, current_offers, next_offers):
        return promote({"offers": current_offers, "offer_count": len(current_offers)}, {"offers": next_offers}, TODAY)

    def test_only_offers_valid_today_with_documented_end_are_promoted(self):
        nxt = [offer("Gyldig", "2026-10-11", "2026-10-17"), offer("Fremtid", "2026-10-15", "2026-10-17"),
               offer("Uden slutdato", "2026-10-11", None), offer("Udløbet", "2026-10-01", "2026-10-12")]
        c2, n2, promoted, no_end, _ = self.run_promote([], nxt)
        self.assertEqual([o["name"] for o in promoted], ["Gyldig"])
        self.assertEqual({o["name"] for o in n2["offers"]}, {"Fremtid", "Uden slutdato", "Udløbet"})
        self.assertEqual(no_end, 1)
        self.assertEqual(c2["offer_count"], 1)

    def test_no_end_date_is_never_invented(self):
        _, n2, promoted, _, _ = self.run_promote([], [offer("Uden slutdato", "2026-10-11", None)])
        self.assertEqual(promoted, [])
        self.assertIsNone(n2["offers"][0]["valid_to"])

    def test_no_duplicates_when_already_current(self):
        o = offer("Gyldig", "2026-10-11", "2026-10-17")
        c2, n2, promoted, _, present = self.run_promote([dict(o, id="x1")], [o])
        self.assertEqual((len(c2["offers"]), promoted, present, n2["offers"]), (1, [], 1, []))

    def test_promoted_ids_are_stable(self):
        o = offer("Gyldig", "2026-10-11", "2026-10-17")
        self.assertEqual(self.run_promote([], [o])[2][0]["id"], self.run_promote([], [o])[2][0]["id"])


if __name__ == "__main__":
    unittest.main()
