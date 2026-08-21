# BeatBeam + SongAnalyzer — Master Roadmap

> Centrale, levende product- en ontwikkelroadmap voor **SongAnalyzer** en **BeatBeam**.
> Dit bestand moet tijdens programmeerwerk actief worden geraadpleegd en bijgewerkt.

## Werkwijze voor Codex / programmeersessies

Bij iedere programmeertaak:

1. Lees dit bestand vóórdat je wijzigingen maakt.
2. Controleer of de taak al in deze roadmap staat.
3. Werk uitsluitend aan onderdelen die passen binnen de vastgelegde productrichting.
4. Werk de status van relevante taken bij zodra werk aantoonbaar is afgerond.
5. Voeg nieuwe concrete vervolgpunten toe als tijdens implementatie nieuwe noodzakelijke taken ontstaan.
6. Verwijder geen productbeslissingen zonder expliciete opdracht.
7. Markeer twijfel of onderzoek als `ONDERZOEK`, niet als afgerond.
8. Houd de roadmap compact: technische implementatiedetails horen primair in commits/issues/documentatie, niet in deze hoofdlijst.

### Statussen

- `TODO` — nog niet gestart
- `BEZIG` — actief in ontwikkeling
- `ONDERZOEK` — technisch of functioneel onderzoek nodig
- `GEBLOKKEERD` — kan nog niet verder
- `GEREED` — geïmplementeerd en gevalideerd
- `VERVALLEN` — bewust niet meer uitvoeren

---

# M22A — Actuele status

`GEREED` — volledige echte VirtualDJ → SongAnalyzer → bridge → BeatBeam runtime-PASS is handmatig bevestigd en de eindvalidatie is groen.

De PASS omvat phrase boundary, seek, normale NOW/Auto Show, rich current, energy modifier, uncached live track met HIGH-prioriteit, pending/stale-data-safety, exacte Track A/Track B matching, VirtualDJ stop/restart, automatische reconnect en live transport zonder handmatige Connect-knop.

De eerdere Python 3.14 `site-packages`-reproduceerbaarheidskwestie in `build_native_app.sh` is opgelost. De route ontdekt nu de werkelijke venv-dependencies, weigert ABI-onveilige native extensies bij een afwijkende Python-minorversie en bouwt de Beta-bundle zelfstandig inclusief backend-smoke en strict ad-hoc signing. Dit is geen M22A-productfailure.

---

# M23A — Rich Musical Events voor BeatBeam

`BEZIG` — backward-compatible uitbreiding van het canonical rich-analysiscontract met een conservatieve eerste eventset: BUILD, DROP, CHORUS, BREAKDOWN en TRANSITION. Native phrase-semantiek is de primaire eventbron; eventconfidence is type-specifiek en los van boundaryconfidence. De bestaande cache is breed gekarakteriseerd; menselijke muzikale runtimevalidatie blijft nodig. Scope: bar-alignment waar beschikbaar, current/next-eventprojectie en read-only BeatBeam Debug-zichtbaarheid. Smart Hot Cues en een uitgebreide event-driven Auto Show blijven toekomstig.

De phrase-quality-pass vond een systematische early-Outro-zwakte. SongAnalyzer heeft nu een conservatieve rescue voor aantoonbaar ondergesegmenteerde lange segmenten en positionele/sequentiële Outro-validatie. De eerste officiële heranalyse van de runtime-testtrack is technisch groen; menselijke muzikale runtimeacceptatie blijft open.

Menselijke runtimeacceptatie identificeerde daarnaast dat scalar recurrence een duidelijke Chorus binnen een lang Mid-segment kon missen. SongAnalyzer bevat nu bar-aligned section similarity met niet-lokale 4/8/16-bar herhalingsparen, interne energie/onset/spectral-contourvergelijking en conservatieve herhaalde-sectiestart-evidence voor segmentation en native Chorus-classificatie. M23A blijft `BEZIG`: de bijgewerkte runtime vereist opnieuw menselijke muzikale acceptatie.

De vervolgpass voegt compacte repeat-pairs, repeat-end- en membership-exit-evidence toe. Daarmee kan een vloeiende structurele overgang met een aantoonbare profielwissel ook zonder lokale novelty-piek worden gesplitst; de diagnose- en show-readinessgegevens tonen nu tevens bounded repeat-, cache-status- en failure-reasoninformatie. M23A blijft `BEZIG`: de definitieve v11-analyseroute moet nog handmatig muzikaal worden gevalideerd.

De v12-quality-pass corrigeert vervolgens een dominante vaste Verse-family-prior: reeds geaccepteerde repeat-pairs worden begrensd samengevoegd tot section-families met overlap per segment en doorlopende Chorus-/Verse-evidence. Dit maakt de rolkeuze family-bewust zonder `repeat = Chorus` te maken of een tweede similarity-engine toe te voegen. De gerichte stale-route voor Midnight Sun en New Religion is technisch groen; menselijke muzikale v12-acceptatie blijft open. M23A blijft `BEZIG`.

De v13-semantic-pass maakt de canonical section role los van de legacy Verse-nummers, voegt PreChorus als optionele role toe, consolideert veilige aangrenzende Verse-fragmenten en projecteert sterke late Chorus-family-occurrences proportioneel. De gerichte v13-route is technisch groen; menselijke muzikale v13-acceptatie blijft open. M23A blijft `BEZIG`.

V14 onderscheidt repeat-family-membership van canonical role activation en voegt een begrensde multi-chunk PreChorus-trajectory-pass toe. De pass hergebruikt bestaande bar-, boundary-, contour- en family-evidence; family-entry is niet langer zelfstandig bewijs voor directe Chorus-role-activatie. Midnight Sun en New Religion blijven de gerichte menselijke regressietracks; v14-acceptatie blijft open.

## M22A — Performancebaseline

- Cold analysis: circa 6,212 s.
- Rhythm: circa 4,082 s.
- Persistente AnalysisLibrary-cache-hit: circa 7 ms.
- Atomische rich handoff/projectie: circa 12–33 ms.
- BeatBeam fixture/projectie: sub-millisecond.

Er is geen Essentia-optimalisatie uitgevoerd. Cold analysis is relatief zwaar, maar playlist-preanalyse, cache-hit en live-consumptie zijn voldoende snel. Performance-optimalisatie blijft meetgedreven.

## M22A — Canoniek rich-analysiscontract

Schema v2 bevat optioneel `rich_analysis` per track/segment, met waar beschikbaar model/source, duration, confidence, beat- en bar-timing/context, segmentindex, start/einde, semantic/native label, `level = phrase` en energy.

Schema v1 blijft backward-compatible leesbaar. Rich analysis vereist schema v2.

De eerste rich field die BeatBeam daadwerkelijk gebruikt is `PhraseNativeClassificationFeatures.Energy` met semantiek `segment-normalized-rms-z-score`. De bestaande Auto Show-modifier is `clamp(energy_z_score × 0,04, -0,08, +0,08)`. Er is geen pseudo-energyalgoritme toegevoegd; phrase/section-logica, fixture bounds en strobe safety blijven leidend.

## M22A — V1 → V2 en activeTrack-safety

- Een bestaand v1-handoffdocument promoveert bij een rich-analysis-write atomisch naar v2.
- Bestaande tracks en legacy phrase/structuredata blijven behouden.
- Identity-only `activeTrack` blijft behouden.
- Een v1-document zonder rich write mag v1 blijven; cache-hit blijft cache-hit.
- Exact canonical filepath matching, generation-safety en de statussen `ready/pending/unavailable` zijn actief.
- Pending of mismatch projecteert nooit rich-data van de vorige track.
- Een persistent ready `activeTrack` mag tijdelijk de ontbrekende live `track_path` aanvullen; zodra een live pad aanwezig is, blijft exacte matching verplicht.

## M22A — Automatische VirtualDJ-activatie

Runtime bewezen: lifecycle poller, plugin/left/right deckselectors, deck candidates, playing, filepath, selected deck, selection reason, activate/deactivate en echte bridge response.

Voor de gecachte track `Calvin Harris, Clementine Douglas - Blessings.flac`: `VirtualDJ deck 1 → juiste filepath → playing → selected deck 1 → activate → bridge accepted → cache hit/current → activeTrack ready → generation 1`.

Normaal gebruik vereist geen handmatige Connect-knop; de integratie functioneert automatisch.

## M22A — Realtime VirtualDJ-transport

De actuele route is: `VirtualDJ native plugin → bridge transport → begrensde in-memory transport snapshot → BeatBeam transportSnapshot → bestaande PlaybackClock → bestaande NOW / Auto Show`.

Cadans: native circa 200 ms / 5 Hz, BeatBeam maximaal circa 10 Hz read, met de bestaande clock/interpolatie. De transportfeed doet geen audio-callbackwerk, zware analyse, AnalysisLibrary-lookup, handoff-write, generation bump of filesystem-polling.

Transportbron en structuurbron blijven onafhankelijk: transport `Auto / OSC / Tap`; structuurbron `Legacy / SongAnalyzer`. `Auto` kiest VirtualDJ automatisch bij geldige live state, valt veilig terug bij verdwijnen en herstelt automatisch bij terugkeer.

## M22A — Gedeeltelijke end-to-end runtime-PASS

Bewezen met `Calvin Harris, Clementine Douglas - Blessings.flac`:

- Live/VirtualDJ: `virtualdj`, bridge connected, deck 1, exacte track, playing ja, positie circa 9684 ms, positie-leeftijd circa 245 ms, advancing.
- Status ready, generation 1.
- Analyse: schema v2, model `PhraseAnalysisResult`, segment `Intro 1`, energy z-score `-1,12`, modifier `-0,04`, confidence `39`.
- Handoff: exact, `available_current`, rich analysis ja, rich current ja, source `song_analyzer`, geen fallback.
- Queue: 0 NORMAL, 0 HIGH, running 0.

Dit bewijst de keten VirtualDJ playback position → activeTrack → schema-v2 rich analysis → current segment → energy → BeatBeam Auto Show-modifier. M22A als geheel blijft `BEZIG`.

## M22A — Debug-richting

BeatBeam heeft een afzonderlijke native Debug-laag: globale knop, apart niet-modaal verplaatsbaar/resizable/sluitbaar macOS-venster, singleton/focusgedrag en `BEATBEAM_DEBUG_UI=0` als centrale hide-flag. Debug is uitsluitend observability; normale functionaliteit mag ervan niet afhankelijk zijn.

Huidige secties zijn Live / VirtualDJ, Analyse, Queue / Cache / Playlist, Handoff / BeatBeam, Native VDJ Plugin en Bridge Control. De laag toont onder meer deck, track, playing, positie/leeftijd, status/generatie, rich current, energy/modifier/confidence, queue/cache/playlist, selectors/candidates, selectie, IPC, bridge-mutaties en fallback reason. Nieuwe technische diagnose hoort waar redelijk in deze laag terecht te komen, zonder secrets of onbeperkte dumps.

## M22A — Relevante runtime-lessons

Opgelost: stale Python-backend in de Beta-bundle; onvoldoende native deckcandidate-resolutie; bounded native deckselection-telemetry; v1/rich-analysis schemafout; activeTrack te vroeg ready; persistent activeTrack genegeerd zonder live pad; ontbrekende live VirtualDJ-positie voor PlaybackClock/NOW; en de foutieve `track_unavailable`-fallback wanneer alleen positie of current segment ontbrak.

## M22A — Nog open voor volledige runtime-PASS

1. Segmentgrens: positie, segment, energy en modifier moeten zonder refresh wisselen.
2. Seek: positie, beat/bar/phrase en rich current moeten direct volgen zonder oude data.
3. Normale NOW-hoofdinterface: deck, track, positie, BPM, beat, bar, phrase en next; Auto Show mag niet op Waiting blijven door ontbrekende transportfeed.
4. Ongecacheerde Track B: pending/HIGH, geen Track A-rich-data, daarna ready met eigen NOW/rich current/energy/modifier.
5. VirtualDJ stop/restart: veilige waiting/fallback en automatische reconnect zonder Connect-knop.
6. Perceptuele beoordeling van de energy modifier; dit blokkeert de technische M22A-status niet zolang modifier, determinisme en safety bounds aantoonbaar blijven. Tuning van schaalfactor 0,04 wordt apart gepland.

## M22A — Toekomstige rich-analysisuitbreiding

Behoud hetzelfde canonical rich-analysiscontract voor hiërarchische segmentatie, events, builds, drops, breakdowns, transitions, tension, transition strength, novelty en rijkere confidence/quality. Ontwikkel geen parallel analysecontract.

Essentia-optimalisatie zonder meting, een volledig nieuwe hiërarchische analyzer/eventdetector, VirtualDJ-waveform overlays, verplichte Connect, fixture-redesign en een volledige Auto Show-rewrite blijven buiten de huidige M22A-scope.

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

1. `GEREED` M22A: Canoniek BeatBeam Analysis Model en eerste begrensde Auto Show-consument, inclusief echte VirtualDJ-liveketen.
2. `TODO` Volgende toekomstige richting: Rich Musical Events voor BeatBeam — build, drop, chorus, breakdown, transition, confidence en bar alignment.
3. `TODO` Inventariseren welke diepere audiofeatures met de huidige Essentia/Python-pipeline haalbaar zijn.
4. `TODO` Nieuwe hiërarchische segmentatie ontwerpen.
5. `TODO` Analyse-output verder koppelen aan BeatBeam Auto Show.
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

# 13. Smart Hot Cues / DJ Preparation voor VirtualDJ

`TODO` — toekomstige VirtualDJ-richting, na of naast de fundamenten voor rijke
analyse. Dit is geen uitbreiding van de huidige M22A-runtimeacceptatie.

VirtualDJ is het enige actieve DJ-doel. SongAnalyzer blijft de analyse- en
preparation-engine, VirtualDJ de playback-/DJ-interface en BeatBeam de live
lighting/show-engine.

## 13.1 Semantische cue-basis

- `A = MIX IN`: phrasegrenzen, maat/downbeat, intro, bruikbaar ritmisch
  materiaal, energie en ruimte vóór het doel; vocals later alleen wanneer die
  betrouwbaar zijn.
- `B = MAIN`: hoofd- of impactmoment.
- `C = BREAK`: breakdown/break.
- `D = MIX OUT`: outro met phrase/maat/downbeats, laatste chorus/drop,
  afnemende energie, overgang en mixruimte.

Chorus, drop, build-up, breakdown, transitie en event-hiërarchie kunnen deze
basis later verfijnen.

## 13.2 Smart countdowns en cueplan

Rond drops, chorussen, sterke transities en andere betrouwbare events kan een
praktische countdown worden gepland, conceptueel bijvoorbeeld `16 / 12 / 8 / 4 /
target` maten. De planner gebruikt alleen intervallen die passen bij
beschikbare lengte, phrase/downbeat, intro/outro, pickup, eerdere secties,
tracklengte, bestaande cues, slots en confidence. Exacte maat- en
downbeatplaatsing is vereist: dit is een muzikale mixhulp, geen overvolle
cue-lijst.

De prioriteit is deterministisch: eerst MIX IN, MAIN, BREAK en MIX OUT; daarna
drop-/chorus-countdowns en event-cues. Dubbelen, lage-confidence events, cues
buiten een zinvolle mixcontext en onnodige overload worden weggelaten. Bij
beperkte slots blijven de belangrijkste cues behouden. Het conceptuele model
bevat rol, doel-event, timestamp, beat/maat, phrasecontext,
countdown-afstand-in-maten, confidence en prioriteit. Rollen zijn onder meer
`MIX_IN`, `MAIN`, `BREAK`, `MIX_OUT`, `DROP_COUNTDOWN`, `CHORUS_COUNTDOWN`,
`DROP` en `CHORUS`; dit legt nog geen implementatie vast.

## 13.3 Canonieke bron en fasen

Smart Hot Cues gebruikt hetzelfde canonical rich-analysis-contract als BeatBeam:
phrase-/segmentgrenzen, maten/downbeats, energie/confidence, hiërarchie,
builds, drops, chorussen, breakdowns, transities, sterkte en toekomstige
events. Er komt geen parallel model.

1. **Fase 1:** betrouwbare maten, downbeats, phrases en semantische segmentatie;
   A/B/C/D; eenvoudige 4-maten-countdowns rond betrouwbare doelen.
2. **Fase 2:** rijkere chorus-, drop-, build-, breakdown-, transitie- en
   hiërarchische events met confidence.
3. **Fase 3:** prioritering verfijnen op basis van DJ-tests en mixkwaliteit.

Fase-2-features worden niet kunstmatig naar voren gehaald.

## 13.4 VirtualDJ-workflow, cache en veiligheid

De beoogde keten is: playlist → SongAnalyzer-preanalyse → canonical rich
analysis → Smart Hot Cue Plan → beschikbaar voor VirtualDJ → DJ laadt track →
cues zijn bruikbaar. Dit sluit aan op M21A-playlist-preanalyse en minimaliseert
handmatige voorbereiding.

Het cueplan wordt uit persistente analyse opgebouwd of hergebruikt. Een cache-hit
start geen Essentia-heranalyse; ontbrekende of stale `AnalysisVersion` volgt de
normale analyseflow. Onzekere cues worden weggelaten, event-cues vereisen
voldoende confidence en dezelfde input levert altijd hetzelfde plan. Geavanceerde
handmatige correctie is later optioneel, niet de eerste vereiste.

Er komen geen custom waveform-overlays, native VirtualDJ-waveform-hacks of
reverse-engineering. Hot Cues zijn DJ-preparation, navigatie en mixhulp;
BeatBeam gebruikt dezelfde events voor onafhankelijke showbeslissingen. Geen
van beide systemen krijgt een verborgen afhankelijkheid van het andere.

## 13.5 Toekomstige acceptatiecriteria

- MIX IN en MIX OUT zijn muzikaal bruikbaar; MAIN en BREAK zijn betekenisvol.
- Beat- en maatplaatsing is exact wanneer de analyse betrouwbaar is.
- Countdowns rond belangrijke events gebruiken passende 4-maten-intervallen en
  vermijden dubbelen.
- Deterministische prioriteit en slotbeperking bewaren de belangrijkste cues.
- Lagere confidence leidt veilig tot minder cues, niet tot verzonnen precisie.
- Cache-hits starten geen nieuwe zware analyse; gelijke input levert gelijk plan.
- De VirtualDJ-workflow vereist zo weinig mogelijk handmatige voorbereiding.

_Last updated: 2026-08-21_
