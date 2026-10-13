#!/usr/bin/env python3
"""Mark offers whose quantity is unverified (data_sources/offer_quantity_flags.json) in current_offers.json and stores/*.json.

Rules
  * Only quantity_status/quantity_note are added or removed, and only on the listed offer ids. Prices, amounts, units, keys and every
    other field are never changed, and nothing is ever corrected by guessing.
  * A mark is only (re)applied to offers that exist and are not expired. It is never created for an expired or missing offer.
  * It runs automatically in build_data_pipeline.py and promote_future_offers.py, i.e. after every offer import and before the data is
    validated and published, so a fresh import that dropped the mark gets it back as long as the offer is still active.
  * Lifting: set the flag's status to "confirmed" with confirmed_by, confirmed_on, confirmed_source and confirmed_quantity (the amounts the
    ORIGINAL SOURCE states). The mark is only removed when the offer already carries exactly those amounts; otherwise the run stops
    with an error, because package amount, unit price, volume, single package amount and product key must be corrected together first.
Usage: python3 scripts/apply_quantity_flags.py [--check] [--today YYYY-MM-DD]
"""
from __future__ import annotations
import argparse, datetime as dt, glob, json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from offer_schema import offer_status, copenhagen_today

NOTE = "Mængden er ikke bekræftet mod originalkilden (afviger fra samme vare i andre kæder). Tjek pakken."
REGISTRY = "data_sources/offer_quantity_flags.json"
QUANTITY_FIELDS = ("package_count", "single_package_amount", "package_amount", "package_unit")
CONFIRM_FIELDS = ("confirmed_by", "confirmed_on", "confirmed_source", "confirmed_quantity")


class FlagError(ValueError):
    pass


def load_flags(root=ROOT):
    doc = json.loads((Path(root) / REGISTRY).read_text(encoding="utf-8"))
    flags = {}
    for f in doc.get("flags", []):
        if f.get("status") not in ("unverified", "confirmed"):
            raise FlagError(f"{f.get('offer_id')}: status must be 'unverified' or 'confirmed'")
        if f["status"] == "confirmed":
            missing = [k for k in CONFIRM_FIELDS if not f.get(k)]
            if missing:
                raise FlagError(f"{f['offer_id']}: lifting a mark needs {', '.join(missing)}")
            if set(f["confirmed_quantity"]) != set(QUANTITY_FIELDS):
                raise FlagError(f"{f['offer_id']}: confirmed_quantity must state {', '.join(QUANTITY_FIELDS)}")
        if f["offer_id"] in flags:
            raise FlagError(f"duplicate flag for {f['offer_id']}")
        flags[f["offer_id"]] = f
    return flags


def apply_to_offers(offers, flags, today):
    """Mutates the offer dicts in place. Returns (number of offers changed, list of problems)."""
    changed, problems = 0, []
    for o in offers:
        f = flags.get(o.get("id"))
        if not f:
            continue
        marked = o.get("quantity_status") == "unverified"
        if f["status"] == "unverified":
            if offer_status(o, today) == "expired":
                continue  # never (re)create a mark on an expired offer
            if not marked or o.get("quantity_note") != NOTE:
                o["quantity_status"], o["quantity_note"] = "unverified", NOTE
                changed += 1
        else:  # confirmed: amounts must match the source-confirmed quantity on every non-expired offer
            if offer_status(o, today) == "expired":
                continue
            if any(o.get(k) != f["confirmed_quantity"][k] for k in QUANTITY_FIELDS):
                problems.append(f"{o['id']}: source-confirmed quantity {f['confirmed_quantity']} differs from the offer's amounts; "
                                f"correct amount, unit price, volume, single package amount and product key together before lifting the mark")
                continue
            if marked or "quantity_note" in o:
                o.pop("quantity_status", None); o.pop("quantity_note", None)
                changed += 1
    return changed, problems


def files(root=ROOT):
    root = Path(root)
    return [root / "current_offers.json", *sorted(Path(p) for p in glob.glob(str(root / "stores/*.json")))]


def apply(write: bool, today=None, root=ROOT):
    """Applies the registry to current_offers.json and stores/*.json. Returns (changed file names, problems)."""
    today, flags, changed_files, problems = today or copenhagen_today(), load_flags(root), [], []
    for path in files(root):
        if not path.exists():
            continue
        doc = json.loads(path.read_text(encoding="utf-8"))
        n, probs = apply_to_offers(doc.get("offers", []), flags, today)
        problems += probs
        if n:
            changed_files.append(path.name)
            if write and not probs:
                path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return changed_files, problems


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--check", action="store_true"); ap.add_argument("--today")
    a = ap.parse_args()
    try:
        changed, problems = apply(write=not a.check, today=dt.date.fromisoformat(a.today) if a.today else None)
    except FlagError as e:
        print(json.dumps({"error": str(e)})); sys.exit(1)
    print(json.dumps({"files_needing_change" if a.check else "files_updated": changed, "problems": problems}, ensure_ascii=False))
    sys.exit(1 if problems or (a.check and changed) else 0)
