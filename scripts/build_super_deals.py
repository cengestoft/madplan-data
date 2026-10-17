#!/usr/bin/env python3
"""Beregner supertilbud ud fra den daglige Tilbudsugen-fil (data/offers.json i det PRIVATE repo madplan-tilbud).

Koden indeholder ingen data. Den offentlige repo-kode køres i det private repo, og resultatet (data/super_deals.json)
gemmes KUN dér, fordi Tilbudsugen-data kun må deles med den nærmeste familie.

Reglerne er de samme, testede som i apply_super_deals.py (cola, smør, piskefløde, opvasketabs, toiletpapir).
Tilbudsugen-filen mangler pakkeantal, beholder og kategori. De udledes KUN, når tallene går op, og markeres i `derived`:
  - dåse (enhed «ds.») + liter, hvor liter / 0,33 er et helt tal  -> package_count (24 dåser = 7,92 l)
  - flaske (enhed «fl.») + liter                                   -> volume_l
Pant ligger ikke i kilden og indgår derfor ikke i priserne (reglerne kræver pris uden pant).
Kan noget ikke udledes sikkert, bliver tilbuddet ikke et supertilbud (ingen gæt).
"""
from __future__ import annotations
import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_super_deals import annotate  # noqa: E402

CAN_L = 0.33
TOL = 0.02
QTYPE = {"ltr.": "l", "kg.": "kg", "stk.": "stk", "rl.": "stk", "par": "stk", "pk.": "stk"}
CHAIN = {
    "rema1000": "Rema 1000", "foetex": "Føtex", "kvickly": "Kvickly", "meny": "MENY", "spar": "SPAR", "min-koebmand": "Min Købmand",
    "loevbjerg": "Løvbjerg", "let-koeb": "Let-Køb", "365discount": "365discount", "lidl": "Lidl", "superbrugsen": "Brugsen",
    "netto": "Netto", "bilka": "Bilka", "daglibrugsen": "Brugsen", "abc-lavpris": "ABC Lavpris",
}


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def to_app_offer(slug: str, x: dict) -> dict | None:
    """En Tilbudsugen-række -> felter, som apply_super_deals.annotate forstår. None hvis pris eller dato mangler."""
    price = _num(x.get("price_dkk"))
    if not price or price <= 0 or not x.get("valid_from") or not x.get("valid_to"):
        return None
    name = str(x.get("name") or "")
    brand = str(x.get("brand") or "")
    low = (name + " " + brand).lower()
    amount = _num(x.get("quantity_raw")) or 0.0
    unit = QTYPE.get(str(x.get("quantity_type") or ""), "")
    uses = str(x.get("unit_type") or "")
    derived = []
    o = {
        "id": "ts-" + str(x.get("id") or ""), "store": CHAIN.get(slug, slug), "store_slug": slug, "name": name, "brand": brand,
        "price_dkk": price, "unit_price_dkk": _num(x.get("unit_price_dkk")), "package_amount": amount or None, "package_unit": unit,
        "valid_from": x["valid_from"], "valid_to": x["valid_to"], "member_only": False, "source": "Tilbudsugen.dk",
        "category": "", "product_type": "", "source_category": "", "container": "", "package_count": None, "volume_l": None,
    }
    if "cola" in low:
        o["category"], o["product_type"], o["source_category"] = "drikkevarer", "cola", "sodavand"
        if uses == "ds." and unit == "l" and amount:
            n = amount / CAN_L
            if abs(n - round(n)) <= TOL and round(n) >= 1:
                o["container"], o["package_count"] = "can", int(round(n))
                derived.append("package_count_fra_liter_og_33cl")
        elif uses == "fl." and unit == "l" and amount:
            o["container"], o["volume_l"] = "bottle", amount
            derived.append("volume_fra_mængde")
    elif re.search(r"\bsmør\b", low):
        o["category"], o["product_type"] = "mejeri", "butter"
    if derived:
        o["derived"] = derived
    return o


def build(file: dict, today: str, now_iso: str) -> dict:
    offers, scanned = [], 0
    for slug, s in sorted(((file or {}).get("stores") or {}).items()):
        if slug not in CHAIN:
            continue
        for x in s.get("offers") or []:
            scanned += 1
            o = to_app_offer(slug, x)
            if o is None or o["valid_to"] < today:
                continue
            if annotate(o, now_iso):
                offers.append(o)
    return {
        "generated_at": now_iso, "source": "Tilbudsugen.dk", "use": "Privat brug, nærmeste familie. Må ikke gøres offentlig.",
        "source_file_generated_at": (file or {}).get("generated_at"), "scanned": scanned,
        "super_deal_count": len(offers), "offers": offers,
    }


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--in", dest="src", required=True)
    p.add_argument("--out", required=True)
    a = p.parse_args(argv)
    src = json.loads(Path(a.src).read_text(encoding="utf-8"))
    now = dt.datetime.now(dt.timezone.utc)
    today = (now + dt.timedelta(hours=2)).date().isoformat()  # dansk dato er nok til udløbstjek; Worker tjekker igen
    doc = build(src, today, now.isoformat(timespec="seconds"))
    out = Path(a.out)
    tmp = out.with_suffix(out.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(out)
    print("Supertilbud: %d af %d tilbud" % (doc["super_deal_count"], doc["scanned"]))  # kun tal


if __name__ == "__main__":
    main()
