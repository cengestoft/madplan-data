#!/usr/bin/env python3
"""Read-only daily freshness audit for every store. No invented offers or dates."""
import datetime as dt
import json
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
TODAY = dt.datetime.now(ZoneInfo("Europe/Copenhagen")).date()

def main():
    rows = []
    for path in sorted((ROOT / "stores").glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        offers = doc.get("offers", [])
        active = future = expired = unknown = 0
        for o in offers:
            try:
                start = dt.date.fromisoformat(o["valid_from"])
                end = dt.date.fromisoformat(o["valid_to"])
            except (ValueError, TypeError, KeyError):
                unknown += 1
                continue
            if start > TODAY:
                future += 1
            elif end < TODAY:
                expired += 1
            else:
                active += 1
        try:
            generated = dt.datetime.fromisoformat(doc["generated_at"]).date()
            age = (TODAY - generated).days
        except (ValueError, TypeError, KeyError):
            age = None
        rows.append({"store": doc.get("store") or path.stem, "file": str(path.relative_to(ROOT)),
                     "snapshot_age_days": age, "active": active, "future": future,
                     "expired": expired, "unknown_dates": unknown,
                     "needs_refresh": age is None or age > 2 or active == 0})
    result = {"date": str(TODAY), "stores": rows, "stores_needing_refresh": [r["store"] for r in rows if r["needs_refresh"]]}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    Path("daily_store_freshness_report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if result["stores_needing_refresh"]:
        print("::warning::Stale or empty store feeds: " + ", ".join(result["stores_needing_refresh"]))

if __name__ == "__main__":
    main()
