#!/usr/bin/env python3
"""Shared Superkøb product normalization.

The same function is used for current offers and history so normalized_product_key
does not drift between datasets.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

UNIT_ALIASES = {
    "liter": "l", "litre": "l", "ltr": "l", "l": "l",
    "cl": "cl", "ml": "ml",
    "kg": "kg", "kilo": "kg", "g": "g", "gram": "g",
    "stk": "stk", "st": "stk", "pcs": "stk", "pk": "stk",
}

KNOWN_BRANDS = [
    "Salling Princip", "Coca-Cola", "Coca Cola", "Gram Slot", "Thise",
    "Arla", "Pepsi Max", "Pepsi", "Kærgården", "Lurpak", "Milbona",
    "Änglamark", "Coop", "Gestus", "First Price", "X-tra",
]

VARIANTS = [
    "zero sugar", "zero", "light", "max", "økologisk", "øko",
    "laktosefri", "uden sukker", "original", "classic",
]

def _text(value: Any) -> str:
    return str(value or "").strip()

def _slug(value: Any) -> str:
    s = unicodedata.normalize("NFKD", _text(value)).lower()
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.replace("æ", "ae").replace("ø", "oe").replace("å", "aa")
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "unknown"

def normalize_unit(unit: Any) -> str:
    u = _text(unit).lower().replace(".", "")
    return UNIT_ALIASES.get(u, u or "unknown")

def _float(value: Any):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if value is None:
        return None
    try:
        return float(str(value).replace(",", "."))
    except ValueError:
        return None

def infer_brand(record: dict) -> str:
    explicit = _text(record.get("brand"))
    if explicit:
        return explicit
    name = _text(record.get("name"))
    lower = name.lower()
    for brand in sorted(KNOWN_BRANDS, key=len, reverse=True):
        if brand.lower() in lower:
            return "Coca-Cola" if brand.lower() == "coca cola" else brand
    return "generic"

def infer_variant(record: dict) -> str:
    explicit = _text(record.get("variant"))
    if explicit:
        return explicit
    text = f"{_text(record.get('name'))} {_text(record.get('brand'))}".lower()
    for variant in VARIANTS:
        if variant in text:
            return variant
    return "standard"

def infer_pack(record: dict):
    name = _text(record.get("name")).lower().replace(",", ".")
    count = _float(record.get("package_count")) or 1.0
    amount = _float(record.get("single_package_amount"))
    unit = normalize_unit(record.get("single_package_unit"))

    if amount is None:
        amount = _float(record.get("package_amount"))
        unit = normalize_unit(record.get("package_unit"))

    # Explicit multipack in name, e.g. 24 x 33 cl / 6x0.5 l.
    m = re.search(r"(?<!\d)(\d{1,3})\s*[x×]\s*(\d+(?:\.\d+)?)\s*(ml|cl|l|g|kg|stk)\b", name)
    if m:
        count = float(m.group(1))
        amount = float(m.group(2))
        unit = normalize_unit(m.group(3))
    elif amount is None:
        m = re.search(r"(?<!\d)(\d+(?:\.\d+)?)\s*(ml|cl|l|g|kg|stk)\b", name)
        if m:
            amount = float(m.group(1))
            unit = normalize_unit(m.group(2))

    count_i = int(count) if float(count).is_integer() else count
    amount_v = int(amount) if isinstance(amount, float) and amount.is_integer() else amount
    return count_i, amount_v, unit

def canonical_name(record: dict, brand: str, variant: str) -> str:
    name = _text(record.get("name")).lower().replace(",", ".")
    if brand != "generic":
        name = re.sub(re.escape(brand.lower()), " ", name)
        if brand == "Coca-Cola":
            name = re.sub(r"coca\s*-?\s*cola", " ", name)
    if variant != "standard":
        name = re.sub(re.escape(variant.lower()), " ", name)
    name = re.sub(r"(?<!\d)\d{1,3}\s*[x×]\s*\d+(?:\.\d+)?\s*(?:ml|cl|l|g|kg|stk)\b", " ", name)
    name = re.sub(r"(?<!\d)\d+(?:\.\d+)?\s*(?:ml|cl|l|g|kg|stk)\b", " ", name)
    name = re.sub(r"\s+", " ", name).strip(" -_/")
    return name or _text(record.get("product_type")) or "product"

def normalized_product_key(record: dict) -> str:
    brand = infer_brand(record)
    variant = infer_variant(record)
    count, amount, unit = infer_pack(record)
    product = canonical_name(record, brand, variant)
    size = "unknown" if amount is None else f"{amount:g}{unit}"
    return (
        f"brand={_slug(brand)}|product={_slug(product)}|variant={_slug(variant)}"
        f"|count={count}|size={_slug(size)}"
    )

def apply_category_rules(record: dict):
    """Apply only high-confidence category fixes and return quality errors."""
    errors = []
    text = f"{_text(record.get('name'))} {_text(record.get('brand'))}".lower()
    current = _text(record.get("category"))

    if "piskefløde" in text or "piskefloede" in text:
        record["category"] = "mejeri"
        record["product_type"] = "whipping_cream"
        record["category_confidence"] = 1.0
    elif not current or current.lower() in {"unknown", "ukendt", "andet"}:
        errors.append({
            "type": "category_uncertain",
            "offer_id": record.get("id"),
            "name": record.get("name"),
            "current_category": current or None,
            "suggested_category": None,
            "confidence": 0.0,
        })

    return errors

def normalize_record(record: dict):
    out = dict(record)
    out["brand"] = infer_brand(out) if not _text(out.get("brand")) else out.get("brand")
    out["variant"] = infer_variant(out) if not _text(out.get("variant")) else out.get("variant")
    count, amount, unit = infer_pack(out)
    out["package_count"] = count
    if amount is not None:
        out.setdefault("single_package_amount", amount)
        out.setdefault("single_package_unit", unit)
    out["normalized_product_key"] = normalized_product_key(out)
    errors = apply_category_rules(out)
    return out, errors
