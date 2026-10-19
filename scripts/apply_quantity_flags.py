#!/usr/bin/env python3
"""Mark offers whose quantity is unverified (data_sources/offer_quantity_flags.json) in current_offers.json and stores/*.json.

Rules
  * Only quantity_status/quantity_note are added or removed, and only on the listed offer ids. Prices, amounts, units, keys and every
    other field are never changed, and nothing is ever corrected by guessing.
  * A mark is only (re)applied to offers that exist and are not expired. It is never created for an expired or missing offer.
  * It runs automatically in build_data_pipeline.py and promote_future_offers.py, i.e. after every offer import and before the data is
    validated and published, so a fresh import that dropped the mark gets it back as long as the offer is still active.
  * Lifting: set the flag's status to "confirmed" with confirmed_by, confirmed_on, confirmed_source and confirmed_quantity (the amounts the
    ORIGINAL SOURCE states). The mark is only removed when ALL of these agree with it: package_count, single_package_amount,
    package_amount, package_unit, count x single = total, unit_price_dkk (litre price, 2 decimals half-up), volume_l, normalized_package_size
    and normalized_product_key (checked with the existing normalization rules). Any deviation keeps the mark, blocks publication and names
    the deviating fields. The same offer must also carry identical quantity fields in current_offers.json and every store file.
Usage: python3 scripts/apply_quantity_flags.py [--check] [--today YYYY-MM-DD]
"""
from __future__ import annotations
import argparse, datetime as dt, glob, json, math, re, sys
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from offer_schema import offer_status, copenhagen_today
from product_normalization import normalize_record, _slug  # the existing normalization rules; no competing method

NOTE = "Mængden er ikke bekræftet mod originalkilden (afviger fra samme vare i andre kæder). Tjek pakken."
REGISTRY = "data_sources/offer_quantity_flags.json"
QUANTITY_FIELDS = ("package_count", "single_package_amount", "package_amount", "package_unit")
CONFIRM_FIELDS = ("confirmed_by", "confirmed_on", "confirmed_source", "confirmed_quantity")


# Fields that must describe the SAME package size in current_offers.json and every store file.
CONSISTENCY_FIELDS = ("price_dkk", "package_count", "single_package_amount", "single_package_unit", "package_amount", "package_unit",
                      "unit_price_dkk", "volume_l", "normalized_package_count", "normalized_package_size", "normalized_product_key")
_TO_LITRE = {"l": 1.0, "cl": 0.01, "ml": 0.001}


class FlagError(ValueError):
    pass


def _close(a, b):
    try:
        return math.isclose(float(a), float(b), rel_tol=1e-9, abs_tol=1e-9)
    except (TypeError, ValueError):
        return False


def _litres(amount, unit):
    f = _TO_LITRE.get(unit)
    return None if f is None or amount is None else float(amount) * f


def confirmed_deviations(o, cq):
    """Names of the fields of offer `o` that do not agree with the source-confirmed quantity `cq`. Empty list = consistent.
    Never changes anything. Expected values come from the confirmed quantity and the existing normalization rules."""
    dev = [k for k in QUANTITY_FIELDS if o.get(k) != cq[k]]
    n, single, total, unit = cq["package_count"], cq["single_package_amount"], cq["package_amount"], cq["package_unit"]
    if o.get("single_package_unit") != unit and not (_litres(1, o.get("single_package_unit")) and _litres(1, unit)):
        dev.append("single_package_unit")
    s_l, t_l = _litres(single, unit), _litres(total, unit)
    if (s_l is not None and not _close(n * s_l, t_l)) or (s_l is None and not _close(n * single, total)):
        dev.append("confirmed_quantity(count x single != total)")
    if unit == "l":  # litre price, rounded half-up to two decimals
        try:
            exp = (Decimal(str(o["price_dkk"])) / Decimal(str(total))).quantize(Decimal("0.01"), ROUND_HALF_UP)
            if o.get("unit_price_dkk") is None or Decimal(str(o["unit_price_dkk"])) != exp:
                dev.append("unit_price_dkk")
        except Exception:
            dev.append("unit_price_dkk")
    if s_l is not None and not _close(o.get("volume_l"), s_l):
        dev.append("volume_l")
    probe = dict(o, package_count=n, single_package_amount=single, single_package_unit=unit, package_amount=total, package_unit=unit)
    exp_rec, _ = normalize_record(probe)  # existing rules
    if o.get("normalized_package_count") != n:
        dev.append("normalized_package_count")
    size = o.get("normalized_package_size") or {}
    if not (_close(size.get("amount"), single) and size.get("unit") == unit):
        dev.append("normalized_package_size")
    key = o.get("normalized_product_key") or ""
    m = re.search(r"\|count=([^|]+)\|size=([^|]+)$", key)
    want_size = _slug(f"{single:g}{unit}")
    if key != exp_rec["normalized_product_key"] or not m or m.group(1) != str(n) or m.group(2) != want_size:
        dev.append("normalized_product_key")
    seen = set()
    return [d for d in dev if not (d in seen or seen.add(d))]


def consistency_problems(records_by_file, flags, today):
    """Flagged offers must carry identical quantity fields in current_offers.json and every store file. {file name: offers}."""
    problems = []
    for oid in flags:
        found = {}
        for name, offers in records_by_file.items():
            for o in offers:
                if o.get("id") == oid and offer_status(o, today) != "expired":
                    found[name] = normalize_record(o)[0]  # same rules for every file, so light index records compare fairly
        if len(found) > 1:
            (n0, o0), rest = next(iter(found.items())), list(found.items())[1:]
            for n, o in rest:
                diff = [k for k in CONSISTENCY_FIELDS if o0.get(k) != o.get(k)]
                if diff:
                    problems.append(f"{oid}: {n0} and {n} differ in {', '.join(diff)}")
    return problems


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
        else:  # confirmed: every quantity-dependent field must agree with the source-confirmed quantity on every non-expired offer
            if offer_status(o, today) == "expired":
                continue
            # Store files hold light records without normalized_* fields; those are judged with the same normalization rules as in consistency_problems.
            rec = o if o.get("normalized_package_size") is not None else normalize_record(o)[0]  # light record: derive them
            dev = confirmed_deviations(rec, f["confirmed_quantity"])
            if dev:
                problems.append(f"{o['id']}: confirmed quantity disagrees with field(s) {', '.join(dev)}; the mark stays and publication is "
                                f"blocked until amount, unit price, volume, single package amount and product key are corrected together")
                if not marked:  # keep the offer unverified
                    o["quantity_status"], o["quantity_note"] = "unverified", NOTE
                    changed += 1
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
    docs = {path: json.loads(path.read_text(encoding="utf-8")) for path in files(root) if path.exists()}
    problems += consistency_problems({p.name if p.name == "current_offers.json" else f"stores/{p.name}": d.get("offers", [])
                                      for p, d in docs.items()}, flags, today)
    for path, doc in docs.items():
        n, probs = apply_to_offers(doc.get("offers", []), flags, today)
        problems += probs
        if n:
            changed_files.append(path.name)
            if write and not problems:
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
