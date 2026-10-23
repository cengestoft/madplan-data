import datetime as dt, json, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_offers as fo
import offer_guard as og

TODAY = dt.date(2026, 10, 17)
NOW = dt.datetime(2026, 10, 17, 6, 0, tzinfo=dt.timezone.utc)


def offer(i, a="2026-10-12", b="2026-10-25", price=10.0):
    return {"id": i, "name": "Vare %s" % i, "brand": None, "price_dkk": price, "unit_price": None, "quantity_raw": "500",
            "quantity_type": "g", "unit_type": None, "valid_from": a, "valid_to": b, "long_validity": False,
            "chain": "T", "quantity": 500}


def stat(slug, n, **kw):
    st = {"store": slug, "pages_fetched": 2, "total_reported": n, "last_page": 2, "fetched_ids": n, "accepted": n,
          "rejected": {}, "complete": True, "stopped": None, "chains": {"T": n}}
    st.update(kw)
    return st


def fresh(slug, ids, **ofkw):
    offers = {i: offer(i, **ofkw) for i in ids}
    return stat(slug, len(ids)), offers


def prev_doc(stores):
    """stores: {slug: [offer-dicts i filformat]}"""
    out = {}
    for slug, offs in stores.items():
        out[slug] = {"chain": "T", "total_reported": len(offs), "accepted": len(offs), "complete": True, "rejected": {},
                     "offers": [{k: o.get(k) for k in ("id", "name", "brand", "price_dkk", "unit_price", "quantity_raw",
                                                       "quantity_type", "unit_type", "valid_from", "valid_to", "long_validity")} for o in offs]}
    return {"generated_at": "2026-10-16T03:30:00Z", "stores": out}


def four(extra=None):
    d = {s: list(range(30)) for s in ("a", "b", "c", "d")}
    d.update(extra or {})
    return d


def run(per_store, prev):
    return fo.build_guarded_output(per_store, NOW, prev, TODAY)


def prev_of(ids_by_store, **kw):
    return prev_doc({s: [offer(i, **kw) for i in ids] for s, ids in ids_by_store.items()})


class GuardTests(unittest.TestCase):
    def test_normal_update_replaces_store_and_marks_ok(self):
        prev = prev_of(four())
        doc, rep = run([fresh(s, list(range(10, 30)) + list(range(100, 120))) for s in "abcd"], prev)
        self.assertEqual(rep["held"], [])
        self.assertEqual(len(doc["stores"]["a"]["offers"]), 40)
        self.assertEqual(doc["stores"]["a"]["status"], "ok")

    def test_empty_import_for_one_store_keeps_previous_offers(self):
        prev = prev_of(four())
        ps = [fresh(s, range(30)) for s in "bcd"] + [(stat("a", 0, complete=False), {})]
        doc, rep = run(ps, prev)
        self.assertEqual(rep["stores"]["a"]["reason"], "held_empty")
        self.assertEqual(len(doc["stores"]["a"]["offers"]), 30)
        self.assertEqual(doc["stores"]["a"]["status"], "held")
        self.assertEqual(doc["stores"]["a"]["held_since"], "2026-10-17T06:00:00Z")
        self.assertEqual(doc["import_report"]["held"], ["a"])
        self.assertEqual(len(doc["stores"]["b"]["offers"]), 30)

    def test_failure_in_one_store_does_not_block_others(self):
        prev = prev_of(four())
        ps = [fresh(s, list(range(10, 30)) + list(range(200, 210))) for s in "bcd"] + [(stat("a", 90, stopped="http_429", complete=False, fetched_ids=30), {i: offer(i) for i in range(30)})]
        doc, rep = run(ps, prev)
        self.assertEqual(rep["stores"]["a"]["reason"], "held_fetch_stopped")
        self.assertEqual(rep["stores"]["a"]["stopped"], "http_429")
        self.assertEqual({o["id"] for o in doc["stores"]["a"]["offers"]}, set(range(30)))
        self.assertEqual({o["id"] for o in doc["stores"]["b"]["offers"]}, set(range(10, 30)) | set(range(200, 210)))

    def test_partial_import_is_held_even_if_it_has_offers(self):
        prev = prev_of(four())
        st, of = fresh("a", range(5)); st.update(complete=False, total_reported=90)
        doc, rep = run([fresh(s, range(30)) for s in "bcd"] + [(st, of)], prev)
        self.assertEqual(rep["stores"]["a"]["reason"], "held_incomplete")
        self.assertEqual(len(doc["stores"]["a"]["offers"]), 30)

    def test_poor_quality_is_held(self):
        prev = prev_of(four())
        st, of = fresh("a", range(30)); st.update(fetched_ids=60, rejected={"no_or_bad_price": 20, "bad_date_range": 10})
        doc, rep = run([fresh(s, range(30)) for s in "bcd"] + [(st, of)], prev)
        self.assertEqual(rep["stores"]["a"]["reason"], "held_poor_quality")

    def test_expired_rejections_are_not_quality_errors(self):
        st, of = fresh("a", range(30)); st.update(fetched_ids=100, rejected={"expired": 70})
        self.assertEqual(og.evaluate_store(st, of, None, TODAY)[0], "ok")

    def test_natural_switch_between_flyers_is_not_an_error(self):
        # forrige uges 80 tilbud er alle udløbet i går; kun 10 nye. Stort fald i antal, men ingen fejl.
        prev = prev_of({"a": range(80), "b": range(80), "c": range(80), "d": range(80)}, a="2026-10-10", b="2026-10-16")
        doc, rep = run([fresh(s, range(1000, 1010)) for s in "abcd"], prev)
        self.assertEqual(rep["held"], [])
        self.assertEqual(len(doc["stores"]["a"]["offers"]), 10)

    def test_large_drop_while_old_offers_still_valid_is_held(self):
        prev = prev_of(four({"a": list(range(60))}))
        doc, rep = run([fresh(s, range(30)) for s in "bcd"] + [fresh("a", range(10))], prev)
        self.assertEqual(rep["stores"]["a"]["reason"], "held_vanished")
        self.assertEqual(len(doc["stores"]["a"]["offers"]), 60)

    def test_same_offers_with_new_ids_are_not_flagged_as_vanished(self):
        prev = prev_of(four())
        new = {i + 500: offer(i + 500) for i in range(30)}
        for i, o in new.items():
            o["name"] = "Vare %s" % (i - 500)  # samme navn, pris og slutdato som før
        st = stat("a", 30)
        self.assertEqual(og.evaluate_store(st, new, prev["stores"]["a"], TODAY)[0], "ok")

    def test_small_previous_set_is_not_compared(self):
        prev = prev_of({"a": range(5)})
        self.assertEqual(og.evaluate_store(stat("a", 1), {1000: offer(1000)}, prev["stores"]["a"], TODAY)[0], "ok")

    def test_held_store_never_reactivates_expired_offers(self):
        d = four()
        prev = prev_of(d)
        prev["stores"]["a"]["offers"][0]["valid_to"] = "2026-10-16"   # udløbet i går
        ps = [fresh(s, range(30)) for s in "bcd"] + [(stat("a", 0, complete=False), {})]
        doc, _ = run(ps, prev)
        ids = {o["id"] for o in doc["stores"]["a"]["offers"]}
        self.assertNotIn(0, ids)
        self.assertEqual(len(ids), 29)

    def test_future_offers_are_kept_when_held(self):
        prev = prev_of(four({"a": list(range(10))}), a="2026-10-20", b="2026-10-27")
        ps = [fresh(s, range(30)) for s in "bcd"] + [(stat("a", 0, complete=False), {})]
        doc, _ = run(ps, prev)
        self.assertEqual(len(doc["stores"]["a"]["offers"]), 10)

    def test_store_without_previous_data_and_failing_is_unavailable_not_empty(self):
        ps = [fresh(s, range(30)) for s in "bcd"] + [(stat("a", 0, complete=False), {})]
        doc, rep = run(ps, None)
        self.assertEqual(rep["stores"]["a"]["status"], "unavailable")
        self.assertNotIn("a", doc["stores"])

    def test_held_since_and_last_good_are_preserved_across_runs(self):
        prev = prev_of(four())
        prev["stores"]["a"].update(status="held", held_since="2026-10-15T06:00:00Z", last_good_at="2026-10-14T06:00:00Z")
        ps = [fresh(s, range(30)) for s in "bcd"] + [(stat("a", 0, complete=False), {})]
        doc, _ = run(ps, prev)
        self.assertEqual(doc["stores"]["a"]["held_since"], "2026-10-15T06:00:00Z")
        self.assertEqual(doc["stores"]["a"]["last_good_at"], "2026-10-14T06:00:00Z")

    def test_systemic_failure_blocks_whole_run(self):
        prev = prev_of(four())
        ps = [(stat(s, 0, complete=False), {}) for s in "ab"] + [fresh(s, range(30)) for s in "cd"]
        doc, rep = run(ps, prev)
        self.assertIsNone(doc)
        self.assertEqual(rep["blocked_reason"], "systemic_half_or_more_held")

    def test_everything_empty_is_blocked(self):
        doc, rep = run([(stat("a", 0, complete=False), {})], None)
        self.assertIsNone(doc)


class LoadAndMainTests(unittest.TestCase):
    def test_load_previous_rejects_wrong_format(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d, "o.json")
            self.assertIsNone(og.load_previous(p))                       # findes ikke
            for bad in ("", "ikke json", "[]", '{"stores": []}', '{"x": 1}', "null"):
                p.write_text(bad); self.assertIsNone(og.load_previous(p), bad)
            p.write_text('{"stores": {}}'); self.assertIsNotNone(og.load_previous(p))

    def _site(self, total):
        import test_fetch_offers as tf
        return tf.FakeSite(total, True)

    def test_main_keeps_file_unchanged_when_run_is_blocked(self):
        import test_fetch_offers as tf
        good = tf.FakeSite(40, True)
        with tempfile.TemporaryDirectory() as d:
            out = str(Path(d, "data", "offers.json"))
            self.assertEqual(fo.main(good.get, lambda s: None, argv=["--out", out], today=TODAY), 0)
            before = Path(out).read_text()
            self.assertEqual(fo.main(lambda u: (500, b""), lambda s: None, argv=["--out", out], today=TODAY), 1)
            self.assertEqual(Path(out).read_text(), before)
            self.assertFalse(Path(out + ".tmp").exists())

    def test_main_output_contains_import_report_without_content(self):
        import test_fetch_offers as tf
        with tempfile.TemporaryDirectory() as d:
            out = str(Path(d, "o.json"))
            fo.main(tf.FakeSite(40, True).get, lambda s: None, argv=["--out", out], today=TODAY)
            doc = json.loads(Path(out).read_text())
            self.assertEqual(doc["import_report"]["held"], [])
            for r in doc["import_report"]["stores"].values():
                self.assertEqual(set(r), {"accepted", "previous_running", "vanished", "bad_share", "status", "reason"})


if __name__ == "__main__":
    unittest.main()
