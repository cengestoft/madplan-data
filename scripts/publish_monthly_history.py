#!/usr/bin/env python3
from __future__ import annotations
import datetime as dt, json, pathlib, re, statistics, urllib.request
from collections import defaultdict
from product_normalization import normalized_product_key

URL = "https://dagligepriser.dk/data/latest-canonical.json"
OUT = pathlib.Path("monthly_price_history.json")
MAX_BYTES = 98 * 1024 * 1024
STORES = {
    "bilkatogo":"Bilka","fotex":"føtex","meny":"MENY","minkobmand":"Min Købmand",
    "nemlig":"Nemlig.com","netto":"Netto","rema1000":"REMA 1000","spar":"SPAR"
}
NONFOOD = re.compile(
    r"(shampoo|balsam|deodorant|parfume|tandpasta|tandbørste|mundskyl|bleer|"
    r"vådserviet|toiletpapir|køkkenrulle|rengøring|vaskemiddel|skyllemiddel|"
    r"opvask|håndcreme|ansigtscreme|bodylotion|solcreme|makeup|kosttilskud|"
    r"vitamin|kapsler|tabletter|kattefoder|hundefoder|dyrefoder|vådfoder|"
    r"tørfoder|kattesand|whiskas|pedigree|royal canin|dreamies|vitakraft|"
    r"best friend|ballon|gavepapir|kalender|blyant|kuglepen|batteri|lampe|"
    r"stearinlys|optænding|maling|værktøj|oplader|kaffekop|kaffeske|"
    r"drikkeglas|tallerken|bestik|stegepande|gryde|bageform|skærebræt|"
    r"madkasse|drikkedunk|frysepose|affaldspose|bagepapir|stanniol|alufolie|"
    r"viskestykke|legetøj|lego|dukke|bamse|trøje|bukser|strømper|sko |"
    r"håndklæde|sengetøj|pude|dyne|gardin|plante|gødning|motorolie|bilpleje)",
    re.I
)
FOOD = re.compile(
    r"(mælk|yoghurt|skyr|fløde|ost|smør|margarine|ægge|kød|oksekød|grisekød|"
    r"kylling|kalkun|pølse|bacon|skinke|salami|leverpostej|pålæg|fisk|laks|"
    r"torsk|tun|makrel|sild|reje|skaldyr|brød|rugbrød|toast|bolle|croissant|"
    r"kage|cookie|kiks|knækbrød|tortilla|pizza|lasagne|suppe|bouillon|pasta|"
    r"spaghetti|nudler|havre|müsli|granola|cereal|gryn|quinoa|couscous|"
    r"sauce|sovs|dressing|ketchup|sennep|mayonnaise|remoulade|pesto|olie|"
    r"eddike|salt|peber|krydder|vanilje|sukker|sirup|honning|marmelade|"
    r"syltetøj|chokolade|slik|lakrids|vingummi|chips|snacks|popcorn|nød|"
    r"mandel|cashew|pistacie|peanut|kaffe|espresso|kakao|sodavand|cola|juice|"
    r"saft|mineralvand|danskvand|energidrik|frugt|grønt|grøntsag|æble|pære|"
    r"banan|appelsin|mandarin|clementin|citron|lime|grapefrugt|mango|ananas|"
    r"kiwi|melon|jordbær|hindbær|blåbær|brombær|druer|fersken|avocado|tomat|"
    r"agurk|peberfrugt|chili|hvidløg|kartoffel|gulerod|broccoli|blomkål|"
    r"spinat|salat|majs|ærter|bønner|linser|kikært|champignon|svampe|aubergine|"
    r"squash|selleri|porre|rødbede|asparges|ingefær|basilikum|persille|dild|"
    r"timian|rosmarin|koriander|sorbet|dessert|pudding|fromage|smoothie|babymad|"
    r"modermælkserstatning|grød|(?<!\w)æg(?!\w)|(?<!\w)te(?!\w)|"
    r"(?<!\w)mel(?!\w)|(?<!\w)ris(?!\w)|(?<!\w)ost\w*)",
    re.I
)

def is_food(product: dict) -> bool:
    name = str(product.get("name") or "")
    if NONFOOD.search(name):
        return False
    category = str(product.get("category") or "")
    if len(category) >= 1 and category[0] in "0123456":
        return True
    return bool(FOOD.search(name))

def brand_from_name(name: str):
    first = name.split(",",1)[0].strip()
    return first if 0 < len(first) <= 50 else None

def package_probe(product: dict, h: dict):
    name = product.get("name")
    return {
        "name": name,
        "brand": product.get("brand") or brand_from_name(str(name or "")),
        "variant": product.get("variant"),
        "package_count": h.get("package_count", 1),
        "package_amount": h.get("quantity"),
        "package_unit": h.get("unit"),
    }

def valid_hist(h: dict):
    try:
        dt.date.fromisoformat(h.get("date"))
        p = float(h.get("price"))
        q = float(h.get("quantity"))
        u = h.get("unit")
        return p > 0 and q > 0 and bool(u)
    except Exception:
        return False

def dump(doc):
    OUT.write_text(json.dumps(doc,ensure_ascii=False,separators=(",",":"))+"\n",encoding="utf-8")

raw = urllib.request.urlopen(URL, timeout=300).read()
products = json.loads(raw)
buckets = defaultdict(list)
names = {}
for product in products:
    store_code = product.get("store")
    if store_code not in STORES or not is_food(product):
        continue
    for h in product.get("priceHistory", []):
        if not valid_hist(h):
            continue
        probe = package_probe(product,h)
        key = normalized_product_key(probe)
        month = h["date"][:7]
        bkey = (key, STORES[store_code], month)
        buckets[bkey].append(float(h["price"]))
        names[key] = product.get("name")

rows=[]
for (key,store,month), prices in buckets.items():
    rows.append({
        "normalized_product_key": key,
        "store": store,
        "month": month,
        "observation_count": len(prices),
        "median_price_dkk": round(float(statistics.median(prices)),2),
        "min_price_dkk": round(min(prices),2),
        "source": "dagligepriser.dk",
    })
rows.sort(key=lambda r:(r["normalized_product_key"],r["store"],r["month"]))
doc={
    "schema_version":2,
    "source":"dagligepriser.dk",
    "aggregation":"normalized_product_key + store + month",
    "food_only":True,
    "raw_data_included":False,
    "generated_at":dt.datetime.now(dt.timezone.utc).isoformat(),
    "record_count":len(rows),
    "records":rows,
}
dump(doc)

# GitHub rejects blobs above 100 MiB. If needed, remove the least useful
# single-observation months deterministically, oldest first, until safely below.
if OUT.stat().st_size > MAX_BYTES:
    singles = sorted(
        (r for r in rows if r["observation_count"] == 1),
        key=lambda r:(r["month"],r["normalized_product_key"],r["store"])
    )
    remove_ids=set()
    for r in singles:
        remove_ids.add((r["normalized_product_key"],r["store"],r["month"]))
        if len(remove_ids) % 5000 == 0:
            kept=[x for x in rows if (x["normalized_product_key"],x["store"],x["month"]) not in remove_ids]
            doc["records"]=kept; doc["record_count"]=len(kept)
            dump(doc)
            if OUT.stat().st_size <= MAX_BYTES:
                rows=kept
                break
    if OUT.stat().st_size > MAX_BYTES:
        raise SystemExit(f"monthly_price_history.json still too large: {OUT.stat().st_size} bytes")

print(json.dumps({
    "products":len(products),
    "records":doc["record_count"],
    "bytes":OUT.stat().st_size,
    "source":"dagligepriser.dk",
    "raw_committed":False
},ensure_ascii=False))
