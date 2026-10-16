#!/usr/bin/env python3
"""Tør kørsel: kan kildesiderne hentes, og ligner de noget vi kan læse? Skriver INGEN tilbudsdata.

Kun faste, sikre felter pr. kæde (HTTP-status, størrelse, antal strukturerede poster, robots-svar).
Ingen sideindhold, produktnavne, priser eller datoer gemmes eller printes (logs er offentlige).
Én kæde, der fejler, stopper aldrig de øvrige.
"""
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UA = "SuperkoebSourceProbe/1.0 (+https://github.com/cengestoft/madplan-data)"
MAX_BYTES = 5 * 1024 * 1024
CHAINS = {  # import_status.json "sources": fast liste over de 15 kæder
    "rema1000": "rema", "foetex": "foetex", "kvickly": "kvickly", "meny": "meny", "spar": "spar",
    "min-koebmand": "min-koebmand", "loevbjerg": "loevbjerg", "let-koeb": "let-koeb",
    "365discount": "365discount", "lidl": "lidl", "superbrugsen": "superbrugsen", "netto": "netto",
    "bilka": "bilka", "daglibrugsen": "dagli", "abc-lavpris": "abc-search",
}
RE_LD = re.compile(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.I | re.S)


def fetch(url, opener=urllib.request.urlopen):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,application/json"})
    try:
        with opener(req, timeout=30) as r:
            return r.status, r.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as e:
        return e.code, b""
    except Exception:
        return None, b""


def robots_allows(origin, path, opener=urllib.request.urlopen):
    """Enkel, forsigtig læsning af robots.txt for alle brugeragenter (*). Uklart svar = 'unknown'."""
    status, body = fetch(origin + "/robots.txt", opener)
    if status != 200:
        return "unknown"
    applies, disallow = False, []
    for line in body.decode("utf-8", "replace").splitlines():
        line = line.split("#")[0].strip()
        if not line or ":" not in line:
            continue
        k, v = [x.strip() for x in line.split(":", 1)]
        if k.lower() == "user-agent":
            applies = v == "*"
        elif applies and k.lower() == "disallow" and v:
            disallow.append(v)
    return "disallowed" if any(path.startswith(d) for d in disallow) else "allowed"


def ld_offer_count(html):
    n = 0
    for m in RE_LD.finditer(html):
        try:
            doc = json.loads(m.group(1))
        except ValueError:
            continue
        stack = [doc]
        while stack:
            x = stack.pop()
            if isinstance(x, dict):
                if str(x.get("@type")) in ("Offer", "Product"):
                    n += 1
                stack.extend(x.values())
            elif isinstance(x, list):
                stack.extend(x)
    return n


def probe_chain(slug, url, opener=urllib.request.urlopen):
    row = {"store": slug, "http": None, "bytes": 0, "too_large": False, "structured_records": 0, "robots": "unknown", "result": "error"}
    try:
        p = urllib.parse.urlparse(url)
        if p.scheme != "https":
            row["result"] = "bad_url"; return row
        row["robots"] = robots_allows(f"{p.scheme}://{p.netloc}", p.path or "/", opener)
        if row["robots"] == "disallowed":
            row["result"] = "robots_disallow"; return row
        status, body = fetch(url, opener)
        row["http"], row["bytes"] = status, min(len(body), MAX_BYTES)
        row["too_large"] = len(body) > MAX_BYTES
        if status != 200:
            row["result"] = "http_error" if status else "unreachable"; return row
        row["structured_records"] = ld_offer_count(body.decode("utf-8", "replace"))
        row["result"] = "ok_structured" if row["structured_records"] else "ok_no_structured_data"
    except Exception:
        row["result"] = "error"
    return row


def main(opener=urllib.request.urlopen):
    status = json.loads((ROOT / "import_status.json").read_text(encoding="utf-8"))["sources"]
    rows = []
    for slug, key in CHAINS.items():
        url = (status.get(key) or {}).get("source_url")
        rows.append(probe_chain(slug, url, opener) if url else {"store": slug, "result": "no_source_url"})
    out = {"mode": "dry_run_no_data_written", "stores": rows}
    print(json.dumps(out, ensure_ascii=False, indent=2))
    Path("source_probe_report.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
