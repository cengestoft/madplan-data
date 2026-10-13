#!/usr/bin/env python3
"""Strict documentation check for human history approvals (review_required -> verified).

A decision is only DOCUMENTED when the offer and the raw product name the same product line:
  * distinctive words (brand, pack sizes, fat numbers, generic product-type words removed) are the same set on both sides, and
  * the raw product is traceable (its raw_id_hash is in the private match-log), and
  * pack count, size and unit already agreed (the importer would have marked a conflict as rejected, never review_required).
Equal normalized_product_key alone is never enough. Everything that does not pass stays review_required.

Raw names are read only from the PRIVATE match-log (data/private/match-log.json); nothing here is written to the repository
except the pruned decisions file (hashes only).

Usage: python3 scripts/history_approval_check.py [--match-log data/private/match-log.json] [--prune]
"""
from __future__ import annotations
import argparse, json, re
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from history_identity import fold

# Words that describe the product TYPE or are filler. They may be missing on one side without changing identity.
GENERIC = set("""med m og u uden tilsat sukker fedt pet i
proteinbar bar bars protein soft is dessert skiveost skiver skive ost floedeost smoereost chokoladeplade slikstjerner stjerner
muslibar laeskedrik knaekbroed hvedeknaekbroed yoghurt_dummy""".split())
UNITS = {"g", "gr", "kg", "ml", "cl", "l", "stk", "pk", "gram", "x", "st"}
SYN = {"rababer": "rabarber", "creatine": "creatin", "kreatin": "creatin", "schweizernoed": "schweizernot", "crakers": "kiks"}


def stem(w: str) -> str:
    w = SYN.get(w, w)
    for suf in ("ede", "er", "et", "e"):
        if len(w) > 5 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def distinctive(text: str, brand: str) -> set:
    brand_words = set(re.findall(r"[a-z0-9]+", fold(brand or "")))
    out = set()
    for w in re.findall(r"[a-z0-9]+", fold(text)):
        if w in GENERIC or w in UNITS or w in brand_words or w[0].isdigit():
            continue
        out.add(stem(w))
    return out


def raw_title(name: str) -> str:
    """Raw names look like 'Brand, Title, Description' (webshops) or 'TITLE, SIZE / BRAND' (supermarket systems)."""
    parts = [p.strip() for p in str(name).split(", ")]
    return parts[1] if len(parts) >= 3 else parts[0]


def documented(offer_names, brand, raw_name) -> tuple[bool, str]:
    rt = distinctive(raw_title(raw_name), brand)
    if not rt:
        # the brand string itself carries the whole product name (e.g. "Coca-Cola Zero"): then compare the words WITH the brand
        rt = distinctive(raw_title(raw_name), "")
        brand = ""
    if not rt:
        return False, "raw title has no distinctive words"
    for on in offer_names:
        ot = distinctive(on, brand)
        if ot != rt:
            return False, f"different words: offer-only {sorted(ot - rt)}, raw-only {sorted(rt - ot)}"
    return True, "same distinctive words"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--match-log", default="data/private/match-log.json")
    ap.add_argument("--decisions", default="data_sources/history_review_decisions.json")
    ap.add_argument("--identities", default="data_sources/history_offer_identities.json")
    ap.add_argument("--prune", action="store_true", help="drop decisions that are not documented (they stay review_required)")
    a = ap.parse_args()
    log = json.loads(Path(a.match_log).read_text(encoding="utf-8"))
    raw = {(e["normalized_product_key"], x["raw_hash"]): x["raw_name"] for e in log["entries"] for x in e.get("raw_examples", [])}
    reg = json.loads(Path(a.identities).read_text(encoding="utf-8"))["keys"]
    doc = json.loads(Path(a.decisions).read_text(encoding="utf-8"))
    keep, drop = [], []
    for d in doc["decisions"]:
        if d["decision"] != "verified":
            keep.append(d); continue
        k, h = d["normalized_product_key"], d["raw_id_hash"]
        offers = reg.get(k, [])
        name = raw.get((k, h))
        if name is None or not offers:
            drop.append((d, "not traceable to a raw product / unknown offer")); continue
        ok, why = documented([o["name"] for o in offers], offers[0].get("brand"), name)
        (keep if ok else drop).append(d if ok else (d, why))
    print(json.dumps({"decisions": len(doc["decisions"]), "documented": len(keep), "not_documented": len(drop)}))
    for d, why in drop[:200]:
        print("  stays review_required:", d["normalized_product_key"], d["raw_id_hash"][:6], "-", why)
    if a.prune:
        doc["decisions"] = keep
        Path(a.decisions).write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
