# Privat Dropbox-import af historik (kandidat, ingen publicering)

Workflow: `.github/workflows/dropbox-history-import.yml` (kun `workflow_dispatch`; ugentlig kørsel er udkommenteret til efter godkendt test).

## Hvad den gør
1. Kører alle Python-tests.
2. Henter `latest-canonical.json` fra Dropbox med OAuth refresh-token (kun GitHub Secrets, ingen delingslinks) til `$RUNNER_TEMP/raw` uden for git, mode 0600.
3. Kontrollerer størrelse (forventet 356964273 bytes), JSON-array og Dropbox `content_hash`; ved afvigelse slettes filen og kørslen stopper.
4. Kører den eksisterende importer (`import_dagligepriser_history.py`, `verified_only`, uændret normalisering, `history_offer_identities.json`) mod en kopi i `$RUNNER_TEMP/out`. Ingen match-log skrives.
5. Sletter rådata (`if: always()`).
6. `scripts/history_import_guard.py` sammenligner før/efter og stopper ved: tom/ugyldig kandidat, ikke `verified_only`, rådata-flag, ≥12 MB, manglende kreditering af dagligepriser.dk, uventede felter i verificeringsfilen, ingen verificerede nøgler, tabt verificeret historik (nøgle eller måneder) uden dokumenteret årsag i `data_sources/history_expected_changes.json`, eller tabte registernøgler.
7. Rapport (`report.md`, `diff.json`) i jobbets summary og som artifact sammen med de aggregerede kandidatfiler (7 dages opbevaring).

Workflowet committer, pusher, merger og publicerer aldrig. En godkendt kandidat lægges ind via en separat PR.

## De 60 foreløbige godkendelser
Importeren anvender kun en menneskelig beslutning, hvis rådata dokumenterer den (`history_approval_check`). Rapporten viser: i filen / anvendt / blokeret (evidens mangler eller modsiger) / ikke set i rådata. Manglende evidens = ingen godkendelse.

## Logs er offentlige (repoet er offentligt)
Der printes kun antal og normaliserede produktnøgler (egne tilbudsdata), aldrig rådata, produktnavne fra rådata, tokens eller svarindhold fra Dropbox.

## Dokumenterede undtagelser
`data_sources/history_expected_changes.json`: `{"allowed_losses":[{"key":"<normalized_product_key>","reason":"<begrundelse>"}]}`. Poster uden begrundelse ignoreres.

## Opsætning (Casper)
Se PR-beskrivelsen: Dropbox-app (scopes `files.metadata.read`, `files.content.read`, offline), GitHub Environment `dropbox-import` med secrets `DROPBOX_APP_KEY`, `DROPBOX_APP_SECRET`, `DROPBOX_REFRESH_TOKEN`, variabel `DROPBOX_RAW_PATH` og påkrævet godkender.
