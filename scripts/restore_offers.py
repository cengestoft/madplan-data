#!/usr/bin/env python3
"""Sikker gendannelse af data/offers.json fra data/offers.previous.json (kun manuel brug).

Udløbne tilbud genaktiveres aldrig: kun tilbud, der stadig er gyldige i dag, tages med. Ugyldig backup eller ingen gyldige tilbud
tilbage: intet skrives, og scriptet fejler. Output er et fast vokabular (intet indhold).

Brug: python scripts/restore_offers.py --from data/offers.previous.json --to data/offers.json
"""
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import offer_guard  # noqa: E402


def main(argv=None, now=None):
    argv = sys.argv[1:] if argv is None else argv
    src = argv[argv.index("--from") + 1] if "--from" in argv else "data/offers.previous.json"
    dst = argv[argv.index("--to") + 1] if "--to" in argv else "data/offers.json"
    now = now or dt.datetime.now(dt.timezone.utc)
    today = now.astimezone(offer_guard.CPH_TZ).date()
    backup = offer_guard.load_previous(src)
    doc, report = offer_guard.restore_doc(backup, today, now)
    print("gendannelse: " + ", ".join("%s=%s" % kv for kv in report.items()))
    if doc is None:
        print("Intet skrevet.")
        return 1
    offer_guard.write_atomic(dst, doc)
    print("Skrev %s" % dst)
    return 0


if __name__ == "__main__":
    sys.exit(main())
