# Madplan data

Maskinlæsbart datasæt med aktuelle dagligvaretilbud til brug i Claude/app.

## Filer
- `current_offers.json`: samlet aktivt datasæt
- `stores/*.json`: tilbud pr. kæde
- `archive/YYYY/week-XX.json`: historiske snapshots

## Kæder
Bilka, SuperBrugsen, SPAR, Netto, 365discount og Lidl.

## Felter
`name`, `store`, `category`, `price_dkk`, `package_amount`, `package_unit`,
`unit_price_dkk`, `organic`, `member_only`, `valid_from`, `valid_to`, `food_relevance`.

## Datakvalitet
`completeness=false` betyder, at filen er et verificeret starter-datasæt og ikke nødvendigvis indeholder hver vare fra de JavaScript-baserede tilbudsaviser endnu. Claude bør kun bruge tilbud, hvis datoen ligger inden for `valid_from` og `valid_to`.
