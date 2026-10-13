# Mængde-markering (quantity_status) – regler

Registeret `offer_quantity_flags.json` er eneste kilde. Markeringen ændrer KUN `quantity_status` og `quantity_note`; priser, mængder, produktnøgler og historik røres aldrig.

## Automatisk
- `build_data_pipeline.py --write` og `promote_future_offers.py --write` anvender registeret på `current_offers.json` og `stores/*.json` **efter hver tilbudsimport og før validering/publicering**. Et nyimporteret, stadig aktivt tilbud får derfor markeringen igen.
- Udløbne tilbud markeres aldrig (heller ikke genskabt). Tilbud, der ikke længere findes, oprettes aldrig.
- Ugyldigt register eller uløst problem ⇒ publicering stoppes ("Publication blocked").
- `python scripts/apply_quantity_flags.py --check` (kører i CI) fejler, hvis markeringer ikke svarer til registeret.

## Fjern markering (kun med kildebekræftelse)
1. Sæt flagets `status` til `confirmed` og udfyld `confirmed_by`, `confirmed_on`, `confirmed_source`, `confirmed_quantity` (package_count, single_package_amount, package_amount, package_unit).
2. Ret samtidig tilbuddets samlede mængde, enhedspris, volume_l, single_package_amount og produktnøgle, så de svarer til `confirmed_quantity`.
3. Passer tilbuddets mængder ikke præcist til `confirmed_quantity`, nægter pipelinen at publicere. Markeringen fjernes først, når alt stemmer.
4. Ingen gæt: uden original kilde forbliver status `unverified`.
