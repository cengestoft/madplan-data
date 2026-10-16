import datetime as dt, json, sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import offer_parser as op

TODAY = dt.date(2026, 10, 16)
BLOCK = '<div><span>Annonce</span><span>{name}</span><span>1 stk.</span><span>{rng}</span><span>{price}</span><a href="/single/{i}">Se produkt</a></div>'


def html_page(*blocks):
    return "<html><title>Test</title>" + "".join(blocks) + "</html>"


class ParserTest(unittest.TestCase):
    def test_json_ld_accepts_only_complete_offers(self):
        doc = {"@graph": [
            {"@type": "Product", "name": "Vare A", "offers": {"@type": "Offer", "price": "12.5", "validFrom": "2026-10-15", "priceValidUntil": "2026-10-21"}},
            {"@type": "Product", "name": "Uden dato", "offers": {"price": "5"}},
            {"@type": "Product", "name": "", "offers": {"price": "5", "validFrom": "2026-10-15", "priceValidUntil": "2026-10-21"}},
        ]}
        ok, d = op.parse_page('<script type="application/ld+json">%s</script>' % json.dumps(doc), TODAY)
        self.assertEqual([r["name"] for r in ok], ["Vare A"])
        self.assertEqual((d["source_used"], d["accepted"]), ("json_ld", 1))
        self.assertEqual(d["rejected"].get("no_dates"), 1)

    def test_next_data_records(self):
        doc = {"props": {"pageProps": {"offers": [{"title": "X", "price": 20, "validFrom": "2026-10-15", "validTo": "2026-10-21"},
                                                  {"title": "Y", "price": 0, "validFrom": "2026-10-15", "validTo": "2026-10-21"}]}}}
        ok, d = op.parse_page('<script id="__NEXT_DATA__" type="application/json">%s</script>' % json.dumps(doc), TODAY)
        self.assertEqual(len(ok), 1); self.assertEqual(d["source_used"], "next_data")
        self.assertEqual(d["rejected"], {"no_or_bad_price": 1})

    def test_html_blocks_infer_year_and_flag_it(self):
        page = html_page(BLOCK.format(name="Hakket svinekød", rng="16.10 - 22.10", price="29,95 kr.", i=1),
                         BLOCK.format(name="Mangler pris", rng="16.10 - 22.10", price="", i=2),
                         BLOCK.format(name="Udløbet", rng="01.10 - 07.10", price="10 kr.", i=3))
        ok, d = op.parse_page(page, TODAY)
        self.assertEqual(len(ok), 1)
        self.assertEqual((ok[0]["valid_from"], ok[0]["valid_to"], ok[0]["year_inferred"]), ("2026-10-16", "2026-10-22", True))
        self.assertEqual(ok[0]["price_dkk"], 29.95)
        self.assertEqual(d["rejected"], {"no_or_bad_price": 1, "expired": 1})

    def test_year_rollover(self):
        a, b, inf = op.parse_range("28.12 - 03.01", dt.date(2026, 12, 29))
        self.assertEqual((a, b, inf), (dt.date(2026, 12, 28), dt.date(2027, 1, 3), True))

    def test_empty_shell_yields_nothing_and_no_content_in_diagnostics(self):
        ok, d = op.parse_page("<html><div id='__next'></div></html>", TODAY)
        self.assertEqual((ok, d["accepted"]), ([], 0))
        self.assertTrue(set(d) <= {"source_used", "candidates", "accepted", "rejected", "year_inferred"})

    def test_load_more_counts_and_fingerprint_ignores_numbers(self):
        self.assertEqual(op.load_more_counts("Indlæs flere tilbud (30 af 734)"), (30, 734))
        a = html_page(BLOCK.format(name="Same", rng="1.1 - 2.1", price="5 kr.", i=1))
        b = html_page(BLOCK.format(name="Same", rng="9.9 - 9.10", price="7 kr.", i=2))
        self.assertEqual(op.content_fingerprint(a), op.content_fingerprint(b))




class ShapeTests(unittest.TestCase):
    HTML = ('<div class="grid"><div class="card c1"><a href="/single/11"><img src="x"></a>'
            '<h3>Hakket oksekød</h3><span class="p">25,00 kr.</span><span class="d">16.10 - 22.10</span></div>'
            '<div class="card c1"><a href="/single/12"></a><h3>Mælk</h3><span>9,95 kr</span><span>16.10 - 22.10</span></div></div>')

    def test_shape_has_structure_but_no_content(self):
        shape = op.page_shape(self.HTML)
        self.assertEqual(len(shape), 2)
        self.assertTrue(shape[0]["date_found"])
        text = "\n".join(shape[0]["skeleton"])
        self.assertIn("DATE", text)
        self.assertIn("PRICE_OR_NUM", text)
        self.assertIn("card.c1", text)
        for forbidden in ("Hakket", "oksekød", "25,00", "16.10", "/single/11"):
            self.assertNotIn(forbidden, text)


class NextShapeTests(unittest.TestCase):
    def test_shape_lists_field_types_not_values(self):
        doc = {"props": {"pageProps": {"offers": [
            {"title": "Hakket oksekød 500 g", "price": 25, "dateRange": "16.10 - 22.10", "start": "2026-10-16", "img": "/x.png"}
            for _ in range(4)]}}}
        html = '<script id="__NEXT_DATA__" type="application/json">' + json.dumps(doc) + '</script>'
        sh = op.next_data_shape(html)
        self.assertTrue(sh["found"])
        lp = sh["list_paths"][0]
        self.assertEqual(lp["path"], "$.props.pageProps.offers[]")
        self.assertEqual(lp["fields"]["dateRange"], "DATE_RANGE")
        self.assertEqual(lp["fields"]["start"], "ISO_DATE")
        self.assertNotIn("oksekød", json.dumps(sh))
        self.assertNotIn("2026-10-16", json.dumps(sh))


    def test_wide_items_and_nested_fields_show_types_only(self):
        item = {"f%d" % i: i for i in range(60)}
        item.update({"name": "Kyllingebryst 400 g", "prices": {"current": 29.5, "validTo": "2026-10-22"}, "range": "16.10 - 22.10"})
        doc = {"props": {"pageProps": {"searchResult": {"items": [dict(item) for _ in range(4)]}}}}
        html = '<script id="__NEXT_DATA__" type="application/json">' + json.dumps(doc) + '</script>'
        lp = op.next_data_shape(html)["list_paths"][0]
        self.assertEqual(lp["fields"]["prices"]["validTo"], "ISO_DATE")
        self.assertEqual(lp["fields"]["range"], "DATE_RANGE")
        self.assertNotIn("Kyllingebryst", json.dumps(lp))


def next_page(items, key="searchResult"):
    doc = {"props": {"pageProps": {key: {"pageOfOrganicProductOffers": {"items": items, "currentPage": 1, "totalItems": 734}}}}}
    return '<script id="__NEXT_DATA__" type="application/json">' + json.dumps(doc) + '</script>'


def item(i, price="25.00", start="2026-10-16", end="2026-10-22", name="Testvare", chain="TestButik", currency="DKK"):
    return {"id": i, "startDate": start, "endDate": end, "price": price, "currency": currency, "quantity": "500",
            "quantityType": "g", "unitType": "stk", "pricePerFullUnitOfQuantityType": "50.00",
            "productName": {"id": 1, "productName": name}, "brand": {"id": 2, "name": "M"}, "chain": {"id": 3, "name": chain}}


class NextItemsTests(unittest.TestCase):
    def test_accepts_only_complete_items_and_reports_counts(self):
        html = next_page([item(1), item(2, price=None), item(3, start="2026-10-05", end="2026-10-10"), item(4, name=None),
                          item(5, start="2026-10-23", end="2026-10-20"), item(6, currency="SEK")])
        ok, diag = op.parse_page(html, TODAY)
        self.assertEqual([r["id"] for r in ok], [1])
        self.assertEqual(ok[0]["price_dkk"], 25.0)
        self.assertEqual(ok[0]["valid_from"], "2026-10-16")
        self.assertEqual(diag["source_used"], "next_items")
        self.assertEqual(diag["candidates"], 6)
        self.assertEqual(diag["rejected"], {"no_or_bad_price": 1, "expired": 1, "no_name": 1, "bad_date_range": 1, "not_dkk": 1})
        self.assertEqual(diag["page_info"], {"currentPage": 1, "totalItems": 734})
        self.assertEqual(diag["chains"], {"TestButik": 1})

    def test_data_container_path(self):
        ok, diag = op.parse_page(next_page([item(1), item(2)], key="data"), TODAY)
        self.assertEqual(len(ok), 2)


class LongValidityTests(unittest.TestCase):
    def test_63_to_120_days_accepted_and_flagged_longer_rejected(self):
        html = next_page([item(1, start="2026-10-01", end="2026-12-15"),   # 75 dage
                          item(2, start="2026-10-01", end="2026-10-20"),   # 19 dage
                          item(3, start="2026-10-01", end="2027-03-01")])  # >120 dage
        ok, diag = op.parse_page(html, TODAY)
        self.assertEqual({r["id"]: r["long_validity"] for r in ok}, {1: True, 2: False})
        self.assertEqual(diag["rejected"], {"bad_date_range": 1})


if __name__ == "__main__":
    unittest.main()
