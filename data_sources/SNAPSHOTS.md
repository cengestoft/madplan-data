# Interne snapshots: current_offers.json og next_week_offers.json

Status: **interne snapshots**. De er ikke kilden til appens tilbud.

## Hvor kommer appens tilbud fra?
Appens aktuelle tilbud kommer fra det **private** repo `cengestoft/madplan-tilbud`:

- `data/offers.json` (daglig import fra Tilbudsugen.dk)
- `data/super_deals.json` (supertilbud beregnet af `scripts/build_super_deals.py`)
- `data/offer_keys.json` (produktnøgler beregnet af `scripts/build_offer_keys.py`)

Worker'en i `cengestoft/Opskrifter` læser disse tre filer. Tilbudsugen-data må kun ligge privat og må aldrig ind i dette offentlige repo.

## Hvad bruges snapshottene til?
`current_offers.json` og `next_week_offers.json` er uændrede og bruges stadig internt af blandt andet `build_data_pipeline.py`, `build_offer_feed.py`, `check_freshness.py`, `promote_future_offers.py`, data-quality-workflowet, Dropbox-importen og `tools/prishistorik` i Opskrifter.

## Friskhedskontrol
`scripts/check_freshness.py --informational` (brugt i data-quality) melder kun en note (`::notice::`) og afslutter altid med 0. Et gammelt snapshot gør derfor ikke længere data-quality rød. Uden flaget opfører scriptet sig som før (advarsel og exit 1).

Friskheden af de rigtige tilbudsfiler overvåges i `madplan-tilbud` efter den daglige import (max 30 timers alder og indbyrdes sammenhæng; GitHub-issue ved fejl).

## Ikke verificeret
Om andre eksterne værktøjer eller apps læser `current_offers.json` eller `next_week_offers.json` direkte, er **ikke verificeret**. Filerne er derfor bevaret uændret.
