#!/usr/bin/env python3
"""Rebuild public monthly history from dagligepriser.dk raw data.

The raw dump is never committed. Keys are generated from raw product/history
fields with the same product_normalization.py code used by current offers.
When a raw key does not directly match a current key, a conservative matcher
may attach it to a current key only when package signature and product-name
evidence agree. No legacy aggregate-key mapping is used.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import re
import statistics
import unicodedata
import urllib.request
from collections import defaultdict

from product_normalization import infer_pack, normalized_product_key

URL = "https://dagligepriser.dk/data/latest-canonical.json"
STORES = {
    "bilkatogo": "Bilka",
    "fotex": "føtex",
    "meny": "MENY",
    "minkobmand": "Min Købmand",
    "nemlig": "Nemlig.com",
    "netto": "Netto",
    "rema1000": "REMA 1000",
    "spar": "SPAR",
}
MAX_PUBLIC_BYTES = 12 * 1024 * 1024
TARGET_BYTES = 11_500_000
MIN_OVERLAP = 0.30

NONFOOD = re.compile(
    r"shampoo|balsam|deodorant|parfume|tandpasta|bleer|toiletpapir|"
    r"køkkenrulle|rengøring|vaskemiddel|opvask|kattefoder|hundefoder|"
    r"dyrefoder|kattesand|ballon|gavepapir|batteri|maling|værktøj|"
    r"kaffekop|drikkeglas|tallerken|bestik|stegepande|gryde|viskestykke|"
    r"legetøj|strømper|håndklæde|sengetøj|gødning",
    re.I,
)
FOOD = re.compile(
    r"mælk|yoghurt|skyr|fløde|ost|smør|æg|kød|kylling|pølse|bacon|"
    r"skinke|fisk|laks|tun|reje|brød|toast|bolle|kage|kiks|pizza|pasta|"
    r"nudler|havre|müsli|sauce|ketchup|sennep|pesto|olie|eddike|salt|"
    r"peber|sukker|honning|marmelade|chokolade|slik|chips|nød|kaffe|"
    r"kakao|sodavand|cola|juice|saft|vand|frugt|grønt|æble|pære|banan|"
    r"appelsin|citron|mango|ananas|melon|jordbær|blåbær|avocado|tomat|"
    r"agurk|kartoffel|gulerod|broccoli|salat|majs|ærter|bønner|linser|"
    r"champignon|dessert|grød",
    re.I,
)
STOP = {
    "med", "og", "i", "af", "til", "fra", "the", "a", "en", "et",
    "stk", "pk", "pak", "gram", "gr", "kg", "ml", "cl", "l",
}


def slug(s):
    s = unicodedata.normalize("NFKD", str(s or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def toks(s):
    return {x for x in slug(s).split() if len(x) > 1 and x not in STOP and not x.isdigit()}


def food(p):
    name = str(p.get("name") or "")
    if NONFOOD.search(name):
        return False
    category = str(p.get("category") or "")
    return (bool(category) and category[0] in "0123456") or bool(FOOD.search(name))


def sig(record):
    count, amount, unit = infer_pack(record)
    if amount is None:
        return None
    total = float(count or 1) * float(amount)
    if unit == "kg":
        family, value = "kg", total
    elif unit == "g":
        family, value = "kg", total / 1000
    elif unit == "l":
        family, value = "l", total
    elif unit == "cl":
        family, value = "l", total / 100
    elif unit == "ml":
        family, value = "l", total / 1000
    elif unit == "stk":
        family, value = "stk", total
    else:
        return None
    return family, round(value, 3)


def raw_probe(product, hist):
    """Build identity from raw data only.

    Historical size/count wins when present. Product-level raw fields are a
    fallback only when the historical row omits them. The product name is kept,
    so explicit pack markers such as "24 pk." are still detected by infer_pack.
    """
    return {
        "name": product.get("name"),
        "brand": product.get("brand"),
        "variant": product.get("variant"),
        "package_count": hist.get("package_count", product.get("package_count", 1)),
        "package_amount": hist.get("quantity", product.get("quantity")),
        "package_unit": hist.get("unit", product.get("unit")),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source-file")
    ap.add_argument("--output", default="monthly_price_history.json")
    ap.add_argument("--current-offers", default="current_offers.json")
    ap.add_argument("--allow-public-output", action="store_true")
    ap.add_argument("--manifest", default="data_sources/dagligepriser_manifest.json")
    args = ap.parse_args()

    manifest_path = pathlib.Path(args.manifest)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    redistribution = manifest.get("redistribution_status", "unresolved")
    output = pathlib.Path(args.output)
    if "data/private" not in output.as_posix() and redistribution != "allowed" and not args.allow_public_output:
        raise SystemExit("Refusing public output while redistribution status is unresolved")

    current = json.loads(pathlib.Path(args.current_offers).read_text(encoding="utf-8"))
    offers = [
        o for o in current.get("offers", [])
        if str(o.get("category") or "").lower() not in {"husholdning", "dyrefoder"}
    ]
    offer_keys = {o.get("normalized_product_key") or normalized_product_key(o) for o in offers}
    offer_keys.discard(None)

    brands = sorted({str(o.get("brand")).strip() for o in offers if o.get("brand")}, key=len, reverse=True)
    brand_lut = {slug(b): b for b in brands}

    index = defaultdict(list)
    for o in offers:
        signature = sig(o)
        if signature:
            index[signature].append(
                (
                    o.get("normalized_product_key") or normalized_product_key(o),
                    toks(o.get("name")),
                    slug(o.get("brand")),
                )
            )

    def detect_brand(name):
        sn = slug(name)
        for sb, brand in brand_lut.items():
            if sn == sb or sn.startswith(sb + " "):
                return brand
        return None

    cache = {}

    def choose_key(product, hist):
        probe = raw_probe(product, hist)
        if not probe.get("brand"):
            probe["brand"] = detect_brand(probe.get("name"))
        cache_key = (
            probe.get("name"), probe.get("brand"), probe.get("variant"),
            probe.get("package_count"), probe.get("package_amount"), probe.get("package_unit"),
        )
        if cache_key in cache:
            return cache[cache_key]

        direct = normalized_product_key(probe)
        if direct in offer_keys:
            cache[cache_key] = direct
            return direct

        candidates = index.get(sig(probe) or (), [])
        if not candidates:
            cache[cache_key] = direct
            return direct

        raw_tokens = toks(probe.get("name"))
        raw_brand = slug(probe.get("brand"))
        scored = []
        for candidate_key, candidate_tokens, candidate_brand in candidates:
            if raw_brand and candidate_brand and raw_brand != candidate_brand:
                continue
            if not raw_tokens or not candidate_tokens:
                continue
            score = len(raw_tokens & candidate_tokens) / max(1, min(len(raw_tokens), len(candidate_tokens)))
            if candidate_brand and raw_brand == candidate_brand:
                score += 0.15
            scored.append((score, candidate_key))
        scored.sort(reverse=True)

        # Conservative raw-to-current identity match. Package signature must
        # already be identical; this threshold only resolves naming differences.
        if scored and scored[0][0] >= 0.50 and (
            len(scored) == 1 or scored[0][0] - scored[1][0] >= 0.01
        ):
            cache[cache_key] = scored[0][1]
            return cache[cache_key]

        cache[cache_key] = direct
        return direct

    raw = (
        pathlib.Path(args.source_file).read_bytes()
        if args.source_file
        else urllib.request.urlopen(URL, timeout=300).read()
    )
    products = json.loads(raw)
    if not isinstance(products, list):
        raise ValueError("Expected product list")

    buckets = defaultdict(list)
    months_by_key = defaultdict(set)
    skipped = 0

    for product in products:
        store_code = product.get("store")
        if store_code not in STORES or not food(product):
            continue
        for hist in product.get("priceHistory", []):
            try:
                dt.date.fromisoformat(hist.get("date"))
                price = float(hist.get("price"))
                probe = raw_probe(product, hist)
                _count, amount, unit = infer_pack(probe)
                if price <= 0 or amount is None or not unit:
                    raise ValueError
            except Exception:
                skipped += 1
                continue

            key = choose_key(product, hist)
            month = hist["date"][:7]
            buckets[(key, STORES[store_code], month)].append(price)
            months_by_key[key].add(month)

    by_key = defaultdict(list)
    for (key, store, month), prices in buckets.items():
        by_key[key].append(
            {
                "normalized_product_key": key,
                "store": store,
                "month": month,
                "observation_count": len(prices),
                "median_price_dkk": round(float(statistics.median(prices)), 2),
                "min_price_dkk": round(float(min(prices)), 2),
                "source": "dagligepriser.dk",
            }
        )
    for rows in by_key.values():
        rows.sort(key=lambda r: (r["month"], r["store"]))

    history_keys = set(by_key)
    direct = offer_keys & history_keys
    overlap = len(direct) / max(1, len(offer_keys))
    if overlap < MIN_OVERLAP:
        raise SystemExit(
            f"History key overlap too low after raw rebuild: "
            f"{len(direct)}/{len(offer_keys)} = {overlap:.1%}"
        )

    def rank(key):
        return (
            -len(months_by_key[key]),
            -sum(r["observation_count"] for r in by_key[key]),
            key,
        )

    required = max(1, int(len(offer_keys) * MIN_OVERLAP + 0.999999))
    selected = list(sorted(direct, key=rank)[:required])
    selected_set = set(selected)

    # Keep useful non-current history (>=3 months) too, while staying compact.
    eligible = {k for k in history_keys if k in offer_keys or len(months_by_key[k]) >= 3}

    def key_bytes(key):
        return sum(
            len(json.dumps(r, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) + 1
            for r in by_key[key]
        )

    used = sum(key_bytes(k) for k in selected)
    if used > TARGET_BYTES:
        for k in selected:
            by_key[k] = sorted(
                by_key[k], key=lambda r: (r["month"], r["store"]), reverse=True
            )[:12]
        used = sum(key_bytes(k) for k in selected)
        if used > TARGET_BYTES:
            raise SystemExit("Required 30% overlap cannot fit under target size")

    for key in sorted(eligible - selected_set, key=lambda k: (0 if k in offer_keys else 1,) + rank(k)):
        size = key_bytes(key)
        if used + size <= TARGET_BYTES:
            selected.append(key)
            selected_set.add(key)
            used += size

    rows = [r for key in selected for r in by_key[key]]
    rows.sort(key=lambda r: (r["normalized_product_key"], r["store"], r["month"]))

    matched = len(selected_set & offer_keys)
    doc = {
        "schema_version": 3,
        "source": "dagligepriser.dk",
        "source_url": URL,
        "credit": "Monthly aggregates derived from dagligepriser.dk raw data",
        "aggregation": "normalized_product_key + store + month",
        "food_only": True,
        "raw_data_included": False,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "record_count": len(rows),
        "offer_key_count": len(offer_keys),
        "matched_offer_keys": matched,
        "offer_key_overlap": round(matched / max(1, len(offer_keys)), 4),
        "skipped": skipped,
        "records": rows,
    }
    payload = json.dumps(doc, ensure_ascii=False, separators=(",", ":")) + "\n"
    size = len(payload.encode("utf-8"))

    if doc["offer_key_overlap"] < MIN_OVERLAP:
        raise SystemExit("Final overlap below 30%")
    if size >= MAX_PUBLIC_BYTES:
        raise SystemExit(f"Output over 12 MB: {size} bytes")

    output.write_text(payload, encoding="utf-8")
    print(
        json.dumps(
            {
                "raw_product_count": len(products),
                "records": len(rows),
                "bytes": size,
                "offer_keys": len(offer_keys),
                "matched": matched,
                "overlap": doc["offer_key_overlap"],
                "skipped": skipped,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
