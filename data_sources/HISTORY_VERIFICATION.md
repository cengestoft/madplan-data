# Verificeret prishistorik (kontrakt)

`monthly_price_history.json` indeholder kun månedlige aggregater for råprodukter, der er **verificeret** som samme produkt som et aktivt tilbud.
`history_verification.json` fortæller pr. aktiv fødevarenøgle, hvordan det gik:

| status | betydning |
|---|---|
| `verified` | mærke, produkttype, smag/variant, kødtype, fedtprocent, antal, størrelse og enhed stemmer. Historikken må bruges. |
| `review_required` | oplysninger mangler eller overlapper kun delvist. Må **ikke** vises som historik, før et menneske har godkendt. |
| `rejected` | modstridende oplysninger (andet mærke, anden kødtype, anden smag, anden fedtprocent, andet antal/størrelse/enhed). |
| `no_candidate` | ingen rå historik fundet for nøglen. |

Lighed i `normalized_product_key` er ikke nok, fordi nøglen er grov (fx "hakket-oksekoed-8-12").

## Appen
En prisgraf baseret på `monthly_price_history.json` må kun vises, når nøglens status i `history_verification.json` er `verified`.
Ellers vises teksten **"Ingen verificeret prishistorik"**. (I dag læser appen ikke filen; det her er kontrakten, når den gør.)

## Overlap (kvalitetsmål, ikke blokerende)
Tæller: unikke aktive fødevarenøgler med status `verified`. Nævner: alle unikke aktive fødevarenøgler (uden husholdning og dyrefoder).
Målet er 30 %, men siden Caspers beslutning 13. oktober 2026 er det et **kvalitetsmål**: de faktiske tal rapporteres altid
(i dag 97 af 1.271 = 7,6 %), og en mangel blokerer ikke publicering af korrekte tilbudsdata. Uverificerede matches tæller aldrig med.

## Blokerende integritetskrav (uændrede)
- Alle historikrækker har en nøgle med status `verified` (`verified_only`).
- Status `verified` gives kun til nøgler med faktisk historik og mindst ét verificeret råprodukt (eller dokumenteret menneskelig beslutning).
- Ingen rådata, ingen automatiske matches ved manglende eller modstridende identitet.
- Tilbud uden verificeret historik vises stadig med pris, pakning og gyldighed, men uden prisgraf.

## Dokumentation og rådata
- Offentligt: kun nøgler, tilbudsnavne (egne data), antal pr. status, metode, konfliktfelter og kontroldato.
- Privat (`data/private/`, ignoreret af git): historisk råprodukt, tilbudsprodukt, identitetsfelter og konflikter.
- Menneskelige beslutninger ligger i `history_review_decisions.json` og indeholder kun hashes (`raw_id_hash`), reviewer og dato.
  En beslutning kan løfte `review_required` til `verified`, men aldrig overstyre en hård konflikt.
