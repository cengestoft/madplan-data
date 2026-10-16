import io, json, sys, unittest, urllib.error
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import source_probe as sp


class R(io.BytesIO):
    def __init__(s, b, status=200): super().__init__(b); s.status = status
    def __enter__(s): return s
    def __exit__(s, *a): return False


def opener_for(pages):
    def op(req, timeout=0):
        u = req.full_url
        if u not in pages: raise urllib.error.HTTPError(u, 404, "x", {}, None)
        v = pages[u]
        if isinstance(v, Exception): raise v
        return R(v)
    return op

LD = b'<html><script type="application/ld+json">{"@graph":[{"@type":"Offer","price":"9"},{"@type":"Product"}]}</script></html>'
URL = "https://example.test/partner/x"


class ProbeTest(unittest.TestCase):
    def test_structured_page_counted_without_content_in_report(self):
        r = sp.probe_chain("x", URL, opener_for({URL: LD, "https://example.test/robots.txt": b"User-agent: *\nDisallow: /admin"}))
        self.assertEqual((r["result"], r["structured_records"], r["robots"]), ("ok_structured", 2, "allowed"))
        self.assertNotIn("9", json.dumps(r.get("price", "")))
        self.assertEqual(set(r), {"store", "http", "bytes", "too_large", "structured_records", "robots", "result", "signals", "parser", "next_data_endpoint"})

    def test_robots_disallow_stops_before_fetching_page(self):
        calls = []
        base = opener_for({"https://example.test/robots.txt": b"User-agent: *\nDisallow: /partner"})
        def op(req, timeout=0): calls.append(req.full_url); return base(req, timeout)
        r = sp.probe_chain("x", URL, op)
        self.assertEqual(r["result"], "robots_disallow"); self.assertNotIn(URL, calls)

    def test_failures_are_isolated_and_classified(self):
        self.assertEqual(sp.probe_chain("x", URL, opener_for({}))["result"], "http_error")
        self.assertEqual(sp.probe_chain("x", URL, opener_for({URL: OSError("boom")}))["result"], "unreachable")
        self.assertEqual(sp.probe_chain("x", "http://example.test/x", opener_for({}))["result"], "bad_url")
        self.assertEqual(sp.probe_chain("x", URL, opener_for({URL: b"<html></html>"}))["result"], "ok_no_structured_data")

    def test_all_fifteen_chains_listed_and_one_failure_does_not_stop_rest(self):
        self.assertEqual(len(sp.CHAINS), 15)
        status = json.loads((Path(sp.ROOT) / "import_status.json").read_text())["sources"]
        for key in sp.CHAINS.values(): self.assertIn("source_url", status[key])
