#!/usr/bin/env python3
"""Build the public monthly price history from dagligepriser.dk raw data.

The raw dump is never committed. Product identity is generated with the same
product_normalization.py code used by current offers and Supertilbud.
"""
from __future__ import annotations

import argparse
import datetime
import json
import pathlib
import statistics
import urllib.request

from product_normalization import normalized_product_key

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


def _load_current_keys(path: pathlib.Path) -> set[str]:
    if not path.exists():
        return set()
    doc = json.loads(path.read_text(encoding="utf-8"))
    return {
        o.get("normalized_product_key")
        for o in doc.get("offers", [])
        if o.get("normalized_product_key")
    }


def aggregate(products, allowed_keys: set[str] | None = None):
    buckets = {}
    skipped = 0

    for product in products:
        store_code = product.get("store")
        if store_code not in STORES:
            skipped += 1
            continue

        # Product-level fields describe identity/name/brand. Historical package
        # size/count must still come from each history row, never today's size.
        base = {
            "name": product.get("name"),
            "brand": product.get("brand"),
            "variant": product.get("variant"),
            "package_count": product.get("package_count", 1),
        }

        for h in product.get("priceHistory", []):
            date = h.get("date")
            price = h.get("price")
            try:
                datetime.date.fromisoformat(date)
            except (TypeError, ValueError):
                skipped += 1
                continue
            if isinstance(price, bool) or not isinstance(price, (int, float)) or price <= 0:
                skipped += 1
                continue

            hist = dict(base)
            hist["package_amount"] = h.get("quantity")
            hist["package_unit"] = h.get("unit")
            hist["package_count"] = h.get("package_count", product.get("package_count", 1))

            # Important: no mapping from old aggregate keys. The key is rebuilt
            # from raw product + raw historical row using shared normalization.
            key = normalized_product_key(hist)
            if allowed_keys and key not in allowed_keys:
                continue

            bucket_key = (key, store_code, date[:7])
            b = buckets.setdefault(
                bucket_key,
                {
                    "normalized_product_key": key,
                    "store": STORES[store_code],
                    "month": date[:7],
                    "prices": [],
                },
            )
            b["prices"].append(float(price))

    rows = []
    for b in buckets.values():
        prices = b.pop("prices")
        b.update(
            {
                "observation_count": len(prices),
                "median_price_dkk": round(float(statistics.median(prices)), 2),
                "min_price_dkk": round(float(min(prices)), 2),
                "source": "dagligepriser.dk",
            }
        )
        rows.append(b)

    rows.sort(key=lambda x: (x["normalized_product_key"], x["store"], x["month"]))
    return rows, skipped


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--source-file")
    p.add_argument("--output", default="monthly_price_history.json")
    p.add_argument("--current-offers", default="current_offers.json")
    p.add_argument("--allow-public-output", action="store_true")
    p.add_argument("--manifest", default="data_sources/dagligepriser_manifest.json")
    a = p.parse_args()

    manifest_path = pathlib.Path(a.manifest)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    status = manifest.get("redistribution_status", "unresolved")
    output = pathlib.Path(a.output)

    if "data/private" not in output.as_posix() and status != "allowed" and not a.allow_public_output:
        raise SystemExit(
            "Refusing public output: dagligepriser redistribution_status is unresolved; "
            "use --allow-public-output only when aggregate publication is explicitly intended."
        )

    raw = (
        pathlib.Path(a.source_file).read_bytes()
        if a.source_file
        else urllib.request.urlopen(URL, timeout=240).read()
    )
    products = json.loads(raw)
    if not isinstance(products, list):
        raise ValueError("Expected product list")

    allowed_keys = _load_current_keys(pathlib.Path(a.current_offers))
    rows, skipped = aggregate(products, allowed_keys=allowed_keys)

    history_keys = {r["normalized_product_key"] for r in rows}
    doc = {
        "schema_version": 3,
        "source": "dagligepriser.dk",
        "source_url": URL,
        "credit": "Aggregated from dagligepriser.dk",
        "aggregation": "normalized_product_key + store + month",
        "food_only": True,
        "raw_data_included": False,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "record_count": len(rows),
        "offer_key_count": len(allowed_keys),
        "matched_offer_keys": len(history_keys),
        "offer_key_overlap": round(len(history_keys) / len(allowed_keys), 4) if allowed_keys else 0,
        "skipped": skipped,
        "records": rows,
    }

    payload = json.dumps(doc, ensure_ascii=False, separators=(",", ":")) + "\n"
    size = len(payload.encode("utf-8"))
    if size >= MAX_PUBLIC_BYTES:
        raise SystemExit(
            f"Refusing output: monthly history is {size} bytes, limit is {MAX_PUBLIC_BYTES}."
        )

    output.write_text(payload, encoding="utf-8")
    print(
        json.dumps(
            {
                "raw_product_count": len(products),
                "monthly_record_count": len(rows),
                "matched_offer_keys": len(history_keys),
                "offer_key_count": len(allowed_keys),
                "output_bytes": size,
                "skipped": skipped,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
