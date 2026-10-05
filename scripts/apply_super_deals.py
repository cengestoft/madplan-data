#!/usr/bin/env python3
"""Annotate offer JSON with centrally calculated Supertilbud status.

Adds to every offer:
  super_deal: bool
  super_deal_rule: str | None
  super_deal_reason: str | None
  super_deal_checked_at: ISO timestamp

The app should display these fields directly and should not duplicate price-rule
logic in the frontend.
"""
from __future__ import annotations
import argparse, json, re
from pathlib import Path
from datetime import datetime

COLA_BRANDS = ("coca cola", "coca-cola", "pepsi", "fanta")

def low(v):
    return str(v or "").lower()

def has_any(text, terms):
    t=low(text)
    return any(x in t for x in terms)

def annotate(o, checked_at):
    name=low(o.get("name"))
    brand=low(o.get("brand"))
    category=low(o.get("category"))
    source_category=low(o.get("source_category"))
    product_type=low(o.get("product_type"))
    container=low(o.get("container"))
    price=o.get("price_dkk")
    unit=o.get("unit_price_dkk")
    count=o.get("package_count")
    volume=o.get("volume_l")
    package_unit=low(o.get("package_unit"))
    package_amount=o.get("package_amount")
    text=f"{name} {brand}"

    matched=None
    reason=None

    # 24-pack cola/soda cans. Beverage category/source category is mandatory;
    # this prevents names like "Corny Chocolate" from false-positive cola matches.
    is_soda = category == "drikkevarer" or "sodavand" in source_category
    is_cola_family = product_type == "cola" or has_any(text, COLA_BRANDS)
    if (
        is_soda and is_cola_family and container == "can"
        and count == 24 and isinstance(price,(int,float)) and price < 69
    ):
        matched="cola_24_cans"
        reason=f"{price:g} kr. < 69 kr. for 24 dåser"

    # 1.5-2 L cola/soda bottles below 11 DKK/L.
    if matched is None and is_soda and is_cola_family and container == "bottle":
        v=volume
        if v is None and package_unit == "l" and isinstance(package_amount,(int,float)):
            v=package_amount
        if isinstance(v,(int,float)) and 1.5 <= v <= 2 and isinstance(unit,(int,float)) and unit < 11:
            matched="cola_large_bottle"
            reason=f"{unit:g} kr./l < 11 kr./l"

    # Real butter only; explicitly exclude spread/blended products.
    exclude=("smørbar","blandingsprodukt","spread","kærgården")
    if matched is None and category == "mejeri" and "smør" in text and not has_any(text,exclude):
        if isinstance(unit,(int,float)) and unit <= 40:
            matched="real_butter"
            reason=f"{unit:g} kr./kg <= 40 kr./kg"

    # Whipping cream: match the product name rather than trusting source category.
    if matched is None and "piskefløde" in text:
        fat=None
        m=re.search(r"(\d{2})\s*%", text)
        if m:
            fat=int(m.group(1))
        if (fat is None or fat >= 36) and isinstance(unit,(int,float)) and unit <= 25:
            matched="whipping_cream"
            reason=f"{unit:g} kr./l <= 25 kr./l"

    # Dishwasher tabs: prefer explicit product_type, but allow clear product names.
    if matched is None and (product_type=="dishwasher_tabs" or "opvasketab" in text):
        per_tab=None
        if package_unit == "stk" and isinstance(unit,(int,float)):
            per_tab=unit
        elif isinstance(price,(int,float)) and isinstance(count,(int,float)) and count>0:
            per_tab=price/count
        if isinstance(per_tab,(int,float)) and per_tab <= 0.75:
            matched="dishwasher_tabs"
            reason=f"{per_tab:.2f} kr./tab <= 0,75 kr./tab"

    # 3-ply toilet paper.
    if matched is None and ("toiletpapir" in text or product_type=="toilet_paper"):
        plies=o.get("plies")
        is_3ply = plies == 3 or bool(re.search(r"3\s*[- ]?lags?", text))
        per_roll=None
        if package_unit=="stk" and isinstance(unit,(int,float)):
            per_roll=unit
        elif isinstance(price,(int,float)) and isinstance(count,(int,float)) and count>0:
            per_roll=price/count
        if is_3ply and isinstance(per_roll,(int,float)) and per_roll <= 2:
            matched="toilet_paper"
            reason=f"{per_roll:.2f} kr./rulle <= 2,00 kr./rulle"

    o["super_deal"]=matched is not None
    o["super_deal_rule"]=matched
    o["super_deal_reason"]=reason
    o["super_deal_checked_at"]=checked_at
    return matched is not None

def process_file(path: Path, checked_at: str):
    data=json.loads(path.read_text(encoding="utf-8"))
    count=0
    if isinstance(data.get("offers"),list):
        for o in data["offers"]:
            count += annotate(o,checked_at)
    if isinstance(data.get("stores"),list):
        for s in data["stores"]:
            for o in s.get("offers",[]):
                annotate(o,checked_at)
    data["super_deal_count"]=count
    data["super_deal_generated_at"]=checked_at
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return count

def main():
    p=argparse.ArgumentParser()
    p.add_argument("paths",nargs="+")
    p.add_argument("--checked-at",default=datetime.now().astimezone().isoformat(timespec="seconds"))
    a=p.parse_args()
    total=0
    for raw in a.paths:
        path=Path(raw)
        n=process_file(path,a.checked_at)
        total += n
        print(f"{path}: {n} super deals")
    print(f"Total: {total}")

if __name__=="__main__":
    main()
