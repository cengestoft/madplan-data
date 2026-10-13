# feed/ – side-opdelt tilbudsfeed til appen

Bygges af `python scripts/build_offer_feed.py` ud fra `current_offers.json`. Filerne er afledt data og skrives kun lokalt. Ingen workflow skriver dem.

## Filer

- `index.json`: `schema_version` (1), `valid_on` (snapshottets danske dato), `encoding` ("utf-8"), `page_char_limit` (5800), `food_only`, `stores` (pr. butik: `file`, `offer_count`, `page_count`, `non_food_count`, `valid_to`) og `excluded` (optælling af udeladte tilbud: `not_active`, `missing_price_or_package`, `duplicate_id`, `non_food_excluded_by_flag`).
- `<butik>.json`: `store`, `offer_count`, `page_count`, `non_food_count`, `valid_to`, `offers` (fuldt struktureret record pr. tilbud: `id`, `name`, `price_dkk`, `package_amount`, `package_unit`, `valid_from`, `valid_to`, `organic`, `member_only`, `category`, `page`, `line`, `name_shortened_in_page_text`), `truncated_lines` (tom normalt) og `pages` (liste af tekster).

## Regler

- Hver tekstside er højst 5800 tegn (appens tekstfelt tillader under 6000). Linjer er adskilt af `\n`, kodet som UTF-8.
- Et tilbud er med, hvis det er aktivt på `valid_on` (valid_from ≤ dato ≤ valid_to, dansk dato), har en pris over 0, en pakkemængde og en enhed. Tilbud uden valid_to er aldrig aktive.
- Hvert gyldigt tilbud står på præcis én side. Fødevarer først (kategorirækkefølge), ukendte kategorier derefter, husholdning og dyrefoder sidst. Kun `--food-only` udelader non-food, og det står i `index.json`.
- Hvis en linje alligevel overstiger grænsen, forkortes kun NAVNET (med "…"). Pris, pakning, øko, medlemskab og slutdato bliver stående. Den fulde tekst ligger i `truncated_lines[].full_text`, og det fulde navn og alle felter ligger altid i `offers[]`. Sidetekster er til visning; `offers[]` er kilden til fuldtekst.
- Slutdato: hvis et tilbuds `valid_to` er tidligere end butikkens seneste slutdato, står `- til D.M.` sidst på linjen, så teksten aldrig får et tilbud til at se gyldigt ud længere end det er.
- Linjeformat: `Navn - pris kr. pr. mængde enhed[ - øko][ - kun medlemmer]`. `øko` vises kun, når `organic` er sand. Ukendt (`null`) vises ikke.

## Integration med appen (status 9. oktober 2026)

Ikke verificeret og ikke aktiv. Appen i `cengestoft/Opskrifter` (`src/indkoeb.js`) henter i dag `current_offers.json`, `next_week_offers.json`, `super_deals_current.json`, `monthly_price_history.json` m.fl. fra dette repo, men læser hverken `feed/index.json` eller `feed/*.json`. Før feedet må kaldes integreret, skal en separat gren i Opskrifter-repoet læse `feed/index.json`, hente siderne og have en test. Indtil da er feedet kun dokumenteret og testet i dette repo.
