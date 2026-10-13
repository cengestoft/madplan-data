#!/usr/bin/env python3
"""Read-only report of VERIFIED history overlap on active food keys (never writes history, never matches fuzzily).

Numerator: unique active food keys with status 'verified' in history_verification.json.
Denominator: all unique active food keys on the snapshot date (household and pet food excluded).
Unverified matches (review_required, rejected) do not count.

  --worklist OUT.json   list every active key that is not verified, with its status and the identity fields that conflict
                        or are missing (no raw text, safe to share)
"""
from __future__ import annotations
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from history_identity import verified_overlap, GROCERY_EXCLUDED
from offer_schema import offer_status, snapshot_date


def main():
    out_path = sys.argv[sys.argv.index("--worklist") + 1] if "--worklist" in sys.argv else None
    cur = json.loads((ROOT / "current_offers.json").read_text(encoding="utf-8"))
    vpath = ROOT / "history_verification.json"
    ver = json.loads(vpath.read_text(encoding="utf-8")) if vpath.exists() else None
    today = snapshot_date(cur)
    r = verified_overlap(cur, ver, today)
    if out_path:
        rows = []
        names = {}
        for o in cur["offers"]:
            k = o.get("normalized_product_key")
            if k and offer_status(o, today) == "active" and str(o.get("category") or "").lower() not in GROCERY_EXCLUDED:
                names.setdefault(k, o.get("name"))
        for k in sorted(names):
            info = ((ver or {}).get("keys") or {}).get(k) or {}
            if info.get("status") != "verified":
                rows.append({"normalized_product_key": k, "offer_name": names[k], "status": info.get("status", "no_candidate"),
                             "conflict_fields": info.get("conflict_fields", {}), "missing_fields": info.get("missing_fields", {}),
                             "raw_products": info.get("raw_products", {})})
        rows.sort(key=lambda x: (x["status"] != "review_required", x["normalized_product_key"]))
        Path(out_path).write_text(json.dumps(rows, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"snapshot_date": str(today), "active_food_keys": r["active_food_keys"], "verified": r["verified"],
                      "review_required": r["review_required"], "rejected": r["rejected"], "no_candidate": r["no_candidate"],
                      "verified_overlap": round(r["overlap"], 4), "required": r["required"],
                      "additional_verified_needed": r["additional_verified_needed"],
                      "verification_file_present": r["verification_file_present"]}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
