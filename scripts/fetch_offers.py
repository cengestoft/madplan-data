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
import offer_parser  # noqa: E402
import source_probe  # noqa: E402

UA = source_probe.UA
MAX_BYTES = 25 * 1024 * 1024
DELAY = 2.0
MAX_PAGES = 45
MAX_REQUESTS = 400
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
    seen, offers, reasons = set(), {}, collections.Counter()

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
        for r in ok:
            offers[r["id"]] = r
        return info

    info = load(1)
    if info is None:
        return st, offers
    st["total_reported"], st["last_page"] = info.get("totalNumberOfItems"), min(info.get("lastValidPageNumber") or 1, MAX_PAGES)
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
    return st, offers


def summary_lines(results):
    lines = ["| kilde | sider hentet | set/i alt | accepteret | afvist | kæde | komplet | stop |", "|---|---|---|---|---|---|---|---|"]
    for st in results:
        lines.append("| %s | %s | %s/%s | %s | %s | %s | %s | %s |" % (
            st["store"], st["pages_fetched"], st["fetched_ids"], st["total_reported"], st["accepted"],
            json.dumps(st["rejected"], ensure_ascii=False), ",".join(st["chains"]) or "-",
            "ja" if st["complete"] else "nej", st["stopped"] or "-"))
    tot = sum(st["accepted"] for st in results)
    lines += ["", "accepteret i alt: %d, forespørgsler i alt: %d" % (tot, sum(st["pages_fetched"] for st in results))]
    return lines


def main(get=http_get, sleep=time.sleep):
    status = json.loads((ROOT / "import_status.json").read_text(encoding="utf-8"))["sources"]
    today, budget, results = dt.date.today(), Budget(), []
    for slug, key in source_probe.CHAINS.items():
        url = (status.get(key) or {}).get("source_url")
        if not url:
            results.append({"store": slug, "pages_fetched": 0, "total_reported": None, "fetched_ids": 0, "accepted": 0,
                            "rejected": {}, "complete": False, "stopped": "no_source_url", "chains": {}})
            continue
        st, _offers = fetch_chain(slug, url, today, get, sleep, budget)  # prøvekørsel: tilbuddene droppes
        results.append(st)
        sleep(DELAY)
    text = "\n".join(summary_lines(results))
    print(text)
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write("## Hent alle tilbudssider (prøvekørsel, intet gemmes)\n\n" + text + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
