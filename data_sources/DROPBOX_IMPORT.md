# Privat Dropbox-import af historik (kandidat, ingen publicering)

Workflow: `.github/workflows/dropbox-history-import.yml` (kun `workflow_dispatch`; ugentlig kørsel er udkommenteret til efter godkendt test).

## Hvad den gør
1. Kører alle Python-tests.
2. Henter `latest-canonical.json` fra Dropbox med OAuth refresh-token (kun GitHub Secrets, ingen delingslinks) til `$RUNNER_TEMP/raw` uden for git, mode 0600.
3. Kontrollerer størrelse (forventet 356964273 bytes), JSON-array og Dropbox `content_hash`; ved afvigelse slettes filen og kørslen stopper.
4. Kører den eksisterende importer (`import_dagligepriser_history.py`, `verified_only`, uændret normalisering, `history_offer_identities.json`) mod en kopi i `$RUNNER_TEMP/out`. Ingen match-log skrives.
5. Sletter rådata (`if: always()`).
6. `scripts/history_import_guard.py` sammenligner før/efter og stopper ved: tom/ugyldig kandidat, ikke `verified_only`, rådata-flag, ≥12 MB, manglende kreditering af dagligepriser.dk, uventede felter i verificeringsfilen, ingen verificerede nøgler, tabt verificeret historik (nøgle eller måneder) uden dokumenteret årsag i `data_sources/history_expected_changes.json`, eller tabte registernøgler.
7. Rapport (`report.md`, `diff.json`) i jobbets summary. Kandidatfiler + rapport uploades KUN hvis alle trin inkl. guarden er bestået (ingen `if: always()` på upload). Ved fejl uploades højst en fast fejlrapport uden rådata, produktnavne eller hemmeligheder, og loggen viser kun "Historikimport fejlede. Ingen kandidat publiceret." (import.err vises aldrig).

Validering: streaming-tjekket ser kun start/slut (`[` … `]`); hele JSON-strukturen valideres af importeren (`json.loads`, kræver liste). Ugyldig JSON med korrekt start/slut giver stop uden kandidat (testet).

Friskhed: `history_verification.json` og historikfilen skal være genereret af denne kørsel (`generated_at` ≥ starttidspunkt, filerne slettes før import). Mangler eller er de gamle, stopper guarden.

Dropbox-sti: `/latest-canonical.json` i Dropbox App Folder (API-stier er relative til app-mappens rod). Standardværdi i koden og i workflowet; kan overstyres med variablen `DROPBOX_RAW_PATH`. Dropbox-appen skal være oprettet med adgangstypen "App folder", og filen skal ligge i app-mappen.

Workflowet committer, pusher, merger og publicerer aldrig. En godkendt kandidat lægges ind via en separat PR.

## De 60 foreløbige godkendelser
Importeren anvender kun en menneskelig beslutning, hvis rådata dokumenterer den (`history_approval_check`). Rapporten viser: i filen / anvendt / blokeret (evidens mangler eller modsiger) / ikke set i rådata. Manglende evidens = ingen godkendelse.

## Logs er offentlige (repoet er offentligt)
Der printes kun antal og normaliserede produktnøgler (egne tilbudsdata), aldrig rådata, produktnavne fra rådata, tokens eller svarindhold fra Dropbox.

## Dokumenterede undtagelser
`data_sources/history_expected_changes.json`: `{"allowed_losses":[{"key":"<normalized_product_key>","reason":"<begrundelse>"}]}`. Poster uden begrundelse ignoreres.

## Opsætning (Casper)
Se PR-beskrivelsen: Dropbox-app (scopes `files.metadata.read`, `files.content.read`, offline), GitHub Environment `dropbox-import` med secrets `DROPBOX_APP_KEY`, `DROPBOX_APP_SECRET`, `DROPBOX_REFRESH_TOKEN`, variabel `DROPBOX_RAW_PATH` og påkrævet godkender.

## Fejlfinding uden adgang til loggen
Ved fejl skriver workflowet en fast `fejlrapport.txt` (artifact `fejlrapport` + jobbets summary) med kun trinstatus (`success`/`failure`/`skipped`) for: stier, checkout, tests_foer, dropbox_hentning, import, sikkerhedstjek, tests_efter. Dropbox-fejl vises som HTTP-status plus en fast kode (fx `HTTP 409 (path/not_found)`, `HTTP 400 (invalid_grant)`), aldrig svarindhold. Loggen viser også den anvendte `Dropbox-sti`. Typiske årsager: manglende secret (`missing secret …`), udløbet/forkert refresh-token (`invalid_grant`), forkert sti i variablen `DROPBOX_RAW_PATH` (`path/not_found`), afvigende filstørrelse (`remote size … differs from expected …`).

## Download-kaldet (files/download)
`POST https://content.dropboxapi.com/2/files/download`, parametre kun i `Dropbox-API-Arg` (ASCII-JSON `{"path": "/latest-canonical.json"}`), tom body, `Content-Type: application/octet-stream` (en af de værdier Dropbox accepterer til content-endpoints). Svarer Dropbox HTTP 400, hentes den samme fil via `files/get_temporary_link` (kort levetid, maskeret i loggen, hentes uden credentials, kun `*.dropboxusercontent.com` over https). Størrelse og `content_hash` verificeres uændret. Andre fejlkoder (401/403/409/429/5xx) giver ingen fallback. Fejlbeskeder viser KUN HTTP-status og en fast, tilladt fejlkode (fx `path/not_found`; alt ukendt vises som `other`). Fritekst fra Dropbox' svar (response body) vises aldrig i logs, heller ikke maskeret eller renset.

## Fejlfinding ved HTTP 400 på files/download (2026-10-14)
Kørsel #9 fejlede med HTTP 400 på både `files/download` og `files/get_temporary_link`, mens `files/get_metadata` (samme sti, samme token) lykkedes. De præcise anmodninger er verificeret med en lokal server i `WireRequestTest` (metode, Content-Length, Content-Type, body, `Dropbox-API-Arg` som ASCII): de svarer til Dropbox' dokumentation. Årsagen er derfor ikke dokumenteret endnu; den næste kørsel viser kun faste, sikre oplysninger:
- `Dropbox-rettigheder: …` – de rettigheder (scopes) tokenet faktisk har, kun fra en fast hvidliste. Mangler `files.content.read` eller `files.metadata.read`, stopper hentningen før filanmodninger med en klar besked.
- `HTTP 400 (<kode>)` – kode fra et fast ordforråd, fx `text/bad_content_type`, `text/bad_api_arg`, `text/bad_json`, `text/missing_scope`, `text/bad_authorization`, `text/bad_path_argument`, `text/unclassified`, `empty` eller `missing_scope/files.content.read`. Svarets tekst vises aldrig.
- `Range-probe` – efter at begge downloads er fejlet: kan de første 1024 bytes hentes? (kun status, intet indhold).
Hvis tokenet mangler `files.content.read`: ret rettighederne under *Permissions* i Dropbox App Console, tryk *Submit*, og opret et NYT refresh token (eksisterende tokens får ikke nye rettigheder).
