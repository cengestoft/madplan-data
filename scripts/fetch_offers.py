#!/usr/bin/env python3
"""Henter ALLE tilbudssider fra Tilbudsugen.dk for de 15 kilder (kun prøvekørsel: gemmer ingen data).

Tilladelse: Tilbudsugen.dk har skrevet (16/10 2026) at privat, ikke-kommerciel brug er tilladt, inkl. automatisk
hentning med rimelig belastning (fx én gang dagligt) og lagring af navne, priser, butikker og gyldighedsperioder.
Kilden skal angives som Tilbudsugen.dk i appen. Data må ikke videregives uden for den nærmeste familie.

Høflighed: 2 sek. pause mellem forespørgsler, højst 400 forespørgsler pr. kørsel, stop ved 429/5xx.
Strategi: side 1, derefter sidste side. Giver sidste side næsten alle tilbud (kumulativ paginering), stopper vi;
ellers hentes side 2..N-1 én ad gangen indtil alle id'er er set.
Rapporten (log + kørselsoversigt) indeholder KUN tal og kædenavne.
"""
import collections
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import offer_guard  # noqa: E402
import offer_parser  # noqa: E402
import source_probe  # noqa: E402

UA = source_probe.UA
MAX_BYTES = 25 * 1024 * 1024
DELAY = 2.0
MAX_PAGES = 80
MAX_REQUESTS = 600
COMPLETE_SHARE = 0.98


class Budget:
    def __init__(self, n=MAX_REQUESTS):
        self.left = n


def http_get(url, opener=urllib.request.urlopen):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html"})
    try:
        with opener(req, timeout=60) as r:
            return r.status, r.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as e:
        return e.code, b""
    except Exception:
        return None, b""


def page_url(url, n):
    return url if n == 1 else url + ("&" if urllib.parse.urlparse(url).query else "?") + "page=%d" % n


def fetch_chain(slug, url, today, get=http_get, sleep=time.sleep, budget=None):
    budget = budget or Budget()
    st = {"store": slug, "pages_fetched": 0, "total_reported": None, "last_page": None, "fetched_ids": 0,
          "accepted": 0, "rejected": {}, "complete": False, "stopped": None, "chains": {}}
    seen, offers, reasons, buckets = set(), {}, collections.Counter(), collections.Counter()

    def load(n):
        if budget.left <= 0:
            st["stopped"] = "request_budget"; return None
        budget.left -= 1
        status, body = get(page_url(url, n))
        st["pages_fetched"] += 1
        if status != 200 or len(body) > MAX_BYTES:
            st["stopped"] = "http_%s" % status if status != 200 else "too_large"; return None
        items, info, _ = offer_parser.next_items(body.decode("utf-8", "replace"))
        if not items:
            st["stopped"] = "no_items"; return None
        new = [i for i in items if i.get("id") not in seen]
        seen.update(i.get("id") for i in new)
        ok, _ = offer_parser.accept_items(new, today, reasons)
        buckets.update(range_buckets(new, today))
        for r in ok:
            offers[r["id"]] = r
        return info

    info = load(1)
    if info is None:
        return st, offers
    st["pages_needed"] = info.get("lastValidPageNumber") or 1  # ukappet: kun til overvågning, bruges ikke af importvagten
    st["total_reported"], st["last_page"] = info.get("totalNumberOfItems"), min(st["pages_needed"], MAX_PAGES)
    total = st["total_reported"] or len(seen)
    done = lambda: len(seen) >= total * COMPLETE_SHARE
    last = st["last_page"]
    if last > 1 and not done():
        sleep(DELAY)
        if load(last) is not None:
            st["strategy"] = "last_page_first"
    n = 2
    while n < last and not done() and not st["stopped"]:
        sleep(DELAY)
        if load(n) is None:
            break
        n += 1
    st["fetched_ids"], st["accepted"], st["rejected"] = len(seen), len(offers), dict(reasons)
    st["complete"] = done()
    st["chains"] = dict(collections.Counter(r["chain"] or "?" for r in offers.values()).most_common(3))
    st["date_issues"] = dict(buckets)
    st["long_validity"] = sum(1 for r in offers.values() if r.get("long_validity"))
    return st, offers


def range_buckets(items, today):
    """Tæller kun, hvorfor datoer afvises (ingen værdier): start efter slut, eller varighed i intervaller."""
    out = collections.Counter()
    for it in items:
        c = offer_parser.candidate_from_item(it)
        a, b = c["valid_from"], c["valid_to"]
        if a is None or b is None:
            out["mangler_dato"] += 1
        elif a > b:
            out["start_efter_slut"] += 1
        else:
            d = (b - a).days
            if d > offer_parser.MAX_DAYS:
                out["varighed_63_120" if d <= 120 else "varighed_121_365" if d <= 365 else "varighed_over_365"] += 1
    return out


def summary_lines(results):
    lines = ["| kilde | sider hentet | set/i alt | accepteret | afvist | kæde | komplet | stop |", "|---|---|---|---|---|---|---|---|"]
    for st in results:
        lines.append("| %s | %s | %s/%s | %s | %s | %s | %s | %s |" % (
            st["store"], st["pages_fetched"], st["fetched_ids"], st["total_reported"], st["accepted"],
            json.dumps(st["rejected"], ensure_ascii=False), ",".join(st["chains"]) or "-",
            "ja" if st["complete"] else "nej", st["stopped"] or "-"))
    issues = [(st["store"], st["date_issues"]) for st in results if st.get("date_issues")]
    if issues:
        lines += ["", "datoafvisninger (kun tal): " + "; ".join("%s %s" % (n, json.dumps(d, ensure_ascii=False)) for n, d in issues)]
    longs = [(st["store"], st["long_validity"]) for st in results if st.get("long_validity")]
    if longs:
        lines += ["", "accepterede tilbud med varighed over %d dage (markeret long_validity): " % offer_parser.LONG_DAYS
                  + "; ".join("%s %d" % x for x in longs)]
    tot = sum(st["accepted"] for st in results)
    lines += ["", "accepteret i alt: %d, forespørgsler i alt: %d" % (tot, sum(st["pages_fetched"] for st in results))]
    return lines


OFFER_FIELDS = (("id", "id"), ("name", "name"), ("brand", "brand"), ("price_dkk", "price_dkk"), ("unit_price", "unit_price_dkk"),
                ("quantity_raw", "quantity_raw"), ("quantity_type", "quantity_type"), ("unit_type", "unit_type"),
                ("valid_from", "valid_from"), ("valid_to", "valid_to"), ("long_validity", "long_validity"))


def store_entry(st, offers):
    return {"chain": next(iter(st.get("chains") or {}), None), "total_reported": st["total_reported"],
            "accepted": st["accepted"], "complete": st["complete"], "rejected": st["rejected"],
            "offers": [{out: o.get(src) for src, out in OFFER_FIELDS} for _, o in sorted(offers.items(), key=lambda kv: str(kv[0]))]}


def build_output(per_store, now=None):
    """Uden importvagt (bevaret til kompatibilitet). Brug build_guarded_output i produktion."""
    now = now or dt.datetime.now(dt.timezone.utc)
    return {"generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "source": "Tilbudsugen.dk",
            "source_url": "https://www.tilbudsugen.dk",
            "use": "Privat, ikke-kommerciel brug. Må kun deles med nærmeste familie. Angiv Tilbudsugen.dk som datakilde.",
            "stores": {st["store"]: store_entry(st, offers) for st, offers in per_store}}


def fetch_report(per_store, requests_left=None):
    """Kun tal til overvågning (ingen tilbud): sider hentet og krævet pr. kæde, grænser og forbrugte forespørgsler.
    Ligger uden for stores/import_report og læses ikke af importvagten."""
    chains = {st["store"]: {"pages_fetched": st.get("pages_fetched", 0), "pages_needed": st.get("pages_needed"),
                            "stopped": st.get("stopped")} for st, _ in per_store}
    rep = {"page_limit": MAX_PAGES, "request_budget": MAX_REQUESTS, "chains": chains}
    if requests_left is not None:
        rep["requests_used"] = MAX_REQUESTS - requests_left
    return rep


def build_guarded_output(per_store, now=None, prev_doc=None, today=None, requests_left=None):
    """Samlet fil til privat lager. Kun navn, pris, butik og gyldighed (ingen billeder eller links).
    Importvagten (offer_guard) beslutter pr. butik, om nye data må erstatte forrige. Returnerer (fil eller None, rapport)."""
    now = now or dt.datetime.now(dt.timezone.utc)
    today = today or now.date()
    body, summary = offer_guard.assemble(per_store, prev_doc, today, now, store_entry)
    if body is None:
        return None, summary
    doc = {"generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "source": "Tilbudsugen.dk",
           "source_url": "https://www.tilbudsugen.dk",
           "use": "Privat, ikke-kommerciel brug. Må kun deles med nærmeste familie. Angiv Tilbudsugen.dk som datakilde.",
           "stores": body["stores"], "import_report": body["import_report"],
           "fetch_report": fetch_report(per_store, requests_left)}
    return doc, summary


def main(get=http_get, sleep=time.sleep, argv=None):
    argv = sys.argv[1:] if argv is None else argv
    out_path = argv[argv.index("--out") + 1] if "--out" in argv else None
    status = json.loads((ROOT / "import_status.json").read_text(encoding="utf-8"))["sources"]
    today, budget, results, per_store = dt.date.today(), Budget(), [], []
    for slug, key in source_probe.CHAINS.items():
        url = (status.get(key) or {}).get("source_url")
        if not url:
            results.append({"store": slug, "pages_fetched": 0, "total_reported": None, "fetched_ids": 0, "accepted": 0,
                            "rejected": {}, "complete": False, "stopped": "no_source_url", "chains": {}})
            continue
        st, offers = fetch_chain(slug, url, today, get, sleep, budget)
        results.append(st)
        per_store.append((st, offers))
        sleep(DELAY)
    text = "\n".join(summary_lines(results))
    print(text)
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write("## Hent alle tilbudssider (prøvekørsel, intet gemmes)\n\n" + text + "\n")
    if out_path:
        prev = offer_guard.load_previous(out_path)
        doc, summary = build_guarded_output(per_store, prev_doc=prev, today=today, requests_left=budget.left)
        for slug, r in summary["stores"].items():
            if r["status"] != "ok":
                print("TILBAGEHOLDT %s: %s (accepteret %s, tidligere gyldige %s, væk %s)" % (
                    slug, r["reason"], r["accepted"], r["previous_running"], r["vanished"]))
        if doc is None:
            print("Kørslen blokeret (%s). Filen er uændret." % summary.get("blocked_reason"))
            return 1
        if offer_guard.backup_previous(out_path, prev):
            print("Forrige gyldige fil gemt som %s" % offer_guard.BACKUP_NAME)
        else:
            print("Ingen forrige gyldig fil at tage backup af (eksisterende backup bevares).")
        offer_guard.write_atomic(out_path, doc)
        print("Skrev %s (%d tilbud, %d butikker tilbageholdt)" % (
            out_path, sum(len(s["offers"]) for s in doc["stores"].values()), len(summary["held"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
