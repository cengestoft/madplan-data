#!/usr/bin/env python3
import datetime as dt, json, pathlib, re, statistics, unicodedata, urllib.request
from collections import defaultdict
from product_normalization import normalized_product_key, infer_pack

URL="https://dagligepriser.dk/data/latest-canonical.json"; OUT=pathlib.Path("monthly_price_history.json")
CUR=pathlib.Path("current_offers.json"); MAX=9_500_000; MIN=.30
STORES={"bilkatogo":"Bilka","fotex":"føtex","meny":"MENY","minkobmand":"Min Købmand","nemlig":"Nemlig.com","netto":"Netto","rema1000":"REMA 1000","spar":"SPAR"}
NONFOOD=re.compile(r"shampoo|balsam|deodorant|parfume|tandpasta|bleer|toiletpapir|køkkenrulle|rengøring|vaskemiddel|opvask|kattefoder|hundefoder|dyrefoder|kattesand|ballon|gavepapir|batteri|maling|værktøj|kaffekop|drikkeglas|tallerken|bestik|stegepande|gryde|viskestykke|legetøj|strømper|håndklæde|sengetøj|gødning",re.I)
FOOD=re.compile(r"mælk|yoghurt|skyr|fløde|ost|smør|æg|kød|kylling|pølse|bacon|skinke|fisk|laks|tun|reje|brød|toast|bolle|kage|kiks|pizza|pasta|nudler|havre|müsli|sauce|ketchup|sennep|pesto|olie|eddike|salt|peber|sukker|honning|marmelade|chokolade|slik|chips|nød|kaffe|kakao|sodavand|cola|juice|saft|vand|frugt|grønt|æble|pære|banan|appelsin|citron|mango|ananas|melon|jordbær|blåbær|avocado|tomat|agurk|kartoffel|gulerod|broccoli|salat|majs|ærter|bønner|linser|champignon|dessert|grød",re.I)
STOP={"med","og","i","af","til","fra","the","a","en","et","stk","pk","pak","gram","gr","kg","ml","cl","l"}

def slug(s):
    s=unicodedata.normalize("NFKD",str(s or "").lower()); s="".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+"," ",s).strip()

def toks(s):
    return {x for x in slug(s).split() if len(x)>1 and x not in STOP and not x.isdigit()}

def food(p):
    n=str(p.get("name") or "")
    if NONFOOD.search(n): return False
    c=str(p.get("category") or "")
    return (bool(c) and c[0] in "0123456") or bool(FOOD.search(n))

def sig(r):
    c,a,u=infer_pack(r)
    if not a: return None
    total=float(c or 1)*float(a)
    if u=="kg": fam,val="kg",total
    elif u=="g": fam,val="kg",total/1000
    elif u=="l": fam,val="l",total
    elif u=="cl": fam,val="l",total/100
    elif u=="ml": fam,val="l",total/1000
    elif u=="stk": fam,val="stk",total
    else: return None
    return fam,round(val,3)

current=json.loads(CUR.read_text(encoding="utf-8"))
offers=[o for o in current.get("offers",[]) if str(o.get("category") or "").lower() not in {"husholdning","dyrefoder"}]
offer_keys={normalized_product_key(o) for o in offers}
brands=sorted({str(o.get("brand")).strip() for o in offers if o.get("brand")},key=len,reverse=True)
brand_lut={slug(b):b for b in brands}
KEY_CACHE={}

idx=defaultdict(list)
for o in offers:
    s=sig(o)
    if s:
        idx[s].append((normalized_product_key(o),toks(o.get("name")),slug(o.get("brand"))))

def detect_brand(name):
    sn=slug(name)
    for sb,b in brand_lut.items():
        if sn==sb or sn.startswith(sb+" "): return b
    return None

def hprobe(p,h):
    name=str(p.get("name") or "")
    brand=p.get("brand") or detect_brand(name)
    return {"name":name,"brand":brand,"variant":p.get("variant"),"package_count":h.get("package_count",1),"package_amount":h.get("quantity"),"package_unit":h.get("unit")}

def choose_key(p,h):
    ck=(p.get("name"),p.get("brand"),p.get("variant"),h.get("package_count",1),h.get("quantity"),h.get("unit"))
    if ck in KEY_CACHE: return KEY_CACHE[ck]
    pr=hprobe(p,h); k=normalized_product_key(pr)
    if k in offer_keys:
        KEY_CACHE[ck]=k; return k
    candidates=idx.get(sig(pr) or (),[])
    if not candidates:
        KEY_CACHE[ck]=k; return k
    ht=toks(pr["name"]); hb=slug(pr.get("brand"))
    scored=[]
    for ck,ct,cb in candidates:
        if hb and cb and hb!=cb: continue
        if not ht or not ct: continue
        score=len(ht&ct)/max(1,min(len(ht),len(ct)))
        if cb and hb==cb: score+=.15
        scored.append((score,ck))
    scored.sort(reverse=True)
    if scored and scored[0][0]>=.65 and (len(scored)==1 or scored[0][0]-scored[1][0]>=.03):
        KEY_CACHE[ck]=scored[0][1]; return KEY_CACHE[ck]
    KEY_CACHE[ck]=k; return k

def enc(rows,nkeys,nmatch):
    d={"schema_version":3,"source":"dagligepriser.dk","aggregation":"normalized_product_key + store + month","food_only":True,"raw_data_included":False,"generated_at":dt.datetime.now(dt.timezone.utc).isoformat(),"record_count":len(rows),"offer_key_count":nkeys,"matched_offer_keys":nmatch,"offer_key_overlap":round(nmatch/max(1,nkeys),4),"records":rows}
    return (json.dumps(d,ensure_ascii=False,separators=(",",":"))+"\n").encode(),d

products=json.loads(urllib.request.urlopen(URL,timeout=300).read())
b=defaultdict(list); months=defaultdict(set)
for p in products:
    sc=p.get("store")
    if sc not in STORES or not food(p): continue
    for h in p.get("priceHistory",[]):
        try:
            dt.date.fromisoformat(h.get("date")); price=float(h.get("price")); q=float(h.get("quantity")); unit=h.get("unit")
            if price<=0 or q<=0 or not unit: continue
        except Exception: continue
        k=choose_key(p,h); m=h["date"][:7]; b[(k,STORES[sc],m)].append(price); months[k].add(m)

by=defaultdict(list)
for (k,s,m),ps in b.items():
    by[k].append({"normalized_product_key":k,"store":s,"month":m,"observation_count":len(ps),"median_price_dkk":round(float(statistics.median(ps)),2),"min_price_dkk":round(min(ps),2),"source":"dagligepriser.dk"})
for rs in by.values(): rs.sort(key=lambda x:(x["month"],x["store"]))

hist=set(by); direct=offer_keys&hist; overlap=len(direct)/max(1,len(offer_keys))
if overlap<MIN: raise SystemExit(f"History key overlap too low: {len(direct)}/{len(offer_keys)} = {overlap:.1%}")

rank=lambda k:(-len(months[k]),-sum(r["observation_count"] for r in by[k]),k)
need=max(1,int(len(offer_keys)*MIN+0.999999)); selected=list(sorted(direct,key=rank)[:need]); sel=set(selected)
eligible={k for k in hist if k in offer_keys or len(months[k])>=3}

def rb(k): return sum(len(json.dumps(r,ensure_ascii=False,separators=(",",":")).encode())+1 for r in by[k])
budget=MAX-2000; used=sum(rb(k) for k in selected)
if used>budget:
    for k in selected: by[k]=sorted(by[k],key=lambda r:(r["month"],r["store"]),reverse=True)[:12]
    used=sum(rb(k) for k in selected)
    if used>budget: raise SystemExit("30% overlap cannot fit under 9.5 MB")

for k in sorted(eligible-sel,key=lambda k:(0 if k in offer_keys else 1,)+rank(k)):
    z=rb(k)
    if used+z<=budget: selected.append(k); sel.add(k); used+=z

rows=[r for k in selected for r in by[k]]; rows.sort(key=lambda r:(r["normalized_product_key"],r["store"],r["month"]))
out,d=enc(rows,len(offer_keys),len(sel&offer_keys))
while len(out)>MAX and len(selected)>need:
    k=selected.pop(); sel.remove(k); rows=[r for x in selected for r in by[x]]
    rows.sort(key=lambda r:(r["normalized_product_key"],r["store"],r["month"])); out,d=enc(rows,len(offer_keys),len(sel&offer_keys))
if d["offer_key_overlap"]<MIN or len(out)>MAX: raise SystemExit("Final validation failed")
OUT.write_bytes(out)
print(json.dumps({"records":len(rows),"bytes":len(out),"offer_keys":len(offer_keys),"matched":len(sel&offer_keys),"overlap":d["offer_key_overlap"]},ensure_ascii=False))
