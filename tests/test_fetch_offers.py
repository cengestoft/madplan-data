import datetime as dt, json, sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import fetch_offers as fo

TODAY = dt.date(2026, 10, 16)


def make_item(i):
    return {"id": i, "startDate": "2026-10-16", "endDate": "2026-10-22", "price": "10.00", "currency": "DKK",
            "quantity": "500", "quantityType": "g", "pricePerFullUnitOfQuantityType": "20.00",
            "productName": {"id": 1, "productName": "Vare %d" % i}, "brand": {"name": "M"}, "chain": {"name": "Test"}}


def html(ids, total, last):
    c = {"items": [make_item(i) for i in ids], "totalNumberOfItems": total, "lastValidPageNumber": last}
    doc = {"props": {"pageProps": {"searchResult": {"pageOfOrganicProductOffers": c}}}}
    return ('<script id="__NEXT_DATA__" type="application/json">' + json.dumps(doc) + '</script>').encode()


class FakeSite:
    """cumulative=True: side N viser alle tilbud fra side 1..N (som Tilbudsugen.dk gjorde ved ?page=2)."""
    def __init__(self, total, cumulative):
        self.total, self.cum, self.calls = total, cumulative, []
        self.last = -(-total // 30)

    def get(self, url):
        n = int(url.split("page=")[1]) if "page=" in url else 1
        self.calls.append(n)
        lo = 0 if self.cum else (n - 1) * 30
        ids = list(range(lo, min(n * 30, self.total)))
        return 200, html(ids, self.total, self.last)


class FetchTests(unittest.TestCase):
    def run_chain(self, total, cumulative):
        site = FakeSite(total, cumulative)
        st, offers = fo.fetch_chain("x", "https://example.invalid/tilbud/x", TODAY, site.get, lambda s: None)
        return site, st, offers

    def test_cumulative_needs_only_first_and_last_page(self):
        site, st, offers = self.run_chain(95, True)
        self.assertEqual(site.calls, [1, 4])
        self.assertEqual(len(offers), 95)
        self.assertTrue(st["complete"])

    def test_non_cumulative_walks_all_pages_without_duplicates(self):
        site, st, offers = self.run_chain(95, False)
        self.assertEqual(sorted(set(site.calls)), [1, 2, 3, 4])
        self.assertEqual(len(offers), 95)
        self.assertTrue(st["complete"])

    def test_single_page_chain(self):
        site, st, offers = self.run_chain(20, False)
        self.assertEqual(site.calls, [1])
        self.assertEqual(len(offers), 20)

    def test_http_error_stops_chain_and_is_reported(self):
        st, offers = fo.fetch_chain("x", "https://example.invalid/x", TODAY, lambda u: (429, b""), lambda s: None)
        self.assertEqual(st["stopped"], "http_429")
        self.assertFalse(st["complete"])

    def test_request_budget_is_respected(self):
        site = FakeSite(900, False)
        st, _ = fo.fetch_chain("x", "https://example.invalid/x", TODAY, site.get, lambda s: None, fo.Budget(5))
        self.assertLessEqual(len(site.calls), 5)
        self.assertEqual(st["stopped"], "request_budget")


class BucketTests(unittest.TestCase):
    def test_range_buckets_count_reasons_only(self):
        def it(a, b):
            d = make_item(1); d["startDate"], d["endDate"] = a, b; return d
        items = [it("2026-10-20", "2026-10-10"), it("2026-01-01", "2026-06-01"), it("2026-10-16", "2026-10-22"),
                 it("2026-01-01", "2028-01-01")]
        b = fo.range_buckets(items, TODAY)
        self.assertEqual(dict(b), {"start_efter_slut": 1, "varighed_121_365": 1, "varighed_over_365": 1})


class OutputTests(unittest.TestCase):
    def test_build_output_has_only_offer_fields(self):
        site = FakeSite(3, False)
        st, offers = fo.fetch_chain("x", "https://example.invalid/x", TODAY, site.get, lambda s: None)
        out = fo.build_output([(st, offers)], dt.datetime(2026, 10, 16, 3, 0, tzinfo=dt.timezone.utc))
        self.assertEqual(out["source"], "Tilbudsugen.dk")
        self.assertEqual(out["generated_at"], "2026-10-16T03:00:00Z")
        o = out["stores"]["x"]["offers"]
        self.assertEqual(len(o), 3)
        self.assertEqual(set(o[0]), {"id", "name", "brand", "price_dkk", "unit_price_dkk", "quantity_raw", "quantity_type",
                                     "unit_type", "valid_from", "valid_to", "long_validity"})
        self.assertEqual(o[0]["price_dkk"], 10.0)
        self.assertEqual(o[0]["quantity_raw"], "500")

    def test_main_writes_file_only_with_out(self):
        import tempfile, os
        site = FakeSite(40, False)
        orig = fo.source_probe.CHAINS
        fo.source_probe.CHAINS = {"x": "bilka"}
        try:
            with tempfile.TemporaryDirectory() as d:
                self.assertEqual(fo.main(site.get, lambda s: None, argv=[]), 0)
                self.assertEqual(os.listdir(d), [])
                path = os.path.join(d, "data", "offers.json")
                self.assertEqual(fo.main(site.get, lambda s: None, argv=["--out", path]), 0)
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                self.assertEqual(len(data["stores"]["x"]["offers"]), 40)
        finally:
            fo.source_probe.CHAINS = orig


if __name__ == "__main__":
    unittest.main()
