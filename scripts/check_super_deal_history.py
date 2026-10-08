#!/usr/bin/env python3
"""Validate Supertilbud history coverage.

Creates super_deal_history_report.json and optionally appends missing-history
issues to data_quality_errors.json. Frontend must not invent keys or graphs.
"""
from __future__ import annotations
import argparse, json
from pathlib import Path
from datetime import datetime

MIN_MONTHS = 3
MAX_HISTORY_BYTES = 12 * 1024 * 1024

def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))

def build_report(super_deals_path="super_deals_current.json",
                 history_path="monthly_price_history.json"):
    deals=load(super_deals_path)
    history_file=Path(history_path)
    history=load(history_path)
    records=history.get("records",[])
    months_by_key={}
    for r in records:
        key=r.get("normalized_product_key")
        month=r.get("month")
        if key and month:
            months_by_key.setdefault(key,set()).add(month)

    rows=[]
    for o in deals.get("offers",[]):
        key=o.get("normalized_product_key")
        months=sorted(months_by_key.get(key,set()))
        rows.append({
            "offer_id":o.get("id"),
            "name":o.get("name"),
            "store":o.get("store"),
            "normalized_product_key":key,
            "history_month_count":len(months),
            "has_minimum_history":len(months)>=MIN_MONTHS,
            "history_months":months,
            "graph_allowed":len(months)>=MIN_MONTHS
        })

    ok=sum(1 for r in rows if r["has_minimum_history"])
    total=len(rows)
    size=history_file.stat().st_size
    return {
        "schema_version":1,
        "generated_at":datetime.now().astimezone().isoformat(timespec="seconds"),
        "minimum_history_months":MIN_MONTHS,
        "super_deal_count":total,
        "with_minimum_history":ok,
        "without_minimum_history":total-ok,
        "coverage_ratio":round(ok/total,4) if total else 1.0,
        "monthly_history_bytes":size,
        "monthly_history_under_12mb":size < MAX_HISTORY_BYTES,
        "status":"pass" if size < MAX_HISTORY_BYTES else "fail",
        "offers":rows
    }

def update_errors(report, path="data_quality_errors.json"):
    p=Path(path)
    data=load(p) if p.exists() else {"errors":[]}
    errors=[e for e in data.get("errors",[]) if e.get("type")!="super_deal_missing_history"]
    for r in report["offers"]:
        if not r["has_minimum_history"]:
            errors.append({
                "type":"super_deal_missing_history",
                "offer_id":r.get("offer_id"),
                "name":r.get("name"),
                "store":r.get("store"),
                "normalized_product_key":r.get("normalized_product_key"),
                "history_month_count":r.get("history_month_count"),
                "required_months":MIN_MONTHS,
                "frontend_action":"Do not show a price-history graph for this offer."
            })
    data["generated_at"]=report["generated_at"]
    data["errors"]=errors
    data["error_count"]=len(errors)
    data["hard_error_count"]=sum(1 for e in errors if e.get("severity")=="hard")
    p.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--super-deals",default="super_deals_current.json")
    ap.add_argument("--history",default="monthly_price_history.json")
    ap.add_argument("--report",default="super_deal_history_report.json")
    ap.add_argument("--errors",default="data_quality_errors.json")
    args=ap.parse_args()
    report=build_report(args.super_deals,args.history)
    Path(args.report).write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    update_errors(report,args.errors)
    print(json.dumps({
        "super_deal_count":report["super_deal_count"],
        "with_minimum_history":report["with_minimum_history"],
        "without_minimum_history":report["without_minimum_history"],
        "monthly_history_bytes":report["monthly_history_bytes"],
        "monthly_history_under_12mb":report["monthly_history_under_12mb"]
    },ensure_ascii=False))
    if not report["monthly_history_under_12mb"]:
        raise SystemExit("monthly_price_history.json exceeds 12 MB")

if __name__=="__main__":
    main()
