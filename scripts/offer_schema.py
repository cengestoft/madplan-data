#!/usr/bin/env python3
"""Canonical offer schema, Danish-date validity and deterministic classification.

Shared by the pipeline, the acceptance report and the tests so that current,
future and expired offers are always separated by the same rules.
"""
from __future__ import annotations
import datetime as dt
from zoneinfo import ZoneInfo

COPENHAGEN = ZoneInfo("Europe/Copenhagen")

# Aliases seen in next_week_offers.json -> canonical names used everywhere else.
FIELD_ALIASES = {"package_size": "package_amount", "member_required": "member_only"}

# Categories that are documented groceries / non-food in the source data.
FOOD_CATEGORIES = {"frugt_og_gront", "kød", "fjerkræ", "fisk", "mejeri", "brød", "pålæg", "kolonial", "færdigretter"}
NON_FOOD_CATEGORIES = {"husholdning", "dyrefoder"}

def copenhagen_today(now: dt.datetime | None = None) -> dt.date:
    """Today's date in Denmark (not UTC), so offers do not expire early/late."""
    now = now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=dt.timezone.utc)
    return now.astimezone(COPENHAGEN).date()

def snapshot_date(doc: dict) -> dt.date:
    """Danish calendar date of a published snapshot (its generated_at), for deterministic snapshot checks.

    Snapshot integrity is judged on the day the data was generated, never on the
    day the tests happen to run. Live freshness is a separate check
    (scripts/check_freshness.py).
    """
    raw = (doc or {}).get("generated_at")
    try:
        when = dt.datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        raise ValueError(f"snapshot has no valid generated_at: {raw!r}")
    if when.tzinfo is None:
        when = when.replace(tzinfo=COPENHAGEN)
    return when.astimezone(COPENHAGEN).date()

def _date(value):
    try:
        return dt.date.fromisoformat(value)
    except (TypeError, ValueError):
        return None

def canonicalize_offer(offer: dict) -> dict:
    """Rename alias fields to the canonical schema. Values are never changed."""
    out = {}
    for key, value in offer.items():
        target = FIELD_ALIASES.get(key, key)
        if target in out and target != key:
            # Canonical field already present: keep it, never overwrite a value.
            continue
        out[target] = value
    if "organic" not in out:
        out["organic"] = None  # unknown, never guessed
    return out

def offer_status(offer: dict, today: dt.date) -> str:
    """active | future | expired | unknown_end | undated.

    unknown_end: started but valid_to is missing. It is NOT treated as valid
    without limit, so it is never counted as an active offer.
    """
    start, end = _date(offer.get("valid_from")), _date(offer.get("valid_to"))
    if start is None:
        return "undated"
    if start > today:
        return "future"
    if end is None:
        return "unknown_end"
    return "expired" if end < today else "active"

def partition_offers(offers, today: dt.date) -> dict:
    parts = {"active": [], "future": [], "expired": [], "unknown_end": [], "undated": []}
    for offer in offers:
        parts[offer_status(offer, today)].append(offer)
    return parts

def unexplained_losses(previous_offers, incoming_offers, today: dt.date):
    """Verified-valid previous offers (active or future) that are missing from the incoming import.

    Naturally expired offers are NOT data loss. Offers without a valid_to
    (unknown_end) are not verified as valid, so they are not counted here either;
    they are reported separately by unverifiable_missing().
    """
    incoming_ids = {o.get("id") for o in incoming_offers if o.get("id") is not None}
    return [o.get("id") for o in previous_offers
            if o.get("id") is not None and o.get("id") not in incoming_ids
            and offer_status(o, today) in {"active", "future"}]

def unverifiable_missing(previous_offers, incoming_offers, today: dt.date):
    """Previous offers with a start date but no valid_to that are missing now.

    Reported for traceability (data_quality), never treated as unlimited validity
    and never counted as loss of verified offers.
    """
    incoming_ids = {o.get("id") for o in incoming_offers if o.get("id") is not None}
    return [o.get("id") for o in previous_offers
            if o.get("id") is not None and o.get("id") not in incoming_ids
            and offer_status(o, today) == "unknown_end"]

def food_relevance_for(category) -> str | None:
    """Deterministic, category-based. Unknown categories stay unknown (None)."""
    c = str(category or "").lower()
    if c in FOOD_CATEGORIES:
        return "high"
    if c in NON_FOOD_CATEGORIES:
        return "low"
    return None
