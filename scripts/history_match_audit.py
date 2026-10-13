#!/usr/bin/env python3
"""Audit of how every active offer key got its history (reads the PRIVATE match log; writes a text file, never into the repo).

Usage: python3 scripts/history_match_audit.py OUTPUT.txt
One line per matched key: NY/GAMMEL (vs. the committed monthly_price_history.json), methods, raw examples.
The output holds raw product names, so it must not be committed (default location is outside the repo).
"""
from __future__ import annotations
import collections, json, subprocess, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

def one_line(s): return " ".join(str(s).split())[:140]

def main():
    out = Path(sys.argv[1]).expanduser()
    log = json.loads((ROOT / "data/private/match-log.json").read_text(encoding="utf-8"))
    old = json.loads(subprocess.check_output(["git", "-C", str(ROOT), "show", "HEAD:monthly_price_history.json"]))
    old_keys = {r["normalized_product_key"] for r in old["records"]}
    counts = collections.Counter()
    lines = []
    for e in sorted(log["entries"], key=lambda e: e["normalized_product_key"]):
        methods = sorted(e["methods"])
        kind = "kun-direct" if methods == ["direct"] else ("kun-conservative" if methods == ["conservative"] else "blandet")
        age = "GAMMEL" if e["normalized_product_key"] in old_keys else "NY"
        counts[(age, kind)] += 1
        ex = "; ".join(one_line(x["raw_name"]) + f" [{x.get('raw_brand')}]" for x in e["raw_examples"][:2])
        lines.append(f"{age} | {kind} | {e['normalized_product_key']} | {e['month_count']} mdr | {ex}")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("matchede aktive nøgler:", len(lines), "af", log["offer_keys"], f"({len(lines)/max(1,log['offer_keys']):.1%})")
    for k, v in sorted(counts.items()): print(" ", k[0], k[1], v)
    print("skrevet til", out)

if __name__ == "__main__": main()
