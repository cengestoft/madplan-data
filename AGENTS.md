# Fælles AI-arbejdsregler — madplan-data

Dette dokument er den fælles kilde til arbejdsregler for ChatGPT, Claude og andre AI-assistenter, der arbejder i dette repository. Gælder kun dette repository. Læs README.md og relevante eksisterende dokumenter og tests før ændringer. Eksisterende dokumentation og faktiske filer har forrang ved tekniske detaljer; stop og rapportér modstrid.

## Samarbejde og sandhedskilder
- GitHub-repositoryet og dets aktuelle filer er sandhedskilden for kode og versionsstyrede data. Tidligere chats og AI-hukommelse er ikke bevis for den aktuelle drift.
- Verificér aktuelle branches, commits, workflows, filstier og dataskemaer før konklusioner. Gæt aldrig manglende funktioner eller data.
- ChatGPT og Claude deler ikke automatisk samtalehistorik eller hukommelse. Referér til konkrete filer, PR-numre og commits i overdragelser.
- Svar på dansk til brugeren. Markér klart: verificeret, antaget, ikke fundet og kræver godkendelse.

## Godkendelse og sikkerhed
- Læsning, analyse og forslag er tilladt. Udfør ikke merge, deploy, publicering, aktivering af workflows, ændring af cron, ændring af produktionsdata eller ændring/sletning af eksisterende priser uden brugerens udtrykkelige godkendelse til den konkrete handling.
- Særligt: ændr ikke data i Cloudflare (appens lagring er en Durable Object, ikke D1) eller relaterede repositories som bivirkning.
- Kodeændringer skal som udgangspunkt foreslås i særskilt branch og draft PR; aldrig direkte på main uden udtrykkelig godkendelse.
- Udfør ikke sletning, overskrivning, force-push eller migration uden særskilt godkendelse.
- Beskyt hemmeligheder: aldrig tokens, adgangskoder, private URL-nøgler eller persondata i Git, PR-beskrivelser, logs eller AI-overdragelser. Henvis til hemmelighedsnavne, ikke værdier.
- Ved brugerkrævet godkendelse: afslut med et tydeligt afsnit 'GODKENDELSE' med nøjagtigt hvad der ændres, og hvad der ikke ændres.

## Datakvalitet
- Opfind aldrig varepris, pakningsstørrelse, kilde, gyldighedsperiode eller tilbud. Bevar null/uvist, hvor dokumentation mangler.
- Kontroller tilbuddenes gyldighedsdato, kilde, alder og interne konsistens før anvendelse. Skeln mellem datafiler til appen og interne snapshots.
- Referencepriser må ikke ændres uden eksplicit godkendelse. Bevar historiske målinger og dokumentér kilder.
- Respektér eksisterende brugerregler om butikker og særlige tilbud; kontrollér gældende implementering før nye regler tilføjes.

## Arbejdsgang
1. Undersøg eksisterende kode, README, tests og seneste relevante PR'er.
2. Fremlæg præcist problem, forslag, berørte filer, risici og nødvendige tests.
3. Lav kun aftalte ændringer på en separat branch/draft PR.
4. Kør relevante tests, dokumentér resultatet og angiv eventuelle ikke-kørte kontroller.
5. Ingen merge eller produktionsudrulning uden brugerens udtrykkelige ja.
6. Ved overdragelse mellem AI'er: angiv repository, branch/commit/PR, verificerede fund, åbne spørgsmål, næste foreslåede handling og eventuel godkendelse.

## Særligt for dette repository
- Dette repository indeholder data- og kvalitetskontrol til madplan-/indkøbsflowet; det er ikke nødvendigvis selve webappen.
- Arbejde i andre repositories kræver kontrol af deres egne regler, struktur og aktuelle status. Disse regler overføres ikke automatisk til andre repositories.
