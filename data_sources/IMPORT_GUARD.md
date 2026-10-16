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

## Tidsstyring (fase 2)
`scripts/schedule_gate.py` afgør i workflowet "Daily offers" (repoet `madplan-tilbud`), om en planlagt kørsel skal gennemføres.
GitHub-cron er UTC, så workflowet udløses kl. 06:03, 07:03 og 08:03 UTC. En planlagt kørsel gennemføres kun, hvis klokken er 8 eller 9
i København, og dagens hentning ikke allerede er sket (`generated_at` i `data/offers.json`, målt i dansk dato). Det giver præcis én hentning om
dagen ca. 08.03 dansk tid både sommer og vinter, og en reserve en time senere, hvis GitHub er forsinket. Manuel kørsel gennemføres altid.
Testet for hver dag i 2026 og 2027 samt skiftedagene 29. marts og 25. oktober 2026.
