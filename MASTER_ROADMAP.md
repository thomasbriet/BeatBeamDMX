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

V15 veralgemeniseert canonical family-/sequence-role-intelligence naar High, Mid en Low. De native High `Up`/`Down`-labels zijn voortaan evidence en geen harde canonical Verse/Bridge-mapping: lokale native-scorecompetitie, repeat/contour, arrival, salience en sequence-context bepalen de canonical rol. Een brede family mag meerdere canonical rollen bevatten; dit bewaart onder meer New Religion Verse/Chorus en voorkomt dat High-herhaling automatisch Chorus wordt. De gerichte v15-reanalyse herstelt Magnetic naar Verse vanaf 00:09.258, Chorus op 00:38.797 en 01:52.645, en twee Outro-occurrences vanaf 02:36.954 en 02:51.723. De menselijke v15-acceptatie voor Magnetic blijft open; de ontbrekende High raw boundaries rond circa 00:35, 01:49 en 02:22 blijven bewust een afzonderlijke boundary-quality-pass.

V16 vult die drie Magnetic-gaten met een begrensde structural/context-route, zonder de normale noveltyselectie te verlagen. Twee korte, grid-aligned PreChorus-aanlopen blijven semantic trajectories omdat een raw split hun native classifiervenster zou verstoren; de ondersteunde family-exit op 02:22.184 is een raw boundary. Bounded source/route/combined-evidence diagnostics blijven in het canonical contract beschikbaar. De V15 Verse-/Chorus-/Outro-posities en de Midnight Sun-, New Religion- en Free Your Mind-regressies blijven technisch behouden. Menselijke V16-audioacceptatie staat nog open; M23A blijft `BEZIG`.

De V16-human check bevestigt de Magnetic Bridge-boundary op 02:22.184, maar canonical semantics classificeerde het nieuwe deel nog als Verse. V17 verfijnt daarom uitsluitend de canonical Bridge-role: een family-exit is aanvullende evidence en promoveert alleen met afgeronde main-cycle-context en een structurele resolutie naar Outro of terugkerend Chorus. Menselijke V17-acceptatie blijft open; M23A blijft `BEZIG`.

---

# M24A — ArrangementProfile-architectuur en shadow-calibratie

`BEZIG` — De onafhankelijke High/Mid/Low-onafhankelijke analysearchitectuur is
uitgebouwd tot een volledige, menselijke calibratie-infrastructuur. Baseline:
`analysis_version = m14-v5`, `phrase_analysis_version = phrase-analysis-v17`;
M23A blijft `BEZIG` en v17 blijft veilige fallback.

M24A-1/M24A-2 vormen de veilige foundation: nullable shadow-profielen en
additive, in-memory pre-native `RawSectionObservations`, zonder nieuwe
segmentation-engine, thresholds, cache/version bump of canonical wijziging.

`GEREED` M24A-3 — `SectionCharacterProfileShadow` projecteert uitsluitend uit
raw observations: recurrence uit `StrongestSimilarity`, family salience uit
`Coverage`, entry/exit contrast uit boundary scores, build momentum uitsluitend
bij `StructuralRoute = trajectory` en structural novelty uit entry
`Boundary.Novelty`. RelativeEnergy, VocalEvidence en DropImpact blijven
bewust unknown; confidence is nog niet gekalibreerd. Geen High/Mid/Low-, native-,
canonical-role- of Rich Musical Event-input.

`GEREED` M24A-4 — Additieve, optionele `shadow_analysis` in handoff schema v2
maakt shadowdata zichtbaar in BeatBeam Debug. Shadow blijft diagnostics-only,
niet persistent in AnalysisLibrary, niet cachebepalend en niet gebruikt door
canonical analyse, Rich Musical Events of Auto Show. AnalysisHash-safety blijft
actief.

`GEREED` M24A-4A — De expliciete Debugactie `Actieve track heranalyseren` voert
een HIGH force-job uit op de exact gevalideerde actieve path/deck, met normale
atomic canonical save en ephemeral shadowpublicatie naar de actieve handoff.
Completion geeft verse snapshot en shadowprojectie veilig door; normale
cache-hit, failure-safety en productie-isolatie blijven intact. De menselijke
runtimeketen eindigt op `completed` zonder failure.

`GEREED` M24A-4B — BeatBeam Debug heeft lokaal persistent inklapbare groepen
voor live, canonical, rich events, shadow, queue/cache/playlist, failures,
handoff en legacy/native diagnostics. Shadow toont de actuele observation plus
de volledige actieve shadowstructuur; The Bausa - Magnetic bevat 9 observations
in tijdvolgorde. Dit is observability-only.

`GEREED` M24A-5A — menselijke runtime-PASS. `StructuralNovelty` is semantisch
gecorrigeerd naar `BoundaryNovelty`, met exact dezelfde
`EntryBoundary.Novelty`-waarde. Pre-native structural/context-diagnostics zijn
additief en shadow-only beschikbaar: `StructuralContextChange`,
`MembershipExitStrength`, `RepeatedSectionEnd`, `RecurrenceChange`,
`StructuralRoute`, `StructuralEvidence` en `StructuralTargetBar`. `BarCount`
wordt uit SongAnalyzer doorgegeven en BeatBeam toont bijvoorbeeld
`bars 1–5 · 5 bars`, zonder dubbele barrange. Analyzerformules, boundaries en
productieconsumptie zijn niet gewijzigd.

`GEREED` M24A-5B — technische en menselijke runtime-PASS. `RelativeEnergy` is
het gemiddelde van de bestaande trackrelatieve P10–P90 beat-RMS-normalisatie,
bounded `[0,1]`, zonder classifier of threshold en met confidence 0. Bestaande
`EnergyRise` is als signed raw diagnostic zichtbaar (laatste sectiederde minus
eerste sectiederde `normalizedRms`) en is geen `BuildMomentum`. Voor Entry en
Exit zijn waar beschikbaar `EnergyDelta`, `OnsetDelta` en `SilenceDelta`
toegevoegd als onbegrensde post-minus-pre diagnostics; de bestaande absolute
`EnergyChange`, `OnsetChange` en `SilenceChange` blijven ongewijzigd. `HarmonicDelta`
is niet toegevoegd wegens ontbrekende eenduidige pre/post-producer.

Vier-track shadowcalibratie op The Bausa — Magnetic, Prospa/Cloonee — Free Your
Mind, Avicii — Levels en Calling (Extended Club Mix) bevestigt vijf onafhankelijke
informatielagen:

1. `Arrangement identity`: `RecurrenceStrength`, `FamilySalience`.
2. `Local transition magnitude`: `EntryContrast`, `ExitContrast`, `BoundaryNovelty`.
3. `Transition direction`: `EnergyDelta`, `OnsetDelta`, `SilenceDelta`.
4. `State`: `RelativeEnergy`.
5. `Structural departure/context`: `StructuralContextChange`,
   `MembershipExitStrength`, `RepeatedSectionEnd`, `RecurrenceChange`,
   `StructuralRoute`, `StructuralEvidence`.

Recurrence, salience en boundary magnitude bepalen niet zelfstandig eventtype
of event importance. Upward en downward transitions vereisen signed evidence;
structural departure kan bestaan zonder grote acoustic boundary. `EnergyRise` is
trajectory-evidence, maar niet gelijk aan momentum: toekomstige momentum kan
zowel rising preparation als release/tension omvatten. `BuildMomentum`,
`VocalEvidence` en `DropImpact` blijven unknown; `ArrivalImpact` is nog niet
geïmplementeerd. Het generieke `ArrivalImpact`-concept blijft onderzoek, zonder
formule of threshold; recurrence/salience zijn context, geen impactscore.

De VirtualDJ lyrics/VocalEvidence-audit vond geen aantoonbare lokale lyric-
timeline: `database.xml` bevat geen lyricdata en `extra.db`/`Cache/cache.db`
waren gelockt; locks zijn niet omzeild. Trackidentiteit via exact pad en
bestandsgrootte is wel mogelijk. VirtualDJ-lyrics blijven uitsluitend een
conditionele development-only externe calibratiereferentie, nooit verplichte
SongAnalyzer-input. De bestaande `VoiceInstrumental`-classifier produceert
vóór `aggregate()` tijdelijke temporele output die momenteel niet wordt
bewaard; dat is toekomstig onderzoek, zonder nieuwe Essentia-feature.

Baseline blijft `analysis_version = m14-v5` en
`phrase_analysis_version = phrase-analysis-v17`; M23A blijft `BEZIG` en v17
blijft de veilige productionele fallback. Canonical boundaries/sections/
confidence, Rich Musical Events, Auto Show, AnalysisLibrary en cache keys zijn
ongewijzigd. M24A-5A/5B blijven shadow/diagnostics-only.

`GEREED` M24A-5C-2 — technische en menselijke runtime-PASS. De shadow-only,
vectoriële architectuur bestaat uit drie onafhankelijke profielen:

- `PreparationProfileShadow`: `EnergyTrajectory`, `ExitEnergyDirection`,
  `ExitOnsetDirection`, `ExitSilenceDirection` en `ExitStructuralContext`.
  Preparation leest uitsluitend de origin section en haar exit; destination
  state, arrival, canonical role en eventlabels zijn geen input.
- `ArrivalProfileShadow`: `EntryContrast`, `BoundaryNovelty`,
  `EnergyDirection`, `OnsetDirection`, `SilenceDirection`,
  `OriginRelativeEnergy` en `DestinationRelativeEnergy`. Arrival is een
  boundaryvector zonder `ArrivalImpact`-score, gewogen combinatie,
  `RecurrenceStrength` of `FamilySalience` als input.
- `StructuralDepartureProfileShadow`: `StructuralContextChange`,
  `MembershipExitStrength`, `RepeatedSectionEnd`, `RecurrenceChange`,
  `StructuralRoute`, `StructuralEvidence` en `StructuralTargetBar`. Entry en
  Exit blijven zelfstandig boundary-georiënteerd en worden niet in Arrival
  samengevouwen.

`OriginRelativeEnergy` wordt uitsluitend aan een direct aangrenzende vorige
raw observation gekoppeld; eerste, gapped of ongeldige observations blijven
`null`. `BuildMomentum` en `DropImpact` blijven `unknown/null` placeholders.
Er is geen `PreparationType`, eventlabel, threshold of eventinterpretatie.
Schema v2 blijft additief; shadowdata blijft ephemeral en wijzigt geen
persistence, cache of AnalysisLibrary.

De Magnetic-runtimevalidatie bevestigt rond 38.797 s een consistente boundary:
de Preparation-exit en Arrival-entry delen `ΔEnergy +1.30`, `ΔOnset +0.71`
en `ΔSilence -3.79`, met `OriginRelativeEnergy 0.25`,
`DestinationRelativeEnergy 0.84`, `EntryContrast 0.55` en
`BoundaryNovelty 0.97`. De arrival rond 112.645 s bevestigt hetzelfde patroon
(`ΔEnergy +1.39`, `ΔOnset +1.02`, `ΔSilence -4.14`, `0.31 → 0.93`). De
Magnetic Bridge rond 142.184 s bevestigt de scheiding: lokaal kleine arrival
(`RelativeEnergy 0.93 → 0.91`, `ΔEnergy ≈ 0`, `ΔOnset ≈ -0.06`,
`ΔSilence ≈ +0.18`, `EntryContrast 0.10`, `BoundaryNovelty 0.13`) tegenover
onafhankelijke structural departure (`MembershipExitStrength 0.78`,
`RepeatedSectionEnd 0.78`, route `family-exit`, `StructuralEvidence 0.70`).
De laatste overgang bevestigt bovendien een expliciet downward profiel:
`RelativeEnergy 0.91 → 0.03`, `EnergyDirection -1.35`,
`OnsetDirection -0.81`, `SilenceDirection +2.72`, `EntryContrast 0.60` en
`BoundaryNovelty 0.92`.

Baseline blijft `analysis_version = m14-v5` en
`phrase_analysis_version = phrase-analysis-v17`; M23A blijft `BEZIG` en v17
blijft de veilige productionele fallback. Canonical output, Rich Musical
Events, Auto Show, AnalysisLibrary en cachegedrag zijn ongewijzigd.

Volgende actieve ontwikkelstap: `M24A-5C-3 — multi-track runtimecalibratie van
de vectorprofielen`, `STATUS = NOG NIET GESTART`. Beoordeel Free Your Mind,
Levels en Calling naast de geaccepteerde Magnetic-guard op
boundaryconsistentie, tekenbehoud, origin/destination state, nullgedrag,
onafhankelijkheid van arrangement identity en structural departure, en
diagnostische leesbaarheid. Geen track-specifieke tuning en nog geen
eventinterpretatie. `M24A-5D` blijft pas daarna kandidaat voor shadow event
interpretation.

## M24A — Show-readiness als eerstvolgende hoofdprioriteit

De volledige relevante VirtualDJ-playlist moet worden geanalyseerd en current
en ready zijn, zonder runner/analyzer-failures of stale relevante analyses.
Canonical structuur en de keten VirtualDJ → SongAnalyzer/bridge → BeatBeam
moeten betrouwbaar zijn; verdachte tracks worden gericht menselijk gecontroleerd
en BeatBeam/Auto Show moet optredenwaardig zijn. Daarna volgt feature freeze:
voornamelijk testen, repeteren en noodzakelijke bugfix/tuning.

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

**Besluit:** Rekordbox is legacy en geen actief doelplatform.

- `VERVALLEN` Rekordbox phrase-analyse verder uitbouwen als kernfunctie.
- `VERVALLEN` Eigen phrase-structuur beperken tot Rekordbox native phrase-types.
- `TODO` Bestaande veilige Rekordbox-functionaliteit behouden waar die nog nuttig is.
- `TODO` Rekordbox-koppelingen los houden van de nieuwe BeatBeam-analyse.

## 1.3 VirtualDJ

**Doel:** VirtualDJ is de playback-/live-DJ-integratie.

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

1. `BEZIG` Volledige VirtualDJ-playlist show-readiness, daarna feature freeze.
2. `BEZIG` M23A: menselijke runtimevalidatie van phrase-analysis-v17.
3. `BEZIG` M24A: muzikale shadow-calibratie op een kleine representatieve trackset.
4. `TODO` Rich Musical Events en verdere hiërarchische analyse na show-readiness.
5. `TODO` Geen nieuwe Essentia-features zonder aantoonbare evidence gap.

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

## 13.6 M23A runtime failure diagnostics

M23A-runtimetests hebben track-specifieke analyzerfailures blootgelegd terwijl
HIGH-prioriteit, queuegezondheid en v14-voortgang correct werken. De bridge
bevat nu bounded running-job- en failurediagnostics, inclusief fase, veilige
foutdetails, optionele stderr-tail en active-track filtering. De eerste
concrete v14-oorzaak is vastgesteld en in SongAnalyzer verholpen: semantic_sections
behandelde een lege trusted-family-set als dictionary en riep .values() aan;
dit veroorzaakte AttributeError: 'set' object has no attribute 'values' in
phrase_analysis. De failure diagnostics bewezen de oorzaak; menselijke
muzikale acceptatie van M23A loopt door. M23A blijft BEZIG.
