#!/usr/bin/env python3
"""Mark offers whose quantity is unverified (data_sources/offer_quantity_flags.json) in current_offers.json and stores/*.json.

Only adds quantity_status/quantity_note to the listed offer ids. Prices, amounts, units, keys and all other fields are never changed.
Re-run after a new offer import overwrote the records. Usage: python3 scripts/apply_quantity_flags.py [--check]
"""
from __future__ import annotations
import glob, json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
NOTE = "Mængden er ikke bekræftet mod originalkilden (afviger fra samme vare i andre kæder). Tjek pakken."

def load_flags():
    return {f["offer_id"]: f for f in json.loads((ROOT / "data_sources/offer_quantity_flags.json").read_text(encoding="utf-8"))["flags"]}

def files():
    return [ROOT / "current_offers.json", *sorted(Path(p) for p in glob.glob(str(ROOT / "stores/*.json")))]

def apply(write: bool):
    flags, changed = load_flags(), []
    for path in files():
        doc = json.loads(path.read_text(encoding="utf-8"))
        dirty = False
        for o in doc.get("offers", []):
            if o.get("id") in flags and (o.get("quantity_status") != "unverified" or o.get("quantity_note") != NOTE):
                o["quantity_status"], o["quantity_note"] = "unverified", NOTE
                dirty = True
        if dirty:
            changed.append(path.name)
            if write:
                path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return changed

if __name__ == "__main__":
    check = "--check" in sys.argv
    changed = apply(write=not check)
    print(json.dumps({"files_needing_flag" if check else "files_updated": changed}))
    sys.exit(1 if check and changed else 0)
