#!/usr/bin/env python3
"""Streng tilbudsparser (kun diagnostik, skriver ALDRIG tilbud til repositoryet).

Accepterer kun poster med navn + pris + gyldighedsdatoer (valid_from <= valid_to). Alt andet afvises
og tælles pr. årsag. Tre kilder forsøges i prioriteret rækkefølge: JSON-LD, __NEXT_DATA__ (Next.js)
og tekstblokke i server-renderet HTML (blokke afgrænset af /single/<id>-links).

STATUS: Parseren er testet mod syntetiske fixtures. Den er IKKE verificeret mod live-HTML endnu;
det er formålet med diagnoserapporten fra GitHub Actions (se source_probe.py).
"""
import collections
import datetime as dt
import hashlib
import json
import re
from html.parser import HTMLParser

RE_LD = re.compile(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.I | re.S)
RE_NEXT = re.compile(r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>', re.I | re.S)
RE_RANGE = re.compile(r"(?<!\d)(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?\s*[-–]\s*(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?(?!\d)")
RE_PRICE = re.compile(r"(?<![\d,.])(\d{1,4}(?:[.,]\d{1,2})?)\s*(?:kr\.?|,-|DKK)", re.I)
RE_LOADMORE = re.compile(r"Indlæs flere tilbud\s*\((\d+)\s*af\s*(\d+)\)", re.I)
RE_SINGLE = re.compile(r"/single/(\d+)")
MAX_DAYS = 62
NAME_KEYS = ("name", "title", "productName", "product_name", "heading")
PRICE_KEYS = ("price", "price_dkk", "priceDkk", "offerPrice", "salePrice")
FROM_KEYS = ("valid_from", "validFrom", "startDate", "from", "start", "priceValidFrom")
TO_KEYS = ("valid_to", "validTo", "endDate", "to", "end", "priceValidUntil")


def _num(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        m = re.fullmatch(r"\s*(\d{1,5}(?:[.,]\d{1,2})?)\s*(?:kr\.?|DKK|,-)?\s*", v, re.I)
        if m:
            return float(m.group(1).replace(",", "."))
    return None


def _date(v):
    if isinstance(v, str):
        try:
            return dt.date.fromisoformat(v[:10])
        except ValueError:
            return None
    return None


def parse_range(text, today):
    """'16.10 - 22.10' (uden år) -> (from, to, year_inferred). Året udledes ud fra 'today' og markeres."""
    m = RE_RANGE.search(text)
    if not m:
        return None
    d1, m1, y1, d2, m2, y2 = m.groups()

    def yr(y):
        if y is None:
            return None
        return int(y) + 2000 if len(y) == 2 else int(y)
    try:
        ya, yb = yr(y1), yr(y2)
        inferred = ya is None or yb is None
        yb = yb or ya or today.year
        ya = ya or yb
        a, b = dt.date(ya, int(m1), int(d1)), dt.date(yb, int(m2), int(d2))
        if inferred and b < a:  # årsskifte, fx 28.12 - 03.01: vælg efter hvilken halvdel af året vi er i
            if today.month >= 7:
                a, b = dt.date(today.year, int(m1), int(d1)), dt.date(today.year + 1, int(m2), int(d2))
            else:
                a, b = dt.date(today.year - 1, int(m1), int(d1)), dt.date(today.year, int(m2), int(d2))
        return a, b, inferred
    except ValueError:
        return None


def accept(rec, today, reasons):
    name = (rec.get("name") or "").strip()
    price, a, b = rec.get("price"), rec.get("valid_from"), rec.get("valid_to")
    if not name:
        reasons["no_name"] += 1; return None
    if price is None or not (0 < price < 10000):
        reasons["no_or_bad_price"] += 1; return None
    if a is None or b is None:
        reasons["no_dates"] += 1; return None
    if a > b or (b - a).days > MAX_DAYS:
        reasons["bad_date_range"] += 1; return None
    if b < today:
        reasons["expired"] += 1; return None
    return {"name": name, "price_dkk": price, "valid_from": a.isoformat(), "valid_to": b.isoformat(),
            "year_inferred": bool(rec.get("year_inferred"))}


def _first(d, keys):
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return None


def candidates_from_json(doc):
    """Gå et JSON-træ igennem; kandidater er dicts med både navn, pris og to datoer."""
    out, stack = [], [doc]
    while stack:
        x = stack.pop()
        if isinstance(x, dict):
            name, price = _first(x, NAME_KEYS), _first(x, PRICE_KEYS)
            if isinstance(price, dict):  # JSON-LD: offers.price
                price = _first(price, PRICE_KEYS)
            offers = x.get("offers")
            o = offers[0] if isinstance(offers, list) and offers else offers if isinstance(offers, dict) else {}
            if price is None and isinstance(o, dict):
                price = _first(o, PRICE_KEYS)
            a = _date(_first(x, FROM_KEYS) or (o.get("validFrom") if isinstance(o, dict) else None))
            b = _date(_first(x, TO_KEYS) or (o.get("priceValidUntil") if isinstance(o, dict) else None))
            if isinstance(name, str) and price is not None:
                out.append({"name": name, "price": _num(price), "valid_from": a, "valid_to": b})
            stack.extend(x.values())
        elif isinstance(x, list):
            stack.extend(x)
    return out


class _Blocks(HTMLParser):
    """Deler siden i tekstblokke, hver afsluttet af et /single/<id>-link."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks, self.cur, self.skip = [], [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self.skip += 1
        if tag == "a" and RE_SINGLE.search(dict(attrs).get("href") or ""):
            if self.cur:
                self.blocks.append(self.cur)
            self.cur = []

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript") and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        t = data.strip()
        if t and not self.skip:
            self.cur.append(t)


def candidates_from_html(html, today):
    p = _Blocks()
    p.feed(html)
    out = []
    for lines in p.blocks:
        text = " | ".join(lines)
        rng = parse_range(text, today)
        pm = RE_PRICE.search(text) or next((m for m in (re.fullmatch(r"(\d{1,4}(?:[.,]\d{1,2})?)", ln) for ln in lines) if m), None)
        name = next((ln for ln in lines if re.search(r"[A-Za-zÆØÅæøå]{3}", ln) and not RE_RANGE.search(ln)
                     and not RE_PRICE.search(ln) and ln.lower() not in ("annonce", "se produkt", "se avis")), "")
        out.append({"name": name, "price": _num(pm.group(1)) if pm else None,
                    "valid_from": rng[0] if rng else None, "valid_to": rng[1] if rng else None,
                    "year_inferred": bool(rng and rng[2])})
    return out


def parse_page(html, today=None):
    """Returnerer (accepterede poster, sikker diagnostik). Diagnostikken indeholder kun tal og kategorier."""
    today = today or dt.date.today()
    reasons = collections.Counter()
    diag = {"source_used": None, "candidates": 0, "accepted": 0, "rejected": {}, "year_inferred": 0}
    for label, getter in (
        ("json_ld", lambda: [c for m in RE_LD.finditer(html) for c in candidates_from_json(_loads(m.group(1)))]),
        ("next_data", lambda: [c for m in RE_NEXT.finditer(html) for c in candidates_from_json(_loads(m.group(1)))]),
        ("html_blocks", lambda: candidates_from_html(html, today)),
    ):
        cands = getter()
        reasons.clear()
        ok = [r for r in (accept(c, today, reasons) for c in cands) if r]
        if ok:
            diag.update(source_used=label, candidates=len(cands), accepted=len(ok),
                        rejected=dict(reasons), year_inferred=sum(r["year_inferred"] for r in ok))
            return ok, diag
        if diag["source_used"] is None and cands:
            diag.update(candidates=len(cands), rejected=dict(reasons))
    return [], diag


def _loads(s):
    try:
        return json.loads(s)
    except ValueError:
        return {}


def content_fingerprint(html):
    """Hash af synlig tekst uden tal/whitespace; kun hash gemmes, så fælles standardsider kan opdages."""
    p = _Blocks()
    p.feed(html)
    text = " ".join(" ".join(b) for b in p.blocks + [p.cur])
    return hashlib.sha256(re.sub(r"\d+|\s+", "", text).encode()).hexdigest()[:16]


def load_more_counts(html):
    m = RE_LOADMORE.search(html)
    return (int(m.group(1)), int(m.group(2))) if m else (None, None)


def parse_json_doc(doc, today=None):
    """Som parse_page, men for et allerede hentet JSON-dokument (fx /_next/data/...json)."""
    today = today or dt.date.today()
    reasons = collections.Counter()
    cands = candidates_from_json(doc)
    ok = [r for r in (accept(c, today, reasons) for c in cands) if r]
    return ok, {"source_used": "json_doc" if ok else None, "candidates": len(cands), "accepted": len(ok),
                "rejected": dict(reasons), "year_inferred": 0}
