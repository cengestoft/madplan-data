#!/usr/bin/env python3
"""Read-only snapshot freshness audit; never relabels old offers as new."""
import argparse
import datetime as dt
import json
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
MAX_AGE_DAYS = 4


def audit(root=ROOT, now=None):
    now = now or dt.datetime.now(ZoneInfo("Europe/Copenhagen"))
    today = now.astimezone(ZoneInfo("Europe/Copenhagen")).date()
    files = {}
    for filename in ("current_offers.json", "next_week_offers.json"):
        try:
            data = json.loads((root / filename).read_text(encoding="utf-8"))
            generated = dt.datetime.fromisoformat(data["generated_at"].replace("Z", "+00:00"))
            if generated.tzinfo is None:\n                raise ValueError("generated_at must include timezone")\n            age = (today - generated.astimezone(ZoneInfo("Europe/Copenhagen")).date()).days
            files[filename] = {
                "generated_at": data["generated_at"],
                "age_days": age,
                "fresh": 0 <= age <= MAX_AGE_DAYS,
            }
        except (OSError, ValueError, KeyError, TypeError) as exc:
            files[filename] = {"fresh": False, "error": type(exc).__name__}
    healthy = all(v["fresh"] for v in files.values())
    return {
        "checked_at": now.isoformat(),
        "status": "fresh" if healthy else "stale_unverified",
        "freshness_only": healthy,\n        "safe_to_import": False,
        "files": files,
        "reason": None if healthy else "No verified refresh of internal snapshots; do not update generated_at or import prices.",
        "next_action": "Verify rights-cleared source and implement separately reviewed importer; private Tilbudsugen data must not be published here.",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path("snapshot_audit.json"))
    args = parser.parse_args()
    result = audit()
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    if not result["freshness_only"]:
        print("::warning::Internal offer snapshots stale or unreadable. No data changed.")


if __name__ == "__main__":
    main()
