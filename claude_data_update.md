# Superkøb: priser, historik og næste arbejde til Claude

Kontrolleret 5. oktober 2026. Repository: https://github.com/cengestoft/madplan-data

## Brugerens mål og faste butik

Indsaml så mange dokumenterede dagligvare- og fødevarepriser som muligt, både gamle og nye. Brug dem til tilbudssammenligning, prisudvikling og ændringer i pakkestørrelser. Brugeren har bekræftet **ABC Lavpris Videbæk**, Høgevej 2, 6920 Videbæk, som fast ABC-butik. Det tidligere navn Vildbjerg var en fejl. ABC Tarm-priser må ikke bruges som Videbæk-priser. Den officielle side oplyser, at butiksvalg kan påvirke tilbud: https://www.abc-lavpris.dk/butikker/videbaek

## Data leveret i denne opdatering

- `current_offers.json`: 5.184 aktuelt gyldige dagligvaretilbud fra 14 kæder, med kilde, pris, mængde, medlemskrav og gyldighed. Portalkontrol er ikke garanti for kasseprisen.
- `stores/*.json`: samme tilbud opdelt efter kæde. `offers` og `stores[].offers` er alternative visninger, ikke to datasæt. Importér kun én.
- ABC Tarm-udtrækket er bevaret særskilt i arkivet med det korrekte sted. ABC Videbæk afventer verificerede varepriser.
- `price_history.json`: de nye tilbudsobservationer er én indsamling, ikke dokumentation for flere års udvikling.
- `data_sources/dagligepriser_manifest.json`: optælling af et faktisk hentet historisk dataudtræk.
- `scripts/import_dagligepriser_history.py`: importerer historik til separate NDJSON-filer pr. kæde. Den aktiverer ikke historiske priser som aktuelle tilbud.

## Stort historisk dataudtræk: konkret fund

Direkte JSON-download: **https://dagligepriser.dk/data/latest-canonical.json**

Faktisk hentet snapshot: 226.142 vareposter, 2.336.261 indlejrede historiske prisregistreringer, datospænd 2023-10-29 til 2026-10-05. Uk komprimeret ca. 355 MB; gzip ca. 20,8 MB. Tallene er kildeposter, ikke nødvendigvis unikke fødevarer, daglige målinger eller stadig tilgængelige varer.

| Kildebutik | Superkøb-navn | Vareposter |
|---|---|---:|
| bilkatogo | Bilka | 93.305 |
| fotex | føtex | 56.911 |
| meny | MENY | 22.398 |
| minkobmand | Min Købmand | 10.839 |
| nemlig | Nemlig.com | 5.464 |
| netto | Netto | 10.438 |
| rema1000 | REMA 1000 | 11.595 |
| spar | SPAR | 15.192 |

Kør fra repo: `python scripts/import_dagligepriser_history.py`. Alternativt `--source-file /sti/dump.json`. Importen skriver `data/history/dagligepriser/*.ndjson` og manifest. Brug database/object storage til millionrækker; lad ikke browseren hente 355 MB eller gem store råfiler i Git.

Kildekode: https://github.com/Herover/heissepreise . Projektets kode har MIT-licens; afklar separat vilkår for offentlig videredistribution af prisdata. README indeholder også arvede østrigske links: `heisse-preise.io` er ikke dette danske udtræk. Prisposter har `store`, `id`, `name`, `price`, `priceHistory`, `quantity`, `unit`, `url`, `bio` og evt. `unavailable`. Historikposter kan indeholde egen `quantity` og `unit`; manglende historisk størrelse må aldrig udfyldes med nutidens størrelse. Seneste prisændring er ikke nødvendigvis seneste daglige kontrol.

## Flere kilder til løbende import

### Madpris: offentlig vare-API og prishistorik

Dokumentation: https://madpris.gratis.dk/api-dokumentation

Ingen autentifikation på offentligt niveau; 500 kald pr. IP pr. UTC-dag. `GET /api/products?page=1` returnerer 50 rå butiksvarer pr. side. Ved vores faktiske opslag havde API'en 140.628 rå vareposter fordelt på 2.813 sider. Det fulde katalog kan derfor ikke hentes på én dag med standardkvoten. Gem checkpoint, hent maks. inden for kvoten, respekter 429/Retry-After, og brug højere kvote kun med en legitim nøgle. Eksempler i dokumentationen er ikke faktiske optællinger.

Andre endpoints: `/api/filters`, `/api/stats`, `/api/product-by-ean?ean=...`, `/api/merged-products`, `/api/price-history?group_id=...` eller `store` + `name`. `POST /api/products/batch` understøtter højst 500 kendte produkt-ID'er, ikke download af 500 vilkårlige ukendte produkter.

Bevar `price_observed_at`, `price_last_seen_at`, `price_status` og publikationsheaders. `observed`, `historical` og `reverted_to_normal` betyder forskellige ting: en automatisk tilbageført normalpris er ikke en ny observeret pris. Den faktiske respons kan bruge `size: "75 cl"` og `unit: "66.67 kr/l"`; pars størrelse, og behandl ikke enhedspristekst som en pakkeenhed. Undersøg location-dækning især for ABC. Den komplette Madpris-historik er ikke hentet i denne levering.

### Supermarkedspriser: åbne aggregater, vare-API med nøgle

https://supermarkedspriser.dk/data tilbyder CSV/JSON med kædernes samlede 100-varekurv pr. dag under CC BY 4.0 med kildeangivelse. Det er godt til markedsindeks, men kan ikke blive til priser på mælk, smør eller andre enkeltvarer. Siden oplyser 5.313.785 prismålinger på 59.026 varer i 20 kæder siden 2026-08-11 ved kontrollen. Varepriser og varehistorik udleveres gennem API med nøgle. Milliontallet beskriver databasen, ikke det frit tilgængelige downloadindhold. Ingen nøgle bestilt eller aftale indgået her.

### Aktuelle tilbud

Tilbudsugen giver bred tilbudsdækning og bruges i det aktuelle udtræk. Bevar annonce-ID og kildeadresse, og foretræk kædens egen kilde ved konflikter. Undersøg officielle tilbudsaviser for ABC Videbæk. Nemlig.com har både historiske poster i dumpet og katalogposter i Madpris; disse må ikke automatisk betegnes aktuelle tilbud uden friskhed og gyldighed.

Open Food Facts kan være nyttigt til EAN, indhold og vareidentitet, men et produktkatalog er ikke i sig selv prishistorik. Der er ikke dokumenteret ét komplet frit historisk dump for samtlige brugerens kæder.

## Implementering Claude skal udføre

1. Hent de nyeste GitHub-filer og fjern gamle hardcodede butikslister/cache. Vis `generated_at`, faktisk antal indlæste tilbud og fejlstatus. Brug kun én af de duplikerede JSON-visninger. `fetch(..., {cache: "no-store"})` hjælper, men kontrollér også service worker og localStorage.
2. Kør den historiske importer i backend og opbevar rå kildeposter separat. Historik er ikke allerede indlæst i Superkøbs brugerflade. Klassificér dagligvarer og fødevarer, og filtrér øvrige kategorier fra appens søgning uden at ødelægge rådata.
3. Opret tabeller for produkter, butiksvarer, tilbud og prisobservationer. Observationer skal tilføjes, ikke overskrives. Brug unik nøgle `(source, source_product_id, store_location, observation_date, price, quantity, unit, member_condition)` og import-run med tidspunkt, kilde og checksum. Manglende lokalitet bliver ukendt, ikke Videbæk.
4. Match helst på EAN/GTIN + variant + størrelse. Navnelighed alene er kun et forslag. Bevar kilde-ID. Slå ikke økologisk/konventionel, forskellig fedtprocent, smør/smørbar eller enkeltpakke/flerpakke sammen.
5. Normalisér g til kg og ml/cl til liter; beregn kr./kg, kr./l eller kr./stk. Bevar original pris, antal pakker, mængde, pant og medlemskrav. Ukendt mængde giver ingen pålidelig enhedspris. En prisskiftshistorik må ikke behandles som en fuld daglig tidsserie uden dokumentation.
6. Vis sammenligning med samme vare/størrelse og separat normaliseret sammenligning ved ændret størrelse. Beregn fx 30/90/365-dages udvikling kun hvor datadækning faktisk findes. Vis antal observationer, første/seneste dato og kilde. Ingen opdigtede normalpriser, gamle priser eller tilbudsrabatter.
7. Brug ABC Videbæk som fast butiksfilter. Bevar Tarm kun i særskilt data med sted. Udløbne tilbud går til historik; fremtidige tilbud vises separat. Datamangel vises tydeligt.
8. Lav løbende import med rate limits, retries, checkpoint og fejlrapport. Publicér først nyt aktuelt snapshot efter validering; behold sidste fungerende snapshot ved kildefejl. Brug `.gitignore` til `data/history/` og lokale rådump; rapportér seneste vellykkede import pr. kilde.

## Acceptkriterier

Appen viser 14 kæder med nye aktive tilbud, og afventende kæder bliver ikke skjult af gammel cache. ABC er Videbæk. Historiske priser har korrekt dato og kilde, ingen historiske rækker aktiveres som dagens tilbud, og genimport fordobler ikke observationsantal. Prisgrafen skelner faktisk observeret pris fra infereret normalpris og viser datamangler. Produkt- og mængdematching testes med samme EAN, ændret pakke, medlemstilbud og flerpakke.
