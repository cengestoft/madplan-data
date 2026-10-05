# Claude – ændring af Supertilbud-fanen

Dato: 2026-10-05

## Formål

Supertilbud skal **ikke længere beregnes i frontend** ud fra egne hardcodede prisregler.

ChatGPT/data-pipelinen afgør nu centralt, hvilke tilbud der er Supertilbud.

## Ny datakilde

Brug:

`https://raw.githubusercontent.com/cengestoft/madplan-data/main/super_deals_current.json`

Filen indeholder kun aktuelle tilbud, der allerede er godkendt som Supertilbud.

Vigtige felter:

- `super_deal: true`
- `super_deal_rule`
- `super_deal_reason`
- `super_deal_checked_at`
- `super_deal_count` på filniveau
- `counts_by_store`

## Frontend-adfærd

1. Fanen **Supertilbud** skal hente `super_deals_current.json`.
2. Vis tilbuddene i `offers` direkte.
3. Badge/tæller ved "Supertilbud" skal bruge `super_deal_count`.
4. Frontend må **ikke** genberegne prisgrænser.
5. Vis gerne `super_deal_reason` som forklaring, fx:
   - "59 kr. < 69 kr. for 24 dåser"
6. Pant skal fortsat vises separat og må ikke lægges til den pris, der sammenlignes med grænsen.
7. Brug `fetch(..., { cache: "no-store" })` eller tilsvarende, så appen ikke viser en gammel feed.
8. Hvis `super_deals_current.json` midlertidigt ikke kan hentes, må appen vise en fejl/ingen data — den må ikke falde tilbage til opdigtede eller gamle Supertilbud.

## Test der SKAL bestås

Netto-tilbuddet:

- Coca-Cola 24 x 33 cl
- pris: 59 kr. + pant
- gyldig 3.–9. oktober 2026
- regel: `cola_24_cans`

skal vises som Supertilbud.

Coca-Cola Zero må ikke vises som Supertilbud under Coca-Cola-reglen.

## Reglernes kilde

Prisregler vedligeholdes centralt i:

`super_deal_rules.json`

Frontend skal ikke kopiere disse regler.

Aktuelle grænser:

- Almindelig Coca-Cola 24 dåser: under 69 kr. (ikke Zero, Light, Pepsi/Pepsi Max eller Fanta)
- Almindelig Coca-Cola 1,25–2,0 L: under 11 kr./liter (ikke Zero, Light, Pepsi/Pepsi Max eller Fanta)
- Rigtigt smør: højst 40 kr./kg, ikke smørbar/blandingsprodukt
- Piskefløde 36%+: højst 25 kr./liter
- Opvasketabs: højst 0,75 kr./tab
- Toiletpapir 3-lags: højst 2,00 kr./rulle

## Datakvalitet

Klassificering foretages nu centralt. Match for cola kræver drikkevare/sodavand-kontekst, så varer som fx Corny Chocolate ikke fejlagtigt kan blive klassificeret som cola.

## Vigtigt

`current_offers.json` og `stores/*.json` bruges fortsat til de almindelige tilbudsvisninger, tilbudsaviser og menuplan.

Kun **Supertilbud-fanen** bør skifte til den nye canonical feed `super_deals_current.json`.

Efter ændringen: genindlæs uden cache og kontroller, at badge-tallet svarer til `super_deal_count`.


## Rettelse 5. oktober 2026 kl. 20:20
- Cola-reglerne gælder kun almindelig Coca-Cola.
- Coca-Cola Zero, Coca-Cola Light, Pepsi, Pepsi Max og Fanta er udelukket.
- Flaskeintervallet er 1,25–2,0 liter.
- Frontend skal fortsat stole på `super_deals_current.json` og må ikke genberegne disse regler.
