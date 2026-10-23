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

    def test_large_chain_above_old_45_page_limit_is_complete(self):
        # Bilka havde 1339 af mere end 1350 tilbud hentet, fordi grænsen var 45 sider (~1350 tilbud) og kæden blev meldt ufuldstændig.
        site, st, offers = self.run_chain(1800, True)
        self.assertEqual(site.calls, [1, 60])
        self.assertEqual(len(offers), 1800)
        self.assertTrue(st["complete"])

    def test_large_non_cumulative_chain_walks_all_pages(self):
        site, st, offers = self.run_chain(1800, False)
        self.assertGreaterEqual(len(offers), 1800 * fo.COMPLETE_SHARE)
        self.assertTrue(st["complete"])
        self.assertLessEqual(max(site.calls), 60)

    def test_chain_above_page_cap_is_still_reported_incomplete(self):
        site, st, offers = self.run_chain(80 * 30 + 600, True)
        self.assertFalse(st["complete"])
        self.assertLessEqual(max(site.calls), fo.MAX_PAGES)

    def test_pages_needed_is_uncapped_and_recorded(self):
        site, st, offers = self.run_chain(80 * 30 + 600, True)
        self.assertEqual(st["pages_needed"], -(-(80 * 30 + 600) // 30))   # 100 > MAX_PAGES: behovet ses trods klipning
        self.assertEqual(st["last_page"], fo.MAX_PAGES)

    def test_fetch_report_has_only_numbers_and_never_offers(self):
        site, st, offers = self.run_chain(95, True)
        rep = fo.fetch_report([(st, offers)], requests_left=fo.MAX_REQUESTS - 7)
        self.assertEqual(rep["page_limit"], fo.MAX_PAGES)
        self.assertEqual(rep["request_budget"], fo.MAX_REQUESTS)
        self.assertEqual(rep["requests_used"], 7)
        self.assertEqual(rep["chains"]["x"], {"pages_fetched": 2, "pages_needed": 4, "stopped": None})
        self.assertNotIn("offers", json.dumps(rep))

    def test_guarded_output_carries_fetch_report_without_changing_stores_or_import_report(self):
        site, st, offers = self.run_chain(95, True)
        ps = [(dict(st, store=s), offers) for s in "abcd"]
        a, ra = fo.build_guarded_output(ps, dt.datetime(2026, 10, 16, 6, 0, tzinfo=dt.timezone.utc), None, TODAY)
        b, rb = fo.build_guarded_output(ps, dt.datetime(2026, 10, 16, 6, 0, tzinfo=dt.timezone.utc), None, TODAY, requests_left=300)
        self.assertIn("fetch_report", b)
        self.assertEqual(b["fetch_report"]["requests_used"], fo.MAX_REQUESTS - 300)
        self.assertEqual(a["stores"], b["stores"])
        self.assertEqual(a["import_report"], b["import_report"])
        self.assertEqual(ra, rb)

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
                self.assertEqual(fo.main(site.get, lambda s: None, argv=[], today=TODAY), 0)
                self.assertEqual(os.listdir(d), [])
                path = os.path.join(d, "data", "offers.json")
                self.assertEqual(fo.main(site.get, lambda s: None, argv=["--out", path], today=TODAY), 0)
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                self.assertEqual(len(data["stores"]["x"]["offers"]), 40)
        finally:
            fo.source_probe.CHAINS = orig


if __name__ == "__main__":
    unittest.main()
