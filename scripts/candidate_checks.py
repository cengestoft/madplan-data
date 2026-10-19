#!/usr/bin/env python3
"""Offline control of a Dropbox history CANDIDATE (artifact `kandidat-historik`) against the committed files. Read-only.

Needs NO raw data. Reads only aggregated files and writes a report with COUNTS and normalized product keys, never raw text.
Checks (PASS/FAIL each):
  1 existing price rows unchanged      2 previously verified keys kept      3 Coca-Cola keys without pack_size conflict
  4 Faxe Kondi rejection kept          5 no new approvals applied           6 the 60 approvals still provisional
  7 no raw data / tokens / unexpected files in the artifact
Usage: python3 scripts/candidate_checks.py --before-dir . --after-dir DIR_WITH_UNZIPPED_ARTIFACT [--report OUT.md] [--main-ref origin/main]
Exit code 1 if any check fails.
"""
from __future__ import annotations
import argparse, hashlib, json, re, subprocess, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from history_import_guard import ALLOWED_KEY_FIELDS, months_by_key  # noqa: E402

COLA_KEYS = ["brand=coca-cola|product=cola|variant=standard|count=24|size=0-25l",
             "brand=coca-cola|product=cola|variant=zero|count=24|size=0-25l",
             "brand=coca-cola|product=cola|variant=zero|count=24|size=0-33l"]
ZERO25_KEY = "brand=coca-cola|product=cola|variant=zero|count=24|size=0-25l"
FAXE_KEY = "brand=faxe-kondi|product=sportssodavand-24-pk|variant=standard|count=24|size=0-33l"
EXPECTED_FILES = {"monthly_price_history.json", "history_verification.json", "history_offer_identities.json", "price_history.json", "report.md", "diff.json"}
PROVISIONAL = "provisional_until_checked_against_private_match_log"
TOKEN_PATTERNS = [r"sl\.[A-Za-z0-9_-]{20,}", r"ghp_[A-Za-z0-9]{20,}", r"github_pat_[A-Za-z0-9_]{20,}", r"(?i)bearer\s+[A-Za-z0-9._-]{20,}",
                  r"(?i)(refresh_token|app_secret|api[_-]?key)\"?\s*[:=]\s*\"?[A-Za-z0-9._-]{12,}", r"sk-ant-[A-Za-z0-9_-]{10,}"]
RAW_FIELD_NAMES = {"raw_name", "raw_examples", "raw_hash", "examples", "match_log", "description", "priceHistory"}


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def row_key(r):
    return (r["normalized_product_key"], r["store"], r["month"])


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main_ref_sha(ref, rel, cwd):
    try:
        blob = subprocess.run(["git", "show", f"{ref}:{rel}"], cwd=cwd, capture_output=True, check=True).stdout
        return hashlib.sha256(blob).hexdigest()
    except Exception:
        return None


def run_checks(before, after, main_ref=None):
    """Returns (results, lines). results: {n: (PASS|FAIL, text)}."""
    before, after = Path(before), Path(after)
    res, notes = {}, []
    b_hist, a_hist = load(before / "monthly_price_history.json"), load(after / "monthly_price_history.json")
    b_ver, a_ver = load(before / "history_verification.json"), load(after / "history_verification.json")
    bk, ak = b_ver["keys"], a_ver["keys"]

    # 1 rows unchanged
    a_rows = {row_key(r): r for r in a_hist["records"]}
    missing = [k for k in (row_key(r) for r in b_hist["records"]) if k not in a_rows]
    changed = [row_key(r) for r in b_hist["records"] if row_key(r) in a_rows and a_rows[row_key(r)] != r]
    res[1] = ("PASS" if not missing and not changed else "FAIL",
              f"{len(b_hist['records'])} eksisterende rækker; manglende {len(missing)}, ændrede {len(changed)}; kandidat har {len(a_hist['records'])} rækker ({len(a_hist['records']) - len(b_hist['records'])} nye)")

    # 2 verified keys kept (status and months)
    b_verified = {k for k, v in bk.items() if v.get("status") == "verified"}
    lost = sorted(k for k in b_verified if ak.get(k, {}).get("status") != "verified")
    bm, am = months_by_key(b_hist), months_by_key(a_hist)
    shrunk = sorted(k for k in b_verified if not bm.get(k, set()) <= am.get(k, set()))
    a_verified = sum(1 for v in ak.values() if v.get("status") == "verified")
    res[2] = ("PASS" if not lost and not shrunk else "FAIL",
              f"{len(b_verified)} tidligere verificerede nøgler; tabt {len(lost)}, mistet måneder {len(shrunk)}; kandidat har {a_verified} verificerede" + (f"; tabt: {lost[:5]}" if lost else ""))

    # 3 Coca-Cola
    bad, parts = [], []
    for k in COLA_KEYS:
        v = ak.get(k)
        if v is None:
            bad.append(f"{k}: findes ikke"); continue
        conf = v.get("conflict_fields") or {}
        parts.append(f"{k.split('|', 1)[1]}: main={bk.get(k, {}).get('status')} -> kandidat={v.get('status')}, konflikter={conf or 'ingen'}")
        if "pack_size" in conf:
            bad.append(f"{k}: pack_size-konflikt")
    still_rej = [k for k in COLA_KEYS if ak.get(k, {}).get("status") == "rejected"]
    if bad:
        res[3] = ("FAIL", "; ".join(bad))
    elif still_rej:
        res[3] = ("FAIL", "ingen pack_size-konflikt, men stadig afvist (anden årsag, skal undersøges): " + "; ".join(parts))
    else:
        res[3] = ("PASS", "; ".join(parts))

    # 4 Faxe
    fv, fb = ak.get(FAXE_KEY), bk.get(FAXE_KEY, {})
    if fv is None:
        res[4] = ("FAIL", "nøglen findes ikke i kandidaten")
    elif fv.get("status") == "rejected":
        how = "videreført (carried_over)" if fv.get("carried_over") else "afvist direkte af nye rå matches"
        res[4] = ("PASS", f"main={fb.get('status')} -> kandidat=rejected, {how}; rå produkter {fv.get('raw_products')}. Årsagen til de manglende matches: kan ikke afgøres uden match-log")
    else:
        res[4] = ("FAIL", f"main={fb.get('status')} -> kandidat={fv.get('status')}, rå produkter {fv.get('raw_products')}")
    rej_lost = sorted(k for k, v in bk.items() if v.get("status") == "rejected" and ak.get(k, {}).get("status") != "rejected"
                      and sum((ak.get(k, {}).get("raw_products") or {}).values()) == 0)
    if rej_lost and res[4][0] == "PASS":
        res[4] = ("FAIL", f"{len(rej_lost)} andre afvisninger mistet uden rå produkter")
    notes.append(f"Videreførte afvisninger: {sum(1 for v in ak.values() if v.get('carried_over'))}")

    # 5 + 6 approvals
    dec_path = before / "data_sources" / "history_review_decisions.json"
    dec = load(dec_path)
    dec_keys = {d["normalized_product_key"] for d in dec.get("decisions", []) if d.get("decision") == "verified"}
    applied = sum(v.get("manual_decisions", 0) for v in ak.values())
    blocked = sum(v.get("manual_decisions_blocked", 0) for v in ak.values())
    manual_keys = {k for k, v in ak.items() if v.get("manual_decisions")}
    outside = sorted(manual_keys - dec_keys)
    verified_decisions = len([d for d in dec.get("decisions", []) if d.get("decision") == "verified"])
    ok5 = applied <= verified_decisions and not outside and blocked == 0
    res[5] = ("PASS" if ok5 else "FAIL", f"{verified_decisions} godkendelser i filen, anvendt {applied}, blokeret {blocked}, nøgler med manuelle godkendelser {len(manual_keys)}, uden for filen {len(outside)}")
    same = None
    if main_ref:
        ref = main_ref_sha(main_ref, "data_sources/history_review_decisions.json", before)
        same = ref is not None and ref == sha(dec_path)
    ok6 = dec.get("status") == PROVISIONAL and same is not False
    res[6] = ("PASS" if ok6 else "FAIL", f"decisions-filens status = {dec.get('status')}; filen " + ("identisk med main" if same else "ikke sammenlignet med main" if same is None else "ER ÆNDRET i forhold til main"))

    # 7 leaks
    problems = []
    files = {p.name for p in after.iterdir() if p.is_file()}
    extra, absent = sorted(files - EXPECTED_FILES), sorted(EXPECTED_FILES - files)
    if extra: problems.append(f"uventede filer {extra}")
    if absent: problems.append(f"manglende filer {absent}")
    if any(p.is_dir() for p in after.iterdir()): problems.append("undermapper i artifact")
    for name, doc in (("monthly_price_history.json", a_hist), ("history_verification.json", a_ver)):
        if doc.get("raw_data_included") is not False: problems.append(f"{name}: raw_data_included er ikke false")
    for k, v in ak.items():
        ex = set(v) - ALLOWED_KEY_FIELDS
        if ex: problems.append(f"nøgle med uventede felter {sorted(ex)}"); break
    bad_names = set()
    def walk(o):
        if isinstance(o, dict):
            for kk, vv in o.items():
                if kk in RAW_FIELD_NAMES: bad_names.add(kk)
                walk(vv)
        elif isinstance(o, list):
            for x in o: walk(x)
    walk(a_ver); walk(a_hist)
    if bad_names: problems.append(f"felter der kan indeholde rådata: {sorted(bad_names)}")
    own_names = set()
    for rel in ("current_offers.json", "data_sources/history_offer_identities.json"):
        p = before / rel
        if p.exists():
            d = load(p)
            if rel.startswith("current"):
                own_names |= {str(o.get("name")) for o in d.get("offers", [])}
            else:
                own_names |= {str(r.get("name")) for recs in d.get("keys", {}).values() for r in recs}
    for k, v in ak.items():
        for n in v.get("offer_names") or []:
            if n not in own_names:
                problems.append("offer_names med navn, der ikke findes i egne tilbuds- eller identitetsdata"); break
        else:
            continue
        break
    pat = [re.compile(p) for p in TOKEN_PATTERNS]
    for p in sorted(after.iterdir()):
        if p.is_file() and any(rx.search(p.read_text(encoding="utf-8", errors="ignore")) for rx in pat):
            problems.append(f"{p.name}: indeholder noget, der ligner et token/en hemmelighed")
    res[7] = ("PASS" if not problems else "FAIL", "6 forventede filer, ingen rådatafelter, ingen token-mønstre, offer_names kun fra egne data" if not problems else "; ".join(problems))

    # 8 no verified key may rest on an offer whose package size is unverified (explicitly incl. Coca-Cola Zero 24 x 25 cl)
    cur = load(before / "current_offers.json") if (before / "current_offers.json").exists() else {"offers": []}
    unv = {o.get("normalized_product_key") for o in cur.get("offers", []) if o.get("quantity_status") == "unverified" and o.get("normalized_product_key")}
    holds_p = before / "data_sources" / "history_holds.json"
    holds = load(holds_p) if holds_p.exists() else {}
    released = {r.get("key") for r in holds.get("releases", []) if r.get("approved_by") == "Casper" and r.get("approved_on")}
    bad8 = sorted(k for k in unv if ak.get(k, {}).get("status") == "verified")
    zero = ak.get(ZERO25_KEY, {})
    zero_bad = zero.get("status") == "verified" and (ZERO25_KEY in unv or ZERO25_KEY not in released)
    if zero_bad and ZERO25_KEY not in bad8: bad8.append(ZERO25_KEY)
    held = sorted(k for k, v in ak.items() if v.get("held"))
    res[8] = ("PASS" if not bad8 else "FAIL",
              (f"{len(unv)} nøgle(r) med ubekræftet tilbudsmængde, ingen er verificeret; Zero 24 x 25 cl: {zero.get('status')}" + (f" (holdt: {zero.get('held')})" if zero.get("held") else "") + f"; holdte nøgler: {len(held)}")
              if not bad8 else "verificeret på ubekræftet mængde/uden Caspers frigivelse: " + "; ".join(k.split("|", 1)[1] for k in bad8))

    # 9 approval status changes vs the first candidate (keys + counts only)
    base_p = before / "data_sources" / "history_approval_baseline.json"
    if base_p.exists():
        base = load(base_p).get("keys", {})
        cur_ap = {k: v.get("manual_decisions", 0) for k, v in ak.items() if v.get("manual_decisions")}
        diffs = sorted(k for k in set(base) | set(cur_ap) if base.get(k, 0) != cur_ap.get(k, 0))
        promoted = [k for k in diffs if cur_ap.get(k, 0) > base.get(k, 0) and ak.get(k, {}).get("status") == "verified"]
        desc = "; ".join(f"{k.split('|', 1)[1]}: {base.get(k, 0)} -> {cur_ap.get(k, 0)} ({ak.get(k, {}).get('status')})" for k in diffs)
        res[9] = ("PASS" if not promoted else "FAIL",
                  f"baseline {len(base)} nøgler/{sum(base.values())} godkendelser; kandidat {len(cur_ap)} nøgler/{sum(cur_ap.values())}; ændrede nøgler: {len(diffs)}" + (f" [{desc}]" if desc else "")
                  + (f". Nyligt anvendte godkendelser har gjort {len(promoted)} nøgle(r) verificeret – kræver Caspers vurdering" if promoted else ""))
    else:
        res[9] = ("FAIL", "baseline-filen data_sources/history_approval_baseline.json mangler")
    return res, notes


TITLES = {1: "3.485 eksisterende prisrækker uændrede", 2: "97 tidligere verificerede nøgler bevaret", 3: "Coca-Cola uden falske pakkestørrelseskonflikter",
          4: "Faxe Kondis afvisning bevaret", 5: "Ingen nye, udokumenterede godkendelser anvendt", 6: "De foreløbige godkendelser stadig foreløbige",
          7: "Ingen rådata, private logs eller tokens i artifact",
          8: "Ingen verificeret nøgle bygger på ubekræftet tilbudsmængde (inkl. Coca-Cola Zero 24 x 25 cl)", 9: "Ændringer i anvendte godkendelser rapporteret og ikke promoveret"}


def report(res, notes):
    allp = all(v[0] == "PASS" for v in res.values())
    lines = ["## Kontrol af Dropbox-kandidat (offline, ingen rådata)", "", f"**Samlet: {'PASS' if allp else 'FAIL'}**", ""]
    for n in sorted(res):
        lines.append(f"{n}. {TITLES[n]}: **{res[n][0]}**")
        lines.append(f"   - {res[n][1]}")
    lines += [""] + [f"- {x}" for x in notes] + ["", "Kandidaten er ikke publiceret og er ikke godkendt. De foreløbige godkendelser skal stadig kontrolleres mod den private match-log."]
    return "\n".join(lines) + "\n", allp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--before-dir", default="."); ap.add_argument("--after-dir", required=True)
    ap.add_argument("--report"); ap.add_argument("--main-ref", default="origin/main")
    a = ap.parse_args()
    res, notes = run_checks(a.before_dir, a.after_dir, a.main_ref)
    text, ok = report(res, notes)
    print(text)
    if a.report: Path(a.report).write_text(text, encoding="utf-8")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
