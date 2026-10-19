#!/usr/bin/env python3
"""Importvagt for Tilbudsugen-hentningen. Beslutter pr. butik, om nye data må erstatte de forrige.

Princip: nye data erstatter kun forrige, hvis de er hentet fuldstændigt og ser rigtige ud. Ellers beholdes butikkens
forrige tilbud (kun dem, der stadig er gyldige i dag, så udløbne aldrig genaktiveres), og de andre butikker
opdateres som normalt. Ingen fast procentgrænse på antal: et naturligt skift mellem tilbudsuger (de gamle tilbud
udløber, nye kommer) er ikke en fejl. Vi sammenligner kun med forrige butiks tilbud, der STADIG ER I GYLDIGHED i dag.

Årsagskoder er et fast vokabular (logs er offentlige): ok, held_fetch_stopped, held_empty, held_incomplete,
held_poor_quality, held_vanished, unavailable.
"""
import datetime as dt
import json
import re
from pathlib import Path
from zoneinfo import ZoneInfo

CPH_TZ = ZoneInfo("Europe/Copenhagen")
BAD_REASONS = ("no_name", "no_or_bad_price", "no_dates", "bad_date_range", "not_dkk")
MAX_BAD_SHARE = 0.25      # andel af hentede poster med ødelagt navn/pris/dato (udløbne tæller ikke som fejl)
MIN_PREV_VALID = 20       # under dette antal gyldige forrige tilbud sammenlignes der ikke
MAX_VANISHED_SHARE = 0.5  # over halvdelen af de stadig gyldige forrige tilbud er væk fra kilden
SYSTEMIC_MIN_STORES = 4   # fra så mange butikker: hvis halvdelen eller flere holdes tilbage, skrives intet


def _date(s):
    try:
        return dt.date.fromisoformat(s)
    except (TypeError, ValueError):
        return None


def running(o, today):
    """Tilbud, der gælder i dag (start <= i dag <= slut). Alt andet er udløbet eller kommende."""
    a, b = _date(o.get("valid_from")), _date(o.get("valid_to"))
    return a is not None and b is not None and a <= today <= b


def still_valid(o, today):
    b = _date(o.get("valid_to"))
    return b is not None and b >= today


def _keys(o):
    return {("id", str(o.get("id"))), ("nk", (str(o.get("name") or "").lower().strip(), o.get("price_dkk"), o.get("valid_to")))}


def load_previous(path):
    """Forrige fil, kun hvis den ligner en gyldig fil. Ellers None (ingen sammenligningsgrundlag)."""
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(doc, dict) or not isinstance(doc.get("stores"), dict):
        return None
    return doc


def _bad_share(st):
    fetched = st.get("fetched_ids") or 0
    if not fetched:
        return 0.0
    return sum((st.get("rejected") or {}).get(r, 0) for r in BAD_REASONS) / fetched


def evaluate_store(st, offers, prev_store, today):
    """Returnerer (verdict, årsagskode, detaljer). verdict er 'ok' eller 'held'."""
    prev_offers = (prev_store or {}).get("offers") or []
    prev_running = [o for o in prev_offers if running(o, today)]
    new_keys = set()
    for o in offers.values():
        new_keys |= _keys({"id": o.get("id"), "name": o.get("name"), "price_dkk": o.get("price_dkk"), "valid_to": o.get("valid_to")})
    vanished = sum(1 for o in prev_running if not (_keys(o) & new_keys)) if prev_running else 0
    detail = {"accepted": len(offers), "previous_running": len(prev_running), "vanished": vanished,
              "bad_share": round(_bad_share(st), 3)}
    stopped = st.get("stopped")
    if stopped:
        detail["stopped"] = re.sub(r"[^a-z0-9_]", "", str(stopped).lower())[:30]
        return "held", "held_fetch_stopped", detail
    if not offers:
        return "held", "held_empty", detail
    if not st.get("complete"):
        return "held", "held_incomplete", detail
    if detail["bad_share"] > MAX_BAD_SHARE:
        return "held", "held_poor_quality", detail
    if len(prev_running) >= MIN_PREV_VALID and vanished / len(prev_running) > MAX_VANISHED_SHARE:
        return "held", "held_vanished", detail
    return "ok", "ok", detail


def assemble(per_store, prev_doc, today, now, entry_fn):
    """Bygger den samlede fil. per_store: [(st, offers)]. entry_fn(st, offers) -> butikkens felter (som før).
    Returnerer (doc eller None hvis hele kørslen blokeres, rapport)."""
    prev_stores = (prev_doc or {}).get("stores") or {}
    now_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    prev_good = (prev_doc or {}).get("generated_at")
    stores, report = {}, {}
    for st, offers in per_store:
        slug = st["store"]
        prev = prev_stores.get(slug)
        verdict, reason, detail = evaluate_store(st, offers, prev, today)
        row = dict(detail, status=verdict, reason=reason)
        if verdict == "ok":
            e = entry_fn(st, offers)
            e.update(status="ok", last_good_at=now_iso)
            stores[slug] = e
        elif prev and isinstance(prev.get("offers"), list):
            carried = [o for o in prev["offers"] if still_valid(o, today)]
            e = {k: v for k, v in prev.items() if k not in ("offers",)}
            e.update(offers=carried, accepted=len(carried), status="held", held_reason=reason,
                     held_since=prev.get("held_since") or now_iso,
                     last_good_at=prev.get("last_good_at") or prev_good)
            stores[slug] = e
            row["carried"] = len(carried)
        else:
            row["status"], row["reason"] = "unavailable", "unavailable"
        report[slug] = row
    held = [s for s, r in report.items() if r["status"] != "ok"]
    summary = {"stores": report, "held": sorted(held), "blocked": False}
    n = len(report)
    if n >= SYSTEMIC_MIN_STORES and len(held) * 2 >= n:
        summary["blocked"] = True
        summary["blocked_reason"] = "systemic_half_or_more_held"
        return None, summary
    if not any(e.get("offers") for e in stores.values()):
        summary["blocked"] = True
        summary["blocked_reason"] = "no_offers_at_all"
        return None, summary
    return {"stores": stores, "import_report": {"run_at": now_iso, "held": sorted(held), "stores": report}}, summary


# ---- Backup og gendannelse (fase 3) ----
BACKUP_NAME = "offers.previous.json"


def valid_backup(doc):
    """En fil må kun blive til backup, hvis den ligner en brugbar fil: butikker og mindst ét tilbud i alt."""
    if not isinstance(doc, dict) or not isinstance(doc.get("stores"), dict):
        return False
    return any(isinstance(s, dict) and isinstance(s.get("offers"), list) and s["offers"] for s in doc["stores"].values())


def write_atomic(path, doc):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    tmp.replace(path)


def backup_previous(out_path, prev_doc):
    """Gemmer forrige gyldige fil ved siden af den nye, FØR den nye skrives. En ugyldig forrige fil overskriver aldrig en god backup.
    Returnerer True, hvis der blev gemt en backup."""
    if not valid_backup(prev_doc):
        return False
    write_atomic(Path(out_path).with_name(BACKUP_NAME), prev_doc)
    return True


def restore_doc(backup, today, now):
    """Gendanner fra en backup uden at genaktivere udløbne tilbud: kun tilbud, der stadig er gyldige i dag, tages med
    (kommende tilbud beholdes). generated_at bevares, så alderen på data forbliver synlig i appen.
    Returnerer (doc, rapport). doc er None, hvis backup'en er ugyldig, eller der ikke er noget gyldigt tilbage."""
    if not valid_backup(backup):
        return None, {"result": "refused", "reason": "backup_invalid"}
    stores, dropped = {}, 0
    for slug, s in backup["stores"].items():
        if not isinstance(s, dict) or not isinstance(s.get("offers"), list):
            continue
        keep = [o for o in s["offers"] if still_valid(o, today)]
        dropped += len(s["offers"]) - len(keep)
        if keep:
            e = {k: v for k, v in s.items() if k not in ("offers", "held_reason", "held_since")}
            e.update(offers=keep, accepted=len(keep), status="restored")
            stores[slug] = e
    if not stores:
        return None, {"result": "refused", "reason": "nothing_still_valid", "dropped_expired": dropped}
    now_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    doc = {k: v for k, v in backup.items() if k not in ("stores", "import_report")}
    doc["stores"] = stores
    doc["restored"] = {"at": now_iso, "from_generated_at": backup.get("generated_at"), "dropped_expired": dropped}
    doc["import_report"] = {"run_at": now_iso, "held": [], "restored": True, "stores": {}}
    return doc, {"result": "restored", "stores": len(stores), "offers": sum(len(e["offers"]) for e in stores.values()),
                 "dropped_expired": dropped}
