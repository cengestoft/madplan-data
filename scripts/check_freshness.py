#!/usr/bin/env python3
"""Live freshness of the published offer data (separate from snapshot integrity).

Snapshot tests must not fail just because the calendar moved. This check does the
opposite on purpose: it reports, clearly, when the published data is old.
Exit 1 = stale (advisory in CI), 0 = fresh. It never writes anything.
"""
from __future__ import annotations
import argparse, datetime as dt, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from offer_schema import copenhagen_today, offer_status, snapshot_date

ROOT = Path(__file__).resolve().parents[1]

def freshness(cur: dict, today: dt.date, max_age_days: int = 2):
    snap = snapshot_date(cur)
    age = (today - snap).days
    offers = cur.get("offers", [])
    expiring = sum(1 for o in offers if offer_status(o, today) == "expired")
    return {"today": str(today), "snapshot_date": str(snap), "age_days": age, "max_age_days": max_age_days,
            "stale": age > max_age_days or expiring > 0, "expired_in_index": expiring}

def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--today"); ap.add_argument("--max-age-days", type=int, default=2)
    ap.add_argument("--informational", action="store_true",
                    help="Meld kun en note og afslut altid med 0 (bruges til de interne snapshots, som ikke er appens tilbudskilde)")
    a = ap.parse_args(argv)
    today = dt.date.fromisoformat(a.today) if a.today else copenhagen_today()
    res = freshness(json.loads((ROOT / "current_offers.json").read_text(encoding="utf-8")), today, a.max_age_days)
    print(json.dumps(res))
    if res["stale"]:
        msg = (f"snapshot {res['snapshot_date']} is {res['age_days']} days old; "
               f"{res['expired_in_index']} offers in the index have expired on {res['today']}.")
        if a.informational:
            print("::notice::Intern snapshot (current_offers.json), ikke appens tilbudskilde: " + msg)
        else:
            print("::warning::Live offer data is stale: " + msg)
    return 0 if a.informational else (1 if res["stale"] else 0)

if __name__ == "__main__": sys.exit(main())
