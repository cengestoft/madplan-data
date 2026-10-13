#!/usr/bin/env python3
"""Product identity check for history matching.

A raw (historical) product may only feed the price history of an offer key when it is the SAME product as
the offer: brand, product type, flavour/variant, meat type, fat percentage, pack count, size and unit.
Equal normalized_product_key is NOT enough, because the key is deliberately coarse (e.g. "hakket-oksekoed-8-12").

Verdicts
  verified         every identity field is present on both sides and equal
  review_required  something is missing, only partly overlapping or unknown (never approved automatically)
  rejected         a field conflicts (other brand, other meat, other flavour, other fat %, other pack count, other variant)

Nothing here stores raw text. Callers keep raw names only in private (git-ignored) logs.
"""
from __future__ import annotations
import hashlib, re, unicodedata

VERIFIED, REVIEW, REJECTED = "verified", "review_required", "rejected"
FIELDS = ("brand", "product_type", "flavour", "variant", "meat", "fat_percent", "pack_count", "pack_size", "unit")

_STOP = {"med", "og", "i", "af", "til", "fra", "the", "a", "en", "et", "m", "u", "pr", "ca", "dk", "stk", "pak", "pk",
         "gram", "gr", "kg", "ml", "cl", "l", "ltr", "lt", "g", "x", "fedt", "tilsat", "uden", "frost", "danmark",
         "brutto", "netto", "vaegt", "draenet", "norge", "sverige", "letland", "italien", "bar", "pet", "dase"}

# --- vocabularies (folded text: lower case, ae/oe/aa, no diacritics) --------------------------------------------------
_MEAT_PREFIX = {"okse": "okse", "kalv": "kalv", "gris": "gris", "svin": "gris", "kylling": "kylling", "kalkun": "kalkun",
                "laks": "laks", "torsk": "torsk", "makrel": "makrel", "rejer": "rejer", "sild": "sild", "hoens": "kylling"}
_MEAT_EXACT = {"lam": "lam", "and": "and", "tun": "tun", "lammekoed": "lam", "ande": "and"}

_FLAVOUR = {  # canonical -> folded substrings (searched in the text with spaces removed)
    "vanilje": ("vanilje", "vanilla"), "jordbaer": ("jordbaer", "strawberry"), "skovbaer": ("skovbaer", "forestberr"),
    "blaabaer": ("blaabaer", "blueberr"), "hindbaer": ("hindbaer", "raspberr"), "banan": ("banan",), "mango": ("mango",),
    "passion": ("passion",), "abrikos": ("abrikos", "apricot"), "fersken": ("fersken", "peach"),
    "karamel": ("karamel", "caramel"), "chokolade": ("chokolade", "choko", "chocolate", "kakao", "cocoa"),
    "nougat": ("nougat",), "cognac": ("cognac",), "baileys": ("bailey",), "havsalt": ("havsalt", "seasalt", "havssalt"),
    "sourcream": ("sourcream",), "loeg": ("loeg", "onion"), "tomat": ("tomat",), "bacon": ("bacon",),
    "peber": ("peber", "pepper"), "chili": ("chili", "chilli"), "citron": ("citron", "lemon", "lime"),
    "appelsin": ("appelsin", "orange"), "aeble": ("aeble", "apple"), "ananas": ("ananas", "pineapple"),
    "kanel": ("kanel", "cinnamon"), "mint": ("mint", "mynte"), "jordnoed": ("jordnoed", "peanut"),
    "hasselnoed": ("hasselnoed", "hazelnut"), "mandel": ("mandel", "mandorle", "almond"), "pistacie": ("pistach", "pistacie"),
    "kokos": ("kokos", "coconut"), "lakrids": ("lakrids",), "hvidloeg": ("hvidloeg", "garlic"), "dild": ("dild",),
    "spinat": ("spinat",), "basilikum": ("basilikum", "basil"), "honning": ("honning", "honey"), "bbq": ("bbq",),
    "rabarber": ("rabarber", "rhubarb"), "teriyaki": ("teriyaki",), "marshmallow": ("marshmallow", "skumfidus"),
    "brownie": ("brownie",), "cookiedough": ("cookiedough",), "mascarpone": ("mascarpone",), "kommen": ("kommen",),
    "urter": ("urter", "herbs"), "mandarin": ("mandarin",), "groentsag": ("groentsag", "vegetabl"),
    "gravad": ("gravad",), "roeget": ("roeget", "smoked"), "timian": ("timian",), "ingefaer": ("ingefaer", "ginger"),
}
_FLAGS = {  # variant flags: sets must be EQUAL (a zero/light/organic version is a different product and price class)
    "zero": ("zero", "nul", "sukkerfri", "0kalorier"), "light": ("light", "lite", "let", "fedtreduceret"),
    "max": ("max",), "oeko": ("oeko", "oekologisk", "organic", "bio"), "laktosefri": ("laktosefri", "lactofree", "lactofre"),
    "vegansk": ("vegansk", "vegan", "plantebaseret"), "glutenfri": ("glutenfri", "glf"), "fuldkorn": ("fuldkorn",),
    "usoedet": ("usoedet",),
}
_FAT_SENSITIVE_WORDS = ("hakket", "hytteost", "skyr", "yoghurt", "maelk", "floede", "fraiche", "smoer", "mayonnaise", "remoulade")


def fold(s) -> str:
    s = str(s or "").lower().replace("æ", "ae").replace("ø", "oe").replace("å", "aa").replace("ö", "o").replace("ä", "a")
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


def words(s):
    return [w for w in re.split(r"[^a-z0-9]+", fold(s)) if w]


def raw_id_hash(store, raw_id, raw_name="") -> str:
    """Stable id for a raw product that does not reveal the raw text (used in public decision files)."""
    return hashlib.sha256(f"{store}|{raw_id}|{raw_name}".encode("utf-8")).hexdigest()[:16]


def brand_slug(b) -> str:
    return " ".join(words(b))


def meats(text):
    out = set()
    for w in words(text):
        if w in _MEAT_EXACT: out.add(_MEAT_EXACT[w]); continue
        for p, c in _MEAT_PREFIX.items():
            if w.startswith(p): out.add(c)
    return out


def flavours(text):
    compact = "".join(words(text))
    return {c for c, subs in _FLAVOUR.items() if subs and any(s in compact for s in subs)}


def flags(text):
    toks = set(words(text)); compact = "".join(words(text))
    out = set()
    for c, subs in _FLAGS.items():
        for s in subs:
            if s in toks or (len(s) >= 5 and s in compact) or (s == "0kalorier" and s in compact):
                out.add(c); break
    return out


def fat_percents(text):
    """All percentages in the text as normalised strings: '1.5', '8-12'."""
    out = set()
    for a, b in re.findall(r"(\d+(?:[.,]\d+)?)\s*(?:-\s*(\d+(?:[.,]\d+)?))?\s*%", str(text or "").replace("–", "-")):
        norm = lambda v: ("%g" % float(v.replace(",", ".")))
        out.add(norm(a) + ("-" + norm(b) if b else ""))
    return out


def _fat_sensitive(text) -> bool:
    ws = words(text)
    return any(any(w.startswith(f) or w.endswith("ost") for f in _FAT_SENSITIVE_WORDS) or w.endswith("ost") for w in ws)


def product_words(text, brand=""):
    drop = set(words(brand))
    voc = set()
    for c, subs in list(_FLAVOUR.items()) + list(_FLAGS.items()):
        voc.add(c); voc.update(subs)
    out = set()
    for w in words(text):
        if len(w) < 3 or w.isdigit() or w in _STOP or w in drop or re.fullmatch(r"\d+[a-z]*", w): continue
        out.add(w)
    return out


def _same_word(a, b):
    return a == b or (min(len(a), len(b)) >= 4 and (a.startswith(b) or b.startswith(a)))


def _overlap(offer_words, raw_words):
    shared = {o for o in offer_words if any(_same_word(o, r) for r in raw_words)}
    return shared


def compare(raw: dict, offer: dict) -> dict:
    """Compare one raw probe with one offer. Both dicts: name, brand, pack_count, pack_amount, pack_unit_family,
    pack_value, text (name + variant + description). Returns verdict + per-field result (never raw text)."""
    res = {f: "match" for f in FIELDS}
    conflicts, missing = [], []

    def conflict(f): res[f] = "conflict"; conflicts.append(f)
    def miss(f): res[f] = "missing" if res[f] != "conflict" else "conflict"; missing.append(f) if f not in missing else None

    rtext, otext = raw.get("text") or raw.get("name") or "", offer.get("text") or offer.get("name") or ""

    # brand
    rb, ob = brand_slug(raw.get("brand")), brand_slug(offer.get("brand"))
    if ob in ("", "generic"): ob = ""
    if not rb and ob:
        # The raw feed has no brand field: the brand is evidence only when its words appear in the raw name.
        rw_all = " " + " ".join(words(rtext)) + " "
        rb = ob if (" " + ob + " ") in rw_all else ""
    if rb and ob:
        if rb != ob:
            (miss if (rb.startswith(ob + " ") or ob.startswith(rb + " ")) else conflict)("brand")
    elif rb or ob:
        miss("brand")  # unknown brand on one side: not enough to approve
    # pack count / size / unit
    if raw.get("pack_count") is not None and offer.get("pack_count") is not None and float(raw["pack_count"]) != float(offer["pack_count"]):
        conflict("pack_count")
    rf, of_ = (raw.get("pack_family"), raw.get("pack_value")), (offer.get("pack_family"), offer.get("pack_value"))
    if None in rf or None in of_: miss("pack_size")
    else:
        if rf[0] != of_[0]: conflict("unit")
        elif abs(float(rf[1]) - float(of_[1])) > 1e-6: conflict("pack_size")
    # meat
    rm, om = meats(rtext), meats(otext)
    if rm and om:
        if rm != om: conflict("meat")
    elif rm or om: miss("meat")
    # fat percent (only where the fat share defines the product)
    rp, op = fat_percents(rtext), fat_percents(otext)
    if rp and op:
        if not (rp & op): conflict("fat_percent")
    elif (rp or op) and (_fat_sensitive(otext) or _fat_sensitive(rtext)): miss("fat_percent")
    # flavour
    rfl, ofl = flavours(rtext), flavours(otext)
    if rfl and ofl:
        if rfl != ofl: (conflict if not (rfl & ofl) else miss)("flavour")
    elif rfl or ofl: miss("flavour")
    # variant flags (zero / light / max / organic / lactose-free / vegan / gluten-free / whole grain)
    if flags(rtext) != flags(otext): conflict("variant")
    # product type: product words with brand removed must overlap
    ow, rw = product_words(otext, offer.get("brand")), product_words(rtext, raw.get("brand") or offer.get("brand"))
    # attribute words are checked above; compare the rest
    shared = _overlap(ow, rw)
    if ow and rw:
        if not shared: conflict("product_type")
        elif len(shared) < len(ow): miss("product_type")  # every distinctive offer word must be found; "Jungle" is not "Fairy"
    else: miss("product_type")

    if conflicts: status = REJECTED
    elif missing: status = REVIEW
    else: status = VERIFIED
    return {"status": status, "fields": res, "conflicts": sorted(set(conflicts)), "missing": sorted(set(missing))}


def describe(record: dict, text_fields=("name", "variant", "description")) -> dict:
    """Identity inputs from a raw probe or an offer record (uses the project's own pack inference)."""
    from product_normalization import infer_pack
    count, amount, unit = infer_pack(record)
    fam = val = None
    if amount is not None:
        total = float(count or 1) * float(amount)
        u = str(unit or "")
        table = {"kg": ("kg", 1), "g": ("kg", 1e-3), "l": ("l", 1), "cl": ("l", 1e-2), "ml": ("l", 1e-3), "stk": ("stk", 1)}
        if u in table: fam, val = table[u][0], round(total * table[u][1], 6)
    return {"name": record.get("name"), "brand": record.get("brand"), "pack_count": float(count or 1) if amount is not None else None,
            "pack_family": fam, "pack_value": val,
            "text": " ".join(str(record.get(f) or "") for f in text_fields)}


def combine(verdicts) -> dict:
    """One raw product against SEVERAL offers that share the same key: verified only if it verifies against all,
    rejected only if it conflicts with all, otherwise review_required."""
    verdicts = list(verdicts)
    if not verdicts: return {"status": REVIEW, "fields": {}, "conflicts": [], "missing": ["no_offer"]}
    sts = {v["status"] for v in verdicts}
    if len(sts) == 1: return verdicts[0]  # all verified, all rejected or all review_required
    worst = next((v for v in verdicts if v["status"] != VERIFIED), verdicts[0])
    return {"status": REVIEW, "fields": worst["fields"], "conflicts": sorted({c for v in verdicts for c in v["conflicts"]}),
            "missing": sorted({m for v in verdicts for m in v["missing"]} | {"ambiguous_offers"})}


def key_status(counts: dict) -> str:
    """Status of a history key from the verdict counts of its raw products."""
    if counts.get(VERIFIED, 0) > 0: return VERIFIED
    if counts.get(REVIEW, 0) > 0: return REVIEW
    if counts.get(REJECTED, 0) > 0: return REJECTED
    return "no_candidate"


GROCERY_EXCLUDED = {"husholdning", "dyrefoder"}


def verified_overlap(current: dict, verification: dict | None, today, min_overlap: float = 0.30) -> dict:
    """Share of unique ACTIVE food product keys whose history is verified. Unverified matches never count.

    Numerator: active food keys with status 'verified' in the verification file. Denominator: all unique active food keys.
    """
    from offer_schema import offer_status
    keys = {o.get("normalized_product_key") for o in current.get("offers", [])
            if o.get("normalized_product_key") and offer_status(o, today) == "active"
            and str(o.get("category") or "").lower() not in GROCERY_EXCLUDED}
    status = {}
    for k in keys:
        status[k] = ((verification or {}).get("keys", {}).get(k) or {}).get("status", "no_candidate")
    n = {st: sum(1 for v in status.values() if v == st) for st in (VERIFIED, REVIEW, REJECTED, "no_candidate")}
    total = len(keys)
    import math
    needed = max(0, math.ceil(min_overlap * total) - n[VERIFIED])
    return {"active_food_keys": total, "verified": n[VERIFIED], "review_required": n[REVIEW], "rejected": n[REJECTED],
            "no_candidate": n["no_candidate"], "overlap": n[VERIFIED] / max(1, total), "required": min_overlap,
            "additional_verified_needed": needed, "verification_file_present": verification is not None}


def history_integrity(hist: dict, verification: dict | None) -> dict:
    """Blocking integrity facts about the history file against the verification file.

    - rows_unverified: history rows whose key is not 'verified' (must be 0)
    - verified_without_history: keys marked 'verified' that have no history rows or months (must be 0)
    - verified_without_raw: keys marked 'verified' without any verified raw product behind them (must be 0)
    """
    keys = (verification or {}).get("keys", {})
    rows_by_key: dict = {}
    for r in hist.get("records", []):
        rows_by_key[r.get("normalized_product_key")] = rows_by_key.get(r.get("normalized_product_key"), 0) + 1
    rows_unverified = sum(n for k, n in rows_by_key.items() if (keys.get(k) or {}).get("status") != VERIFIED)
    verified = [k for k, v in keys.items() if v.get("status") == VERIFIED]
    without_history = sorted(k for k in verified if rows_by_key.get(k, 0) == 0 or not (keys[k].get("months") or 0))
    without_raw = sorted(k for k in verified
                         if not ((keys[k].get("raw_products") or {}).get(VERIFIED) or keys[k].get("manual_decisions")))
    return {"rows_total": sum(rows_by_key.values()), "history_keys": len(rows_by_key), "rows_unverified": rows_unverified,
            "verified_keys": len(verified), "verified_without_history": without_history, "verified_without_raw": without_raw,
            "verified_only_flag": hist.get("verified_only") is True, "verification_file_present": verification is not None}
