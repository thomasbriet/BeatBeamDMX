# BeatBeam + SongAnalyzer — Master Backlog

> Centrale, levende backlog voor de ontwikkeling van **SongAnalyzer** en **BeatBeam**.
> Dit bestand moet tijdens programmeerwerk actief worden geraadpleegd en bijgewerkt.

## Werkwijze voor Codex / programmeersessies

Bij iedere programmeertaak:

1. Lees dit bestand vóórdat je wijzigingen maakt.
2. Controleer of de taak al in deze backlog staat.
3. Werk uitsluitend aan onderdelen die passen binnen de vastgelegde productrichting.
4. Werk de status van relevante taken bij zodra werk aantoonbaar is afgerond.
5. Voeg nieuwe concrete vervolgpunten toe als tijdens implementatie nieuwe noodzakelijke taken ontstaan.
6. Verwijder geen productbeslissingen zonder expliciete opdracht.
7. Markeer twijfel of onderzoek als `ONDERZOEK`, niet als afgerond.
8. Houd de backlog compact: technische implementatiedetails horen primair in commits/issues/documentatie, niet in deze hoofdlijst.

### Statussen

- `TODO` — nog niet gestart
- `BEZIG` — actief in ontwikkeling
- `ONDERZOEK` — technisch of functioneel onderzoek nodig
- `GEBLOKKEERD` — kan nog niet verder
- `GEREED` — geïmplementeerd en gevalideerd
- `VERVALLEN` — bewust niet meer uitvoeren

---

# 1. Productrichting

## 1.1 SongAnalyzer

**Doel:** SongAnalyzer wordt het centrale analysebrein dat muziek zo diep mogelijk analyseert en rijke, software-onafhankelijke data produceert voor BeatBeam.

- `GEREED` Basis lokale audio-analyse bestaat.
- `TODO` Analyse-engine verder verdiepen voorbij eenvoudige phrase-labels.
- `TODO` Muzikale structuur hiërarchisch modelleren.
- `TODO` Analyse-uitvoer geschikt maken voor directe consumptie door BeatBeam.
- `TODO` Analysekwaliteit per onderdeel meetbaar maken met confidence/quality-scores.
- `TODO` Analyse zo ontwerpen dat nieuwe features later toegevoegd kunnen worden zonder bestaand formaat te breken.

## 1.2 Rekordbox

**Besluit:** Rekordbox-specifieke phrase-analyse is niet langer het primaire productdoel.

- `VERVALLEN` Rekordbox phrase-analyse verder uitbouwen als kernfunctie.
- `VERVALLEN` Eigen phrase-structuur beperken tot Rekordbox native phrase-types.
- `TODO` Bestaande veilige Rekordbox-functionaliteit behouden waar die nog nuttig is.
- `TODO` Rekordbox-koppelingen los houden van de nieuwe BeatBeam-analyse.

## 1.3 VirtualDJ

**Doel:** VirtualDJ is primair de playback-/DJ-laag.

- `VERVALLEN` Eigen SongAnalyzer/BeatBeam phrases zichtbaar proberen te maken in de VirtualDJ-waveform.
- `TODO` SongAnalyzer-analyse vanuit de VirtualDJ-workflow bereikbaar maken.
- `TODO` Analyse-status zo dicht mogelijk in VirtualDJ zichtbaar maken, voor zover de SDK/API dit ondersteunt.
- `TODO` Handmatige analyseactie voor tracks onderzoeken/implementeren.
- `TODO` Batch-analyse van geselecteerde tracks/playlists onderzoeken/implementeren.
- `TODO` Automatische analyse bij nieuwe/imported tracks onderzoeken, mits dit betrouwbaar en niet storend kan.
- `TODO` Statussen ondersteunen, minimaal: `Niet geanalyseerd`, `In wachtrij`, `Bezig`, `Klaar`, `Verouderd`, `Mislukt`.
- `TODO` Heranalyse/retry eenvoudig beschikbaar maken.
- `TODO` Een duidelijke `Prepared by BeatBeam` / vergelijkbare gereed-status toevoegen als dat binnen VirtualDJ technisch mogelijk is.

---

# 2. Diepe muziekanalyse

## 2.1 Hiërarchische segmentatie

**Doel:** niet alleen klassieke phrases herkennen, maar de muzikale structuur op meerdere niveaus beschrijven.

- `TODO` Track-level structuur bepalen.
- `TODO` Hoofdsecties detecteren.
- `TODO` Subsecties binnen hoofdsecties detecteren.
- `TODO` Micro-events binnen secties detecteren.

Mogelijke secties/events die de engine moet kunnen onderscheiden:

- Intro
- Outro
- Verse
- Pre-chorus
- Chorus
- Hook
- Bridge
- Break
- Breakdown
- Build-up
- Drop
- Post-drop
- Instrumental
- Vocal section
- Solo
- Fill
- Transition
- Tension rise
- Release
- Silence / near-silence
- Impact / hit
- Risers
- Downlifters
- Percussive fills
- Andere later toe te voegen native BeatBeam-segmenten

## 2.2 Eigenschappen per segment

Iedere gedetecteerde sectie moet waar mogelijk aanvullende eigenschappen bevatten.

- `TODO` Starttijd / eindtijd
- `TODO` Startbeat / eindbeat
- `TODO` Startbar / eindbar
- `TODO` Energy
- `TODO` Energy change / slope
- `TODO` Danceability
- `TODO` Tension
- `TODO` Brightness / spectral character
- `TODO` Bass-intensiteit
- `TODO` Percussie-intensiteit
- `TODO` Vocal presence
- `TODO` Instrumental density
- `TODO` Rhythm density
- `TODO` Harmonic density
- `TODO` Loudness
- `TODO` Dynamic contrast
- `TODO` Transition strength
- `TODO` Confidence
- `TODO` Event importance / salience

## 2.3 Muzikale events

- `TODO` Drops expliciet detecteren.
- `TODO` Build-ups expliciet detecteren.
- `TODO` Breakdowns expliciet detecteren.
- `TODO` Grote impacts detecteren.
- `TODO` Fills detecteren.
- `TODO` Risers/downlifters detecteren.
- `TODO` Bass-entry en bass-removal herkennen.
- `TODO` Percussie-entry/removal herkennen.
- `TODO` Vocal-entry/removal herkennen.
- `TODO` Sterke energie-overgangen herkennen.
- `TODO` Herhalende patronen herkennen.
- `TODO` Relaties tussen terugkerende secties herkennen.

## 2.4 Analysekwaliteit

- `TODO` Per feature confidence opslaan.
- `TODO` Per segment gecombineerde confidence berekenen.
- `TODO` Onzekere analyse expliciet markeren in plaats van geforceerd classificeren.
- `TODO` Testset samenstellen met verschillende genres en structuren.
- `TODO` Vergelijkingsweergave maken voor analyseversies.
- `TODO` Regressietests maken zodat nieuwe modellen bestaande goede detecties niet ongemerkt verslechteren.

---

# 3. BeatBeam analyseformaat

**Doel:** een eigen rijk gegevensmodel tussen SongAnalyzer en BeatBeam, onafhankelijk van Rekordbox/VirtualDJ.

- `TODO` Canoniek BeatBeam Analysis Model ontwerpen.
- `TODO` Versienummer in analyseformaat opnemen.
- `TODO` Track metadata opnemen.
- `TODO` Beatgrid/bargrid opnemen.
- `TODO` Hiërarchische segmenten opnemen.
- `TODO` Events opnemen.
- `TODO` Continuous features/timelines ondersteunen.
- `TODO` Confidence per eigenschap ondersteunen.
- `TODO` Compatibele serialisatie kiezen.
- `TODO` Migratiepad voor toekomstige analyseversies ontwerpen.
- `TODO` Cache invalidation baseren op analyseversie + audiobestand-identiteit.

---

# 4. BeatBeam Auto Show

## 4.1 Kern

**Doel:** BeatBeam vertaalt de rijke muziekanalyse automatisch naar een lichtshow die muzikaal logisch reageert.

- `TODO` Auto Show direct voeden vanuit SongAnalyzer-data.
- `TODO` Showgedrag koppelen aan sectietype.
- `TODO` Showgedrag koppelen aan energy.
- `TODO` Showgedrag koppelen aan danceability.
- `TODO` Showgedrag koppelen aan tension.
- `TODO` Overgangen laten reageren op muzikale transitions.
- `TODO` Drops en impacts duidelijk visueel accentueren.
- `TODO` Rustige secties minder druk maken.
- `TODO` Opbouwen gedurende build-ups.
- `TODO` Variatie toevoegen zodat herhaalde secties niet altijd exact dezelfde show geven.
- `TODO` Voorspelbare grenzen instellen zodat Auto Show nooit ongewenst extreem gedrag veroorzaakt.

## 4.2 Fixture-specifieke programma's

Voor iedere fixture(groep) moet afzonderlijk bepaald kunnen worden welk programma actief is.

- `TODO` Per moving head programma/effect kunnen kiezen.
- `TODO` Per bar programma/effect kunnen kiezen.
- `TODO` Programma's groeperen per fixturetype.
- `TODO` Auto Show-programmakeuze zichtbaar maken.
- `TODO` Auto Show-programmakeuze handmatig kunnen overriden.
- `TODO` Override kunnen teruggeven aan Auto Show.
- `TODO` Vastleggen of overrides tijdelijk, per sectie of persistent zijn.

---

# 5. BeatBeam UI — iPad / live bediening

**Hoofdrichting:** minder knop-heavy; de gebruiker moet in één oogopslag kunnen zien wat BeatBeam doet.

## 5.1 Live visualisatie

- `TODO` Centrale Live Show-weergave ontwerpen.
- `TODO` Zichtbaar maken welke Auto Show-acties op dit moment actief zijn.
- `TODO` Zichtbaar maken waarom een effect actief is, waar praktisch mogelijk.
- `TODO` Actieve muzieksectie tonen.
- `TODO` Komende sectie/transition tonen.
- `TODO` Energy/tension live visualiseren.
- `TODO` Status van iedere fixture/groep live tonen.

## 5.2 Geanimeerde bediening

**Doel:** animatie heeft functionele betekenis.

- `TODO` Actieve knoppen visueel animeren.
- `TODO` Pulse gebruiken voor beat-/tempo-gerelateerde actieve effecten waar passend.
- `TODO` Langzamere animatie gebruiken voor transitions/build-ups waar passend.
- `TODO` Override-status duidelijk onderscheiden van Auto Show-status.
- `TODO` Animatie subtiel genoeg houden voor duidelijk gebruik op iPad tijdens livewerk.

## 5.3 Kleurvisualisatie

- `TODO` Per fixture/groep kleurstatus visualiseren.
- `TODO` Kleurverdeling als cirkel/taartdiagram onderzoeken/implementeren.
- `TODO` Percentage per actieve kleur zichtbaar kunnen maken.
- `TODO` Dominante kleur duidelijk herkenbaar maken.
- `TODO` Live wijzigingen vloeiend tonen.
- `TODO` Ook samengestelde kleurpaletten ondersteunen.

## 5.4 Manual Override

- `TODO` Vanuit Live Show-weergave direct handmatig kunnen overriden.
- `TODO` Eén druk op een andere actie/programma moet direct effect hebben.
- `TODO` Duidelijk tonen dat Auto Show tijdelijk is overschreven.
- `TODO` Één eenvoudige actie om terug te keren naar Auto Show.
- `TODO` Bepalen hoe lang een override geldig blijft.
- `TODO` Voorkomen dat Auto Show onmiddellijk een handmatige keuze terug overschrijft.

## 5.5 Moving-head snelheid

- `TODO` Live slider toevoegen voor moving-head snelheid.
- `TODO` Auto Show-snelheid als uitgangspunt behouden.
- `TODO` Handmatige snelheidsmodifier toepassen bovenop Auto Show.
- `TODO` Zowel vertragen als versnellen ondersteunen.
- `TODO` Neutrale middenstand duidelijk tonen.
- `TODO` Visueel aangeven wanneer gebruiker afwijkt van Auto Show.
- `TODO` Modifier zo ontwerpen dat patroon/positie behouden blijft en alleen bewegingstempo verandert waar technisch mogelijk.

---

# 6. BeatBeam Show Simulator

- `TODO` Simulator bouwen waarmee een analyse zonder echte lampen kan worden afgespeeld.
- `TODO` Fixtures virtueel weergeven.
- `TODO` Kleuruitvoer visualiseren.
- `TODO` Moving-head beweging visualiseren.
- `TODO` Programma/effect per fixture tonen.
- `TODO` Auto Show-beslissingen live tonen.
- `TODO` Handmatige overrides in simulator testbaar maken.
- `TODO` Analyse-tijdlijn scrubbaar maken.
- `TODO` Simulator gebruiken voor regressietests van showlogica.

---

# 7. Analyseworkflow

## 7.1 Centrale Analysis Library

- `GEREED` Persistente AnalysisLibrary delen tussen app/bridge, inclusief playlistreconcile.
- `GEREED` Cache-hit voorkomt onnodige worker/Essentia-run.
- `GEREED` Cache-miss/stale leidt via één begrensde, single-worker centrale wachtrij tot analyse; NORMAL-playlistwerk en HIGH-livewerk zijn gededupliceerd, geprioriteerd en getest.
- `GEREED` Resultaat atomisch opslaan in bestaande cache en multi-track BeatBeam-handoff.
- `TODO` Nieuwe rijke BeatBeam-analyse in dezelfde centrale bibliotheek integreren.
- `TODO` Duidelijke stale-detectie bij nieuwe analyseversies.
- `TODO` Heranalyse per track.
- `TODO` Heranalyse per selectie.
- `TODO` Heranalyse per playlist/batch.

## 7.2 Eén-knopsworkflow

- `TODO` Eén bestand/map openen.
- `TODO` Tracks selecteren.
- `TODO` Eén actie voor volledige analyse/voorbereiding.
- `TODO` Resultaat automatisch in Analysis Library beschikbaar maken voor BeatBeam.
- `TODO` Duidelijke voortgang en foutstatus tonen.
- `TODO` Advanced-opties buiten de standaardworkflow houden.

---

# 8. Desktop/macOS productisering

- `TODO` Zelfstandig startbare macOS `.app`.
- `TODO` Vanuit Finder kunnen starten.
- `TODO` Geen Terminal nodig.
- `TODO` Geen afhankelijkheid van huidige werkmap.
- `TODO` Betrouwbare worker-locatie/resource resolving.
- `TODO` Installatieprocedure.
- `TODO` Updateprocedure.
- `TODO` Diagnose-/statusscherm.
- `TODO` Betere foutmeldingen voor ontbrekende dependencies of corrupte analyse.

---

# 9. Veiligheid en betrouwbaarheid

- `TODO` Geen DJ-performance verstoren door zware analyse op ongewenste momenten.
- `TODO` Analysejobs annuleerbaar maken.
- `GEREED` Queue/prioriteiten voor analysejobs, inclusief FIFO binnen prioriteit, live-promotie, bounded admission, failure-isolatie en graceful shutdown.
- `GEREED` VirtualDJ-playlistexport veilig reconciliëren en live deckactivatie voor BeatBeam scheiden van preanalyse, inclusief owner-PID lifecycle, recovery/resync en read-only diagnostics.
- `TODO` CPU-belasting begrenzen tijdens livegebruik.
- `TODO` Fouten per track isoleren.
- `TODO` Crash in analyseworker mag BeatBeam/VirtualDJ niet meenemen.
- `TODO` Cache writes atomisch houden.
- `TODO` Analyse-output valideren vóór BeatBeam deze gebruikt.
- `TODO` Fallbackgedrag voor tracks zonder volledige analyse.

---

# 10. Niet meer nastreven

Deze punten zijn bewust geschrapt en mogen niet zonder expliciete productbeslissing opnieuw als doel worden geïntroduceerd.

- `VERVALLEN` Eigen phrase-overlay in de VirtualDJ-waveform.
- `VERVALLEN` SongAnalyzer-phrases rechtstreeks zichtbaar maken in de native VirtualDJ waveform.
- `VERVALLEN` Nieuwe analyse-engine beperken tot Rekordbox native phrase-classificatie.
- `VERVALLEN` Rekordbox phrase-analyse als leidende structuur voor BeatBeam.

---

# 11. Eerstvolgende prioriteiten

Aanbevolen volgorde vanaf de huidige productrichting:

1. `TODO` Canoniek BeatBeam Analysis Model definiëren.
2. `TODO` Inventariseren welke diepere audiofeatures met de huidige Essentia/Python-pipeline haalbaar zijn.
3. `TODO` Nieuwe hiërarchische segmentatie ontwerpen.
4. `TODO` Drops/build-ups/breakdowns/transitions als eerste rijke events implementeren.
5. `TODO` Analyse-output koppelen aan BeatBeam Auto Show.
6. `TODO` Live BeatBeam UI herontwerpen rond visualisatie + overrides.
7. `TODO` Moving-head snelheidsmodifier toevoegen.
8. `TODO` VirtualDJ analyseworkflow/status integreren voor zover de SDK dit ondersteunt.
9. `TODO` Simulator bouwen om showlogica sneller te testen.
10. `TODO` Finder-startbare macOS `.app` en productisering afronden.

---

# 12. Beslislog

## 2026-08-19

- Besloten om Rekordbox phrase-analyse niet verder als centraal doel te gebruiken.
- SongAnalyzer wordt een diepgaande, software-onafhankelijke muziekanalyse-engine.
- BeatBeam wordt de primaire consument van de rijke analyse.
- VirtualDJ blijft primair de playback-/DJ-laag.
- Pogingen om eigen phrases in de native VirtualDJ-waveform zichtbaar te maken zijn beëindigd.
- BeatBeam UI moet veel visueler worden en minder bestaan uit losse knoppen.
- Auto Show moet live zichtbaar maken wat het systeem uitvoert.
- Handmatige overrides moeten rechtstreeks vanuit de live interface mogelijk zijn.
- Actieve bediening mag functioneel geanimeerd worden.
- Per fixture/groep moet zichtbaar zijn welke kleuren en programma's actief zijn.
- Kleurverdeling mag als cirkel/taartdiagram worden weergegeven.
- Moving-head snelheid moet live handmatig vertraagd of versneld kunnen worden ten opzichte van Auto Show.
- VirtualDJ-analyse moet bij voorkeur vanuit de VirtualDJ-workflow bereikbaar zijn, met statusweergave, batch/heranalyse en waar mogelijk automatische analyse.

---

_Last updated: 2026-08-19_
