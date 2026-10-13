#!/usr/bin/env python3
"""Normalize, validate and aggregate Superkøb data before publication."""
from __future__ import annotations
import argparse, collections, datetime as dt, json, math, shutil
from pathlib import Path
from product_normalization import normalize_record, normalized_product_key, infer_brand, infer_variant
from apply_quantity_flags import FlagError, REGISTRY as QUANTITY_FLAGS, apply_to_offers, load_flags
from offer_schema import (canonicalize_offer, copenhagen_today, food_relevance_for, offer_status,
                          partition_offers, snapshot_date, unexplained_losses, unverifiable_missing)

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

def validate_import(offers, previous_offers=None, hard_error_count=0, allow_large_drop=False, today=None):
    """Block empty imports, hard errors and real data loss.

    Without `today` the legacy raw-count comparison is used. With `today`, offers
    that simply expired since the previous import are legitimate and ignored:
    only previously valid offers that vanished from the import count as loss.
    """
    if not offers:
        raise RuntimeError("Publication blocked: current offer import is empty")
    rate = hard_error_count / max(1, len(offers))
    if rate > MAX_HARD_ERROR_RATE:
        raise RuntimeError(f"Publication blocked: hard error rate {rate:.1%} > {MAX_HARD_ERROR_RATE:.0%}")
    if previous_offers and not allow_large_drop:
        if today is not None:
            still_valid = [o for o in previous_offers if offer_status(o, today) in {"active", "future"}]
            lost = unexplained_losses(previous_offers, offers, today)
            if still_valid and len(lost) > len(still_valid) * MAX_COUNT_DROP:
                raise RuntimeError(f"Publication blocked: {len(lost)} of {len(still_valid)} previously valid offers "
                                   f"are missing (> {MAX_COUNT_DROP:.0%}); expired offers are not counted")
        else:
            minimum = math.floor(len(previous_offers) * (1 - MAX_COUNT_DROP))
            if len(offers) < minimum:
                raise RuntimeError(f"Publication blocked: offer count {len(offers)} is >{MAX_COUNT_DROP:.0%} below previous {len(previous_offers)}")
    return True

def is_active_offer(offer, on_date=None):
    """True only when valid_from <= date <= valid_to (Danish date). Missing valid_to is NOT active."""
    on_date = on_date or copenhagen_today()
    return offer_status(offer, on_date) == "active"

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

def reconcile_import_status(existing, offers, generated_at, parts=None, rejected=None):
    """Make import_status match the active offers that are actually published.

    `offers` are the published (active) offers. `parts` and `rejected` document
    what was imported versus left out, so the status never claims more than the data.
    """
    status=dict(existing or {}); counts=collections.Counter(o.get("store") or "Ukendt" for o in offers)
    status["generated_at"]=generated_at; status["current_total"]=len(offers); status["offer_count"]=len(offers)
    old=status.get("counts") if isinstance(status.get("counts"),dict) else {}
    status["counts"]={name:counts.get(name,0) for name in old}
    for name,value in sorted(counts.items()): status["counts"][name]=value
    if parts is not None:
        status["imported"]={"active":len(parts["active"]),"future_moved_to_next_week":len(parts["future"]),
                            "unknown_end_date":len(parts["unknown_end"]),"undated":len(parts["undated"])}
        status["future_new"]=len(parts["future"])
    if rejected is not None:
        status["rejected"]=rejected
    return status

def reconcile_history_manifest(manifest, monthly):
    """price_history.json is a manifest: its record_count must equal the real record count."""
    records=monthly.get("records",[])
    out=dict(manifest)
    out["record_count"]=len(records)
    out["data_file"]="monthly_price_history.json"
    out["data_generated_at"]=monthly.get("generated_at")
    if monthly.get("generated_at"): out["updated_at"]=monthly["generated_at"]  # manifest follows the data it describes
    out["distinct_keys"]=len({r.get("normalized_product_key") for r in records})
    months=sorted({r.get("month") for r in records if r.get("month")})
    out["first_month"]=months[0] if months else None; out["last_month"]=months[-1] if months else None
    return out

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

def store_organic_flags(root: Path, conflicts=None):
    """organic flags documented in the rich stores/*.json records, keyed by the stable offer id (booleans only).

    The same id must never carry two different documented values: such an id is
    treated as unknown (None) and listed in `conflicts`, instead of letting the
    last file silently win.
    """
    flags, bad = {}, set()
    for path in sorted((root/"stores").glob("*.json")):
        doc=load_json(path)
        for o in doc.get("offers",[]) if isinstance(doc.get("offers"),list) else []:
            oid=o.get("id")
            if oid is None or not isinstance(o.get("organic"),bool):
                continue
            if oid in flags and flags[oid]!=o["organic"]:
                bad.add(oid)
            flags.setdefault(oid,o["organic"])
    for oid in bad:
        flags.pop(oid,None)
    if conflicts is not None:
        conflicts.extend(sorted(bad,key=str))
    return flags

def enrich_offer(offer, organic_flags):
    """Add organic (documented boolean or null) and food_relevance (category based) when missing."""
    o=dict(offer)
    if "organic" not in o:
        o["organic"]=organic_flags.get(o.get("id"))  # None = unknown, never defaulted to False
    if not o.get("food_relevance"):
        rel=food_relevance_for(o.get("category"))
        if rel: o["food_relevance"]=rel
    return o

def merge_future(existing_future, from_current):
    seen={}; merged=[]
    for o in [canonicalize_offer(x) for x in existing_future]+[canonicalize_offer(x) for x in from_current]:
        ident=(o.get("store"),o.get("name"),o.get("price_dkk"),o.get("valid_from"))
        if ident in seen: continue
        seen[ident]=True; merged.append(o)
    return merged

def summarize_stores(old_stores, published):
    by_store=collections.defaultdict(list)
    for o in published: by_store[o.get("store")].append(o)
    out=[]
    for store in old_stores:
        s=dict(store); rows=by_store.get(s.get("store"),[])
        s["offer_count"]=len(rows)
        if rows:
            s["valid_from"]=min(r["valid_from"] for r in rows); s["valid_to"]=max(r["valid_to"] for r in rows)
            s.pop("no_active_offers",None)
        else:
            s["no_active_offers"]=True
        out.append(s)
    return out

def main():
    p=argparse.ArgumentParser(); p.add_argument("--root",default=str(Path(__file__).resolve().parents[1]))
    p.add_argument("--write",action="store_true"); p.add_argument("--allow-large-drop",action="store_true")
    p.add_argument("--today",help="override Danish date (YYYY-MM-DD), for tests")
    p.add_argument("--snapshot-date",action="store_true",help="validate on the snapshot's own Danish date (CI), not on today's date")
    a=p.parse_args(); root=Path(a.root)
    current_path=root/"current_offers.json"; previous_path=root/"current_offers.previous.json"
    current=load_json(current_path)
    today=dt.date.fromisoformat(a.today) if a.today else (snapshot_date(current) if a.snapshot_date else copenhagen_today())
    if a.snapshot_date and a.write: raise SystemExit("--snapshot-date is validation-only and cannot be combined with --write")
    previous=load_json(previous_path) if previous_path.exists() else None
    # Unverified-quantity marks are (re)applied to every freshly imported offer BEFORE validation and publication.
    # Expired or missing offers never get a mark; a source-confirmed lift with mismatching amounts blocks publication.
    try:
        quantity_flags=load_flags(root) if (root/QUANTITY_FLAGS).exists() else {}
    except FlagError as e:
        raise RuntimeError(f"Publication blocked: quantity flag registry invalid: {e}")
    _n,_problems=apply_to_offers(current.get("offers",[]),quantity_flags,today)
    if _problems: raise RuntimeError("Publication blocked: "+"; ".join(_problems))
    organic_conflicts=[]
    organic_flags=store_organic_flags(root,organic_conflicts)
    offers,errors=normalize_offers(current.get("offers",[])); hard=sum(1 for e in errors if e.get("severity")=="hard")
    offers=[enrich_offer(o,organic_flags) for o in offers]
    for o in current.get("offers",[]):
        documented=organic_flags.get(o.get("id"))
        if isinstance(o.get("organic"),bool) and documented is not None and o["organic"]!=documented:
            errors.append({"type":"organic_mismatch","offer_id":o.get("id"),"severity":"warning",
                           "detail":"organic in current_offers differs from the documented value in stores/*.json."})
    for oid in organic_conflicts:
        errors.append({"type":"organic_conflict","offer_id":oid,"severity":"warning",
                       "detail":"Same id has different documented organic values in stores/*.json: treated as unknown (null)."})
    if previous:
        for oid in unverifiable_missing(previous.get("offers",[]),offers,today):
            errors.append({"type":"unknown_end_offer_missing","offer_id":oid,"severity":"warning",
                           "detail":"Offer without valid_to disappeared; not counted as loss of verified offers."})
    validate_import(offers,(previous or {}).get("offers") if previous else None,hard,a.allow_large_drop,today=today)
    parts=partition_offers(offers,today)
    if not parts["active"]:
        raise RuntimeError(f"Publication blocked: no offers are active on {today}")
    published=parts["active"]
    generated_at=dt.datetime.now().astimezone().isoformat(timespec="seconds")

    next_path=root/"next_week_offers.json"
    next_doc=load_json(next_path) if next_path.exists() else {"schema_version":2,"offers":[]}
    next_offers=merge_future(next_doc.get("offers",[]),parts["future"])
    for o in next_offers:
        if not o.get("valid_to"):
            errors.append({"type":"missing_valid_to","offer_id":o.get("id"),"name":o.get("name"),"store":o.get("store"),
                           "severity":"warning","detail":"End date unknown: not treated as valid without limit."})
    next_status=collections.Counter(offer_status(o,today) for o in next_offers)

    current2=dict(current); current2["offers"]=published; current2["offer_count"]=len(published); current2["generated_at"]=generated_at
    by_id={o.get("id"):o for o in published if o.get("id") is not None}
    if isinstance(current2.get("stores"),list):
        current2["stores"]=summarize_stores(current2["stores"],published)
    rejected={"expired_removed_from_index":len(parts["expired"]),"undated":len(parts["undated"]),
              "duplicate_warnings":sum(1 for e in errors if e.get("type")=="duplicate_offer"),"hard_errors":hard,
              "note":"Expired offers are removed from current_offers.json only; rich records stay in stores/*.json."}
    status_path=root/"import_status.json"; status=reconcile_import_status(load_json(status_path),published,generated_at,parts,rejected)
    if status["offer_count"] != current2["offer_count"]: raise RuntimeError("Publication blocked: status mismatch")
    quality={"generated_at":generated_at,"offer_count":len(published),"error_count":len(errors),
             "hard_error_count":hard,"errors":errors}
    # Canonical history is already monthly aggregated. Validate it; do not expand or
    # rebuild it from price_history.json, which is only a manifest in schema v3.
    history_manifest=load_json(root/"price_history.json")
    monthly=load_json(root/"monthly_price_history.json")
    if history_manifest.get("mode") != "monthly_aggregated":
        raise RuntimeError("Publication blocked: price_history.json must be monthly_aggregated manifest")
    if not isinstance(monthly.get("records"), list):
        raise RuntimeError("Publication blocked: monthly_price_history.json missing records")
    missing_history_keys=sum(1 for r in monthly["records"] if not r.get("normalized_product_key"))
    if missing_history_keys:
        raise RuntimeError(f"Publication blocked: {missing_history_keys} history rows lack normalized_product_key")
    manifest=reconcile_history_manifest(history_manifest,monthly)

    print(json.dumps({"date":str(today),"incoming":len(offers),"active":len(parts["active"]),"future":len(parts["future"]),
                      "expired":len(parts["expired"]),"unknown_end":len(parts["unknown_end"]),"undated":len(parts["undated"]),
                      "next_week_total":len(next_offers),"next_week_status":dict(next_status),
                      "quality_errors":len(errors),"hard_errors":hard,
                      "monthly_history_records":len(monthly["records"]),"duplicates":len(find_duplicates(offers))},
                     ensure_ascii=False))
    if not a.write: return
    shutil.copy2(current_path,previous_path)
    dump_json(current_path,current2); dump_json(status_path,status); dump_json(root/"data_quality_errors.json",quality)
    dump_json(root/"price_history.json",manifest)
    next_doc2=dict(next_doc); next_doc2["schema_version"]=2; next_doc2["offers"]=next_offers; next_doc2["offer_count"]=len(next_offers)
    next_doc2["canonical_schema"]="package_amount, member_only (aliases package_size/member_required are migrated); organic null = unknown"
    dump_json(next_path,next_doc2)

    # Preserve rich store records: normalize them in place instead of replacing
    # them with the lightweight current_offers index records.
    for path in sorted((root/"stores").glob("*.json")):
        doc=load_json(path)
        if isinstance(doc.get("offers"),list):
            doc["offers"]=[normalize_record(o)[0] for o in doc["offers"]]
            apply_to_offers(doc["offers"],quantity_flags,today)
            doc["offer_count"]=len(doc["offers"]); dump_json(path,doc)
    for name in ("super_deals.json","super_deals_current.json"):
        path=root/name
        if path.exists():
            doc=load_json(path)
            if isinstance(doc.get("offers"),list):
                doc["offers"]=[normalize_record(o)[0] for o in doc["offers"]]
                dump_json(path,doc)

if __name__=="__main__": main()
