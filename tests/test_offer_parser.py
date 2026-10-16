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


if __name__ == "__main__":
    unittest.main()
