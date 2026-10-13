#!/usr/bin/env python3
"""Read-only diagnosis of history overlap on active grocery offers (never writes, never matches fuzzily).

Lists which active keys lack exact history, per store, and which of them have the
same brand+product in history under a different size/variant. Those are NOT
matches (package sizes are never invented); they show where the history builder
could be asked for the exact key.
"""
from __future__ import annotations
import collections, json, math, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from generate_acceptance_report import GROCERY_EXCLUDED, MIN_OVERLAP

def parts(k): return dict(p.split("=", 1) for p in k.split("|"))

def worklist(cur, keys, hkeys, hb, store_of):
    """Targeted list for the history builder: every active grocery key without exact history.

    `history_has_same_brand_product` shows which OTHER sizes/variants exist in history, only as a hint
    where to look in the raw data. They are never accepted as matches.
    """
    names = {}
    for o in cur["offers"]:
        k = o.get("normalized_product_key")
        if k in keys and k not in names: names[k] = o.get("name")
    rows = []
    for k in sorted(keys - hkeys):
        d = parts(k)
        rows.append({"normalized_product_key": k, "name": names.get(k), "stores": sorted(store_of[k]),
                     "history_has_same_brand_product": sorted(hb.get((d["brand"], d["product"]), []))})
    rows.sort(key=lambda r: (not r["history_has_same_brand_product"], r["normalized_product_key"]))
    return rows

def main():
    out_path = sys.argv[sys.argv.index("--worklist") + 1] if "--worklist" in sys.argv else None
    cur = json.loads((ROOT / "current_offers.json").read_text(encoding="utf-8"))
    hist = json.loads((ROOT / "monthly_price_history.json").read_text(encoding="utf-8"))
    keys, store_of = set(), collections.defaultdict(set)
    for o in cur["offers"]:
        k = o.get("normalized_product_key")
        if k and str(o.get("category") or "").lower() not in GROCERY_EXCLUDED:
            keys.add(k); store_of[k].add(o["store"])
    hkeys = {r["normalized_product_key"] for r in hist["records"] if r.get("normalized_product_key")}
    matched, missing = keys & hkeys, keys - hkeys
    hb = collections.defaultdict(set)
    for k in hkeys: d = parts(k); hb[(d["brand"], d["product"])].add(k)
    near = sorted(k for k in missing if (parts(k)["brand"], parts(k)["product"]) in hb)
    per_store = collections.Counter(s for k in missing for s in store_of[k])
    need = math.ceil(MIN_OVERLAP * len(keys)) - len(matched)
    if out_path:
        Path(out_path).write_text(json.dumps(worklist(cur, keys, hkeys, hb, store_of), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"active_grocery_keys": len(keys), "with_exact_history": len(matched),
                      "overlap": round(len(matched) / max(1, len(keys)), 4), "required": MIN_OVERLAP,
                      "keys_short_of_required": max(0, need), "missing_by_store": dict(per_store.most_common()),
                      "missing_but_same_brand_product_in_history_other_size_or_variant": len(near),
                      "examples_other_size": near[:10]}, ensure_ascii=False, indent=1))

if __name__ == "__main__": main()
