#!/usr/bin/env python3
"""Move offers from next_week_offers.json to current_offers.json once they are valid today.

Only offers with a documented valid_from AND valid_to that contain today's Danish date are promoted. Offers without valid_to are NEVER
promoted and never get an invented end date. Offers already in current_offers.json (same store, name, price, valid_from) are not duplicated.

Usage: python3 scripts/promote_future_offers.py [--today YYYY-MM-DD] [--write]   (then run build_data_pipeline.py --write, feed and report)
"""
from __future__ import annotations
import argparse, datetime as dt, hashlib, json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from offer_schema import canonicalize_offer, copenhagen_today, offer_status


def ident(o):
    return (o.get("store"), o.get("name"), o.get("price_dkk"), o.get("valid_from"))


def promotable(offer, today):
    return bool(offer.get("valid_from")) and bool(offer.get("valid_to")) and offer_status(canonicalize_offer(offer), today) == "active"


def promote(current, nxt, today):
    """Returns (current2, next2, promoted, skipped_without_end, already_present)."""
    have = {ident(o) for o in current["offers"]}
    promoted, keep, no_end, present = [], [], 0, 0
    for o in nxt["offers"]:
        if not o.get("valid_to") and offer_status(canonicalize_offer(o), today) == "unknown_end":
            no_end += 1
        if not promotable(o, today):
            keep.append(o); continue
        if ident(o) in have:
            present += 1; continue  # already current: drop from next week, do not duplicate
        rec = dict(canonicalize_offer(o))
        rec["id"] = "next-" + hashlib.sha1("|".join(str(x) for x in ident(o)).encode()).hexdigest()[:10]
        promoted.append(rec)
    current2 = dict(current); current2["offers"] = current["offers"] + promoted; current2["offer_count"] = len(current2["offers"])
    next2 = dict(nxt); next2["offers"] = keep; next2["offer_count"] = len(keep)
    return current2, next2, promoted, no_end, present


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--today"); ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    today = dt.date.fromisoformat(a.today) if a.today else copenhagen_today()
    cp, np_ = ROOT / "current_offers.json", ROOT / "next_week_offers.json"
    current, nxt = json.loads(cp.read_text(encoding="utf-8")), json.loads(np_.read_text(encoding="utf-8"))
    c2, n2, promoted, no_end, present = promote(current, nxt, today)
    print(json.dumps({"today": str(today), "promoted": len(promoted), "left_in_next_week": len(n2["offers"]), "without_valid_to_not_promoted": no_end,
                      "already_current": present, "names": [o["name"] for o in promoted]}, ensure_ascii=False))
    if a.write:
        from apply_quantity_flags import apply_to_offers, load_flags
        flags = load_flags()
        _n, problems = apply_to_offers(c2["offers"], flags, today)
        if problems:
            raise SystemExit("; ".join(problems))
        cp.write_text(json.dumps(c2, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        np_.write_text(json.dumps(n2, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
