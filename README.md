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

## Automatik

ChatGPT opdaterer tilbudsdata automatisk tre gange om ugen dansk tid:
- onsdag kl. 13:00: første scan af næste uges offentliggjorte tilbud
- fredag kl. 08:00: hovedscan efter flere kæder har skiftet/offentliggjort ny avis
- søndag kl. 08:00: endelig synkronisering efter bl.a. Lidl og resterende uge-skift

Ved hver kørsel:
1. aktuelle tilbud gennemgås
2. gyldighed kontrolleres
3. fødevarer og relevante dagligvarer normaliseres
4. kg-/literpris beregnes, når data tillader det
5. butiksspecifikke filer opdateres
6. `current_offers.json` opdateres med tilbud, der er gyldige nu
7. `next_week_offers.json` opdateres med offentliggjorte tilbud, der først bliver gyldige senere
8. et historisk uge-snapshot gemmes
9. `price_history.json` opdateres med nye observationer

Manglende priser eller størrelser må ikke gættes. De skal være `null` eller tydeligt markeret som ikke-verificerede.

## Filer

### current_offers.json
Samlet aktivt datasæt med aktuelle tilbud fra alle kæder.

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

Claude skal kun behandle et tilbud som aktuelt, hvis dags dato ligger inden for `valid_from` og `valid_to`.

### next_week_offers.json
Samlet datasæt med tilbud, som allerede er offentliggjort, men først bliver gyldige senere.

Claude må bruge denne fil til planlægning af kommende uge, men må ikke behandle tilbuddene som aktuelle før `valid_from`.

Hvis brugeren spørger om "næste uge", skal Claude læse både `current_offers.json` og `next_week_offers.json` og vælge tilbud efter de konkrete gyldighedsdatoer.

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

### price_history.json
Pris-intelligens og historiske prisobservationer.

Standard score:
- `exceptional`: <= 80 % af seneste median
- `very_good`: > 80 % og <= 90 %
- `good`: > 90 % og <= 97 %
- `normal`: > 97 % og <= 105 %
- `weak`: > 105 %

En pris-score er først pålidelig efter mindst 4 observationer.

Claude må ikke kalde en pris historisk god uden tilstrækkelige observationer.

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
3. læs `current_offers.json`
4. læs `next_week_offers.json` hvis planen gælder en kommende periode
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

## Datakvalitet

Nogle tilbudsaviser er JavaScript-baserede, og datasættet kan derfor være ufuldstændigt.

Hvis `completeness: false`:
- brug de verificerede tilbud
- antag ikke at alle tilbud er med
- opfind aldrig manglende priser
- marker usikkerhed tydeligt

## Hovedkilde til Claude

Claude kan læse den samlede aktuelle fil her:

https://raw.githubusercontent.com/cengestoft/madplan-data/main/current_offers.json

Næste uges offentliggjorte tilbud:

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
