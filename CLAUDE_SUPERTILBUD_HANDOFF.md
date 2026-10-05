# Claude-handoff: Supertilbud skal komme fra GitHub-data

Dato: 2026-10-05

## Formål
Supertilbud må ikke længere afhænge af, at frontend selv fortolker kategorier, produktnavne og prisgrænser. ChatGPT/data-pipelinen beregner Supertilbud centralt og publicerer resultatet i:

- `https://raw.githubusercontent.com/cengestoft/madplan-data/main/super_deals.json`
- reglerne ligger fortsat i `super_deal_rules.json`

## Ændring i appens adfærd

### 1. Supertilbud-fanen
Hent `super_deals.json` direkte og vis `offers`.

Brug:
- `offer_count` til badge/antal
- `offers[].super_deal === true`
- `super_deal_rule`
- `super_deal_reason`
- pris, butik, gyldighed, pakningsstørrelse, enhedspris og billede fra tilbuddet

Frontend skal **ikke** genberegne eller afvise et Supertilbud, fordi kategori eller lokal produktklassifikation ser anderledes ud.

### 2. Autoritativ kilde
`super_deals.json` har `authoritative: true`.

Når filen kan hentes korrekt:
- brug den som sandhed for Supertilbud
- lav ikke en ekstra frontend-filterregel ovenpå
- badge "Supertilbud X" skal være `offer_count`
- hjemmesidens Supertilbud-sektion skal bruge samme datasæt

### 3. Frisk data
Hent GitHub-data med cache-bypass, fx `cache: "no-store"`, og undgå at gammel localStorage/service-worker-cache skjuler nye Supertilbud.

Hvis fetch fejler:
- behold sidste fungerende snapshot
- vis en lille datastatus
- markér ikke nye tilbud ud fra gæt

### 4. Konkret accepttest
Dette aktuelle tilbud skal vises som Supertilbud:

- Butik: Netto
- Vare: Coca-Cola 24 × 33 cl
- Pris: 59 kr. + pant
- Gyldig: 3.–9. oktober 2026
- `super_deal: true`
- `super_deal_rule: "cola_24_cans"`
- `super_deal_reason: "59 kr. < 69 kr. for 24 dåser"`

Coca-Cola Zero 24 × 33 cl til 59 kr. matcher samme regel.

Hvis dette tilbud ikke vises efter ændringen, er frontend stadig koblet til gammel Supertilbud-logik eller gammel cache.

## Regler der er aktive nu
- Coca-Cola 24 dåser: under 69 kr.
- Coca-Cola 1,5–2 L flaske: under 11 kr./liter
- Rigtigt smør: højst 40 kr./kg; smørbar/blandingsprodukter er udelukket
- Piskefløde 36%+: højst 25 kr./liter
- Opvasketabs: højst 0,75 kr./tab
- Toiletpapir 3-lags: højst 2,00 kr./rulle

## Klassifikation
Undgå naive substring-regler for cola. Ord som fx "Chocolate" eller produktnavne som Corny må ikke blive `product_type: "cola"`.

Centralt match kræver relevant drikkevare/sodavandskontekst og et godkendt cola-brand.

## Dataflow
- `current_offers.json`: alle aktuelle tilbud til tilbudsaviser/menuplan/søgning
- `next_week_offers.json`: verificerede kommende tilbud
- `super_deal_rules.json`: prisgrænser og definitioner
- `super_deals.json`: færdigberegnede aktuelle Supertilbud til UI

## Fremadrettet
Når prisgrænser ændres, bør frontend normalt ikke ændres. Reglerne opdateres i data-pipelinen, hvorefter `super_deals.json` regenereres.

Manuelle Supertilbud-regler kan fortsat redigeres i appen, men når de skal være fælles og stabile på tværs af enheder, bør de gemmes centralt og indgå i næste generering.
