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
Ved import anvendes en godkendelse kun, hvis `history_approval_check.documented` bekræfter samme produkt (samme særskilte ord efter fjernelse af mærke, størrelse, fedttal og generiske typeord).
Ellers forbliver produktet `review_required` (`manual_decisions_blocked` tæller dem). Godkendelserne er foreløbige, til de er kontrolleret mod den private match-log.

## Historikken bevares
`data_sources/history_offer_identities.json` husker alle tilbudsidentiteter. Verificeret historik for en nøgle slettes aldrig, fordi dens tilbud udløber;
aktuelle tilbud afgør kun overlap og hvilke grafer der er mulige (`active` pr. nøgle).

## Multipack-identiteter og videreførte afvisninger (19. okt 2026)
- Tilbuddenes `package_amount` er TOTALEN for en multipack (24 x 0,33 l = 7,92 l). Identitetsregistret gemmer derfor også `single_package_amount`/`single_package_unit` for multipacks (count > 1), så `describe()` giver samme pakkestørrelse for et fuldt tilbud og dets registeridentitet. Uden dem blev antal ganget to gange (fx 144 l i stedet for 6 l) og gav falske `pack_size`-afvisninger. Nøglerne er uændrede.
- En tidligere `rejected` nøgle, der ikke har nogen rå produkter i en ny kørsel, forbliver `rejected` med `carried_over: true` (kilde: `--previous-verification`, standard `history_verification.json`). Nye matches bedømmes som normalt. `history_import_guard.py` stopper kørslen, hvis en afvisning forsvinder uden rå produkter.
