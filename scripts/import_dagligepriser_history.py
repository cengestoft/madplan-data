#!/usr/bin/env python3
"""Aggregate dagligepriser.dk history monthly; never commit the raw dump."""
from __future__ import annotations
import argparse, datetime, json, pathlib, urllib.request
from product_normalization import normalized_product_key, infer_brand, infer_variant

URL="https://dagligepriser.dk/data/latest-canonical.json"
STORES={"bilkatogo":"Bilka","fotex":"føtex","meny":"MENY","minkobmand":"Min Købmand","nemlig":"Nemlig.com","netto":"Netto","rema1000":"REMA 1000","spar":"SPAR"}

def aggregate(products):
    buckets={}; skipped=0
    for product in products:
        store_code=product.get("store")
        if store_code not in STORES:
            skipped+=1; continue
        base={"name":product.get("name"),"brand":product.get("brand"),"variant":product.get("variant"),
              "package_count":product.get("package_count",1),"package_amount":product.get("quantity"),
              "package_unit":product.get("unit")}
        for h in product.get("priceHistory",[]):
            date,price=h.get("date"),h.get("price")
            try: datetime.date.fromisoformat(date)
            except (TypeError,ValueError):
                skipped+=1; continue
            if isinstance(price,bool) or not isinstance(price,(int,float)) or price<=0:
                skipped+=1; continue
            hist=dict(base)
            if h.get("quantity") is not None:
                hist["package_amount"]=h.get("quantity")
                hist["package_unit"]=h.get("unit")
                hist["package_count"]=h.get("package_count",base["package_count"])
            key=normalized_product_key(hist)
            b=buckets.setdefault((key,store_code,date[:7]),{
                "normalized_product_key":key,"normalized_brand":infer_brand(hist),
                "normalized_variant":infer_variant(hist),"name":product.get("name"),
                "store":STORES[store_code],"month":date[:7],"prices":[],"dated":[]})
            b["prices"].append(float(price)); b["dated"].append((date,float(price)))
    rows=[]
    for b in buckets.values():
        dated=sorted(b.pop("dated")); prices=b.pop("prices")
        b.update({"observation_count":len(prices),"avg_price_dkk":round(sum(prices)/len(prices),2),
                  "min_price_dkk":min(prices),"max_price_dkk":max(prices),
                  "first_observation_date":dated[0][0],"first_price_dkk":dated[0][1],
                  "last_observation_date":dated[-1][0],"last_price_dkk":dated[-1][1]})
        rows.append(b)
    return rows,skipped

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--source-file")
    p.add_argument("--output",default="data/private/dagligepriser-monthly.json")
    p.add_argument("--allow-public-output",action="store_true")
    p.add_argument("--manifest",default="data_sources/dagligepriser_manifest.json")
    a=p.parse_args()
    manifest_path=pathlib.Path(a.manifest)
    manifest=json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    status=manifest.get("redistribution_status","unresolved")
    output=pathlib.Path(a.output)
    if "data/private" not in output.as_posix() and status!="allowed" and not a.allow_public_output:
        raise SystemExit("Refusing public output: dagligepriser redistribution_status is unresolved")
    raw=pathlib.Path(a.source_file).read_bytes() if a.source_file else urllib.request.urlopen(URL,timeout=180).read()
    products=json.loads(raw)
    if not isinstance(products,list): raise ValueError("Expected product list")
    rows,skipped=aggregate(products)
    doc={"schema_version":1,"source":"dagligepriser.dk","source_url":URL,
         "generated_at":datetime.datetime.now(datetime.timezone.utc).isoformat(),
         "aggregation":"normalized_product_key + store + month",
         "redistribution_status":status,"product_count":len(products),
         "monthly_record_count":len(rows),"skipped":skipped,
         "records":sorted(rows,key=lambda x:(x["normalized_product_key"],x["store"],x["month"]))}
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(doc,ensure_ascii=False,separators=(",",":"))+"\n",encoding="utf-8")
    print(json.dumps({k:doc[k] for k in ("product_count","monthly_record_count","skipped","redistribution_status")},ensure_ascii=False))

if __name__=="__main__": main()
