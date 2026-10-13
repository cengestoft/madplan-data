#!/usr/bin/env python3
"""Review list for history matching (reads the PRIVATE match log; writes a text file OUTSIDE the repo).

Usage: python3 scripts/history_match_audit.py OUTPUT.txt

First lines: counts of verified / review_required / rejected / no_candidate active keys and the verified overlap.
Then one block per key that needs a human look (review_required first), with the raw product's hash, status and
the identity fields that conflict or are missing. The file holds raw product names: never commit it.

A reviewer approves a raw product with scripts/history_decide.py KEY RAW_HASH verified --by NAME (hashes only are stored).
"""
from __future__ import annotations
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]


def one_line(s): return " ".join(str(s).split())[:150]


def main():
    out = Path(sys.argv[1]).expanduser()
    log = json.loads((ROOT / "data/private/match-log.json").read_text(encoding="utf-8"))
    s = log["summary"]
    lines = [f"Aktive fødevarenøgler: {s['active_food_keys']} | verified {s['verified']} | review_required {s['review_required']} | "
             f"rejected {s['rejected']} | ingen kandidat {s['no_candidate']}",
             f"Verificeret overlap: {s['verified_overlap']:.1%} (krav {s['required_overlap']:.0%}; mangler {s['additional_verified_needed']} verified nøgler)", ""]
    order = {"review_required": 0, "rejected": 1, "verified": 2}
    for e in sorted(log["entries"], key=lambda e: (order.get(e["status"], 3), e["normalized_product_key"])):
        if e["status"] == "verified" and "--all" not in sys.argv: continue
        lines.append(f"[{e['status'].upper()}] {e['normalized_product_key']}")
        lines.append(f"  tilbud: {' / '.join(e['offer_names'])}")
        for x in e["raw_examples"]:
            lines.append(f"  - {x['status']} hash={x['raw_hash']} {x['store']} | {one_line(x['raw_name'])}"
                         + (f" | konflikt: {','.join(x['conflicts'])}" if x["conflicts"] else "")
                         + (f" | mangler: {','.join(x['missing'])}" if x["missing"] else ""))
        lines.append("")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:2]))
    print("skrevet til", out)


if __name__ == "__main__":
    main()
