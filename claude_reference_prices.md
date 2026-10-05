# Claude instructions — reference prices

Repository: https://github.com/cengestoft/madplan-data

New file: `reference_prices.json`

This file contains estimated normal/reference prices for 200 common Danish grocery items.

## Use it for
- complete shopping-list budgets
- ingredients not covered by a verified offer
- approximate meal-plan costs
- approximate savings versus a typical normal price

## Price priority
1. Valid verified price in `current_offers.json`
2. Valid verified future price in `next_week_offers.json` for the planned shopping date
3. Other verified store-specific price in the repository
4. `reference_prices.json`
5. Unknown/manual estimate if no sensible match exists

Never let a reference price override a valid verified offer.

## Labeling
Whenever `reference_prices.json` is used, label the price:
**estimeret normalpris**

Never call it:
- tilbudspris
- aktuel butikpris
- verificeret pris

## Matching
Match by product type/name, category, package size and unit.

For kg/liter products, proportional scaling is allowed.
Example: if 1 kg has a reference price of 14 DKK, 300 g may be budgeted at about 4.20 DKK.

For discrete products such as broccoli, avocado, eggs and bread packs, use piece/package logic unless a verified weight exists.

Do not match clearly different products only because the category is similar.

## Fields
- `name`
- `category`
- `package_amount`
- `package_unit`
- `estimated_reference_price_dkk`
- `expected_normal_range_dkk.low/high`
- `estimated_unit_price_dkk`
- `confidence`
- `price_type`

## Complete budget output
Distinguish:
- verified offer total
- estimated normal-price total
- expected checkout total

Example:
Verified offers: 248 DKK
Estimated normal-price items: 117 DKK
Expected total: ca. 365 DKK

## Offer comparison
You may estimate savings:
Reference normal price: ca. 42 DKK
Offer: 30 DKK
Estimated saving: ca. 12 DKK / 29%

State that the baseline is estimated.

For claims such as "lowest price in months", use `price_history.json`, not `reference_prices.json`.

## Existing system files
Continue using:
- `current_offers.json`
- `next_week_offers.json`
- `household_profile.json`
- `pantry.json`
- `price_history.json`
- `recipes/recipes.json`
- `stores/*.json`
- `archive/YYYY/week-XX.json`

README.md remains the primary system documentation.

Goal: produce complete, realistic meal plans and shopping lists even when only some ingredients are on offer.


## Automatic refresh

`reference_prices.json` is updated automatically every Monday at 06:00 Europe/Copenhagen.

Before creating a new meal plan, shopping budget, or normal-price comparison:
1. fetch the latest `reference_prices.json` from GitHub
2. do not rely on a cached local copy if fresh GitHub data is available
3. read `updated_at`, `previous_reference_price_dkk`, `change_percent`, `source_count`, and `confidence` when present

A reference price may only be changed when there is a reasonable current evidence base. If not, retain the previous value.

Historical reference-price snapshots are stored in:
`reference_price_history.json`

Use that history for trend context, but use `price_history.json` for verified offer-history claims.

Priority remains:
verified current offer > verified future offer valid for target date > verified store-specific price > current reference price estimate.
