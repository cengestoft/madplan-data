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

import math
from history_approval_check import documented
from history_identity import (REJECTED, REVIEW, VERIFIED, carry_over_rejections, combine, compare, describe, key_status, raw_id_hash, single_from_key)
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


def conservative_score(raw_brand, raw_tokens, candidate_brand, candidate_tokens):
    """Similarity of a raw product to a current offer, or None when they must not be matched.

    Brand must exist on both sides and be identical (an empty brand never matches anything).
    Brand words are removed before comparing, so 'Salling Princip ... ' can never match a
    different Salling Princip product just because both start with the brand name. At least
    one product word must be shared.
    """
    if not raw_brand or not candidate_brand or raw_brand != candidate_brand:
        return None
    brand_words = set(candidate_brand.split())
    a, b = raw_tokens - brand_words, candidate_tokens - brand_words
    shared = a & b
    if not a or not b or not shared:
        return None
    return len(shared) / max(1, min(len(a), len(b))) + 0.15


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


def reconcile_manifest_file(output: pathlib.Path) -> bool:
    """Keep price_history.json (the manifest next to the output) in step with the rebuilt history: record count, keys, months."""
    manifest_path = output.parent / "price_history.json"
    if not manifest_path.exists():
        return False
    from build_data_pipeline import reconcile_history_manifest
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    monthly = json.loads(output.read_text(encoding="utf-8"))
    manifest_path.write_text(json.dumps(reconcile_history_manifest(manifest, monthly), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return True


def load_decisions(path: pathlib.Path) -> dict:
    """{(normalized_product_key, raw_id_hash): 'verified' | 'rejected'} from the committed review file (hashes only)."""
    if not path.exists():
        return {}
    doc = json.loads(path.read_text(encoding="utf-8"))
    return {(d["normalized_product_key"], d["raw_id_hash"]): d["decision"] for d in doc.get("decisions", [])
            if d.get("decision") in {"verified", "rejected"} and d.get("reviewed_by") and d.get("reviewed_on")}


# single_package_amount/unit are needed by infer_pack(): package_amount of an offer is the TOTAL of a multipack (24 x 0.33 l = 7.92 l),
# so without the single amount describe() would multiply count x total again.
IDENTITY_FIELDS = ("name", "brand", "variant", "package_amount", "package_unit", "package_count", "category", "normalized_product_key",
                   "single_package_amount", "single_package_unit")
REGISTRY_PATH = "data_sources/history_offer_identities.json"


def identity_record(o):
    """Minimal public offer identity (the project's own offer data, no raw dagligepriser text) used to keep verifying history
    for products that temporarily have no active offer."""
    rec = {f: o.get(f) for f in IDENTITY_FIELDS if o.get(f) is not None}
    if not (float(o.get("package_count") or 1) > 1):
        rec.pop("single_package_amount", None); rec.pop("single_package_unit", None)  # only multipacks need them (count x single = total)
    rec["normalized_product_key"] = o.get("normalized_product_key") or normalized_product_key(o)
    return rec


def load_registry(path):
    path = pathlib.Path(path)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8")).get("keys", {})


def merge_registry(registry, offers):
    """Union of known offer identities per history key. Nothing is ever removed because an offer expired."""
    out = {k: list(v) for k, v in registry.items()}
    for o in offers:
        rec = identity_record(o)
        k = rec["normalized_product_key"]
        if not k:
            continue
        ident = lambda r: (r.get("name"), r.get("brand"), r.get("package_amount"), r.get("package_unit"), r.get("package_count"))
        same = [r for r in out.setdefault(k, []) if ident(r) == ident(rec)]
        if not same:
            out[k].append(rec)
        else:
            # Additive only: an identity saved before single_package_* existed gets them from the same offer. Nothing is overwritten.
            for r in same:
                for f in ("single_package_amount", "single_package_unit"):
                    if r.get(f) is None and rec.get(f) is not None:
                        r[f] = rec[f]
    for recs in out.values():  # identities that no longer have an offer: derive the single size from the key, only when it matches the total exactly
        for r in recs:
            if r.get("single_package_amount") is None and float(r.get("package_count") or 1) > 1:
                s = single_from_key(r)
                if s:
                    r["single_package_amount"], r["single_package_unit"] = s
    return {k: sorted(v, key=lambda r: json.dumps(r, sort_keys=True, ensure_ascii=False)) for k, v in sorted(out.items())}


def write_registry(path, registry):
    pathlib.Path(path).write_text(json.dumps({
        "schema_version": 1, "raw_data_included": False,
        "purpose": "Offer identities of every product key that ever had an offer. Verified history is kept for these keys even "
                   "when no offer is active; current offers only decide overlap and which graphs are possible.",
        "keys": registry}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source-file")
    ap.add_argument("--output", default="monthly_price_history.json")
    ap.add_argument("--current-offers", default="current_offers.json")
    ap.add_argument("--allow-public-output", action="store_true")
    ap.add_argument("--manifest", default="data_sources/dagligepriser_manifest.json")
    ap.add_argument("--decisions", default="data_sources/history_review_decisions.json",
                    help="human review decisions (hashes only, no raw text): promote review_required to verified or reject a raw product")
    ap.add_argument("--identities", default=REGISTRY_PATH,
                    help="registry of offer identities for all historical product keys (kept across runs; history is never dropped because an offer expired)")
    ap.add_argument("--previous-verification", default="history_verification.json",
                    help="the previously committed verification file; documented rejections are carried over when this run has no raw products for the key")
    ap.add_argument("--update-identities-only", action="store_true", help="only add the current offers to the identity registry and exit")
    ap.add_argument("--verification", help="public per-key verification status (default: history_verification.json next to the output)")
    ap.add_argument("--match-log", help="write per-key match documentation (method + raw product examples) to this PRIVATE path under data/private/; never committed")
    args = ap.parse_args()

    manifest_path = pathlib.Path(args.manifest)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    redistribution = manifest.get("redistribution_status", "unresolved")
    output = pathlib.Path(args.output)
    if "data/private" not in output.as_posix() and redistribution not in {"allowed", "permitted_aggregated_only"} and not args.allow_public_output:
        raise SystemExit("Refusing public output while redistribution status is unresolved")

    current = json.loads(pathlib.Path(args.current_offers).read_text(encoding="utf-8"))
    offers = [
        o for o in current.get("offers", [])
        if str(o.get("category") or "").lower() not in {"husholdning", "dyrefoder"}
    ]
    offer_keys = {o.get("normalized_product_key") or normalized_product_key(o) for o in offers}  # A: ACTIVE offer keys (overlap, graph options)
    offer_keys.discard(None)
    registry = merge_registry(load_registry(args.identities), offers)  # B: ALL historical keys with a known offer identity
    if args.update_identities_only:
        write_registry(args.identities, registry)
        print(json.dumps({"identity_keys": len(registry), "active_keys": len(offer_keys)}))
        return
    history_keys = set(registry) | offer_keys
    hist_offers = [dict(r) for k in sorted(registry) for r in registry[k]]  # active and historical offer identities

    brands = sorted({str(o.get("brand")).strip() for o in hist_offers if o.get("brand")}, key=len, reverse=True)
    brand_lut = {slug(b): b for b in brands}

    index = defaultdict(list)
    for o in hist_offers:
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
    method_of = {}  # cache_key -> "direct" | "conservative" | "unmatched"

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
        if direct in history_keys:
            cache[cache_key] = direct
            method_of[cache_key] = "direct"
            return direct

        candidates = index.get(sig(probe) or (), [])
        if not candidates:
            cache[cache_key] = direct
            method_of[cache_key] = "unmatched"
            return direct

        raw_tokens = toks(probe.get("name"))
        raw_brand = slug(probe.get("brand"))
        scored = []
        for candidate_key, candidate_tokens, candidate_brand in candidates:
            score = conservative_score(raw_brand, raw_tokens, candidate_brand, candidate_tokens)
            if score is not None:
                scored.append((score, candidate_key))
        scored.sort(reverse=True)

        # Conservative raw-to-current identity match. Package signature must already be identical,
        # the brand must be present on BOTH sides and equal, and the product words (brand words
        # removed) must overlap. This only resolves naming differences, never different products.
        if scored and scored[0][0] >= 0.50 and (
            len(scored) == 1 or scored[0][0] - scored[1][0] >= 0.01
        ):
            cache[cache_key] = scored[0][1]
            method_of[cache_key] = "conservative"
            return cache[cache_key]

        cache[cache_key] = direct
        method_of[cache_key] = "unmatched"
        return direct

    raw = (
        pathlib.Path(args.source_file).read_bytes()
        if args.source_file
        else urllib.request.urlopen(URL, timeout=300).read()
    )
    products = json.loads(raw)
    if not isinstance(products, list):
        raise ValueError("Expected product list")

    decisions = load_decisions(pathlib.Path(args.decisions))
    offers_by_key = defaultdict(list)
    for o in hist_offers:
        k = o.get("normalized_product_key") or normalized_product_key(o)
        if k:
            offers_by_key[k].append(o)
    offer_identity = {k: [describe(x) for x in v] for k, v in offers_by_key.items()}

    verdict_cache = {}
    raw_by_key = defaultdict(lambda: {VERIFIED: set(), REVIEW: set(), REJECTED: set()})
    methods_by_key = defaultdict(lambda: defaultdict(int))
    conflicts_by_key = defaultdict(lambda: defaultdict(int))
    missing_by_key = defaultdict(lambda: defaultdict(int))
    manual_by_key = defaultdict(int)
    blocked_by_key = defaultdict(int)  # approvals NOT applied because the evidence did not document the same product
    examples_by_key = defaultdict(dict)  # PRIVATE: raw names stay out of the repository
    buckets = defaultdict(list)
    months_by_key = defaultdict(set)
    skipped = 0
    non_offer_rows = 0

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
            if key not in history_keys:
                non_offer_rows += 1  # no offer (active or historical) ever had this key; only verified rows are kept anyway
                continue
            ck = (probe.get("name"), probe.get("brand"), probe.get("variant"),
                  probe.get("package_count"), probe.get("package_amount"), probe.get("package_unit"))
            pid = raw_id_hash(store_code, product.get("id"))
            vkey = (ck, key, pid)
            if vkey not in verdict_cache:
                rp = dict(probe)
                rp["description"] = product.get("description")
                verdict = combine(compare(describe(rp), d) for d in offer_identity[key])
                verdict = dict(verdict, method=method_of.get(ck) or "direct", manual=False)
                decision = decisions.get((key, pid))
                if decision == "verified" and verdict["status"] == REVIEW:
                    # A human approval is only applied when it is documented against THIS run's evidence (offer vs raw product name).
                    # Missing or contradicting evidence leaves the product review_required.
                    offs = offers_by_key.get(key, [])
                    ok_doc, _why = documented([x.get("name") for x in offs], (offs[0].get("brand") if offs else None), product.get("name"))
                    if ok_doc:
                        verdict.update(status=decision, manual=True)
                    else:
                        verdict["manual_blocked"] = True
                elif decision == "rejected":
                    verdict.update(status=decision, manual=True)  # a rejection always applies; a human approval never overrides a hard conflict
                verdict_cache[vkey] = verdict
                raw_by_key[key][verdict["status"]].add(pid)
                methods_by_key[key][verdict["method"]] += 1
                for f in verdict["conflicts"]: conflicts_by_key[key][f] += 1
                for f in verdict["missing"]: missing_by_key[key][f] += 1
                if verdict["manual"]: manual_by_key[key] += 1
                if verdict.get("manual_blocked"): blocked_by_key[key] += 1
                if len(examples_by_key[key]) < 12:
                    examples_by_key[key][pid] = {"raw_hash": pid, "raw_name": product.get("name"), "store": STORES[store_code],
                                                 "status": verdict["status"], "method": verdict["method"], "conflicts": verdict["conflicts"],
                                                 "missing": verdict["missing"], "manual": verdict["manual"]}
            if verdict_cache[vkey]["status"] != VERIFIED:
                continue
            month = hist["date"][:7]
            buckets[(key, STORES[store_code], month)].append(price)
            months_by_key[key].add(month)

    by_key = defaultdict(list)
    for (key, store, month), prices in buckets.items():
        by_key[key].append({
            "normalized_product_key": key, "store": store, "month": month, "observation_count": len(prices),
            "median_price_dkk": round(float(statistics.median(prices)), 2), "min_price_dkk": round(float(min(prices)), 2),
            "source": "dagligepriser.dk",
        })
    for rows_ in by_key.values():
        rows_.sort(key=lambda r: (r["month"], r["store"]))
    rows = [r for key in sorted(by_key) for r in by_key[key]]

    today_iso = dt.date.today().isoformat()
    key_info = {}
    for key in sorted(history_keys):
        counts = {st: len(ids) for st, ids in raw_by_key[key].items()} if key in raw_by_key else {}
        key_info[key] = {
            "active": key in offer_keys,
            "status": key_status(counts),
            "offer_names": sorted({str(x.get("name")) for x in offers_by_key.get(key, [])})[:3],
            "raw_products": {st: counts.get(st, 0) for st in (VERIFIED, REVIEW, REJECTED)},
            "methods": dict(methods_by_key.get(key, {})),
            "conflict_fields": dict(conflicts_by_key.get(key, {})),
            "missing_fields": dict(missing_by_key.get(key, {})),
            "manual_decisions": manual_by_key.get(key, 0),
            "manual_decisions_blocked": blocked_by_key.get(key, 0),
            "months": len(months_by_key.get(key, ())),
        }
    prev_path = pathlib.Path(args.previous_verification)
    try:
        prev_keys = json.loads(prev_path.read_text(encoding="utf-8")).get("keys", {}) if prev_path.exists() else {}
    except (ValueError, OSError):
        prev_keys = {}
    carried = carry_over_rejections(key_info, prev_keys)
    status_count = defaultdict(int)
    retained_inactive = sum(1 for info in key_info.values() if not info["active"] and info["status"] == VERIFIED)
    for info in key_info.values():
        if info["active"]: status_count[info["status"]] += 1
    total_keys = len(offer_keys)
    verified_n = status_count[VERIFIED]
    needed = max(0, math.ceil(MIN_OVERLAP * total_keys) - verified_n)
    summary = {"active_food_keys": total_keys, "verified": verified_n, "review_required": status_count[REVIEW],
               "rejected": status_count[REJECTED], "no_candidate": status_count["no_candidate"],
               "verified_overlap": round(verified_n / max(1, total_keys), 4), "required_overlap": MIN_OVERLAP,
               "additional_verified_needed": needed, "meets_required_overlap": needed == 0,
               "retained_verified_keys_without_active_offer": retained_inactive}

    verification = {
        "schema_version": 1, "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(), "control_date": today_iso,
        "source": "dagligepriser.dk", "raw_data_included": False,
        "rules": "A history key is verified only when brand, product type, flavour/variant, meat type, fat percentage, pack count, "
                 "size and unit all agree between the raw product and the offer. Equal normalized_product_key alone is not enough.",
        "summary": summary, "keys": key_info,
    }
    doc = {
        "schema_version": 3, "source": "dagligepriser.dk", "source_url": URL,
        "credit": "Monthly aggregates derived from dagligepriser.dk raw data", "aggregation": "normalized_product_key + store + month",
        "food_only": True, "raw_data_included": False, "verified_only": True, "verification_file": "history_verification.json",
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(), "record_count": len(rows),
        "offer_key_count": total_keys, "matched_offer_keys": verified_n, "offer_key_overlap": summary["verified_overlap"],
        "skipped": skipped, "records": rows,
    }
    payload = json.dumps(doc, ensure_ascii=False, separators=(",", ":")) + "\n"
    size = len(payload.encode("utf-8"))
    if size >= MAX_PUBLIC_BYTES:
        raise SystemExit(f"Output over 12 MB: {size} bytes")

    if args.match_log:
        log_path = pathlib.Path(args.match_log)
        if "data/private" not in log_path.as_posix():
            raise SystemExit("--match-log must be under data/private/ (raw product text must never be committed)")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        entries = [{"normalized_product_key": k, **key_info[k], "months_list": sorted(months_by_key.get(k, ())),
                    "raw_examples": list(examples_by_key.get(k, {}).values())} for k in sorted(history_keys) if k in raw_by_key]
        log_path.write_text(json.dumps({"offer_keys": total_keys, "summary": summary, "entries": entries}, ensure_ascii=False, indent=1) + "\n",
                            encoding="utf-8")

    write_registry(args.identities, registry)
    output.write_text(payload, encoding="utf-8")
    verification_path = pathlib.Path(args.verification) if args.verification else output.parent / "history_verification.json"
    verification_path.write_text(json.dumps(verification, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    reconcile_manifest_file(output)
    print(json.dumps({"raw_product_count": len(products), "records": len(rows), "bytes": size, "skipped": skipped,
                      "non_offer_rows_dropped": non_offer_rows, **summary}, ensure_ascii=False))
    if not summary["meets_required_overlap"]:
        print(f"WARNING: verified overlap {summary['verified_overlap']:.1%} is below the required {MIN_OVERLAP:.0%}; "
              f"{needed} more verified keys needed. Nothing was lowered or invented.")


if __name__ == "__main__":
    main()
