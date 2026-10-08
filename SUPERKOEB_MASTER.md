# SUPERKØB MASTER

Dato: 2026-10-05

Dette er den eneste kanoniske implementeringsfil for Superkøb. Hvis andre ældre Claude/handoff-filer siger noget andet, gælder denne fil.

## Faste regler

- ABC betyder ABC Lavpris generelt; tilbud kan variere mellem afdelinger.
- ABC-data må publiceres som generelle ABC Lavpris-tilbud, men må ikke mærkes som en bestemt afdeling uden dokumentation.
- Aktuelle tilbud og historiske priser er separate datasæt.
- Historiske poster må aldrig blive aktive tilbud alene fordi de er nye i en import.
- Frontend må ikke genberegne centrale Supertilbud-regler.

## Autoritative filer

- current_offers.json: letvægtsindeks over alle aktuelle tilbud med pris, pakning, gyldighed, kategori og normalized_product_key. Fuld kilde-/billedmetadata ligger i stores/*.json.
- current_offers.previous.json: seneste publicerede snapshot før nuværende.
- import_status.json: skal genereres ud fra samme tilbud som current_offers.json.
- super_deal_rules.json: centrale Supertilbud-regler.
- super_deals_current.json: kanonisk feed til Supertilbud-fanen.
- data_quality_errors.json: poster der kræver kontrol.
- monthly_price_history.json: kanonisk aggregeret historik fra data vi må publicere, én række pr. normalized_product_key + butik + måned.
- price_history.json: lille manifest, ikke rå historik.
- data_sources/dagligepriser_manifest.json: kilde-/rettighedsstatus for dagligepriser.dk.

## Normaliseret produktidentitet

Alle aktuelle tilbud og alle historiske produktposter skal have normalized_product_key.

Nøglen bygges deterministisk af:
1. mærke,
2. kanonisk produktnavn,
3. variant,
4. antal i multipack,
5. størrelse og enhed.

Samme normaliseringskode skal bruges på aktuelle og historiske data. Ukendte dele skrives eksplicit som generic, standard, 1 eller unknown i stedet for at blive udeladt.

## Kategorier

Sikre regler rettes automatisk. Eksempel:
- piskefløde -> mejeri / whipping_cream.

Usikre klassifikationer må ikke gættes. De skrives til data_quality_errors.json med fejltype, tilbuds-id, nuværende kategori, foreslået kategori og sikkerhed.

## Historik

Rådumpet fra dagligepriser.dk på ca. 355 MB må ikke lægges i Git.

Historik skal aggregeres pr. normalized_product_key, butik og måned. Hver månedsserie skal mindst indeholde:
- observation_count
- avg_price_dkk
- min_price_dkk
- max_price_dkk
- first_price_dkk
- last_price_dkk
- first_observation_date
- last_observation_date

Hvis pakningsstørrelsen i en historisk observation er ukendt, må nutidens pakningsstørrelse ikke kopieres bagud.

## dagligepriser.dk rettigheder

Projektkoden Herover/heissepreise er MIT-licenseret, og projektets README beskriver download af live rådata. Der er ikke fundet en særskilt licens, der udtrykkeligt giver ret til offentlig videredistribution af selve prisdatabasen eller et stort afledt datasæt.

Konsekvens:
- data må hentes til lokal analyse/importforberedelse,
- rådata må ikke committes,
- offentlig publicering af et stort afledt dagligepriser-datasæt er blokeret indtil eksplicit datalicens/tilladelse er dokumenteret.

Kontakt angivet af sitet: hi+heissepreise@leonora.app.

## Publiceringsvagt

En import må ikke erstatte de gode data hvis:
- current offers er tom,
- antal aktuelle tilbud falder mere end 25 % uden eksplicit override,
- hård fejlrate overstiger 10 %,
- import_status ikke kan afstemmes mod current_offers,
- ABC-data fejlagtigt mærkes som en specifik afdeling uden dokumentation.

Før publicering kopieres nuværende current_offers.json til current_offers.previous.json.

## Supertilbud

super_deals_current.json er eneste kanoniske feed til frontend.

Aktuelle centrale regler:
- almindelig Coca-Cola 24 dåser: under 69 kr.; Zero, Light, Pepsi/Pepsi Max og Fanta er udelukket.
- almindelig Coca-Cola 1,25–2,0 L: under 11 kr./liter.
- rigtigt smør: højst 40 kr./kg; smørbar/blandingsprodukter udelukkes.
- piskefløde 36%+: højst 25 kr./liter.
- opvasketabs: højst 0,75 kr./tab.
- toiletpapir 3-lags: højst 2,00 kr./rulle.

## Automatisk accepttest

CI skal køre tests ved data-/pipelineændringer.

1. Gyldig Coca-Cola 24x33 cl under grænsen bliver Supertilbud.
2. Corny/irrelevante produkter må ikke matches som Coca-Cola.
3. Piskefløde er mejeri.
4. ABC-standardlokation er Videbæk.
5. Udløbet historik er ikke aktivt tilbud.
6. Dubletter opdages.
7. import_status matcher current_offers.
8. Enhedspris kan kontrolleres.
9. Deal-score-funktionen belønner historisk lave priser.
10. Tom/fejlbehæftet import blokeres.

## Arbejdsregel

Datakvalitet og sporbarhed har prioritet over flere features. Nye scripts skal genbruge product_normalization.py og validation-funktionerne, så frontend, aktuelle tilbud og historik ikke udvikler hver sin produktidentitet.

### Bevar rige butiksposter

Pipeline må ikke erstatte poster i `stores/*.json` med det lettere `current_offers.json`-indeks. Butikfiler normaliseres i place, så kilde-URL, billeder og øvrig dokumentation bevares.

## Sekundære tilbudskilder og komplethedskontrol

MineTilbud bruges som sekundær komplethedskilde/fallback, ikke som ukritisk primær kilde.

Regler:
- Eksisterende officielle eller strukturerede feeds er fortsat primære, når de er bedre dokumenteret.
- MineTilbud bruges til at opdage manglende tilbud og manglende sider/kataloger.
- For kæder hvor tilbud kan variere lokalt, skal butik/afdeling være eksplicit verificeret før publicering.
- ABC Lavpris behandles som kæde-niveau. Lokale afdelingsforskelle markeres som mulige, og appen skal tilbyde direkte link til den aktuelle ABC-tilbudsavis.
- ABC Lavpris kan have lokale forskelle. Derfor vises kæde-tilbud som generelle ABC-tilbud, og brugeren kan åbne den aktuelle tilbudsavis for lokale/særlige tilbud.
- Hvis sekundær kilde og primær kilde er uenige, beholdes den verificerede primære post og uoverensstemmelsen sendes til datakvalitetskontrol.
- Ingen sekundær kilde må reducere eksisterende dokumentationsniveau, kilde-URL eller butikssporbarhed.


## Supertilbud og historikdækning

- `normalized_product_key` må kun genereres i backend via `scripts/product_normalization.py`; frontend må aldrig opfinde eller omskrive nøgler.
- Coca-Cola normaliseres med `product=cola`; "Original"/"Classic" behandles som standard-variant, og ml/cl normaliseres semantisk til samme literstørrelse som aktuelle tilbud.
- `scripts/check_super_deal_history.py` køres efter Supertilbud/import og skriver `super_deal_history_report.json`.
- En prisgraf må kun vises for et aktuelt Supertilbud, når den eksakte kanoniske nøgle har mindst 3 forskellige måneder i historikken.
- Manglende historik skrives til `data_quality_errors.json` med typen `super_deal_missing_history`.
- `monthly_price_history.json` skal fortsat være månedligt aggregeret og være under 12 MB; overskridelse skal blokere publicering.
