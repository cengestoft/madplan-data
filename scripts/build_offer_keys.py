#!/usr/bin/env python3
"""Trin A: kobler Tilbudsugen-tilbud til verificerede historiknøgler (normalized_product_key).

Koden indeholder ingen data. Output (data/offer_keys.json) gemmes kun i det private repo madplan-tilbud.

Regler (ingen gæt):
  - Nøglen beregnes med de samme funktioner som historikken (product_normalization.normalize_record) ud fra felter, der kan læses
    sikkert i Tilbudsugen-filen (navn, mærke, mængde, enhed). Pakkeantal for dåser udledes kun som i build_super_deals.
  - Kun nøgler, der findes i history_verification.json med status "verified", gemmes (match = "exact_verified").
  - Samme mærke, vare og variant men anden pakning tælles kun (similar_pack) og gemmes IKKE.
  - Filen kobles til én bestemt tilbudsfil via offers_file_generated_at; Worker ignorerer den, hvis datoen ikke passer.
"""
from __future__ import annotations
import argparse
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_super_deals import CHAIN, to_app_offer  # noqa: E402
from product_normalization import normalize_record  # noqa: E402


def _base(key: str) -> str:
    return "|".join(key.split("|")[:3])


def verified_keys(verification: dict) -> set:
    ks = (verification or {}).get("keys") or {}
    return {k for k, v in ks.items() if isinstance(v, dict) and v.get("status") == "verified"}


def build(file: dict, verification: dict, now_iso: str) -> dict:
    ok = verified_keys(verification)
    ok_base = {_base(k) for k in ok}
    keys, scanned, similar = {}, 0, 0
    for slug, s in sorted(((file or {}).get("stores") or {}).items()):
        if slug not in CHAIN:
            continue
        for x in s.get("offers") or []:
            scanned += 1
            o = to_app_offer(slug, x)
            if o is None or x.get("id") in (None, ""):
                continue
            nk = normalize_record(o)[0]["normalized_product_key"]
            if nk in ok:
                keys[str(x["id"])] = nk
            elif _base(nk) in ok_base:
                similar += 1
    return {
        "generated_at": now_iso, "source": "Tilbudsugen.dk", "use": "Privat brug, nærmeste familie. Må ikke gøres offentlig.",
        "offers_file_generated_at": (file or {}).get("generated_at"),
        "history_verification_generated_at": (verification or {}).get("generated_at"),
        "scanned": scanned, "exact_verified": len(keys), "similar_pack": similar, "keys": keys,
    }


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--in", dest="src", required=True)
    p.add_argument("--verification", required=True)
    p.add_argument("--out", required=True)
    a = p.parse_args(argv)
    src = json.loads(Path(a.src).read_text(encoding="utf-8"))
    ver = json.loads(Path(a.verification).read_text(encoding="utf-8"))
    doc = build(src, ver, dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"))
    out = Path(a.out)
    tmp = out.with_suffix(out.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(out)
    print("Nøgler: %d verificerede, %d kun anden pakning, af %d tilbud" % (doc["exact_verified"], doc["similar_pack"], doc["scanned"]))  # kun tal


if __name__ == "__main__":
    main()
