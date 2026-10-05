#!/usr/bin/env python3
"""Normalize, validate and aggregate Superkøb data before publication."""
from __future__ import annotations
import argparse, collections, datetime as dt, json, math, shutil
from pathlib import Path
from product_normalization import normalize_record, normalized_product_key, infer_brand, infer_variant

MAX_HARD_ERROR_RATE = 0.10
MAX_COUNT_DROP = 0.25

def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))

def dump_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)

def offer_identity(o: dict):
    return (o.get("store"), o.get("store_location"),
            o.get("normalized_product_key") or normalized_product_key(o),
            o.get("price_dkk"), o.get("valid_from"), o.get("valid_to"),
            bool(o.get("member_only")))

def find_duplicates(offers):
    seen, duplicates = {}, []
    for offer in offers:
        ident = offer_identity(offer)
        if ident in seen:
            duplicates.append((seen[ident], offer.get("id"), ident))
        else:
            seen[ident] = offer.get("id")
    return duplicates

def normalize_offers(offers):
    out, errors = [], []
    for offer in offers:
        n, errs = normalize_record(offer)
        out.append(n); errors.extend(errs)
        if not n.get("name"):
            errors.append({"type":"missing_name","offer_id":n.get("id"),"severity":"hard"})
        price = n.get("price_dkk")
        if isinstance(price, bool) or not isinstance(price, (int,float)) or price <= 0:
            errors.append({"type":"invalid_price","offer_id":n.get("id"),"severity":"hard"})
    for first_id, duplicate_id, ident in find_duplicates(out):
        errors.append({"type":"duplicate_offer","offer_id":duplicate_id,
                       "duplicate_of":first_id,"identity":list(ident),"severity":"warning"})
    return out, errors

def validate_import(offers, previous_offers=None, hard_error_count=0, allow_large_drop=False):
    if not offers:
        raise RuntimeError("Publication blocked: current offer import is empty")
    rate = hard_error_count / max(1, len(offers))
    if rate > MAX_HARD_ERROR_RATE:
        raise RuntimeError(f"Publication blocked: hard error rate {rate:.1%} > {MAX_HARD_ERROR_RATE:.0%}")
    if previous_offers and not allow_large_drop:
        minimum = math.floor(len(previous_offers) * (1 - MAX_COUNT_DROP))
        if len(offers) < minimum:
            raise RuntimeError(f"Publication blocked: offer count {len(offers)} is >{MAX_COUNT_DROP:.0%} below previous {len(previous_offers)}")
    return True

def is_active_offer(offer, on_date=None):
    on_date = on_date or dt.date.today()
    try:
        start = dt.date.fromisoformat(offer["valid_from"]); end = dt.date.fromisoformat(offer["valid_to"])
    except (KeyError, TypeError, ValueError):
        return False
    return start <= on_date <= end

def calculate_unit_price(price_dkk, count, amount, unit):
    if not isinstance(price_dkk,(int,float)) or price_dkk <= 0: return None
    if not isinstance(count,(int,float)) or count <= 0: count = 1
    if not isinstance(amount,(int,float)) or amount <= 0: return None
    unit = (unit or "").lower(); total = count * amount
    if unit == "l": basis,label = total,"l"
    elif unit == "cl": basis,label = total/100,"l"
    elif unit == "ml": basis,label = total/1000,"l"
    elif unit == "kg": basis,label = total,"kg"
    elif unit == "g": basis,label = total/1000,"kg"
    elif unit == "stk": basis,label = total,"stk"
    else: return None
    return {"value": round(price_dkk/basis,4), "unit": label} if basis > 0 else None

def deal_score(current_price, historical_prices):
    vals=[float(x) for x in historical_prices if isinstance(x,(int,float)) and not isinstance(x,bool) and x>0]
    if not vals or not isinstance(current_price,(int,float)) or current_price<=0: return None
    low,avg=min(vals),sum(vals)/len(vals)
    if current_price <= low: return 100
    if current_price >= avg: return max(0, round(50*avg/current_price))
    return round(50 + 50*(avg-current_price)/max(avg-low,1e-9))

def reconcile_import_status(existing, offers, generated_at):
    status=dict(existing or {}); counts=collections.Counter(o.get("store") or "Ukendt" for o in offers)
    status["generated_at"]=generated_at; status["current_total"]=len(offers); status["offer_count"]=len(offers)
    old=status.get("counts") if isinstance(status.get("counts"),dict) else {}
    status["counts"]={name:counts.get(name,0) for name in old}
    for name,value in sorted(counts.items()): status["counts"][name]=value
    return status

def normalize_history(history):
    normalized_products=[]; buckets={}
    for product in history.get("products",[]):
        base=dict(product)
        probe={"name":product.get("name"),"brand":product.get("brand"),"variant":product.get("variant"),
               "package_count":product.get("package_count",1),"package_amount":product.get("package_amount"),
               "package_unit":product.get("package_unit")}
        key=normalized_product_key(probe)
        base["normalized_product_key"]=key
        base["normalized_brand"]=infer_brand(probe); base["normalized_variant"]=infer_variant(probe)
        observations=[]
        for obs in product.get("observations",[]):
            o=dict(obs); o["normalized_product_key"]=key; observations.append(o)
            date=o.get("observation_date"); price=o.get("price_dkk")
            if not isinstance(date,str) or len(date)<7 or isinstance(price,bool) or not isinstance(price,(int,float)) or price<=0: continue
            bkey=(key,product.get("store"),product.get("store_location"),date[:7])
            b=buckets.setdefault(bkey,{"normalized_product_key":key,"name":product.get("name"),
                "store":product.get("store"),"store_location":product.get("store_location"),"month":date[:7],
                "prices":[],"dates":[]})
            b["prices"].append(float(price)); b["dates"].append(date)
        base["observations"]=observations; normalized_products.append(base)
    monthly=[]
    for b in buckets.values():
        ordered=sorted(zip(b.pop("dates"),b["prices"])); prices=b.pop("prices")
        b.update({"observation_count":len(prices),"avg_price_dkk":round(sum(prices)/len(prices),2),
                  "min_price_dkk":min(prices),"max_price_dkk":max(prices),
                  "first_observation_date":ordered[0][0],"first_price_dkk":ordered[0][1],
                  "last_observation_date":ordered[-1][0],"last_price_dkk":ordered[-1][1]})
        monthly.append(b)
    history2=dict(history); history2["schema_version"]=2; history2["products"]=normalized_products
    monthly_doc={"schema_version":1,"generated_at":dt.datetime.now(dt.timezone.utc).isoformat(),
                 "currency":history.get("currency","DKK"),
                 "aggregation":"normalized_product_key + store + month",
                 "records":sorted(monthly,key=lambda x:(x["normalized_product_key"],str(x["store"]),x["month"]))}
    return history2, monthly_doc

def main():
    p=argparse.ArgumentParser(); p.add_argument("--root",default=str(Path(__file__).resolve().parents[1]))
    p.add_argument("--write",action="store_true"); p.add_argument("--allow-large-drop",action="store_true")
    a=p.parse_args(); root=Path(a.root)
    current_path=root/"current_offers.json"; previous_path=root/"current_offers.previous.json"
    current=load_json(current_path); previous=load_json(previous_path) if previous_path.exists() else None
    offers,errors=normalize_offers(current.get("offers",[])); hard=sum(1 for e in errors if e.get("severity")=="hard")
    validate_import(offers,(previous or {}).get("offers") if previous else None,hard,a.allow_large_drop)
    generated_at=dt.datetime.now().astimezone().isoformat(timespec="seconds")
    current2=dict(current); current2["offers"]=offers; current2["offer_count"]=len(offers); current2["generated_at"]=generated_at
    by_id={o.get("id"):o for o in offers if o.get("id") is not None}
    if isinstance(current2.get("stores"),list):
        nested=[]
        for store in current2["stores"]:
            s=dict(store)
            if isinstance(s.get("offers"),list):
                s["offers"]=[by_id.get(o.get("id"),normalize_record(o)[0]) for o in s["offers"]]; s["offer_count"]=len(s["offers"])
            nested.append(s)
        current2["stores"]=nested
    status_path=root/"import_status.json"; status=reconcile_import_status(load_json(status_path),offers,generated_at)
    if status["offer_count"] != current2["offer_count"]: raise RuntimeError("Publication blocked: status mismatch")
    quality={"generated_at":generated_at,"offer_count":len(offers),"error_count":len(errors),
             "hard_error_count":hard,"errors":errors}
    history_path=root/"price_history.json"; history2,monthly=normalize_history(load_json(history_path))
    print(json.dumps({"offers":len(offers),"quality_errors":len(errors),"hard_errors":hard,
                      "monthly_history_records":len(monthly["records"]),"duplicates":len(find_duplicates(offers))},
                     ensure_ascii=False))
    if not a.write: return
    shutil.copy2(current_path,previous_path)
    dump_json(current_path,current2); dump_json(status_path,status); dump_json(root/"data_quality_errors.json",quality)
    dump_json(history_path,history2); dump_json(root/"monthly_price_history.json",monthly)
    for path in sorted((root/"stores").glob("*.json")):
        doc=load_json(path)
        if isinstance(doc.get("offers"),list):
            doc["offers"]=[by_id.get(o.get("id"),normalize_record(o)[0]) for o in doc["offers"]]
            doc["offer_count"]=len(doc["offers"]); dump_json(path,doc)
    for name in ("next_week_offers.json","super_deals.json","super_deals_current.json"):
        path=root/name
        if path.exists():
            doc=load_json(path)
            if isinstance(doc.get("offers"),list):
                doc["offers"]=[by_id.get(o.get("id"),normalize_record(o)[0]) for o in doc["offers"]]
                dump_json(path,doc)

if __name__=="__main__": main()
