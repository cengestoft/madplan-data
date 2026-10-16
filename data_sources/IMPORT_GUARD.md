# Importvagt for Tilbudsugen-hentningen (fase 1)

Kode: `scripts/offer_guard.py`, brugt af `scripts/fetch_offers.py`. Tests: `tests/test_offer_guard.py`.

Pr. butik erstatter nye data kun forrige, hvis de er hentet fuldstændigt og ser rigtige ud. Ellers beholdes butikkens forrige tilbud
(kun dem, der stadig er gyldige i dag, så udløbne aldrig genaktiveres), og de andre butikker opdateres som normalt.

| Årsagskode | Betydning |
|---|---|
| `held_fetch_stopped` | hentningen stoppede (HTTP-fejl, ingen poster, for stor, forespørgselsloft) |
| `held_empty` | 0 accepterede tilbud |
| `held_incomplete` | under 98 % af de rapporterede tilbud blev set |
| `held_poor_quality` | over 25 % af de hentede poster har ødelagt navn, pris eller dato (udløbne tæller ikke) |
| `held_vanished` | over halvdelen af butikkens forrige tilbud, der STADIG ER I GYLDIGHED i dag, findes ikke længere i kilden (ved mindst 20) |
| `unavailable` | hentningen fejlede, og der findes ingen forrige data for butikken (butikken udelades, skrives ikke som tom) |

Ingen fast procentgrænse på antal: et naturligt skift mellem tilbudsuger (de gamle tilbud udløber, nye kommer) er ikke en fejl,
fordi kun forrige tilbud, der stadig gælder, sammenlignes. Genkendelse sker på id eller på (navn, pris, slutdato).

Hele kørslen blokeres (filen røres ikke, trinnet fejler), hvis halvdelen eller flere af mindst 4 butikker holdes tilbage
(`systemic_half_or_more_held`), eller hvis der slet ingen tilbud er. Filen skrives atomisk (tmp + omdøb).

Filen får pr. butik `status` (`ok`/`held`), `last_good_at`, og ved tilbageholdelse `held_reason` og `held_since`, samt et
`import_report` med fast vokabular (ingen indhold). Eksisterende felter er uændrede.
