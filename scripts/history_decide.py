#!/usr/bin/env python3
"""Record a human review decision for a raw product (stores only hashes, never raw text).

Usage: python3 scripts/history_decide.py KEY RAW_HASH verified|rejected --by NAME [--note TEXT]

'verified' only promotes a raw product that the importer marked review_required; a hard conflict (other brand, meat,
flavour, fat percentage, pack count, size or unit) is never overridden. 'rejected' always removes the product.
The decision is applied on the next import (data_sources/history_review_decisions.json).
"""
from __future__ import annotations
import argparse, datetime as dt, json
from pathlib import Path
PATH = Path(__file__).resolve().parents[1] / "data_sources" / "history_review_decisions.json"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("key"); ap.add_argument("raw_hash"); ap.add_argument("decision", choices=["verified", "rejected"])
    ap.add_argument("--by", required=True); ap.add_argument("--note", default="")
    a = ap.parse_args()
    doc = json.loads(PATH.read_text(encoding="utf-8")) if PATH.exists() else {"schema_version": 1, "raw_data_included": False, "decisions": []}
    doc["decisions"] = [d for d in doc["decisions"] if (d["normalized_product_key"], d["raw_id_hash"]) != (a.key, a.raw_hash)]
    doc["decisions"].append({"normalized_product_key": a.key, "raw_id_hash": a.raw_hash, "decision": a.decision,
                             "reviewed_by": a.by, "reviewed_on": dt.date.today().isoformat(), "note": a.note})
    doc["decisions"].sort(key=lambda d: (d["normalized_product_key"], d["raw_id_hash"]))
    PATH.parent.mkdir(exist_ok=True)
    PATH.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"gemt: {a.key} {a.raw_hash} {a.decision} ({len(doc['decisions'])} beslutninger)")


if __name__ == "__main__":
    main()
