#!/usr/bin/env python3
"""Prioritised, paginated, categorised offer feed for the app.

Replaces cutting a store's offer text at a fixed length. Every active offer with
a price and package lands on exactly one page, pages never exceed the character
limit, food comes first and non-food (household, pet food) last. Non-food is only
left out when --food-only is given explicitly.
"""
from __future__ import annotations
import argparse, datetime as dt, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from offer_schema import NON_FOOD_CATEGORIES, food_relevance_for, offer_status, snapshot_date

PAGE_LIMIT = 5800  # app text field accepts < 6000 characters
SCHEMA_VERSION = 1
CATEGORY_ORDER = ["frugt_og_gront", "kød", "fjerkræ", "fisk", "mejeri", "brød", "pålæg", "kolonial", "færdigretter",
                  "drikkevarer", "snacks"]
ELLIPSIS = "…"

def _num(x):
    s = ("%.3f" % x).rstrip("0").rstrip(".") if isinstance(x, float) else str(x)
    return s.replace(".", ",")

def _short_date(iso: str) -> str:
    y, m, d = iso.split("-")
    return f"{int(d)}.{int(m)}."

def offer_suffix(o: dict, store_valid_to=None) -> str:
    """Everything after the name: price, package, organic, membership and (when it differs) own end date.

    The end date is written only when it is earlier than the store's latest end date, so the
    page text never makes an offer look valid longer than it is.
    """
    suffix = f" - {_num(o['price_dkk'])} kr. pr. {_num(o['package_amount'])} {o['package_unit']}"
    if o.get("organic") is True: suffix += " - øko"
    if o.get("member_only"): suffix += " - kun medlemmer"
    if store_valid_to and o.get("valid_to") and o["valid_to"] < store_valid_to: suffix += f" - til {_short_date(o['valid_to'])}"
    return suffix

def offer_line(o: dict, store_valid_to=None) -> str:
    return f"{str(o['name']).strip()}{offer_suffix(o, store_valid_to)}"

def fit_line(o: dict, store_valid_to, limit: int):
    """Return (line, full_line_or_None). An over-long line shortens the NAME only; price, package and dates stay intact."""
    full = offer_line(o, store_valid_to)
    if len(full) <= limit: return full, None
    suffix = offer_suffix(o, store_valid_to); room = limit - len(suffix) - 1
    if room < 1:
        # Price, package, organic, membership and end date must never be cut: refuse instead of truncating silently.
        raise ValueError(f"offer {o.get('id')!r}: suffix ({len(suffix)} chars) leaves no room for any name within the {limit}-char limit")
    name = str(o["name"]).strip()[:room] + ELLIPSIS
    line = name + suffix
    assert len(line) <= limit and line.endswith(suffix)
    return line, full

def is_non_food(o: dict) -> bool:
    return str(o.get("category") or "").lower() in NON_FOOD_CATEGORIES or o.get("food_relevance") == "low"

def sort_key(o: dict):
    """Food first (category order), unknown categories next, non-food last."""
    cat = str(o.get("category") or "")
    group = 2 if is_non_food(o) else (0 if cat in CATEGORY_ORDER or food_relevance_for(cat) == "high" else 1)
    rank = CATEGORY_ORDER.index(cat) if cat in CATEGORY_ORDER else len(CATEGORY_ORDER)
    return (group, rank, cat, str(o.get("name")), str(o.get("id")))

def feedable(o: dict, today) -> bool:
    """Active today with a numeric price and a package. Non-food is NOT excluded here."""
    price = o.get("price_dkk")
    return (offer_status(o, today) == "active" and isinstance(price, (int, float)) and not isinstance(price, bool) and price > 0
            and o.get("package_amount") is not None and bool(o.get("package_unit")) and bool(str(o.get("name") or "").strip()))

def paginate(lines, limit=PAGE_LIMIT):
    """Pack lines into pages of at most `limit` characters (lines joined by newline).

    A single line longer than the limit is shortened with an ellipsis, never
    allowed to break the limit. Returns (pages, truncated) where `truncated`
    lists {line_index, original_length} so every cut stays traceable.
    """
    pages, cur, size, truncated = [], [], 0, []
    for i, ln in enumerate(lines):
        if len(ln) > limit:
            truncated.append({"line_index": i, "original_length": len(ln), "kept": ln[: limit - 1] + ELLIPSIS})
            ln = ln[: limit - 1] + ELLIPSIS
        add = len(ln) + (1 if cur else 0)
        if cur and size + add > limit:
            pages.append(cur); cur, size, add = [], 0, len(ln)
        cur.append(ln); size += add
    if cur: pages.append(cur)
    return pages, truncated

def build_feed(offers, today, limit=PAGE_LIMIT, food_only=False):
    """Return (feed_by_store, excluded). Each valid offer appears exactly once (first id wins)."""
    by_store, seen_ids = {}, set()
    excluded = {"not_active": 0, "missing_price_or_package": 0, "duplicate_id": 0, "non_food_excluded_by_flag": 0}
    for o in offers:
        if offer_status(o, today) != "active":
            excluded["not_active"] += 1; continue
        if not feedable(o, today):
            excluded["missing_price_or_package"] += 1; continue
        if food_only and is_non_food(o):
            excluded["non_food_excluded_by_flag"] += 1; continue
        if o.get("id") is not None:
            if o["id"] in seen_ids:
                excluded["duplicate_id"] += 1; continue
            seen_ids.add(o["id"])
        by_store.setdefault(o["store"], []).append(o)
    feed = {}
    for store, rows in sorted(by_store.items()):
        rows.sort(key=sort_key)
        valid_to = max(o["valid_to"] for o in rows)
        fitted = [fit_line(o, valid_to, limit) for o in rows]
        pages, generic_cuts = paginate([f[0] for f in fitted], limit)
        # Structured full record per offer (same order as the lines): full name, price, package and dates are never lost.
        offers_out, truncated, page_no, line_no, left = [], [], 0, 0, len(pages[0]) if pages else 0
        for i, (o, (line, full)) in enumerate(zip(rows, fitted)):
            while line_no >= left and page_no + 1 < len(pages):
                page_no += 1; line_no = 0; left = len(pages[page_no])
            entry = {"id": o.get("id"), "name": str(o["name"]).strip(), "price_dkk": o["price_dkk"],
                     "package_amount": o["package_amount"], "package_unit": o["package_unit"],
                     "valid_from": o.get("valid_from"), "valid_to": o["valid_to"], "organic": o.get("organic"),
                     "member_only": bool(o.get("member_only")), "category": o.get("category"),
                     "page": page_no, "line": line_no, "name_shortened_in_page_text": full is not None}
            if full is not None:
                truncated.append({"offer_index": i, "offer_id": o.get("id"), "original_length": len(full), "full_text": full})
            offers_out.append(entry); line_no += 1
        feed[store] = {"offer_count": len(rows), "page_count": len(pages),
                       "non_food_count": sum(1 for o in rows if is_non_food(o)),
                       "valid_to": valid_to,
                       "truncated_lines": truncated + [{"generic_cut": c} for c in generic_cuts],
                       "offers": offers_out,
                       "pages": ["\n".join(p) for p in pages]}
    return feed, excluded

def slugify(store: str) -> str:
    return store.lower().replace("æ", "ae").replace("ø", "oe").replace("å", "aa").replace("'", "").replace(" ", "-")

def render(feed, excluded, valid_on, limit=PAGE_LIMIT, food_only=False):
    """All output files as {relative_name: text}, deterministic for a given snapshot."""
    files, stores = {}, {}
    for store, doc in feed.items():
        slug = slugify(store)
        files[f"{slug}.json"] = json.dumps({"store": store, **doc}, ensure_ascii=False, indent=1) + "\n"
        stores[store] = {"file": f"{slug}.json", "offer_count": doc["offer_count"], "page_count": doc["page_count"],
                         "non_food_count": doc["non_food_count"], "valid_to": doc["valid_to"]}
    files["index.json"] = json.dumps({"schema_version": SCHEMA_VERSION, "valid_on": str(valid_on), "encoding": "utf-8",
                                      "page_char_limit": limit, "food_only": food_only, "stores": stores,
                                      "excluded": excluded}, ensure_ascii=False, indent=1) + "\n"
    return files

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--current", default="current_offers.json"); ap.add_argument("--out", default="feed")
    ap.add_argument("--today", help="override valid-on date (YYYY-MM-DD); default is the snapshot's own Danish date")
    ap.add_argument("--food-only", action="store_true", help="explicitly leave out household and pet food")
    ap.add_argument("--check", action="store_true", help="do not write; fail if files in --out differ from a fresh build")
    a = ap.parse_args()
    doc = json.loads(Path(a.current).read_text(encoding="utf-8"))
    today = dt.date.fromisoformat(a.today) if a.today else snapshot_date(doc)
    feed, excluded = build_feed(doc["offers"], today, food_only=a.food_only)
    files = render(feed, excluded, today, food_only=a.food_only)
    out = Path(a.out)
    if a.check:
        bad = [n for n, t in files.items() if not (out / n).exists() or (out / n).read_text(encoding="utf-8") != t]
        stale = sorted(p.name for p in out.glob("*.json") if p.name not in files) if out.exists() else []
        print(json.dumps({"valid_on": str(today), "differs": bad, "stale_files": stale}, ensure_ascii=False))
        sys.exit(1 if bad or stale else 0)
    out.mkdir(exist_ok=True)
    for n, t in files.items(): (out / n).write_text(t, encoding="utf-8")
    print(json.dumps({"valid_on": str(today), "stores": len(feed), "offers": sum(d["offer_count"] for d in feed.values()),
                      "excluded": excluded}, ensure_ascii=False))

if __name__ == "__main__": main()
