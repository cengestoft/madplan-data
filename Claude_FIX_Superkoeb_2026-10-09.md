# Opgave til Claude – Superkøb / Indkøbs App (9. oktober 2026)

## STOPREGEL: INGEN UDRULNING
Arbejd udelukkende på separat branch og åbn PR til kontrol. **Ingen merge, direkte push til main, deploy, publicering eller aktivering af skrivende workflows uden brugerens udtrykkelige godkendelse.** ChatGPT kontrollerer PR, og brugeren godkender før eventuel udrulning.

## Eksisterende fejl fundet ved kontrol
1. **Udløbne tilbud:** current_offers.json har udløbne poster. Filtrér efter danske datoer; future i next_week_offers.json. Bevar rige stores/*.json. Skeln legitimt udløb fra datatab i importvagten.
2. **Falsk PASS:** acceptance_report.json siger PASS for ingen udløbne, men nævner 362 udløbne pr. 8/10. Ret selve testlogikken, ikke kun rapporten.
3. **Manifest:** price_history.json viser record_count=4958, mens monthly_price_history.json-rapporten viser ca. 48057. Genberegn fra faktiske data, afstem alle metadata.
4. **Nøgler:** Genbrug scripts/product_normalization.py konsekvent for aktuelle og historiske poster; ingen frontend-aliaser.
5. **Supertilbud:** Genberegn super_deals_current.json og check_super_deal_history.py. Kræv >=3 forskellige historikmåneder for graf; ellers graph_allowed=false og kvalitetsfejl.
6. **Historik:** Aggregeret per normalized_product_key + butik + måned; under 12 MiB. Uafklaret datalicens til dagligepriser.dk må ikke omgås.
7. **Workflow:** .github/workflows/rebuild-monthly-history.yml har contents:write og automatisk git push til main. Deaktivér alle automatisk skrivende/publicerende trin indtil særskilt eksplicit godkendelse. CI på PR må kun validere.

## Nye fejl meldt af Claude
8. **next_week_offers.json schema:** Bruger package_size i stedet for package_amount og member_required i stedet for member_only. Standardisér til dokumenteret kanonisk schema, og opdater læsere/tests. Bevar alle værdier. organic=null på 18 poster skal forblive ukendt, ikke gættes.
9. **Slutdato:** 12 af 18 fremtidige tilbud (Lidl) har valid_to=null. Find verificerbar kilde for hver slutdato. Gæt ikke; hvis ukendt, flag usikkerhed og undlad at behandle dem som ubegrænset gyldige. Sørg for korrekt udløbslogik i app.
10. **Økologi:** current_offers.json mangler organic. Tilføj boolean når dokumenteret, ellers null; undlad at sætte false som standard. Appens eco=false må ikke tolkes som verificeret ikke-økologisk.
11. **Bilka og 365discount:** Claude fandt kun 6 gyldige Bilka- og 5 gyldige 365discount-tilbud 9/10. Find nyere dokumenterede tilbud, genimportér med korrekte gyldighedsdatoer og verificer antal. Brugsen missing_or_pending vs SuperBrugsen 477: afklar særskilt kæde, ikke sammenbland.
12. **6000 tegn i app:** Implementér prioriteret, pagineret eller kategoriseret feed i stedet for at afskære Netto ved 128/395 og Lidl ved 123/576. Sæt food_relevance deterministisk hvor dokumenteret; ikke-fødevarer må ikke fejlagtigt klassificeres som mad.
13. **Status og sikkerhed:** import_status skal afstemmes mod faktiske aktive poster, bevar current_offers.previous.json, blokér tom import, reelt datatab og hårde fejl. Beskriv hvad der faktisk er importeret kontra afvist.

## Claudes appændringer – ikke gentag
18 nye Lidl-prisrækker fra 11./15. oktober, tilbudstekster for Bilka, Brugsen, Netto, 365discount, Lidl og 6 uændrede opskrifter. 1071 eksisterende identiske prisrækker blev ikke rørt.

## Leverance
- Branch + PR-link, fil-for-fil diff og testresultater.
- Antal gyldige/kommende/udløbne tilbud pr. kæde, manglende felter, datakvalitetsfejl og historikdækning.
- Dokumentér at ingen workflow eller handling kan skrive til main før godkendelse.
- Ingen gættede priser, datoer, pakningsstørrelser eller økologiflag.
- Stop efter PR og vent på ChatGPT-kontrol og brugerens udtrykkelige godkendelse.
