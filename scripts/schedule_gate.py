#!/usr/bin/env python3
"""Tidsstyring for den daglige hentning kl. 08 dansk tid, med korrekt sommer-/vintertid.

GitHub Actions-cron er altid UTC. Workflowet udløses derfor 3 gange (06:03, 07:03 og 08:03 UTC), og dette trin afgør,
om kørslen skal gennemføres:
  - manuel kørsel (workflow_dispatch): altid ja
  - planlagt kørsel: kun hvis klokken er 8 eller 9 i København OG dagens hentning ikke allerede er sket
Resultat: præcis én hentning om dagen (ca. 08.03 dansk tid), og en reserve en time senere, hvis GitHub er forsinket.
Output er et fast vokabular (ingen indhold): run=yes|no og reason.
"""
import datetime as dt
import json
import os
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

CPH = ZoneInfo("Europe/Copenhagen")
WINDOW_HOURS = (8, 9)


def last_fetch_date(path):
    """Dansk dato for den seneste hentning (fra generated_at i filen), eller None."""
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
        ts = dt.datetime.fromisoformat(str(doc["generated_at"]).replace("Z", "+00:00"))
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=dt.timezone.utc)
    return ts.astimezone(CPH).date()


def decide(event, now_utc, last_date):
    """Returnerer (kør: bool, årsag)."""
    if event != "schedule":
        return True, "manuel"
    local = now_utc.astimezone(CPH)
    if local.hour not in WINDOW_HOURS:
        return False, "udenfor_tidsrum"
    if last_date == local.date():
        return False, "allerede_hentet"
    return True, "planlagt"


def main(argv=None, now=None):
    argv = sys.argv[1:] if argv is None else argv
    event = argv[argv.index("--event") + 1] if "--event" in argv else "schedule"
    path = argv[argv.index("--last") + 1] if "--last" in argv else "data/offers.json"
    now = now or dt.datetime.now(dt.timezone.utc)
    run, reason = decide(event, now, last_fetch_date(path))
    line = "run=%s\nreason=%s" % ("yes" if run else "no", reason)
    print(line)
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
