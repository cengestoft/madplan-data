#!/usr/bin/env python3
import datetime as dt, json, pathlib, re, statistics, urllib.request
from collections import defaultdict
from product_normalization import normalized_product_key

URL="https://dagligepriser.dk/data/latest-canonical.json"; OUT=pathlib.Path("monthly_price_history.json")
CUR=pathlib.Path("current_offers.json"); MAX=9_500_000; MIN=.30
STORES={"bilkatogo":"Bilka","fotex":"føtex","meny":"MENY","minkobmand":"Min Købmand","nemlig":"Nemlig.com","netto":"Netto","rema1000":"REMA 1000","spar":"SPAR"}
NONFOOD=re.compile(r"shampoo|balsam|deodorant|parfume|tandpasta|bleer|toiletpapir|køkkenrulle|rengøring|vaskemiddel|opvask|kattefoder|hundefoder|dyrefoder|kattesand|ballon|gavepapir|batteri|maling|værktøj|kaffekop|drikkeglas|tallerken|bestik|stegepande|gryde|viskestykke|legetøj|strømper|håndklæde|sengetøj|gødning",re.I)
FOOD=re.compile(r"mælk|yoghurt|skyr|fløde|ost|smør|æg|kød|kylling|pølse|bacon|skinke|fisk|laks|tun|reje|brød|toast|bolle|kage|kiks|pizza|pasta|nudler|havre|müsli|sauce|ketchup|sennep|pesto|olie|eddike|salt|peber|sukker|honning|marmelade|chokolade|slik|chips|nød|kaffe|kakao|sodavand|cola|juice|saft|vand|frugt|grønt|æble|pære|banan|appelsin|citron|mango|ananas|melon|jordbær|blåbær|avocado|tomat|agurk|kartoffel|gulerod|broccoli|salat|majs|ærter|bønner|linser|champignon|dessert|grød",re.I)

def food(p):
    n=str(p.get("name") or "")
    if NONFOOD.search(n): return False
    c=str(p.get("category") or "")
    return (bool(c) and c[0] in "0123456") or bool(FOOD.search(n))

def hkey(p,h):
    return normalized_product_key({"name":p.get("name"),"brand":p.get("brand"),"variant":p.get("variant"),"package_count":h.get("package_count",1),"package_amount":h.get("quantity"),"package_unit":h.get("unit")})

def offer_keys():
    d=json.loads(CUR.read_text(encoding="utf-8"))
    return {normalized_product_key(o) for o in d.get("offers",[]) if str(o.get("category") or "").lower() not in {"husholdning","dyrefoder"}}

def doc(rows,nkeys,nmatch):
    return {"schema_version":3,"source":"dagligepriser.dk","aggregation":"normalized_product_key + store + month","food_only":True,"raw_data_included":False,"generated_at":dt.datetime.now(dt.timezone.utc).isoformat(),"record_count":len(rows),"offer_key_count":nkeys,"matched_offer_keys":nmatch,"offer_key_overlap":round(nmatch/max(1,nkeys),4),"records":rows}

def payload(d): return (json.dumps(d,ensure_ascii=False,separators=(",",":"))+"\n").encode()

offers=offer_keys(); products=json.loads(urllib.request.urlopen(URL,timeout=300).read())
b=defaultdict(list); months=defaultdict(set)
for p in products:
    sc=p.get("store")
    if sc not in STORES or not food(p): continue
    for h in p.get("priceHistory",[]):
        try:
            dt.date.fromisoformat(h.get("date")); price=float(h.get("price")); q=float(h.get("quantity")); unit=h.get("unit")
            if price<=0 or q<=0 or not unit: continue
        except Exception: continue
        k=hkey(p,h); m=h["date"][:7]; b[(k,STORES[sc],m)].append(price); months[k].add(m)

by=defaultdict(list)
for (k,s,m),ps in b.items():
    by[k].append({"normalized_product_key":k,"store":s,"month":m,"observation_count":len(ps),"median_price_dkk":round(float(statistics.median(ps)),2),"min_price_dkk":round(min(ps),2),"source":"dagligepriser.dk"})
for rs in by.values(): rs.sort(key=lambda x:(x["month"],x["store"]))

hist=set(by); direct=offers&hist; overlap=len(direct)/max(1,len(offers))
if overlap<MIN: raise SystemExit(f"History key overlap too low: {len(direct)}/{len(offers)} = {overlap:.1%}")

rank=lambda k:(-len(months[k]),-sum(r["observation_count"] for r in by[k]),k)
need=max(1,int(len(offers)*MIN+0.999999)); selected=list(sorted(direct,key=rank)[:need]); selected_set=set(selected)
eligible={k for k in hist if k in offers or len(months[k])>=3}
remaining=sorted(eligible-selected_set,key=lambda k:(0 if k in offers else 1,)+rank(k))

def row_bytes(k):
    return sum(len(json.dumps(r,ensure_ascii=False,separators=(",",":")).encode())+1 for r in by[k])

budget=MAX-2000; used=sum(row_bytes(k) for k in selected)
if used>budget:
    trimmed={}
    for k in selected:
        trimmed[k]=sorted(by[k],key=lambda r:(r["month"],r["store"]),reverse=True)[:12]
    by.update(trimmed); used=sum(row_bytes(k) for k in selected)
    if used>budget: raise SystemExit("30% overlap cannot fit under 9.5 MB")

for k in remaining:
    sz=row_bytes(k)
    if used+sz<=budget:
        selected.append(k); selected_set.add(k); used+=sz

rows=[r for k in selected for r in by[k]]
rows.sort(key=lambda r:(r["normalized_product_key"],r["store"],r["month"]))
d=doc(rows,len(offers),len(selected_set&offers)); out=payload(d)
while len(out)>MAX and len(selected)>need:
    k=selected.pop(); selected_set.remove(k); rows=[r for x in selected for r in by[x]]
    rows.sort(key=lambda r:(r["normalized_product_key"],r["store"],r["month"]))
    d=doc(rows,len(offers),len(selected_set&offers)); out=payload(d)

if d["offer_key_overlap"]<MIN: raise SystemExit("Final overlap below 30%")
if len(out)>MAX: raise SystemExit("Output over 9.5 MB")
if any(r["source"]!="dagligepriser.dk" for r in rows): raise SystemExit("Bad source")
OUT.write_bytes(out)
print(json.dumps({"records":len(rows),"bytes":len(out),"offer_keys":len(offers),"matched":len(selected_set&offers),"overlap":d["offer_key_overlap"]},ensure_ascii=False))
