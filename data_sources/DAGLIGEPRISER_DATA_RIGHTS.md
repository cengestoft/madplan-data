# dagligepriser.dk – datarettigheder

Status opdateret 2026-10-09. Tidligere vurdering (5. oktober, "uafklaret") er erstattet af skriftlig tilladelse.

## Skriftlig tilladelse (modtaget 5. og 6. oktober 2026)

dagligepriser.dk har skriftligt givet projektejeren tilladelse til at bruge og offentliggøre den månedligt aggregerede prishistorik. Ordlyden står i `cengestoft/Opskrifter`, filen `docs/dagligepriser_tilladelse.md`.

Vilkår:
- Kun aggregerede data pr. produkt, butik og måned (antal observationer, median/gennemsnit, min og max).
- Rådata og daglige observationer må ikke offentliggøres.
- Det oprindelige dump på ca. 355 MB må aldrig ligge i Git.
- Appen skal vise en synlig kreditering med link til dagligepriser.dk ("Historiske prisdata: dagligepriser.dk").
- Tilladelsen kan trækkes tilbage, hvis vilkårene ikke overholdes. Kontakt: hi+heissepreise@leonora.app.

## Konsekvens i dette repo

- `monthly_price_history.json` må ligge offentligt, men kun som aggregat (`raw_data_included: false`, `credit` og `source_url` udfyldt, kun fødevarer).
- `data_sources/dagligepriser_manifest.json` har `redistribution_status = permitted_aggregated_only`.
- Rådump og daglige observationer forbliver lokale. Tests i `tests/test_data_integrity.py` (HistoryRights) vogter vilkårene.
- Workflows må stadig ikke bygge, committe eller publicere historik automatisk. Hver publicering kræver brugerens udtrykkelige godkendelse.

Kilder tidligere: kildekoden Herover/heissepreise er MIT. Dette dokument er ikke juridisk rådgivning.
