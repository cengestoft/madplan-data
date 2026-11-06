# Madplan Data

Dette repository er datalag for en madplans-/indkøbsapp, hvor ChatGPT vedligeholder tilbudsdata og Claude bruger dataene til at generere madplaner, indkøbslister og prisvurderinger.

## Formål

Systemet skal hjælpe med at:
- finde aktuelle dagligvaretilbud
- sammenligne priser på tværs af butikker
- prioritere økologi, grøntsager og børnevenlig mad
- minimere madspild
- udnytte varer, der allerede findes hjemme
- vurdere om et tilbud faktisk er godt ud fra pris-historik
- matche tilbud med opskrifter
- begrænse antallet af butikker, når besparelsen ved ekstra butikker er lille

## Butikker

Følgende kæder indgår:
- Bilka
- SuperBrugsen
- SPAR
- Netto
- 365discount
- Lidl

## Tilbudskilder og opdatering

**Appens aktive tilbud kommer fra det private repository `cengestoft/madplan-tilbud`, ikke fra `current_offers.json` eller `next_week_offers.json` i dette repository.** Den private daglige GitHub Actions-kørsel (`daily-offers.yml`) er planlagt omkring kl. 08 dansk tid og vedligeholder `data/offers.json`, `data/super_deals.json` og `data/offer_keys.json`. Se `data_sources/SNAPSHOTS.md` og det private repos `README-DRIFT.md` for drift og kontrol. En planlagt kørsel er ikke i sig selv dokumentation for vellykket import til Worker eller appdatabase.

`current_offers.json` og `next_week_offers.json` er **ældre interne snapshots** og bliver **ikke automatisk opdateret onsdag kl. 13, fredag kl. 08 og søndag kl. 08** af den aktive private tilbudskæde. De kan være forældede og må ikke præsenteres som appens aktuelle tilbud. De bevares, fordi interne scripts og muligvis eksterne værktøjer stadig bruger dem; afhængighederne er ikke fuldt afklaret.

`scripts/check_freshness.py --informational` rapporterer alderen på det interne `current_offers.json` uden at få data-quality-workflowet til at fejle. Uden flaget kan scriptet fortsat give fejlstatus for gamle snapshots. Friskhed af de private tilbudsfiler kontrolleres separat (maks. 30 timer og sammenhæng mellem filernes tidsstempler).

Der må ikke kopieres private Tilbudsugen-data til dette offentlige repository. Manglende gyldighedsdatoer og priser må ikke gættes.

## Filer

### current_offers.json
Letvægtsindeks over alle aktuelle tilbud fra alle kæder. Det indeholder de felter, der bruges til søgning/prissammenligning samt `normalized_product_key`. Fuld kilde-, billed- og øvrig detaljemetadata bevares i `stores/*.json`.

Vigtige felter:
- `name`
- `store`
- `category`
- `price_dkk`
- `package_amount`
- `package_unit`
- `unit_price_dkk`
- `organic`
- `member_only`
- `valid_from`
- `valid_to`
- `food_relevance`

For interne snapshots må Claude kun behandle et tilbud som aktuelt, hvis gyldighedsperioden er dokumenteret og dækker den relevante dato. Brug ikke dette snapshot som appens live-tilbudskilde.

### next_week_offers.json
Samlet datasæt med tilbud, som allerede er offentliggjort, men først bliver gyldige senere.

Claude må bruge denne fil til planlægning af kommende uge, men må ikke behandle tilbuddene som aktuelle før `valid_from`.

Ved historisk analyse af disse interne snapshots skal Claude filtrere på dokumenterede gyldighedsdatoer. Til aktuelle eller kommende tilbud i appen bruges den aktive private tilbudskilde.

### stores/
Butiksspecifikke filer:
- `stores/bilka.json`
- `stores/superbrugsen.json`
- `stores/spar.json`
- `stores/netto.json`
- `stores/365discount.json`
- `stores/lidl.json`

### archive/YYYY/week-XX.json
Historiske snapshots af ugens samlede tilbud. Bruges til pris-historik og senere analyser.

### household_profile.json
Fast profil for husstanden og standardpræferencer.

Indeholder bl.a.:
- 2 voksne
- 2 børn
- 4 middage som standard
- mange grøntsager
- mild/børnevenlig mad
- økologi prioriteres, når prisforskellen er rimelig
- maks. ca. 2 butikker som udgangspunkt
- fokus på rester, hele pakker og lavt madspild

Claude skal bruge denne fil som standard, medmindre brugeren specifikt beder om noget andet.

### pantry.json
Aktuelt lager i:
- køkkenskab
- køleskab
- fryser

Claude må kun antage, at en vare findes hjemme, hvis den står i denne fil.

Regler:
- brug lager før der købes dubletter
- prioriter varer markeret `use_first`
- træk lagerbeholdning fra indkøbslisten
- foreslå frysning af overskud, når det giver mening

### price_history.json / monthly_price_history.json
`price_history.json` er et lille manifest. Den publicerbare historik ligger i `monthly_price_history.json` og er aggregeret pr. `normalized_product_key`, butik og måned.

Rå prisdumps må ikke ligge i Git. Historiske rækker uden verificeret pakningsstørrelse må ikke få nutidens størrelse kopieret bagud.


### recipes/recipes.json
Opskriftsdatabase med:
- opskrifts-id
- navn
- kategori
- proteintype
- ingredienser
- tilbuds-matchord
- børnevenlighed
- grøntsagsniveau
- fryseegnet
- egnet til rester
- hverdagsvenlig

Claude skal prioritere opskrifter, der:
- matcher flere aktuelle tilbud
- bruger varer fra pantry
- genbruger ingredienser mellem retter
- minimerer specialvarer og madspild
- passer til familiens profil

## Beslutningslogik for madplan

Når Claude laver en madplan, bør rækkefølgen være:

1. læs `household_profile.json`
2. læs `pantry.json`
3. hent verificerede, aktuelle tilbud fra den aktive private tilbudskilde (ikke de gamle interne snapshots)
4. filtrér tilbud efter den konkrete planlægningsperiode
5. filtrér tilbud efter de konkrete datoer for madplanen
6. sammenlign `unit_price_dkk`, når muligt
7. brug `price_history.json` som sekundær vurdering
8. match relevante tilbud mod `recipes/recipes.json`
9. prioriter retter, der bruger samme råvarer på tværs af flere dage
10. begræns antal butikker
11. beregn samlet indkøbspris

## Standard madplans-output

Som standard bør en madplan indeholde:
- 4 middage
- 2 voksne + 2 børn
- mindst 2 slags grønt i de fleste retter
- gerne 1 fiskeret
- gerne 1 vegetarisk eller grøntsagstung ret
- mild krydring
- rester/genbrug af råvarer, hvor det giver mening

Output bør vise:
- ret pr. dag
- hvilke tilbudsvarer der bruges
- butik
- pris pr. vare
- samlet indkøbsliste
- subtotal pr. butik
- samlet pris
- ca. pris pr. middag
- ca. pris pr. person
- hvilke varer der er estimerede normalpriser
- hvilke varer der allerede findes i pantry

## Butiksoptimering

Claude skal som udgangspunkt forsøge at holde indkøbet til 1-2 butikker.

Hvis en ekstra butik kun sparer et lille beløb, skal den ikke automatisk anbefales.

Standardgrænse:
- ekstra butik bør normalt spare mindst ca. 20 kr.

## Økologi

Når økologi ønskes:
- prioriter `organic: true`
- især frugt/grønt, kød, æg og mejeri
- hvis prisforskellen er lille, vælg økologisk
- hvis forskellen er stor, vis begge muligheder

## Interne snapshots
`current_offers.json` og `next_week_offers.json` er interne snapshots. Appens tilbud kommer fra det private `madplan-tilbud`. Se `data_sources/SNAPSHOTS.md`.

## Datakvalitet

Nogle tilbudsaviser er JavaScript-baserede, og datasættet kan derfor være ufuldstændigt.

Hvis `completeness: false`:
- brug de verificerede tilbud
- antag ikke at alle tilbud er med
- opfind aldrig manglende priser
- marker usikkerhed tydeligt

## Hovedkilde til Claude

Claude kan læse det historiske/interne snapshot her (ikke appens aktuelle tilbud):

https://raw.githubusercontent.com/cengestoft/madplan-data/main/current_offers.json

Internt snapshot for tidligere offentliggjorte kommende tilbud (kan være forældet):

https://raw.githubusercontent.com/cengestoft/madplan-data/main/next_week_offers.json

Supplerende filer ligger i samme repository og bør bruges sammen med denne fil.

## Arbejdsdeling

ChatGPT:
- indsamler og vedligeholder tilbudsdata
- opdaterer GitHub
- bygger pris-historik
- udvider datastrukturen

Claude:
- bruger dataene i appen
- laver madplaner
- laver indkøbslister
- optimerer pris, butikker, økologi og madspild
- foreslår alternativer og bytter retter ud efter behov

Målet er et system, hvor appen altid kan arbejde ud fra friske, strukturerede og sammenlignelige data.


## Referencepriser
- `reference_prices.json`: estimerede normal-/referencepriser for 200 almindelige danske dagligvarer.
- Bruges til budgettering, når en nødvendig vare ikke har en verificeret tilbudspris.
- En gyldig verificeret tilbudspris har altid højere prioritet.
- Referencepriser må ikke præsenteres som aktuelle butikpriser.
- `claude_reference_prices.md`: instruktion til Claude om brug af referenceprisdatabasen.


## Automatisk opdatering af referencepriser
- Referencepriser opdateres automatisk hver mandag kl. 06:00 dansk tid.
- `reference_prices.json` er den aktuelle normalpris-database.
- `reference_price_history.json` gemmer historiske snapshots, så tidligere normalpris-estimater ikke mistes.
- En referencepris må kun ændres, hvis der er et rimeligt aktuelt datagrundlag; ellers beholdes den eksisterende værdi.
- Claude skal hente den nyeste `reference_prices.json` fra GitHub før nye budget- eller madplansberegninger.


## Opdatering 5. oktober 2026
5.184 aktuelle tilbud fra 14 kæder. ABC Lavpris behandles på kædeniveau (ingen fast afdeling); Tarm er alene særskilt arkiv. Se `SUPERKOEB_MASTER.md` for den kanoniske implementeringsvejledning og `data_sources/dagligepriser_manifest.json` for det fundne historiske dump (226.142 vareposter, 2.336.261 historiske prisregistreringer). Kør `scripts/import_dagligepriser_history.py` for lokal månedlig aggregering. Rådumpet må ikke ligge i Git. Månedligt aggregeret historik må publiceres efter dagligepriser.dks skriftlige tilladelse (se `data_sources/DAGLIGEPRISER_DATA_RIGHTS.md`).

## Kanonisk Superkøb-master

`SUPERKOEB_MASTER.md` er den eneste masterfil for Superkøb-dataflow, ABC Lavpris (kædeniveau), normalisering, Supertilbud, historik og accepttests. Ældre Claude-handoff-filer er fjernet for at undgå modstridende regler.


## Supertilbud – historikvalidering
- Frontend må ikke konstruere eller aliasere `normalized_product_key`; nøgler kommer fra backend-normalisering.
- `super_deal_history_report.json` viser efter import, hvor mange aktuelle Supertilbud der har mindst 3 måneders prishistorik.
- Tilbud med færre end 3 måneder får `graph_allowed: false` og registreres i `data_quality_errors.json`.
- `monthly_price_history.json` skal være aggregeret og under 12 MB.
