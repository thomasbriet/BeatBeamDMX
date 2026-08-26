# BeatBeam + SongAnalyzer — Master Roadmap

> Centrale, levende product- en ontwikkelroadmap voor **SongAnalyzer** en **BeatBeam**.
> Dit bestand moet tijdens programmeerwerk actief worden geraadpleegd en bijgewerkt.
> Zie ook `CURRENT_ROADMAP.md` voor de compacte actuele status, prioriteiten en blockers.

## Current reconciliation map — 2026-08-26

`CURRENT_ROADMAP.md` is de compacte actuele status en `MASTER_BACKLOG.md` is
de enige levende werkvoorraad. De chronologische delen onder deze kaart blijven
bewust behouden als architectuur-, evidence- en besluitgeschiedenis. Hun oude
`TODO`, `BEZIG` en `NOG NIET GESTART`-labels zijn **geen actieve opdracht**
wanneer ze hieronder als completed, superseded, deferred of closed zijn
geclassificeerd.

De actuele keten is: **VirtualDJ** voor playback/live deck/master-authority,
**SongAnalyzer** voor software-onafhankelijke diepe analyse en compact
runtime-handoff, en **BeatBeam** voor veilige lighting/show-output. De actieve
composertruth is `ContinuousMusicalState`: sectietiming/-voortgang, relatieve
energie/traject, recurrence/material return, section character en structurele
change. BUILD/BREAK/ARRIVAL/RELEASE/DROP/RETURN/DEPARTURE/TRANSITION zijn
optionele bounded modifiers; RME is nooit de continuous backbone. Rekordbox is
uitsluitend `LEGACY / HISTORICAL / RESEARCH CONTEXT`.

| Historisch onderwerp | Gereconcilieerde status |
| --- | --- |
| M22A runtime, transport en rich-analysis handoff | `COMPLETED`; de oude open runtimepass is superseded door de actuele lifecycle- en coverage-passes. |
| M23A RME-uitbreidingen | `COMPLETED_FOUNDATION`; RME is persisted, deterministic en fail-closed. Oude semantic-tuningregels zijn historische research, geen actieve backlog. |
| M24/M24A canonical candidate-pad | `CLOSED`: `M24_CANONICAL_AUTHORITY_CLOSEOUT_PASS`; `LEGACY_ONLY_PRODUCTION_CANDIDATE_SHADOW_RETAINED`; `CANONICAL_CANDIDATE_PRODUCTION_AUTHORITY = DISABLED_UNDER_CURRENT_EVIDENCE_CONTRACT`. Niet heropenen via thresholds, whitelist, kleine samples, candidate==legacy of hetzelfde evidencepakket. |
| Continuous state, Event Envelope, variation en production selector | `COMPLETED_TECHNICAL / PRODUCTION_GATE_OFF`; runtime blijft `BASELINE_ONLY`, production promotion is alleen een toekomstige expliciete gated beslissing. |
| VirtualDJ prewarm, master authority, observability en activate-path | `COMPLETED`: `VDJ_DECK_PREWARM_MASTER_SYNC = PASS` en `MASTER_SWITCH_ACTIVATE_LATENCY_OPTIMIZATION_PASS`. |
| Analysis-worker operations en job lifecycle | `COMPLETED`: `ANALYSIS_WORKER_OPERATIONAL_HARDENING_PASS`; bounded sequential queue, explicit states, cancellation/timeout, crash isolation, stale recovery en diagnostics. |
| BeatBeam Live Show UX V2 | `TECHNICAL_PASS / HOLD_USER_REVIEW`: Live Show projecteert bestaande typed runtime-state; Preview, Manual en Advanced scheiden operatie, preview en raw diagnostics. Geen wijziging van `BASELINE_ONLY` of fysieke authority. |
| FILL micro-evidence | `TECHNICAL_PASS / HOLD_HUMAN_LABELS`; het 36-item reviewpakket bepaalt of calibratie of shadow-eventpromotie ooit gerechtvaardigd is. Geen FILL → strobe-regel. |
| Beat pulse, live intensity, Event Envelope en variation | `TECHNICAL_PASS / HUMAN_HOLD`; uitsluitend de actuele reviewgates in `MASTER_BACKLOG.md` zijn nog open. |

## Analysis-worker operational hardening

`ANALYSIS_WORKER_OPERATIONAL_HARDENING_PASS`. De bestaande VirtualDJ-bridge
behoudt één sequential heavy-analysis worker en begrenst de queue op 128 jobs,
terminal history op 256 en failure diagnostics op 24. Jobs exposen `QUEUED`,
`RUNNING`, `COMPLETED`, `FAILED`, `CANCELLED` en `TIMED_OUT`; equivalente
inflight aanvragen worden samengevoegd. Running cancellation en de
10-minutentimeout beëindigen de exacte child-process tree bounded, waarna de
queue zonder service-restart doorgaat. Protocol-, request-, filepath-,
file-content- en snapshot-identiteit falen closed met beperkte machinecodes.

Cache en BeatBeam-handoff blijven via hun bestaande atomic writers publiceren;
een fout, cancellation of timeout kan dus geen partial current state maken. Een
persisted `pending` active-track wordt bij bridgestart naar `unavailable`
hersteld, met behoud van de laatste valide analyse-index en normale plugin-resync.
Queue-/jobleeftijd, worker-PID/health, terminal counters, failurecategorie en
stale recovery zijn additief zichtbaar in protocol v1 diagnostics. Pressure-,
failure-storm-, shutdown-, restart- en echte runtimeacceptatie eindigden idle
met nul orphan workers. Analysis-, phrase-, RME- en continuous-stateversies zijn
ongewijzigd; de current library bleef 215/215 en BeatBeam bleef
`BASELINE_ONLY`.

## Historical planning snapshot — superseded as active backlog

De secties `# 1` tot en met `# 11` hieronder zijn een behouden snapshot van
eerdere productverkenning. Zij blijven nuttig voor rationale en afbakening,
maar zijn geen huidige planning. Alleen items die expliciet in
`MASTER_BACKLOG.md` staan, zijn actief; alles anders is `COMPLETED`,
`SUPERSEDED`, `DEFERRED`, `LEGACY` of `STATUS_REQUIRES_CONFIRMATION`.

## Full continuous-state coverage en protected-worktree checkpoint

`PASS / PRODUCTION GATE OFF`. Vijf tracks met een actuele analysis-container
maar oude phrase-analysis zijn via de normale VirtualDJ bridge-workerflow
gericht heranalyseerd. Daarna waren 215/215 tracks current en bruikbaar voor
continuous-state shadowcomposition: 2.203 sectie-observaties en 11.741/11.741
geldige frames. No-current-RME bleef normale composerinput; alle envelope-
completion-, renderer- en baseline-identityinvarianten bleven groen. Een tweede
pass over dezelfde vijf tracks veranderde geen cachehash, saved timestamp of
mtime en bevestigde daarmee echte cache-hits en current handofflifecycle.

De eerder beschermde dirty sourcegraphs zijn na actuele hunkreview in normale
lokale commits bewaard: FILL evidence, pure Dynamic Composer, BeatBeam preview/
runtime-diagnostics, shadow-handoff persistence en VirtualDJ deck lifecycle.
Generated audio/soaks/buildoutput en de user-owned workspacefile bleven buiten
Git. SongAnalyzer heeft geen remote; BeatBeam bleef `LOCAL_COMMITS_ONLY`.
Production blijft de bestaande `BASELINE_ONLY`-route
`existing_autoshow -> current_values`; human review-/visual gates zijn niet
automatisch gepromoveerd.

## FILL micro-evidence en Dynamic Composer production selector

`TECHNICAL PASS / PRODUCTION GATE OFF / HUMAN HOLDS`. Live-intensity status exposeert analyzed,
raw/normalized live, modifier, effective, source age/deck/generation en
fallback. De bestaande filter en ±0,06-bound zijn niet getuned omdat de live
runtime tijdens acceptatie niet advancing was; echte passage- en human evidence
blijft vereist.

SongAnalyzer heeft een kleine pre-native `ShortAccentObservation`-laag. Zij
hergebruikt de bestaande 512-hop RMS-onset-envelope en reeds berekende
beat-onset, spectral-flux en RMS, aggregeert die muzikaal in kwartbeats en
publiceert alleen sparse twee-beat shadow candidates. Canonical/native labels,
genre, titel en artiest zijn geen input; raw-boundaryafstand is annotatie en
geen gate. Synthetische guards dekken steady four-on-floor/hi-hat, sustained
chorus, BUILD, DROP/ARRIVAL-impact, BREAK, isolated clap en silence-to-sound.
De representatieve corpusrun (24 tracks, 71,54 min, 8.855 windows) leverde 82
candidates op 23 tracks; 7 lagen binnen 0–2 beats vóór een raw boundary en er
was overlap met BUILD 24, BREAK 17, ARRIVAL 12, RELEASE 6 en DROP 2. Gate:
`EVIDENCE_PROMISING_MORE_CALIBRATION_REQUIRED`; FILL-RME en EventEnvelope blijven
HOLD tot een compacte hoorbare labeled review calibratie rechtvaardigt.

De eerder ontworpen production-selector is nu centraal vóór de ene bestaande
renderer geïmplementeerd. Modi zijn `BASELINE_ONLY`,
`DYNAMIC_COMPOSER_SHADOW` en `DYNAMIC_COMPOSER_ENABLED`; de runtime gebruikt
een niet-configureerbare interne `BASELINE_ONLY`-constante en unknown faalt
eveneens daarheen. SHADOW meet candidate/eligibility/signatures maar selecteert
altijd bestaande Auto Show. De pure selector valideert exacte track, current
handoff, playback/handoff/composer-generation, continuous state, finite bekende
bounded primitives, rendererstatus en alle manual overrides; iedere fout kiest
de baseline van hetzelfde frame. Current RME en live intensity zijn optioneel.
Blackout, capabilitychecks, clamps en strobe-safety blijven downstream in de
bestaande renderer. Preview blijft Dynamic Composer kunnen tonen terwijl
physical output `auto_show -> current_values` blijft. ENABLED is alleen direct
in pure tests aangeroepen; er is geen UI/config/env/automatische activatie.
Rollback is één interne mode naar `BASELINE_ONLY`, zonder migratie of reinstall.
Zie `DYNAMIC_COMPOSER_PRODUCTION_PROMOTION_DESIGN.md`.

Een volledige current-handoff shadow-soak (210/215 bruikbare tracks, 11.445
frames) en een 100.000-frame lifecycle-soak bevestigen de centrale
architectuur: no-current-RME en analyzed-only intensity blijven geldige
composerinput, terwijl fysieke output in ieder frame dezelfde baselinebron
houdt. Fault injection valideert same-frame failback voor alle selector- en
safetygates. De soak vond twee generieke state-machinefouten die bounded zijn
hersteld: een lager-prioritaire point-envelope kon na de completion van een
same-boundary DROP herleven, en recurrence reuse kon de direct vorige volledige
signature kiezen. De invariant is nu respectievelijk boundary-winner completion
zonder oudere resurrection en geen directe recurrence-repeat. Dit verandert
geen production authority; runtime blijft intern `BASELINE_ONLY`.

De FILL-foundation heeft nu een reproduceerbaar geblindeerd human-reviewpakket
met 24 gestratificeerde candidates, 12 guarded controls en lokale snippets.
Dit is uitsluitend reviewvoorbereiding: labels blijven pending, thresholds zijn
ongewijzigd en `FILL_CALIBRATION = HOLD_HUMAN_LABELS`.

## Realtime Beat Phase + Live Intensity Foundation — technical pass / runtime hold

De VirtualDJ-transportlaag gebruikt `get_beatpos` als fase-anker; normale Auto
Show-pulsen zijn frame-onafhankelijk een functie van die actuele fase. N→N+2
samples en rendererframeverlies verliezen geen toekomstige EVERY_BEAT;
half-time, baraccenten, subdivisies en sparse ritmes zijn expliciete intentie.
Read-only debug toont fase, bronleeftijd en classificatie. Physical DMX blijft
ongewijzigd.

De plugin publiceert als begrensde live-previewcorrectie alleen de
deck-scoped pre-master `get_level`-waarde. De bridge bindt die uitsluitend bij
exact actieve deck/path aan lifecycle-generation; BeatBeam accepteert alleen
verse advancing samples en valt anders analyzed-only terug. Relatieve
normalisatie, attack/release en ±0,06 blijven preview-only. Tests/build zijn
PASS; deployment, veilige VirtualDJ-restart en human acceptance zijn HOLD.

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

# VirtualDJ deck-prewarm + master authority sync

`GEREED — LIVE RUNTIME + ACTIVATE-PATH LATENCY PASS`. De native
VirtualDJ-plugin gebruikt `get_activedeck` als directe officiële sync-masterbron
en leest die bij iedere lifecyclepoll naast filepath, playing en decknummer. De
masterroute is fail-closed: bij ontbrekende/ongeldige direct signal ontstaat
`master_signal_unavailable`; de voormalige one-playing/current/recent-loaded-
heuristiek is verwijderd. Alleen een loaded én playing directe master mag via
`activate` `active_track` en de transport-snapshot wijzigen. Een A→B-wissel is
daardoor een normale deck-/trackdiscontinuity met nieuwe generation in plaats
van een guessed handoff. De bounded native diagnostics tonen masterquery/raw/
deck, candidates, selected deck/path/reason, IPC, generation en recovery.

Een geladen niet-masterdeck gebruikt `prewarm`: een cache-hit schrijft alleen
zijn track-entry in de handoff-index; een miss start één normale, gededupeerde
analysejob en publiceert bij completion uitsluitend die entry. Prewarm schrijft
nooit `active_track` en wijzigt daardoor NOW, BeatBeam-transport, Auto Show,
Dynamic Composer, event envelopes, rendersemantiek of fysieke DMX niet. Een
vervangen deck vervangt diens prewarm-status; hetzelfde bestand op twee decks
blijft deck-identiteit behouden. Technische cache-hit/miss, deduplicatie,
failure, replacement, master A→B, same-path en unavailable-mastertests zijn
groen. De live run met beide decks ready bevestigde A→B en B→A met
`get_activedeck` authority, exacte active track/generation, transport, handoff
en Dynamic Composer-context. De activate-route verwijdert uitsluitend
non-authoritative prewarm vóór activate/transport en promoveert een exact
gevalideerde `(canonical_path, deck)` ready-prewarm zonder cache-herlezing.
Gemeten: T1→T2 0 ms, handoff-current 176 ms, bridge-ready 224/236 ms; eerdere
baseline was 627 ms intern. Physical DMX-semantiek bleef ongewijzigd.

Na deze lifecycleacceptatie blijft de productprioriteit de preview-only,
menselijke Musical Event Envelope-acceptatie; dit opent geen production-DMX-
of Auto-Show-authority.

# M23A — Rich Musical Events voor BeatBeam

`GEREED` — bounded foundation plus runtime-shadowacceptatie: bestaande software-
onafhankelijke SongAnalyzer-evidence wordt geprojecteerd naar een expliciet Rich
Musical Events-contract voor read-only/shadow-consumptie door BeatBeam. De
projectie gebruikt structurele boundaries, recurrence/families, section-character,
energy/build/release en arrival/departure-evidence zonder canonical- of legacy-
`SectionRole` als semantische input. BeatBeam-productiegedrag, Auto Show, DMX,
VirtualDJ en runtime deployment blijven ongewijzigd. M24 canonical authority is
afgesloten en blijft `LEGACY_ONLY_PRODUCTION_CANDIDATE_SHADOW_RETAINED`;
`AUTHORITY_DEPENDENCY = NO`.

`GEREED — M23A_RICH_MUSICAL_EVENTS_PASS — READY_FOR_RUNTIME_SHADOW_ACCEPTANCE`.
SongAnalyzer commit `2d3f9ead1ddccda2f892d011f465b1e44bbb5260` voegt een
pure Core-projector en deterministische schema-1 handoff toe voor `SECTION_START`,
`SECTION_END`, `BUILD`, `RELEASE`, `DROP`, `BREAK`, `ARRIVAL`, `DEPARTURE`,
`RETURN` en `TRANSITION`. BUILD/BREAK zijn intervallen; de overige wijzigingen
zijn points of boundary-transitions. Provenance bevat uitsluitend expliciete
software-onafhankelijke inputnamen en propositions, zonder numeric confidence.
Missingness faalt per event gesloten. Canonical/legacy role, H/M/L, Rekordbox,
tracktitel, artiest en genre zijn geen derivatie-input.

BeatBeam commit `fe814faff1149bcf449f0bbb93c5a467256cd856` voegt de
strikte pure schema-parser en read-only observer toe in
`BEATBEAM_RICH_EVENT_MODE = SHADOW_ONLY`; er is geen backend-, Auto Show-,
fixture-, render- of DMX-wiring. De echte C#→Python handofftest is PASS. De nieuwe
tests zijn SongAnalyzer 10/10 en BeatBeam 7/7; relevante SongAnalyzer-regressies
59/59, volledige huidige suites 1056/1056 en 215/215, en clean committed snapshots
10/10 plus build en 200/200 plus beta-package. SongAnalyzer Release build heeft
0 warnings/0 errors. BeatBeam packaging/sign/import is PASS met alleen de bestaande
Swift CFString-pointerwarning.

De frozen/read-only corpusobservatie matchte alle 173 tracks zonder fresh
audioanalyse. Ephemeral shadow-input was beschikbaar voor 13 tracks, 142 sections
en 84 boundaries; 160 tracks produceerden correct fail-closed niets. Op beschikbare
input ontstonden 468 events: SECTION_START 142, SECTION_END 142, BUILD 15,
RELEASE 6, DROP 4, BREAK 15, ARRIVAL 76, DEPARTURE 4, RETURN 60 en TRANSITION 4.
Duplicaten zijn 0 en herhaalde projectie is byte-deterministisch. Human review is
voor deze bounded shadowfoundation niet vereist. M24 authority blijft afgesloten
als `LEGACY_ONLY_PRODUCTION_CANDIDATE_SHADOW_RETAINED`; production lighting en
VirtualDJ zijn identiek en deployment is niet uitgevoerd.

`GEREED — M23A_RUNTIME_SHADOW_FULL_CORPUS_PASS`. De lifecycle-audit bewees dat
`rawSectionObservations` uitsluitend uit de fresh phrase-workerresponse werden
geparseerd en via `PhraseAnalysisBatchItem.ShadowProjection` tijdelijk bereikbaar
bleven. `PhraseAnalysisSessionCache` en de persistente `TrackAnalysisResult`
bewaarden alleen `PhraseAnalysisResult`; een cache-hit bouwde daardoor bewust een
lege shadowprojectie. De historische 13/173 was dus `CACHE_HIT_MISSINGNESS` plus
een ephemeral/serialization-gap, niet true upstream-evidence-missingness.

De gekozen architectuur is `SAME_LIFECYCLE_PROJECTION + COMPACT_RICH_EVENT_CACHE`:
de bestaande projector draait direct na fresh raw/shadowprojectie en uitsluitend
de compacte Rich Musical Events plus `rich-musical-events-v1` worden in het
bestaande analysisresult gecachet. Raw observations, section/arrangementprofielen
en shadow event evidence worden niet breed persistent gemaakt. Een oude cache
zonder deze compacte projection-version wordt expliciet stale en volgt éénmaal de
normale analyseflow; forced reanalysis is geen blijvende productoplossing.

De echte `PhraseAnalysisService` → analysis store →
`JsonBeatBeamStructureHandoffStore`-route is op het volledige 173-trackcorpus fresh
en daarna met een nieuwe bridge-runner als cache-hit gevalideerd. Resultaat:
173/173 tracks gematcht, 173/173 met benodigde upstream evidence, 1.702 raw
sections, 1.529 boundaries, 173/173 met Rich Events en 0 zonder. De 6.594 events
zijn: SECTION_START 1.702, SECTION_END 1.702, BUILD 236, RELEASE 215, DROP 114,
BREAK 304, ARRIVAL 1.356, DEPARTURE 6, RETURN 953 en TRANSITION 6. Duplicaten zijn
0; determinisme en family-relabel invariance zijn PASS. BeatBeam parseerde alle
173 compacte handoffs als exact/current, exposeerde ze uitsluitend via Debug als
`SHADOW_ONLY` en via 0/173 production projections. Auto Show, lighting/DMX,
VirtualDJ, legacy authority en disabled canonical-candidate authority bleven
ongewijzigd; runtime deployment is niet uitgevoerd.

`M23A_RUNTIME_SHADOW_ACCEPTANCE = GEREED`; deze lijn heeft geen directe
semantic-tuning- of human-reviewvervolgstap. De bestaande show-readinessrichting
blijft leidend; Rich Event-semantiek wordt pas opnieuw geopend bij een concrete,
hoorbare vraag.

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

`GEREED` M24A-5C-3 — multi-track menselijke runtime-PASS. De nieuwe
vectorprofielen zijn zonder track-specifieke tuning of codecorrectie bevestigd
op The Bausa — Magnetic, Prospa/Cloonee — Free Your Mind, Avicii — Levels
(Original Version) en Sebastian Ingrosso/Alesso/Ryan Tedder — Calling (Extended
Club Mix). Preparation en Arrival behouden dezelfde boundary-direction
evidence; origin- en destination-energy blijven afzonderlijke state; signed
energy-, onset- en silence-richtingen blijven onafhankelijk. Recurrence en
family salience blijven buiten Arrival, structural departure blijft zelfstandig
van lokale arrival magnitude/direction, en eerste/gapped/eind-observations
behouden veilig nullgedrag. `BuildMomentum` en `DropImpact` blijven
`unknown/null`; er is geen `ArrivalImpact`-score.

De bestaande Magnetic-guards zijn onderdeel van deze calibratie: upward
arrivals rond 38.797 en 112.645 s, de Bridge rond 142.184 s met kleine lokale
arrival maar duidelijke structural departure, en de sterke downward transition
naar de laatste observation. Free Your Mind bevestigt upward arrival rond
46.254 s, downward transition rond 74.379 s, een rising-preparation-traject
rond 136.254–166.255 s zonder BUILD-label en zelfstandige family-exit aan het
einde. Levels bevestigt afwisselende richtingen binnen dezelfde trackidentity,
waarbij hoge recurrence/salience en boundary magnitude nooit direction
bepalen; lokale EnergyDirection kan bovendien afwijken van de gemiddelde
origin/destination-state. Calling is de cyclische stresstest: zeer hoge
recurrence en family salience bevatten zowel upward als downward vectors,
inclusief tegengestelde EnergyDirection/OnsetDirection-tekens. Daarmee zijn
RecurrenceStrength, FamilySalience en lokale magnitude geen event- of
ArrivalImpact-proxy.

Cross-track blijft de leidende scheiding:
`PreparationProfile` = origin-trajectory plus exit, `ArrivalProfile` = lokale
boundary magnitude plus signed direction plus origin/destination state,
`StructuralDepartureProfile` = structurele/contextuele departure, en
Arrangement Identity = recurrence/family salience. Deze lagen worden pas in
een latere interpretatielaag bovenop elkaar gelezen en niet vooraf tot één
generieke score samengevoegd. Baseline, canonical output, Rich Musical Events,
Auto Show, AnalysisLibrary, cache keys/persistence en ephemeral shadowveiligheid
blijven ongewijzigd; `m14-v5`, `phrase-analysis-v17`, M23A `BEZIG` en v17 als
veilige productionele fallback blijven gelden.

`GEREED` M24A-5D-1 — read-only shadow event semantics audit. De eventroute is
abstention-first: onafhankelijke evidence → boundary-georiënteerde
`ShadowEventEvidence` → later nul of meer conservatieve hypotheses → pas na
calibratie eventuele productionele interpretatie. Er is geen hard `EventType`;
evidence-nabije aspecten blijven gescheiden van latere muzikale hypotheses.

`GEREED` M24A-5D-2 — technische en menselijke runtime-PASS. Per bestaande
geldige contiguous raw boundary `i → i+1` wordt exact één additive, ephemeral,
shadow-only `ShadowEventEvidence` gemaakt. `BoundarySeconds` is exact de
destination-starttijd en `BoundaryBar` de bestaande destination-startbar
(Debug één-gebaseerd); eerste observations hebben geen kunstmatige inbound,
laatste geen kunstmatige outbound en gaps leveren geen record. De evidence
bevat uitsluitend `OriginObservationId`, `DestinationObservationId`,
`BoundarySeconds`, `BoundaryBar`, `PreparationAspect`, `ArrivalAspect`,
`StructuralDepartureAspect` (`OriginExit` en `DestinationEntry`) en
`ArrangementIdentityAspect` (`RecurrenceStrength`, `FamilySalience`, `FamilyId`,
`HasEarlierFamilyOccurrence`). Preparation komt alleen uit origin-exit,
Arrival alleen uit destination-entry; arrangement identity blijft context en
verandert Arrival niet.

`HasEarlierFamilyOccurrence` is uitsluitend chronologische raw-family-history:
`true` bij een geldige geselecteerde FamilyId die eerder in dezelfde raw sequence
voorkwam, `false` bij geldige identity/history zonder eerdere occurrence, anders
`null`. RecurrenceStrength of FamilySalience kunnen dit nooit op `true` zetten.
`EvidenceCompleteness` en `MissingEvidence` zijn bewust niet toegevoegd:
zonder concrete eventhypothese zou een algemene COMPLETE-status schijnprecisie
zijn.

De Magnetic-runtime-PASS bevestigt acht records voor negen raw observations:
de upward boundaries rond 38.797 s en 112.645 s, de Bridge-guard rond 142.184 s
met kleine lokale Arrival maar zelfstandige structural departure, en de sterke
downward boundary rond 171.723 s zonder automatisch eventlabel. De eerste
family-occurrence toont `section-family-001` met `HasEarlierFamilyOccurrence =
false`; latere occurrences tonen correct `true`. Debug/handoff exposeert
optioneel `shadow_analysis.event_evidence` binnen schema v2 met een aparte
`SHADOW EVENT EVIDENCE`-sectie; dit beïnvloedt geen `rich_analysis.events`,
`current_event`, `next_event` of Auto Show.

Productioneel blijft alles geïsoleerd: `analysis_version = m14-v5`,
`phrase_analysis_version = phrase-analysis-v17`, M23A blijft `BEZIG` en v17 de
veilige fallback. Canonical boundaries/sections/confidence, Rich Musical Events,
AnalysisLibrary, cache, persistence en Auto Show zijn ongewijzigd; er is geen
shadow-event persistence, hypothese, threshold, weight, confidence of winner.

`GEREED` M24A-5D-3A — read-only candidate-hypothesisdesign. Hypotheses zijn
abstention-first en ondersteunen nul of meer hypotheses per boundary, zonder
score, confidence, ranking, winner of lineaire samengestelde evidence. Canonical
roles, native types, Rich Musical Events, genre en Auto Show zijn geen input.
BUILD was alleen als strenge rising-subset klaar voor een eerste shadow-gate;
DROP en RETURN hadden meer evidence nodig; BREAKDOWN werd geparkeerd.

`GEREED` M24A-5D-3B — brede read-only distribution audit op Ralf Feest:
190 playlistentries, 173 unieke FLAC-tracks, 17 duplicaten, 0 ontbrekend;
173/173 verwerkt, 1.702 raw observations en 1.529 contiguous boundaries zonder
gaps. De audit was standalone en niet-persistent; AnalysisLibrary, cache,
handoff, versions, canonical output, Rich Musical Events en Auto Show bleven
ongewijzigd. EntryContrast en BoundaryNovelty correleren sterk (`r ≈ 0.833`)
en zijn geen onafhankelijke stemmen. Signed evidence is breed verdeeld; teken,
aanwezigheid en coherentie zijn voorlopig bruikbaarder dan magnitude-thresholds.
Lokale EnergyDirection en destination-vs-origin state-shift zijn in circa 23,4%
van de boundaries tegengesteld. Slechts 15 boundaries hebben StructuralRoute;
alle 15 zijn `family-exit`. De eerste presence-bundle is route `family-exit`+
StructuralEvidence aanwezig+MembershipExitStrength aanwezig, zonder numerieke
threshold; deze komt op 7 boundaries voor. MembershipExitStrength en
RepeatedSectionEnd delen dezelfde repeat-end-provenance en tellen niet dubbel.
HasEarlierFamilyOccurrence is te breed voor RETURN: 953 true-cases, waarvan
ongeveer 744 directe family-continuations en circa 107 aantoonbare onderbrekingen.

`GEREED` M24A-5D-3C0 — technische en menselijke runtime-PASS. Additief
`ShadowEventEvidence.DestinationIsTerminal : bool` projecteert uitsluitend raw
sequence-topology (`destinationIndex == observations.Count - 1`) naar
`destination_is_terminal` in schema v2. Legacy handoff zonder dit veld blijft
geldig; BeatBeam inferreert terminaliteit niet. Magnetic 142.184 s is
non-terminal; John De Bever 154.088 s is terminal.

`GEREED` M24A-5D-3C — technische en menselijke runtime-PASS. Dit is de eerste
shadow-eventinterpretatie; uitsluitend `STRUCTURAL_TRANSITION_CANDIDATE` kan
worden geproduceerd. Het boundary-model ondersteunt 0..N hypotheses per
evidence-record. `AnchorKind = Boundary`, `StartSeconds = TargetSeconds =
BoundarySeconds`, `EndSeconds = null`. De gate vereist non-terminal destination
én op dezelfde zijde (`OriginExit` of `DestinationEntry`) de complete bundle:
`StructuralRoute == family-exit`, StructuralEvidence aanwezig en
MembershipExitStrength aanwezig. Origin- en destinationvelden worden nooit
gemengd; dubbele coherente zijden leveren exact één kandidaat en conflicterende
routes sluiten fail-closed. SupportingEvidence bevat alleen stabiele codes;
ConflictingEvidence is normaal leeg. RepeatedSectionEnd is geen tweede bron en
er zijn geen numerieke thresholds, confidence, score, ranking of winner.
Magnetic 142.184 s, Calling 338.955 s en Losse Pols 50.306 s zijn positieve
guards; John De Bever 154.088 s is de terminale negatieve guard. Kleine Arrival
blokkeert de kandidaat niet.

BUILD_CANDIDATE, DROP_CANDIDATE, RETURN_CANDIDATE en generieke
`TRANSITION_CANDIDATE` zijn niet geïmplementeerd; BREAKDOWN blijft geparkeerd.
Er bestaat geen `NO_EVENT`- of `ABSTAINED`-object: geen hypothesis is een lege
lijst. De shadow-hypotheses zijn additive, ephemeral en Debug-only; productie-
output, Auto Show, AnalysisLibrary, cache en persistence blijven geïsoleerd.
Baseline blijft `analysis_version = m14-v5` en
`phrase_analysis_version = phrase-analysis-v17`; M23A blijft `BEZIG` en v17 de
veilige fallback.

`GEREED` M24A-5D-4A — strikt read-only human sample-review op de bestaande
M24A-5D-3B-auditoutput. De reviewset bevatte 16 boundaries (A=4, B=4, C=3,
D=2, E=2, F=1) met 5 `DROP_LIKE`, 7 `NOT_DROP` en 4 `AMBIGUOUS`. De review
liet zien dat veel tracks geen duidelijke klassieke drop bevatten: een
belangrijke upward arrival kan showmatig relevant zijn zonder als klassieke
Drop te worden ervaren. Extreme lokale salience is geen Drop-proxy (stratum A
0/4 `DROP_LIKE`; inclusief top-5%-reference/control 0/6); EntryContrast en
BoundaryNovelty blijven één gecorreleerde saliencefamilie zonder monotone
threshold. De tijdelijke reviewoutput staat buiten de repository.

`GEREED` M24A-5D-4B — read-only evidencevergelijking en menselijke design-PASS;
geen code-implementatie of productgate. `DROP_DIRECT_GATE_STATUS =
SEMANTIC_LAYER_TOO_SPECIFIC`; `UPWARD_ARRIVAL_LAYER_STATUS = SUPPORTED`.
Alle human `DROP_LIKE`-cases hebben positieve `EnergyDirection` én
`StateShift`, maar EnergyDirection alleen onderscheidt onvoldoende.
`DestinationRelativeEnergy` is in deze kleine sample onderscheidender (mediaan
ongeveer 0.912 versus 0.405 bij `NOT_DROP`) en is relevante
`UPWARD_ARRIVAL`-evidence, zonder numerieke productthreshold. D12 en D13 zijn
`NOT_DROP` met positieve EnergyDirection maar negatieve StateShift (ongeveer
-0.080 en -0.366); `StateShift <= 0` is daarom uitsluitend een te valideren
`HARD_BLOCKER_CANDIDATE` voor een toekomstige upward-hypothese. D14 en D15
tonen dat negatieve OnsetDirection geen harde eis of blocker mag zijn.
Preparation- en silencevectoren blijven afzonderlijke ondersteunende evidence;
recurrence/family- en structurele evidence zijn geen Drop-gate. Alle 16 cases
waren non-terminal en geen ervan droeg `STRUCTURAL_TRANSITION_CANDIDATE`.
`AMBIGUOUS` blijft expliciete abstention en wordt niet naar yes/no gedwongen.

Voorlopige semantische layering voor vervolgdesign:
`RawSectionObservation`/boundary evidence → Preparation/Arrival/
StructuralDeparture/ArrangementIdentity → shadow event hypotheses →
`UPWARD_ARRIVAL_CANDIDATE` → optionele strengere `DROP_CANDIDATE`-interpretatie.
`ArrivalProfileShadow` blijft evidence; `UPWARD_ARRIVAL_CANDIDATE` is geen
vervanging daarvan. `STRUCTURAL_TRANSITION_CANDIDATE` blijft onafhankelijk.

`GEREED` M24A-5D-4C — read-only Upward Arrival gate-design en 16 nieuwe,
onafhankelijke human controls. Oude Drop-verdicts zijn niet hergebruikt; de
reviewcodering was 1=`UPWARD_ARRIVAL`, 2=`NOT_UPWARD_ARRIVAL`,
3=`AMBIGUOUS`. De controlgroepen waren clean core, lagere/midden
destination-state, StateShift/EnergyDirection-conflict, StateShift-controls,
terminaliteit en StructuralTransition-overlap.

`GEREED` M24A-5D-4D — read-only human verdict × evidence analyse en menselijke
design-PASS; dit is geen productgate. De verdictverdeling was 6
`UPWARD_ARRIVAL`, 7 `NOT_UPWARD_ARRIVAL` en 3 `AMBIGUOUS`.
`UPWARD_ARRIVAL_GATE_STATUS = NEEDS_MORE_HUMAN_CONTROLS`.
`DestinationRelativeEnergy` blijft belangrijke calibration-evidence zonder
threshold; U-A was 3/3 upward bij ongeveer 0.842–0.867, terwijl U-B 0/3
duidelijke upward was bij ongeveer 0.091, 0.623 en 0.707. Hoge
destination-state overlapt echter met NOT_UPWARD en AMBIGUOUS.
`ENERGY_DIRECTION_POSITIVE_STATUS = SUPPORTING_ONLY`: U07/U08/U09 hadden
alle positieve StateShift en niet-positieve EnergyDirection, maar alleen U08
was upward. U10/U11/U12 ondersteunden aanvankelijk een StateShift-blocker,
maar U16 was human `UPWARD_ARRIVAL` met StateShift ongeveer -0.247.
`STATE_SHIFT_NONPOSITIVE_STATUS = NOT_SUPPORTED`; StateShift <= 0 is geen
universele blocker. U13 was terminal en upward, dus
`TERMINALITY_STATUS = NOT_A_BLOCKER`. U15 was structural-compatible maar niet
upward en U16 structural-compatible én upward; daarom
`STRUCTURAL_COEXISTENCE_STATUS = SUPPORTED` en blijven de hypothese-assen
orthogonaal met 0..N hypotheses, zonder winner/ranking. U06/U12/U14 blijven
abstentioncases; lokale salience, onset, silence en preparation zijn geen
universele harde voorwaarden.

Brede sanitycheck: StateShift > 0 betreft 872 boundaries/173 tracks (59
terminal, 3 structural-overlap); met EnergyDirection > 0 zijn dat 664/172
(47, 2); met EnergyDirection <= 0 208/118 (12, 1). Destination-state en
perceptuele coherentie zijn zonder nieuwe gevalideerde semantiek niet
thresholdvrij als booleaanse gate te evalueren. Geen van de drie voorlopige
gatevarianten is klaar voor implementatie.

`GEREED` M24A-5D-4E — read-only matched Upward Arrival human controls. De
matched set bevatte 12 boundaries op 12 verschillende tracks; geen boundary
was eerder human-reviewed. De groepen waren M-A U08-type direction-conflict
(3), M-B U16-type negative/nonpositive StateShift (3), M-C high destination
(2), M-D lower/mid destination (2) en M-E terminal/StructuralTransition
replicaties (2). De menselijke verdicts waren 1 `UPWARD_ARRIVAL` (M08), 9
`NOT_UPWARD_ARRIVAL` (M01–M05, M07, M09–M10, M12) en 2 `AMBIGUOUS` (M06,
M11). M-A reproduceerde U08 niet (0/3 duidelijke upward); M-B reproduceerde
U16 evenmin (0/3 duidelijke upward). M07/M08 tonen tegengestelde verdicts
bij vergelijkbare hoge destination-state. M11 bevestigt dat terminaliteit geen
algemene blocker is; M12 bevestigt dat StructuralTransition geen Upward-proxy
is. DestinationRelativeEnergy blijft calibration-evidence zonder threshold.

`GEREED` M24A-5D-4F — read-only matched verdict × evidence diagnosis en human
design-PASS. `SECTION_AVERAGE_STATE_STATUS = LIKELY_TOO_COARSE`;
`EXISTING_EVIDENCE_STATUS = SUFFICIENT_IF_REEXPOSE_EXISTING_TEMPORAL_EVIDENCE`.
U08 is met bestaande lokale boundary-evidence descriptief te onderscheiden van
de matched NOT-controls, maar dit rechtvaardigt geen gate, score of threshold.
U16 blijft met de geëxporteerde section-/boundarysamenvattingen onverklaard:
een negatieve section-average StateShift maakt StateShift niet fout, maar
StateShift is geen universele representatie van perceptuele arrival. M07/M08
bevestigen dat Upward niet mag degenereren tot `HIGH_ENERGY_DESTINATION`.
Relevante fijnere temporal evidence bestaat al in de pipeline; de volgende
route is B: ontwerp additive shadow-exposure met provenance-clean per-bar,
voor/na-boundary en bestaande lokale energy-evidence. Geen nieuwe audio- of
Essentia-feature is nodig. `ENERGY_DIRECTION_POSITIVE_STATUS =
SUPPORTING_ONLY`; `STATE_SHIFT_NONPOSITIVE_STATUS = NOT_SUPPORTED`;
`TERMINALITY_STATUS = NOT_A_BLOCKER`; `STRUCTURAL_COEXISTENCE_STATUS =
SUPPORTED`. OnsetDirection is geen harde eis of blocker; local salience is één
gecorreleerde evidencefamilie; preparation is alleen supporting context.
`UPWARD_ARRIVAL_GATE_STATUS = NEEDS_MORE_HUMAN_CONTROLS / EVIDENCE EXPOSURE`;
er is nog geen shadow gate. BUILD, RETURN en DROP zijn niet geïmplementeerd;
BREAKDOWN blijft geparkeerd.

`GEREED` M24A-5D-4G — read-only fine-grained temporal shadow evidence design en
human design-PASS. `TEMPORAL_EXPOSURE_DESIGN_STATUS = READY_FOR_IMPLEMENTATION`,
uitsluitend voor additive temporal shadow exposure; dit maakt
`UPWARD_ARRIVAL_CANDIDATE` niet implementatieklaar. De bestaande route is
`beat_features` → `aggregate_bars` / `relative_energy_bars` →
`boundary_candidates` / `raw_section_observations` → C# shadowprojectie.
`RelativeEnergy` is een section-average van per-bar relative energy;
`EnergyRise` vergelijkt eerste en laatste derde van `normalizedRms`; de audit-
`StateShift` is `DestinationRelativeEnergy - OriginRelativeEnergy`. Daardoor
gaan laatste originbar en eerste destinationbar verloren; StateShift blijft een
section-state diagnostic, maar geen universele boundary-arrivalrepresentatie.
De bestaande deltas zijn één barpaar: `EnergyDelta = normalizedRms[i] -
normalizedRms[i-1]`, met dezelfde vorm voor onset en silence; operands worden
niet behouden. Late origin en early destination zijn beide
`YES_DERIVABLE_FROM_EXISTING_INTERMEDIATE`.

Minimale exposure: `PreBoundaryNormalizedRms` en `PostBoundaryNormalizedRms`
(`ENERGY_LOCAL_BOUNDARY`) plus `LateOriginRelativeEnergy` en
`EarlyDestinationRelativeEnergy` (`ENERGY_STATE`). Alle vier zijn nullable,
additive, ephemeral, shadow-only en Debug-only. Advies:
`ADD_DEDICATED_TEMPORAL_CONTEXT` met conceptueel
`BoundaryTemporalContextShadow` aan `ShadowEventEvidence`; `ArrivalProfileShadow`
wordt geen temporal dump. Pre/post-RMS en EnergyDelta zijn één bronfamilie;
relative-energy-randwaarden en section averages één beat-RMS-familie. Onset- en
silence-operands worden niet opnieuw geëxposeerd; U08 is met bestaande lokale
direction-evidence al descriptief bruikbaar. Schema v2 blijft additive zonder
version bump, cachewijziging, AnalysisLibrary-persistence of cache-invalidation.
Baseline blijft `m14-v5` / `phrase-analysis-v17`; M23A blijft `BEZIG` en v17 de
veilige fallback. BUILD, RETURN en DROP zijn niet geïmplementeerd;
BREAKDOWN blijft geparkeerd.

`GEREED` M24A-5D-4H — technische + menselijke runtime-PASS voor fine-grained
temporal shadow evidence exposure. `BoundaryTemporalContextShadow` is aan
`ShadowEventEvidence` gekoppeld met exact vier nullable additive velden:
`PreBoundaryNormalizedRms`, `PostBoundaryNormalizedRms`,
`LateOriginRelativeEnergy` en `EarlyDestinationRelativeEnergy`. De eerste twee
zijn de bestaande normalizedRms van exact de laatste originbar en eerste
destinationbar; de laatste twee zijn de bestaande P10/P90-normalized
relative-energywaarden van diezelfde bars. Er zijn geen nieuwe audiofeatures,
Essentia-calls, onset-/silence-operands of semantische scores toegevoegd.

`EnergyDelta` blijft ongewijzigd uit zijn bestaande productiebron en is op alle
vier anchors algebraïsch gelijk aan post minus pre binnen Debug-precisie.
`PreBoundaryNormalizedRms`, `PostBoundaryNormalizedRms` en `EnergyDelta` vormen
één `ENERGY_LOCAL_BOUNDARY`-provenancefamilie; `LateOriginRelativeEnergy`,
`EarlyDestinationRelativeEnergy`, `OriginRelativeEnergy` en
`DestinationRelativeEnergy` één `ENERGY_STATE`-familie. Deze velden mogen later
niet als onafhankelijke stemmen worden geteld. Handoff blijft schema v2,
additive, backward-compatible, optional, nullable, ephemeral, shadow-only en
Debug-only. Er is geen persistence-, cache-, invalidation- of version-bump.
Baseline blijft `m14-v5` / `phrase-analysis-v17`; M23A blijft `BEZIG`.

Voor deployment is een pre-existing macOS-testhostblocker gevonden in
`DiagnosticsProviderCombinesWatcherAndActiveTrackSnapshots`: een echte
`PlaylistWatcher`/`FileSystemWatcher`-lifecycle hing. `Flush(true)` was niet de
directe oorzaak. De test-only fixture seedt nu alleen de gelezen watcher- en
active-trackstatus; assertions en de echte writerdekking bleven intact.
Daarna waren de probleemtest 3x, bridge 30/30, StructureHandoff 16/16, 4H
targeted .NET 47/47, volledige .NET 854/854, Python 185/185, BeatBeam 107/107
en build 0 warnings/0 errors groen.

Na verse deployment werd de runtimeblocker vastgesteld als
`PLAYLIST_WATCHER_STARTUP_BLOCKED_PRE_BIND`: de bridge blokkeerde vóór de
Unix-socket bind. De lifecyclefix laat `UnixBridgeServer` eerst binden en start
de `PlaylistWatcher` daarna asynchroon via expliciete `Start()`; een
bindvolgorde-regressietest is toegevoegd. De fix wijzigt geen temporal- of
eventsemantiek. Eindvalidatie: bridge 31/31, SongAnalyzer .NET 855/855,
ARM64 self-contained publish/socket-smoke PASS, ARM64/signing/plugin-verificatie
PASS, `bridge.sock` beschikbaar, diagnostics geldig en native plugin- plus
active-tracktelemetrie ontvangen.

Vier-anchor runtimeconclusie: U08 (Upward) heeft section-relative-energy
ongeveer 0.43→0.88 maar een lokale RMS-edge van ongeveer +0.03→−0.52 en
EnergyDelta −0.56; één-bar landing verklaart Upward dus niet universeel. U16
(Upward) gaat zowel section-state als lokale edge omlaag; de eerdere hypothese
dat U16 lokaal omhoog zou zijn is niet bevestigd. M07 (Not Upward) heeft een
licht stijgende section-state maar duidelijk dalende lokale edge; M08 (Upward)
heeft beide stijgend. De vier technische projecties zijn PASS en tonen dat
één-bar edge-context informatief maar niet universeel voldoende is.

`UPWARD_ARRIVAL_CANDIDATE` is niet geïmplementeerd: geen gate, threshold, score,
confidence, classifier, winner of ranking. Alleen
`STRUCTURAL_TRANSITION_CANDIDATE` blijft geïmplementeerd.

`GEREED` M24A-5D-4I — read-only multi-scale temporal arrival diagnosis en
design-PASS. Tijdens workeranalyse bestaan per-bar `normalizedRms`,
`relative_energy`, normalized onset en normalized silence, maar de volledige
barreeksen zijn niet bewaard in audit-artifacts, AnalysisLibrary, phrase-cache
of huidige shadow handoff. Alleen de 4H-E1-randcontext blijft beschikbaar.
Daarom `MULTISCALE_EXISTING_DATA_STATUS = EXISTING_DATA_STILL_INSUFFICIENT`.

De audit gebruikte E1 (laatste/ eerste bar), E2 (laatste/ eerste twee bars) en
E4 (laatste/ eerste maximaal vier bars) uitsluitend als diagnostische vensters;
E2/E4 zijn geen productmetrics en waren zonder tijdelijke barreeksen niet
berekenbaar. U08 blijft `UPWARD_ARRIVAL` met dalende E1 en stijgende
section-state; bars 2–4 ontbreken, dus
`U08_MULTISCALE_EXPLANATION_STATUS = INSUFFICIENT_DATA`. U16 blijft
`UPWARD_ARRIVAL` met dalende E1 en section-state; bars 2–4 ontbreken en de
boundary-alignment is `CLEAN`, dus
`U16_MULTISCALE_EXPLANATION_STATUS = INSUFFICIENT_DATA`. M07 (`NOT_UPWARD`)
heeft dalende E1 bij licht stijgende section-state; M08 (`UPWARD`) heeft beide
stijgend. Dit contrast is informatief, maar E2/E4 blijven onbekend.

Boundary alignment is `CLEAN` voor U08, U16, M07 en M08 (M08 terminal); geen
van de vier anchors vraagt nu om boundaryverschuiving of segmentationdiagnose.
Onset/silence bestaan per bar in de worker, maar alleen E1-delta is bewaard;
geen multi-scale conclusie of nieuwe onset-/silencevelden zijn gemaakt. Er is
geen voldoende onderbouwde multi-scale arrival-routehypothese. Er is geen
nieuwe audiofeature nodig.

`UPWARD_ARRIVAL_CANDIDATE` blijft niet geïmplementeerd: geen gate, threshold,
score, classifier, confidence of ranking. Alleen
`STRUCTURAL_TRANSITION_CANDIDATE` blijft geïmplementeerd. Baseline blijft
`m14-v5` / `phrase-analysis-v17`; M23A blijft `BEZIG`.

`GEREED` M24A-5D-4J — read-only multi-scale temporal shadow exposure design +
design-PASS. `MULTISCALE_EXPOSURE_DESIGN_STATUS = READY_FOR_IMPLEMENTATION`
geldt uitsluitend voor additive exposure; geen upward-arrival gate, semantic
classifier of threshold. De bestaande route blijft beat-RMS → baraggregatie /
track-robuste normalisatie → track-P10/P90-relative-energy → raw section
observations vóór High-refinement → shadow-eventprojectie. De window hoort vóór
het verlies van worker-bararrays in de bestaande raw-observation /
boundary-projectie te ontstaan. `boundaryBar` is 0-based en de eerste
destinationbar; sections zijn start-inclusive/end-exclusive en een pair moet
strict contiguous zijn.

Aanbevolen model: maximaal 4 origin- en 4 destinationbars, één ordered
relative sequence (variant B) met offsets `-4,-3,-2,-1,+1,+2,+3,+4`; geen
offset 0. De sequence wordt optioneel genest als `window` binnen
`BoundaryTemporalContextShadow`, uitsluitend onder
`shadow_analysis.event_evidence[].temporal_context.window`. Elk barsample bevat
alleen `RelativeBarOffset`, bestaande `NormalizedRms` en bestaande
`RelativeEnergy`; onset en silence blijven `DEFER`. Korte sections leveren een
partiële window zonder padding, duplicatie, nearest-bar of average fallback;
ongeldige/non-contiguous ranges of waarden geven `TemporalWindow = null`.

`E1_COMPATIBILITY_STRATEGY = A`: de bestaande vier 4H-fields blijven behouden
en offsets `-1/+1` moeten exact overeenkomen; mismatch is fail-closed. Window,
E1, EnergyDelta en section-relative-energy zijn temporele views uit dezelfde
beat-RMS-provenancefamilies, geen extra votes. Schema v2 blijft additive,
backward-compatible, optional/nullable, shadow-only, ephemeral en Debug-only;
geen AnalysisLibrary-, cache-, persistence- of version-bump. E1/E2/E4 zijn
uitsluitend calibration derivations. Een gerichte human calibration gebruikt
10 bestaande boundaries (U08, U16, M07, M08, vijf reviewed controls en één
ambiguous case), zonder vooraf getoond human verdict. Payloadraming blijft
circa 10,7 KiB per track en 860 KiB voor de 1.529-boundary auditset.

`M24A-5D-4K — Implement multi-scale temporal shadow exposure` — `STATUS =
4K_RUNTIME_PASS — READY_FOR_MULTISCALE_HUMAN_CALIBRATION`. De additive
temporal context is runtime-gevalideerd met `temporal_context.window.bars[]`:
maximaal vier origin- en vier destinationbars, offsets `-4…-1,+1…+4`, en
uitsluitend `RelativeBarOffset`, `NormalizedRms` en `RelativeEnergy`. Schema v2
is additive, partial/fail-closed en behoudt E1 `-1/+1`-compatibility en de
`EnergyDelta`-invariant. Onset en silence zijn nog niet geïmplementeerd en er
zijn geen production semantic wijzigingen. 4K mag uitsluitend deze additive
window, schema-v2-serialisatie, parser/Debug, tests en fresh deployment implementeren; geen
`UPWARD_ARRIVAL_CANDIDATE`, gate, threshold, score, classifier, confidence,
ranking, nieuwe audiofeature/Essentia-call, onset/silence-window,
AnalysisLibrary-persistence, cachewijziging of version bump. `UPWARD_ARRIVAL_CANDIDATE`
blijft niet geïmplementeerd; alleen `STRUCTURAL_TRANSITION_CANDIDATE` blijft
geïmplementeerd. Baseline blijft `m14-v5` / `phrase-analysis-v17`; M23A blijft
`BEZIG`.

`M24A-5D-4L` = `GEREED — blind multi-scale human calibration + human-review
PASS`. Stopstatus: `4L_CALIBRATION_PASS — READY_FOR_HUMAN_REVIEW_OF_FINDINGS`.
De exact tien reeds human-reviewed boundaries (U08, U16, M07, M08, U01, U02,
U05, U07, U10 en U06) zijn vers blind geanalyseerd en pas daarna aan de labels
gekoppeld; U06 bleef `AMBIGUOUS`. Er was geen labelgestuurde featureselectie,
tuning, accuracy- of thresholdoptimalisatie. U08 is
`EXPLAINS_E1_EXCEPTION`; U16 is `DOES_NOT_EXPLAIN`; het M07/M08-contrast is
`STRENGTHENED`. E4 voegt descriptief de duidelijkste aanvullende context toe,
maar positieve energy-windows overlappen met U05 en U06.

`MULTISCALE_ENERGY_CALIBRATION_STATUS = ENERGY_WINDOWS_PARTIALLY_INFORMATIVE`.
Geen E1-, E2-, E4-, section-delta- of gecombineerde energy-only gate is
gevalideerd; `UPWARD_ARRIVAL_CANDIDATE` is niet geïmplementeerd. De enige
bestaande nieuwe shadow-eventhypothese blijft
`STRUCTURAL_TRANSITION_CANDIDATE`.

`NEXT_DIRECTION = B`: energy-window helpt, maar moeilijke cases vereisen eerst
read-only onderzoek naar bestaande onset- en silence-temporal context.
`ONSET_SILENCE_STATUS = READ_ONLY_INVESTIGATION_JUSTIFIED`; dit is geen
productfield-, exposure- of schemawijziging en niet `INCLUDE_NOW`.

### M24A-5D-4M — Onset/silence temporal calibration audit

`STATUS = GEREED — blind onset/silence temporal calibration audit + human-review
PASS`. Stopstatus: `4M_CALIBRATION_PASS — READY_FOR_HUMAN_REVIEW_OF_ACTIVITY_RELEASE_FINDINGS`.
Dezelfde tien 4L-anchors zijn gebruikt; onset/silence zijn eerst blind
geëxtraheerd en pas daarna met human labels gejoined. U06 bleef `AMBIGUOUS` en
werd niet als positief of negatief trainingspunt behandeld. Er was geen
labelgestuurde tuning, threshold- of accuracy-optimalisatie.

De bestaande `onsetStrength` per beatframe gebruikt de gemiddelde positieve
sample-afgeleide; `silencePercentage` gebruikt het percentage samples met
`abs(sample) < 0.001`. `aggregate_bars` gebruikt dezelfde bar-indexruimte als
de raw boundary-context; `robust_normalize` past bestaande mediaan/IQR-
normalisatie, fallbacks en begrenzing op `[-4,4]` toe. Er zijn geen nieuwe
audiofeatures of Essentia-calls toegevoegd.

`U16_ACTIVITY_RELEASE_STATUS = DOES_NOT_EXPLAIN`: energy, onset en silence
verklaren gezamenlijk de menselijke `UPWARD_ARRIVAL` niet. U05 blijft
`NOT_IMPROVED`; U06 is `EVIDENCE_BECOMES_ONE_SIDED` zonder herlabeling; U08 is
`ADDS_CLEAR_INFORMATION`; M07/M08 is `CONTRADICTED`.

`ONSET_INCREMENTAL_INFORMATION_STATUS = PARTIALLY_ADDITIVE` en
`SILENCE_INCREMENTAL_INFORMATION_STATUS = PARTIALLY_ADDITIVE`.
`LOW_LEVEL_TEMPORAL_EVIDENCE_STATUS = LOW_LEVEL_TEMPORAL_EVIDENCE_NOT_SUFFICIENT`.
`ONSET/SILENCE EXPOSURE = NOT JUSTIFIED AS NEXT IMPLEMENTATION STEP` en
`NEW_AUDIO_FEATURES_NEEDED = NO`. Er zijn geen shadow fields, handoffvelden,
schema-uitbreiding, gate, threshold, score, classifier of confidence toegevoegd.

`NEXT_DIRECTION = D`: terug naar inhoudelijk andere musical, structural en
contextual evidence; geen verdere stapeling van vergelijkbare low-level
boundarymetrics. `UPWARD_ARRIVAL_CANDIDATE` blijft niet geïmplementeerd; alleen
`STRUCTURAL_TRANSITION_CANDIDATE` blijft geïmplementeerd.

### M24A-5D-4N — Musical/structural arrival context audit

`STATUS = GEREED — blind musical/structural arrival context audit + human-review PASS`.
Stopstatus: `4N_STRUCTURAL_AUDIT_PASS — READY_FOR_HUMAN_REVIEW_OF_CONTEXT_FINDINGS`.
De exact dezelfde tien anchors als 4L/4M zijn gebruikt: U08, U16, M07, M08,
U01, U02, U05, U07, U10 en U06; U06 bleef `AMBIGUOUS`. Structurele evidence
is eerst blind geëxtraheerd en pas daarna met human labels gejoined. Er was
geen labelgestuurde tuning, threshold, score of accuracy-optimalisatie.

De provenance/circularity is vooraf geaudit. Gebruikt zijn alleen provenance-
clean pre-native raw observations/boundaries, section-family identity,
occurrence/return-context, recurrence, family salience, membership-exit,
structural route, terminaliteit en actuele shadowprojectors waar veilig.
Canonical roles, PhraseType/canonical classification, canonical output,
native High/Mid/Low als musical meaning, native/Rekordbox phrase types en
human verdicts als input zijn uitgesloten.

`CANONICAL_ROLE_USED_AS_INPUT = NO`.

U16 gaat van `section-family-002` naar `section-family-001`: destination is
occurrence 3/3 en een `RETURN`; origin is occurrence 14/14 en structureel
salienter/recurrenter. Veilige evidence: `MembershipExitStrength ≈ 0.939565`,
`StructuralEvidence ≈ 0.841682`, `StructuralRoute = family-exit`, destination
non-terminal. De bestaande `STRUCTURAL_TRANSITION_CANDIDATE` is aanwezig,
maar was geen input. `U16_STRUCTURAL_CONTEXT_STATUS =
PARTIAL_CONTEXTUAL_EXPLANATION`: descriptief plausibele structural release/
return zonder acoustische rise, maar niet breed genoeg voor een arrivalregel.

`U08_STRUCTURAL_ADDED_VALUE = PARTIALLY_ADDITIVE` (same-family return naast
de nuttige E4-context).
`M07_M08_STRUCTURAL_CONTRAST = PRESERVED`: M07 is NOT_UPWARD en same-family
return; M08 is UPWARD, return en terminal; terminaliteit is geen blocker.
`U05_STRUCTURAL_DISCRIMINATION_STATUS = NOT_IMPROVED`: same-family return,
maar geen oplossing voor de eerdere energy false-positive.
`U06_STRUCTURAL_AMBIGUITY_STATUS = PRESERVED`: family context onvoldoende.

Alleen U16 van de tien anchors heeft `STRUCTURAL_TRANSITION_CANDIDATE`; vier
andere bekende UPWARD-cases missen deze. De candidate is dus geen proxy voor
`UPWARD_ARRIVAL` en wordt niet aangepast.

`RETURN_RECURRENCE_INFORMATION_STATUS = PARTIALLY_ADDITIVE`.
`FAMILY_SALIENCE_INFORMATION_STATUS = NOT_INFORMATIVE`.
`SEQUENCE_CONTEXT_INFORMATION_STATUS = PARTIALLY_ADDITIVE`.
`STRUCTURAL_TRANSITION_INFORMATION_STATUS = PARTIALLY_ADDITIVE`.
`MUSICAL_STRUCTURAL_CONTEXT_STATUS = PARTIALLY_INFORMATIVE`.
`NEW_AUDIO_FEATURES_NEEDED = NO`.
`NEXT_DIRECTION = C`: recurrence/family evidence is nuttig, maar sequence-
context moet eerst dieper read-only worden onderzocht. Geen aanvullende
shadow exposure is daarvoor eerst nodig; bestaande 3B raw observability is
voldoende.

Geen `UPWARD_ARRIVAL_CANDIDATE`, gate, threshold, score, classifier,
confidence, nieuwe fields, productionwijziging of nieuwe audiofeature.

### M24A-5D-4O — Sequence-context arrival pattern audit

`STATUS = GEREED — blind sequence-context arrival pattern audit + human-review PASS`.
Stopstatus: `4O_SEQUENCE_AUDIT_PASS — READY_FOR_HUMAN_REVIEW_OF_SEQUENCE_FINDINGS`.
Dezelfde tien anchors als 4L/4M/4N zijn gebruikt; U06 bleef `AMBIGUOUS`.
Sequence-context is eerst blind gereconstrueerd uit provenance-clean 3B raw
observations/familyvelden en directe raw section ordering, zonder nearest-
sectionheuristiek, ingevulde identities, canonical/native semantics of
labelgestuurde tuning. Daarna zijn de human labels gejoined.

`CANONICAL_ROLE_USED_AS_INPUT = NO`.

U16 heeft raw sequence `family-001 × 2 → family-002 × 7 → Unknown →
family-002 × 7 → family-001 → Unknown`. Rond de boundary is dit
`family-002 → family-002 → family-002 → family-001 → Unknown`: origin
family-002, occurrence 14/14, laatste occurrence en actuele contiguous run 7;
destination family-001, occurrence 3/3, eerder gehoord, return distance 15 en
geen destination-continuation. De bestaande family-exit/membership-exit-context
blijft relevant. Dit langere patroon is uniek in de calibratieset.

`U16_SEQUENCE_CONTEXT_STATUS = PARTIAL_SEQUENCE_EXPLANATION`.
`U08_SEQUENCE_ADDED_VALUE = MOSTLY_REDUNDANT`.
`M07_M08_SEQUENCE_CONTRAST = STRENGTHENED`.
`U05_SEQUENCE_DISCRIMINATION_STATUS = PARTIALLY_IMPROVED`.
`U06_SEQUENCE_AMBIGUITY_STATUS = PRESERVED`.
`RETURN_DISTANCE_INFORMATION_STATUS = PARTIALLY_ADDITIVE`.
`OCCURRENCE_POSITION_INFORMATION_STATUS = MOSTLY_REDUNDANT`.
`RUN_LENGTH_INFORMATION_STATUS = PARTIALLY_ADDITIVE`.
`DESTINATION_CONTINUATION_INFORMATION_STATUS = NOT_INFORMATIVE`.
`SEQUENCE_PATTERN_CONTEXT_STATUS = PARTIALLY_INFORMATIVE`.

De combinatie lange origin-run + laatste origin occurrence + return naar een
gevestigde destination family + afstand 15 + family-exit is een
`U16-SPECIFIC OBSERVATION`, geen algemene contextual-arrival route. Alleen U16
heeft in de tien-set `STRUCTURAL_TRANSITION_CANDIDATE`; vier andere UPWARD-
cases missen hem. De candidate blijft referentie-only en geen UPWARD-proxy.

`NEXT_DIRECTION = C`: zoek eerst gerichte structureel vergelijkbare controls.
`NEW_AUDIO_FEATURES_NEEDED = NO`.
`ADDITIONAL_SHADOW_EXPOSURE_NEEDED = NO` voor de eerstvolgende read-only audit;
bestaande 3B raw observability is voldoende.

Geen `UPWARD_ARRIVAL_CANDIDATE`, gate, threshold, score, classifier,
confidence, nieuwe fields, exposure, productie- of sequence-contextcode.

### M24A-5D-4P — Targeted sequence-analogue control audit

`STATUS = GEREED — blinded human-review PASS; analogue evidence MIXED`.
De blindering-integriteit is PASS; zes vooraf vastgelegde verdicts zijn pas na
unblinding met de selectiekey vergeleken. Complete U16-like coreanalogues:
2 `UPWARD`, 1 `NOT_UPWARD`; de partial family-exit analogue is `AMBIGUOUS`, de
partial last-origin/non-zero-return analogue `UPWARD` en het origin-not-last
contrast `NOT_UPWARD`.

Long run + last origin + non-zero return is dus geen algemene arrivalregel.
De exacte U16 plus-family-exit context blijft onvoldoende extern gecontroleerd;
U08 wordt niet als sequence-regel versterkt. `NEW_AUDIO_FEATURE_NEEDED = NO`.

### M24A-5D-4Q — Mixed contextual-evidence synthesis audit

`STATUS = GEREED — synthesis PASS; recurrence-core rejected; exact U16 family-exit/destination/non-terminal conjunction requires targeted controls`.

De U16 recurrence-core is als algemene regel verworpen: run length + origin-last
+ non-zero return is `NON_DISCRIMINATING`. Family-exit is
`PARTIALLY_INFORMATIVE` maar ondergecontroleerd; destination identity is
`INCONCLUSIVE` en terminaliteit `NON_DISCRIMINATING`. Bestaande audio-evidence
blijft `SUPPORTING_SOFT_CONTEXT`; een algemene upward rule is `NOT_READY` en
multiple context routes zijn plausibel maar niet gevalideerd.

`NEW_AUDIO_FEATURE_NEEDED = NO`; implementation readiness is `NOT_READY`.
Het primaire gat blijft: externe provenance-clean controls voor de exacte U16
family-exit + recurring destination + non-terminal conjunction.

### M24A-5D-4R — Family-exit conjunction control-universe audit

`STATUS = GEREED — control-universe PASS; broad U16 conjunction falsified as general rule`.

De provenance-clean control universe omvat 173 tracks, 1.529 transitions,
1.150 evaluable transitions en 379 `UNKNOWN`/non-evaluable transitions.
Predicate: `FAMILY_EXIT + DESTINATION_SEEN_BEFORE + NON_TERMINAL`. Er zijn 10
complete matches en 9 onafhankelijke externe complete controls, met bestaande
complete verdicts: 1 `UPWARD`, 2 `NOT_UPWARD`, 1 `AMBIGUOUS`, 6 `UNREVIEWED`.
B3-0441 en B3-0883 zijn onafhankelijke complete `NOT_UPWARD`-controls; de
brede drie-conditionele U16-conjunction is daarom
`FALSIFIED_AS_GENERAL_RULE` en de density `VERY_SPARSE`.

U16's f002→f001 family-ID-wissel heeft geen externe vergelijkbare control.
`NEW_HUMAN_CONTROL_REVIEW_NEEDED = NO`; `NEW_AUDIO_FEATURE_NEEDED = NO` en
implementation readiness blijft `NOT_READY`.

### M24A-5D-4S — Corpus gap / hypothesis deprioritization decision

`STATUS = GEREED — deprioritization PASS; U16-specific route stopped, family topology retained only as bounded soft-context research boundary`.

De brede U16-conjunction blijft rejected. Het U16 family-ID-paar is
track-lokaal; er is geen established cross-track relationele U16-subcontext en
het overfit-risico is `HIGH`. `CONTINUE_U16_SPECIFIC_CONTROL_SEARCH = NO`.
Multiple context routes blijven plausibel maar niet gevalideerd; bestaande audio
blijft `SUPPORTING_SOFT_CONTEXT`, `NEW_AUDIO_FEATURE_NEEDED = NO`, classifier
rule readiness is `NOT_READY` en context-model readiness is
`NEEDS_MORE_TARGETED_EVIDENCE`.

De behouden structurele richting is raw family recurrence/topology uitsluitend
als zachte context.

### M24A-5D-4T — Generalizable family-recurrence topology boundary audit

`STATUS = GEREED — topology boundary PASS; predecessor/successor relation topology selected for targeted evidence audit`.

Track-lokale family IDs zijn uitgesloten. Occurrence/order/neighbour-relations
zijn derived stable; `StructuralRoute` is `RAW_STRUCTURAL` maar deels gekoppeld
aan membership/context en low-level boundary evidence. Topology audio
independence is `PARTIALLY_AUDIO_DERIVED`.

Occurrence/return/destination-aliases zijn grotendeels redundant;
predecessor/successor-beschikbaarheid is hoog, terwijl relationele
neighbourvelden low–medium dekking hebben. Recurrence topology blijft soft-
context candidate, destination topology is `TOO_REDUNDANT` en predecessor/
successor field readiness is `READY_FOR_TARGETED_EVIDENCE_AUDIT`. Forbidden
reconstructions blijven actief; composite context model is `NOT_READY`,
`NEW_AUDIO_FEATURE_NEEDED = NO` en implementation is `NO`.

### M24A-5D-4U — Local predecessor/successor relation topology targeted evidence audit

`STATUS = GEREED — neighbour evidence PASS; mostly redundant; no surviving independent neighbour evidence family`.

De transition universe omvat 1.529 overgangen, met 489 volledige P/O/D/S-
windows en 13 relation signatures. De signatures worden gedomineerd door
redundante continuity/run-patterns: `P=O` en `D=S` zijn directe run-aliases,
`P=D` is een immediate-return-alias, `O=S` is een
next-occurrence-distance-1-alias en `O=D` is een same-family-transition-alias.
`P=S` blijft onafhankelijk maar onvoldoende gelabeld. De incremental
information van neighbour evidence is daarom `MOSTLY_REDUNDANT`; neighbour
evidence is `REDUNDANT` en surviving neighbour evidence families zijn `NONE`.
Het composite context model blijft `NOT_READY`, `NEW_AUDIO_FEATURE_NEEDED = NO`
en implementation is `NO`.

### M24A-5D-4V — Broader ArrangementProfile context boundary synthesis

`GEREED — arrangement-context synthesis PASS; microhypothesis search closed;
ready for precanonical profile→canonical architecture contract`.

De 4L–4U-microhypotheselijn is formeel afgesloten. Structure-first architecture
is `SUPPORTED`; audio is supporting multi-role context, family topology is
supporting structural context en canonical interpretation blijft downstream.
Er is geen nieuwe audiofeature nodig en structural microhypothesis search is
`STOP`. De composite context architecture is ready for design; de resterende
gap is het eenrichtingscontract van precanonical profile naar canonical role.

### M24 Architecture Contract Milestone — Precanonical Profile → Canonical One-Way Input Contract

`GEREED/HOLD — precanonical one-way contract PASS; bounded implementation
blocked only by missing provenance-clean canonical semantic decision contract`.

De shadow/precanonical pipeline is canonical-independent `PASS`; one-way,
missingness en provenance zijn contractueel vastgelegd. High/Mid/Low is
verboden als nieuwe canonical input, genre blijft buiten het eerste bounded
pad en dual-compute met legacy authority is gekozen. Zolang de candidate een
ephemeral sidecar blijft is geen version/persistence bump nodig. De enige
resterende blocker is een pure canonical semantic candidate policy.

### M24 CANONICAL SEMANTIC DESIGN MILESTONE — Provenance-clean Candidate Role Decision Contract

`GEREED — semantic design PASS; pure provenance-clean canonical candidate
contract ready for bounded implementation`.

De vocabulary is de clean subset Intro / Verse / PreChorus / Chorus / Bridge /
Outro; Unknown/abstention is geldig en er is geen Other. Structure leidt
character evidence via multi-evidence interpretation with abstention. De eerste
bounded path krijgt geen numeric confidence. Legacy blijft uitsluitend
comparison/authority en nooit candidate input. Versioning/persistence blijven
ongewijzigd; implementation kan één milestone zijn en er zijn geen resterende
human product decisions.

### M24 BOUNDED IMPLEMENTATION MILESTONE — Precanonical Profile → Canonical Candidate Path

`GEREED — provenance-clean canonical candidate sidecar implemented; Git
layering resolved through verified M24 foundation prerequisite commit;
dual-compute legacy authority preserved; ready for calibration + human
acceptance`.

Foundationcommits `f79c071918ed914ab7e70ea860ca08eb44400bf3` en
`cdbe50ee8bdcf70e19cb90acc1ec76911d0d4d31` leggen de bestaande
RawSectionObservation/ArrangementProfileShadow-laag vast; candidatecommit
`b6b04d051b1ca88d349a786f790a4189f0a19808` bevat de zuivere sidecar-delta.
Beide committed snapshots bouwen in Release met 0 warnings/0 errors. De
candidatecommit bevat 52 nieuwe candidate-tests; de schone snapshot haalt
901/901 .NET-tests (de eerdere 909 bevatte acht beschermde, ongecommitteerde
testgevallen). Legacy authority, persistence, versions en BeatBeam/VirtualDJ
handoff zijn ongewijzigd. De candidate heeft geen authority, introduceert geen
nieuwe audiofeatures en gebruikt geen numeric role score/weight/threshold.

### M24 CALIBRATION + ACCEPTANCE MILESTONE — Canonical Candidate Semantic Quality

`GEREED — M24_CANONICAL_ARCHITECTURE_PASS_SEMANTIC_TUNING_REQUIRED —
CANONICAL_PATH_VALIDATED_BUT_ROLE_PROJECTOR_NOT_READY_FOR_AUTHORITY`.

De frozen candidate is op het volledige provenance-clean corpus van 173 tracks
en 1702 sections gekalibreerd: 1102 Produced (64,75%), 593
InsufficientEvidence (34,84%), 7 Conflict en 0 NotProduced. Alle freeze-hashes,
determinisme (173/173), recurrence-relabel invariance, structural-first,
software-onafhankelijke provenance en role-contract sanity zijn PASS. De
24-case blinde menselijke review gaf 7/18 exacte Produced-matches (38,89%);
Bridge was vooral systematisch te breed (1/8 exact; dikwijls Verse/Chorus),
Verse was ondergedetecteerd, Chorus mogelijk te breed en de 5 valide
abstention-controls gaven ieder een duidelijke menselijke role. REVIEW-01 is
als section-boundary/alignment-quality finding buiten de pure accuracy-noemer
gehouden. Architecture acceptance is PASS; semantic-classifier acceptance en
production-authority acceptance zijn FAIL voor de huidige projector. Candidate
blijft sidecar/no-authority; legacy blijft production authority; persistence,
versions en BeatBeam/VirtualDJ-handoff blijven ongewijzigd.

Volgende milestone: `M24 CANONICAL ROLE CALIBRATION — Human-Grounded Role
Semantics`; dit wordt één grotere human-grounded calibration milestone zonder
terugkeer naar mood/native, literal family-ID, neighbour- of family-exitregels.

### M24 CANONICAL ROLE CALIBRATION — Human-Grounded Role Semantics

`STATUS = GEREED — M24_CANONICAL_ROLE_CALIBRATION_PARTIAL —
ONE_BOUNDED_SEMANTIC_REFINEMENT_REQUIRED`.

SongAnalyzer-commit `1a6d3262664d62127ef78222b4bd6f05a2e80814` implementeert
Semantic Role Contract v2 met tracklokale recurrence-runs, gevestigde
focal/bodycycles, scoreloze predecessor/departure-resolutie en orthogonale
section-character. De oorspronkelijke 24 cases zijn uitsluitend calibration:
23 valide cases verbeterden 7→12 exact en 5→4 possible over-abstention. Op 173
frozen tracks gingen Verse 17→329, Bridge 231→6, Chorus 710→642 en volledig
abstained 57→58; PreChorus is abstract relationeel bereikbaar maar geen frozen
input voldoet aan het volledige contract.

De onafhankelijke 24-track frozen holdout is vóór tuning geselecteerd, heeft nul
overlap met de calibration-set en de packet-hash bleef exact gelijk. Na unblinding
is post-v2 9/24 exact bij 20 Produced (45,0%), 11 role mismatches en 4 heldere
human-role abstentions; pre→post is 7→9 exact en 7→4 abstentions. Intro
function-over-material is ondersteund (HOLDOUT-04), Verse generaliseert slechts
partieel, Bridge-overbreadth is weg maar true-positive Bridge is 0/4, Chorus is
partieel en PreChorus is 0/2 met ontbrekende relationele input-evidence. Overfit
risk is MODERATE. Architecture acceptance is PASS; semantic-classifier en
production-authority acceptance zijn HOLD. Candidate blijft sidecar/no-authority;
legacy blijft production authority; persistence, versions en BeatBeam/VirtualDJ-
handoff zijn ongewijzigd.

Exacte volgende milestone: `M24 CANONICAL ROLE REFINEMENT — Bounded
Holdout-Grounded Semantic Corrections`. Dit is één bounded refinement op de nu
zichtbare algemene failure patterns, gevolgd door een kleinere tweede
onafhankelijke validation set vóór enige authority-overweging.

### M24 CANONICAL ROLE REFINEMENT — Bounded Holdout-Grounded Semantic Corrections

`STATUS = GEREED — M24_CANONICAL_ROLE_REFINEMENT_PARTIAL —
SPECIFIC_SEMANTIC_BLOCKER_REMAINS`.

De eerdere role-calibration blijft `GEREED — PARTIAL`: projector v2
generaliseert aantoonbaar, maar één bounded, holdout-grounded semantic
refinement is nodig. Voor iedere v3-codewijziging wordt een derde onafhankelijke
blinde validation-set bevroren. De 48 bekende menselijke cases worden daarna
uitsluitend als calibration-evidence gebruikt. Candidate authority blijft NONE;
legacy authority, persistence, versions en downstream handoffs blijven
ongewijzigd.

SongAnalyzer-commit `85daf3ea89cf8f4389ee8d2c4427c6e8722572cb`
implementeert v3-correcties voor return-gated one-off Bridge, functionele
PreChorus-routes, directionele focal destinations en retrospectieve early body.
Alle 48 bekende human cases zijn uitsluitend calibration-evidence (47 valide):
exact 21→25, mismatches 18→15 en abstention 8→7. Human Bridge is 0→1 true
positive met 0 v3-false positives; de vijf resterende cases hebben een concrete
return/cycle/inputblocker. Beide human PreChorus-cases zijn exact; runtime is
41 sections op 25 tracks en blijft blind te valideren.

De derde validation-set is vóór coding bevroren: 18 unieke tracks/sections,
één per track en nul overlap met beide eerdere human sets; het packet bleef
byte-identiek. Op 173 frozen tracks gaat Produced 1193→1230, PreChorus 0→41 en
Bridge 6→15, met determinism/relabel PASS 173/173. Candidate authority blijft
NONE; legacy authority, persistence, versions en BeatBeam/VirtualDJ-handoff zijn
ongewijzigd.

De onafhankelijke, vóór refinement bevroren Set C is integer: 18 unieke tracks
met nul eerdere human-overlap; één geval is valide `UNCLEAR`, geen audio/window-
fout (focus binnen de laatste raw section en vóór de echte audiogrens). Op 17
valide semantic cases is de onafhankelijke delta MIXED: v2 11→v3 10 exact,
mismatch 3→5 en abstention 3→2. Intro is 2/2, Chorus 3/3 en Outro 1/1; Bridge
heeft één menselijke case, gemist zonder false-positive Bridge. De concrete
blocker is PreChorus: 0/4 exact, twee abstentions, twee Verse/Chorus-mismatches
en twee Verse→PreChorus false positives. Overfit risk is MODERATE, beperkt tot
die v3-route. Architecture acceptance blijft PASS; semantic-classifier en
production-authority acceptance zijn HOLD. Candidate blijft NONE; legacy,
persistence, versions en handoffs zijn ongewijzigd.

Exacte volgende milestone: `M24 CANONICAL PRECHORUS EVIDENCE BOUNDARY
DECISION`. Die ene bounded beslissing bepaalt of bestaande evidence een
generaliseerbare canonical PreChorus kan dragen of fail-closed buiten de
candidate baseline moet blijven; nog niet gestart.

### M24 CANONICAL PRECHORUS EVIDENCE BOUNDARY DECISION

`STATUS = GEREED — M24_PRECHORUS_EVIDENCE_BOUNDARY_PASS —
CURRENT_EVIDENCE_INSUFFICIENT_FOR_RELIABLE_PRECHORUS`.

De voorafgaande canonical-role-refinement is `GEREED — PARTIAL`. Independent
Set C valideerde Intro, Chorus en Outro grotendeels en Verse gedeeltelijk, maar
PreChorus generaliseerde niet: 0/4 onafhankelijke menselijke PreChorus-cases
was exact en twee menselijke Verse-controls werden false-positive PreChorus.
Deze begrenzingsmijlpaal bepaalt read-only of huidige provenance-clean evidence
een functionele preparation-role kan onderscheiden van normale body/Verse. Er
volgt hier geen nieuwe semantic tuning, audiofeature of projectorimplementatie.

De read-only audit gebruikt zes menselijke PreChorus-cases: twee Set-B-cases
die v3 na calibration exact maakte en vier onafhankelijke Set-C-cases waarvan
v3 er 0 exact had. De enige corpusbereikbare v3-route produceert 41 sections op
25 tracks, allemaal als niet-evalueerbare predecessor vóór twee compound focal
visits. Diezelfde topology verklaart zowel de twee Set-B-treffers als de twee
onafhankelijke menselijke Verse→PreChorus false positives. Directe adjacency,
herhaalde slotpositie, bodycontext, barlengte, focal return en bestaande
character/energy-evidence verwerpen die controls niet betrouwbaar. Andere true
cases vallen binnen focal material identity, missen een established cycle of
liggen in één samengevoegde recurrence-run.

Evidence-boundary C is daarom technisch beslist: huidige precanonical evidence
is onvoldoende voor betrouwbare PreChorus. Extra upstream diagnostiek bestaat,
maar geen exact bestaand, provenance-clean signaal draagt aantoonbaar de
functionele human route-equivalence; exposure zonder zo'n contract zou opnieuw
een arbitrary heuristic/scorezoektocht zijn. `PRECHORUS_DEFERABILITY =
SAFE_TO_DEFER`: vocabulary/schema kan stabiel blijven terwijl positieve
PreChorus-productie voorlopig fail-closed/abstain-only is. Geen nieuwe
audiofeature, menselijke luisterreview, SongAnalyzer-code of tests zijn
gewijzigd. Architecture blijft PASS; semantic-classifier en production
authority blijven HOLD. Candidate authority blijft NONE; legacy, persistence,
versions en BeatBeam/VirtualDJ-handoffs blijven ongewijzigd.

Exacte volgende milestone: `M24 CANONICAL BASELINE ACCEPTANCE — PreChorus
Deferred, Five-Role Authority Boundary`. Nog niet gestart; geen runtime
deployment.

### M24 CANONICAL BASELINE ACCEPTANCE — PreChorus Deferred, Five-Role Authority Boundary

`STATUS = GEREED — M24_CANONICAL_BASELINE_ACCEPTANCE_PASS —
PRECHORUS_DEFERRED_FIVE_ROLE_BASELINE_READY_FOR_AUTHORITY_DESIGN`.

Evidence Boundary C is `GEREED`: huidige evidence is onvoldoende voor
betrouwbare PreChorus en `SAFE_TO_DEFER`. Deze bounded implementation behoudt
de zesrole vocabulary, maar converteert positieve PreChorus-candidates naar
expliciete fail-closed abstention. Intro, Verse, Chorus, Bridge en Outro moeten
section-voor-section identiek blijven. Daarna wordt uitsluitend de five-role
semantic baseline gevalideerd en wordt een toekomstige authority-eligibility
boundary ontworpen; authority zelf blijft uit.

SongAnalyzer-commit `fb45497ccebc5541c98827fc0a13f837e12d76e2` behoudt de
zesrole vocabulary, maar converteert iedere anders Produced PreChorus-candidate
centraal naar `InsufficientEvidence`, role null en
`PreChorusEvidenceDeferred`. Er is geen stille Verse/Chorus-herclassificatie.
Op de 173-track frozen corpus gaat Produced 1230→1189 en
InsufficientEvidence 472→513: alle 41 positive PreChoruses verdwijnen, terwijl
Intro 93, Verse 346, Chorus 668, Bridge 15 en Outro 67 exact gelijk blijven.
Non-PreChorus candidate identity is PASS 1661/1661; determinism en recurrence-
relabel invariant zijn PASS 173/173. De twee bekende onafhankelijke
Verse→PreChorus false positives zijn beide fail-closed abstentions.

Onder 58 valide menselijke supported-role cases zijn 33 exact, 14 mismatch en
11 abstention; dit is geen nieuwe accuracyclaim maar behoud van alle bewezen
niet-PreChorus semantics zonder regression. Bridge blijft beperkt (7 human
cases: 1 exact, 4 mismatch, 2 abstention) en krijgt later een strengere
eligibilitygrens. Architecture en five-role semantic baseline acceptance zijn
PASS; production authority is HOLD. Candidate authority blijft NONE en legacy
blijft production authority. Persistence, versions en BeatBeam/VirtualDJ-
handoffs zijn ongewijzigd; geen nieuwe audiofeature, score, tracklookup of
authority-selector is toegevoegd.

De toekomstige authority-boundary is uitsluitend ontworpen: alleen provenance-
clean, conflictvrije Produced Intro/Verse/Chorus/Bridge/Outro met vereiste
structurele propositions en zonder essentiële missingness kunnen later in
aanmerking komen. PreChorus, abstentions, Conflict, Invalid en
UnavailableCacheHit zijn niet eligible.

Exacte volgende milestone: `M24 BOUNDED CANONICAL AUTHORITY DESIGN`. Nog niet
gestart; geen runtime deployment.

### M24 BOUNDED CANONICAL AUTHORITY DESIGN

`STATUS = GEREED — M24_BOUNDED_CANONICAL_AUTHORITY_DESIGN_PASS —
READY_FOR_GATE_OFF_SHADOW_SELECTOR_IMPLEMENTATION`.

Authoritygranulariteit is `HYBRID`: één same-request trackgate vereist een
volledig exact aligned candidate/legacy-boundarypartition; daarna kan alleen de
semantic role per exact gekoppelde section worden geselecteerd. Er is geen
boundary mutation, merge, split of overlapmatching. Mixed-source tracks zijn
alleen conditioneel toegestaan binnen zo'n identieke legacyordering en
boundaryset, met source/fallback per section observeerbaar. In de read-only
frozen audit waren 9/173 tracks (63 sections) volledig exact aligned; deze
coverage is geen accuracyclaim.

Eligibility is role- en evidence-specifiek: Intro vereist bewezen opening
framing, Verse alleen expliciete leading/trailing established-body matching,
Chorus een confirmed recurrent focal return en Outro zowel post-cycle framing
als closing position. Bridge blijft `DISABLED_FIRST_ROLLOUT`, omdat de huidige
candidate-diagnostics de human-zwakke Bridge-populatie niet authority-grade
kunnen vernauwen. PreChorus blijft vocabulary-only, positive production
deferred en `AUTHORITY_ELIGIBLE = NEVER`.

De pure selector ondersteunt `LEGACY_ONLY`, `SHADOW_COMPARE` en
`BOUNDED_CANDIDATE`, maar default en eerste wiring zijn hard `LEGACY_ONLY`.
Iedere missingness, conflict, invalid/cache-unavailable state, alignmentfout of
exception valt terug naar legacy; ontbrekende legacy wordt nooit door candidate
opgevuld. Eerste persistence is `IN_MEMORY_SHADOW_ONLY`: geen cache-invalidation
of reanalysis, geen AnalysisVersion/PhraseAnalysisVersion/schema bump en geen
BeatBeam/VirtualDJ-behaviorwijziging. Observability bevat sectionrecords en
trackaggregates zonder score/accuracyclaim; gate-off production identity moet
exact legacy blijven. Rollback is `TRIVIAL` via één mode. Er is geen human
productdecision nodig. Candidate authority blijft `NONE`; legacy blijft
production authority.

Exacte volgende milestone: `M24 BOUNDED CANONICAL AUTHORITY IMPLEMENTATION —
Shadow Selector + Gate-Off Parity`. Gate enable en runtime deployment zijn daar
beide `NO`.

### M24 BOUNDED CANONICAL AUTHORITY IMPLEMENTATION — Shadow Selector + Gate-Off Parity

`STATUS = GEREED — M24_BOUNDED_CANONICAL_AUTHORITY_IMPLEMENTATION_PASS —
READY_FOR_GATE_OFF_RUNTIME_ACCEPTANCE`.

SongAnalyzer-commit
`84cca3c0abcc67bc0b75de428e03a340d022bf02` implementeert de pure full-track
alignmentgate, role-specifieke eligibility, fail-closed selector en optionele
in-memory authorityobservatie. De service is hard `LegacyOnly`; er is geen
runtime-enablemechanisme. Production retourneert exact dezelfde legacy
`PhraseAnalysisResult`-referentie en onveranderde canonical sections.
`GATE_OFF_PRODUCTION_IDENTITY = PASS`; candidate productionselecties en
production source Candidate zijn beide 0.

Het alignmentcontract accepteert alleen een volledige count/index/bar/timing-
bijectie met `1e-6 s` tolerantie en zonder boundarymutation. Intro, expliciete
leading/trailing Verse, recurrent-focal Chorus en closing-frame Outro kunnen
alleen hypothetisch eligible zijn. Bridge blijft disabled en PreChorus nooit
eligible. De frozen read-only audit reproduceert 173 tracks / 1702 sections:
9 tracks / 63 sections exact aligned, 141 count mismatches en 23 bar
mismatches. Daarvan zijn 30 sections hypothetisch candidate-eligible (Intro 4,
Verse 2, Chorus 20, Outro 4), met 33 legacyfallbacks; production blijft 63/63
legacy. Dit is coverage/paritydiagnostiek, geen accuracyclaim.

De 104 nieuwe authority-cases overschrijden het minimum van 54; candidate-
regressies waren 85/85 en de volledige hoofdworktree-suite 1046/1046 groen.
Release-build: 0 warnings/0 errors. De clean committed snapshot bouwt schoon en
heeft authority 104/104 en candidate 85/85 groen; alleen de bekende externe
worker-venv-test ontbreekt daar (1037 groen, 1 environmentfailure). Geen
persistence-, cache-, AnalysisVersion-, PhraseAnalysisVersion-, downstream-
schema-, VirtualDJ- of BeatBeambehaviorwijziging en geen deployment. Candidate
production authority blijft `NONE`; legacy blijft production authority.

### M24 BOUNDED CANONICAL AUTHORITY RUNTIME ACCEPTANCE — Gate-Off Shadow Observation

`STATUS = GEREED — HOLD: M24_BOUNDED_CANONICAL_AUTHORITY_RUNTIME_ACCEPTANCE_HOLD — AUTHORITY_SELECTION_NOT_HUMAN_SAFE`.

De echte fresh `PhraseAnalysisService`-run is lokaal en niet-persistent uitgevoerd op
173 unieke corpus-tracks, met harde `LegacyOnly` productie-authority. Alle 173 tracks
zijn geanalyseerd zonder analyse-, worker- of servicefout. Productie bleef volledig
legacy (`canonicalCandidateSelectedCount = 0`); de production-identitycontrole is
173/173 PASS. De actuele alignmentverdeling is 10 `Exact` (76 secties), 142
`CountMismatch` en 21 `BarRangeMismatch`; de hypothetische selector zou 44 tracks
eligible maken (Intro 7, Verse 2, Chorus 30, Outro 5) en 32 tracks legacy fallback
laten houden. Zes cache-hits en 173 deterministische herhalingen zijn PASS.

De bestaande menselijke A/B/C-evidence bevatte geen veilige exacte mapping naar een
actuele fresh runtime-sectie. Het gefixeerde acht-case blinde authoritypacket
(`40272549938fc97c4b516b324c8e3f84967363953d74bf4ddf2d07cb07d16d3e`) is
integraal en pas na alle verdicts unblinded. De human verdicts waren Chorus,
Verse, Chorus, Unclear, PreChorus, Verse, Intro en Bridge. Candidate was exact
in één clear case, mismatch in zes; legacy was exact in drie clear cases. Van de
zeven candidate/legacy-differ-cases was candidate éénmaal beter, legacy driemaal
beter, tweemaal waren beide fout en één case was human-unclear.

Elke observed candidate role heeft daardoor een concrete human-clear mismatch:
Intro, Verse, Chorus en Outro zijn alle `HOLD_KNOWN_HUMAN_MISMATCH` en
`DISABLED_PENDING_FURTHER_EVIDENCE`. Bridge blijft disabled en PreChorus deferred.
Technische runtimeacceptatie blijft PASS, maar human safety en production authority
acceptance zijn HOLD. Production blijft legacy, candidate production authority
blijft `NONE`; er is geen enable-design, tuning of deployment gestart.
Er is daarom geen volgende authority-enable-design milestone: vervolg vereist een
nieuw expliciet en begrensd human-safetybesluit.

De runtimeacceptance observeert uitsluitend de gecommitteerde service-sidecar
op het lokale 173-track corpus, fresh en via cache-hit. Production blijft voor
iedere invocation hard `LegacyOnly`; geen deployment, enablepad,
authoritypromotion of sourcewijziging. `BoundedCandidate` blijft pure
test-/hypothetische semantiek.

### M24 CANONICAL AUTHORITY CLOSEOUT — Legacy-Only Production, Candidate Shadow Retained

`GEREED — M24_CANONICAL_AUTHORITY_CLOSEOUT_PASS — LEGACY_ONLY_PRODUCTION_CANDIDATE_SHADOW_RETAINED`.

De volledige M24 bounded-canonical-authority-lijn is administratief afgesloten:
de 173-track runtime-technische acceptance was PASS, maar de acht-case blind
authority review leverde slechts 1/7 human-clear candidate-exact op en 6/7
human-clear candidate-mismatches. Candidate was éénmaal beter, legacy driemaal
beter en beide waren tweemaal fout. Intro, Verse, Chorus en Outro blijven alle
`HOLD_KNOWN_HUMAN_MISMATCH`; Bridge is `DISABLED_BY_POLICY` en PreChorus
`DEFERRED_BY_POLICY`. `ROLES_ALLOWED_FOR_ENABLE_DESIGN = NONE`.

De definitieve productgrens is:

- `CANONICAL_CANDIDATE_PRODUCTION_AUTHORITY = DISABLED_UNDER_CURRENT_EVIDENCE_CONTRACT`;
- `LEGACY_SEMANTIC_PRODUCTION_AUTHORITY = ACTIVE`;
- `CANONICAL_CANDIDATE_SHADOW = RETAINED`;
- `AUTHORITY_OBSERVABILITY = RETAINED`;
- `BOUNDED_CANDIDATE_MODE = TEST_ONLY / NON-RUNTIME-ENABLEABLE`;
- `RUNTIME_ENABLE_MECHANISM = ABSENT`.

Geen huidige candidate role mag de legacy `SectionRole` overrulen. De authority-
lijn wordt niet heropend door strengere guards, nieuwe thresholds, exclusions,
match-proxies, role-whitelists of kleine nieuwe samples. Heropening is alleen
toegestaan bij wezenlijk nieuwe, onafhankelijke, generaliseerbare evidence die
niet uit legacy semantics, runtime-human labels, track-specific patronen of
numeric thresholdpatches komt en de bestaande false-positive classes werkelijk
discrimineert. Tot dan is de authority-roadmap `CLOSED / DEFERRED`.

`CanonicalCandidateProjection`, `PreChorus` fail-closed, alignment/eligibility-
evaluators, selector, `LegacyOnly`, shadow/hypothetical comparison, per-section
source/fallback-observability, deterministische trackaggregaten en de frozen
calibration/validation-artifacts blijven behouden als diagnostic/research-
infrastructuur; niets wordt verwijderd. `ARCHITECTURE_ACCEPTANCE = PASS` en
`FIVE_ROLE_SEMANTIC_BASELINE = PASS` blijven research-baselineclaims, geen
production-authorityclaim. `PRODUCTION_AUTHORITY_ACCEPTANCE = CLOSED_UNDER_CURRENT_EVIDENCE`.
PreChorus vocabulary blijft aanwezig maar production authority blijft deferred;
Bridge blijft semantically supported but weakly validated en authority-disabled.

De volgende grote bestaande productrichting is `M23A — Rich Musical Events voor
BeatBeam` (bestaande roadmapnaam, vervolg in deze closeout nog niet gestart):
structurele en muzikale evidence zoals boundaries, recurrence/families,
section-character, energy/build/release, arrivals/departures, drops, breaks,
transitions en Rich Musical Events direct bruikbaar maken voor de lighting engine
en live-integratielaag. Dit is nu passend omdat de low-level analyse-infrastructuur
en shadow-calibratie bestaan, terwijl canonical authority onder het huidige
evidencecontract gesloten is. De authority-afhankelijkheid is `NO`.

`HISTORICAL_NEXT_MAJOR_MILESTONE = M23A — Rich Musical Events voor BeatBeam`.
`HISTORICAL_NEXT_MAJOR_MILESTONE_STATUS = NOG NIET GESTART`.
Deze overgangsnotitie is superseded: de RME-foundation is completed; actuele
human holds en vervolgwerk staan uitsluitend in `MASTER_BACKLOG.md`.

## Historical M24A — Show-readiness framing (SUPERSEDED AS ACTIVE PRIORITY)

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

# 1. Historische productrichting (SUPERSEDED AS ACTIVE BACKLOG)

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

## 4.3 Parallel architectuurcheckpoint — Auto Show Intent Continuity Foundation

`GEREED — pure offline foundation + tests PASS` — Dit checkpoint bevat het
minimale architectuurcontract en de geïsoleerde foundationimplementatie.

`ShowIntent` is de interne, fixture-onafhankelijke visual-intent state tussen
muzikale/contextuele interpretatie en latere fixture-/group-programselectie:

`musical/context input → Show Interpreter → ShowIntent → fixture/group
interpretation → DMX rendering`

De huidige production Auto Show wordt hierdoor nog niet vervangen of gewijzigd.

### ShowIntent v0

De foundation bevat uitsluitend reeds afgesproken, fixture-onafhankelijke
inhoud:

- de bestaande section/phrase bucket;
- de bestaande begrensde energy modifier, met de huidige BeatBeam-semantiek,
  types en bounds als source of truth.

Er wordt geen nieuwe phrase-taxonomie of energy-normalisatie ontworpen. Tension,
danceability, drop, impact, transition strength, repetition variation, fixture
program, fixture identity, fixture group, DMX values, human override en
canonical SongAnalyzer-semantic uitbreiding vallen buiten v0 en blijven
downstream, voorlopig of toekomstig.

### Continuity-contract

`candidate = None` betekent: behoud de bestaande actuele `ShowIntent`. “Geen
nieuw event” betekent dus niet neutral, lights off, defaultprogramma of intent
reset.

Alleen wanneer geen eerdere intent bestaat, wordt een expliciete neutrale,
fail-closed initiële state gebruikt, waarbij latere implementatie bestaande
BeatBeam-neutral/fail-closed-semantiek hergebruikt. Een geldige expliciete
candidate vervangt de vorige intent als één immutable nieuwe state; partial
mutation en hidden carry-over buiten dit contract zijn niet toegestaan.

Fixture-/group-programselectie, handmatige override, DMX safety bounds,
fixture-rendering en DMX-output blijven buiten ShowIntent v0. Manual override en
safety blijven downstream leidend; ShowIntent mag die niet omzeilen.

ShowIntent is geen `event → hardcoded DMX-effect`-mapping, maar beschrijft
doorlopende fixture-onafhankelijke visuele intentie. Deze foundation is
onafhankelijk van M24A-5D-4P-verdicts, UPWARD_ARRIVAL, nieuwe SongAnalyzer
semantic roles, handoff-schemawijzigingen, VirtualDJ en productie-DMX.

### Volgende parallelle stap

`Auto Show Intent Continuity Foundation — implementation` — `GEREED — pure offline foundation + tests PASS`.

GEREED: de nieuwe pure module `show_intent.py` en synthetische testmodule
`tests/test_show_intent.py` bevatten een immutable `ShowIntent` met uitsluitend
`section_bucket` en `energy_modifier`. De bucketset is `intro`, `verse`,
`build`, `chorus`, `drop`, `down`, `break`, `outro` en `unknown`; een ongeldige
bucket valt terug op `unknown`. De energy modifier blijft binnen `-0.08 …
+0.08`; een ongeldige of niet-finite modifier valt terug op `0.0`.

De neutrale beginstate is `ShowIntent("unknown", 0.0)`. Bij een aanwezige
`previous` en `candidate = None` blijft exact dezelfde vorige intent behouden.
Een aanwezige candidate vervangt de vorige state atomair en immutable, zonder
hidden carry-over. Er is geen production wiring en geen fixture-, DMX-, UI-,
SongAnalyzer- of VirtualDJ-afhankelijkheid. De volledige BeatBeam-suite is
`119/119 PASS`; deployment is niet nodig. De production Auto Show is volledig
ongewijzigd.

Volgende parallelle ontwerpstap: `Show Interpreter Input Contract Audit` —
`NOG NIET GESTART`. Doel is read-only bepalen welke bestaande
production-safe muzikale/structurele input later een ShowIntent-candidate mag
vormen, zonder current_event/next_event production-wiring, SongAnalyzer
semantic wijzigingen, UPWARD_ARRIVAL of fixture-/DMX-mapping. Er wordt geen
implementatiescope vastgelegd voordat deze audit is afgerond.

### Show Interpreter Input Contract Audit

`GEREED — architecture/source audit PASS` —
`SHOW_INTERPRETER_INPUT_AUDIT_PASS — READY_FOR_DECISION`.

Het minimale immutable `ShowInterpreterInput` bevat uitsluitend de twee
`REQUIRED_V0`-velden `section_bucket: str` en `energy_modifier: float`; v0
bevat geen metadata. `section_bucket` is de reeds effectieve BeatBeam
section/phrase bucket, wordt upstream bepaald en wordt door Show Interpreter
v0 niet opnieuw geclassificeerd. `energy_modifier` is de reeds upstream
afgeleide en begrensde modifier binnen `-0.08 … +0.08`; v0 interpreteert geen
raw energy opnieuw. Er is dus geen dubbele bucketclassificatie of tweede
energy-classifier.

`OPTIONAL_V0`, maar nu niet geïmplementeerd: huidig segment
label/start/end/progress/confidence en rich-current level/progress/confidence.
`FUTURE_ONLY`: semantic section role/occurrence/family/energy,
`current_event`, `next_event` en Rich Musical Events. M23A/Rich Musical Events
blijven `BEZIG` en `RICH_EVENT_DEPENDENCY_V0 = NONE`. `DO_NOT_USE` in v0:
transportpositie, BPM, beat/bar, playback generation, discontinuity, raw rich
energy, M24/shadowcontext, native High/Mid/Low, manual overrides, fixtures en
DMX.

`STATE_OWNERSHIP_STATUS = CONTINUITY_RESOLVER_ONLY`: input bevat geen previous
ShowIntent; een toekomstige interpreter is een pure mapping naar een
ShowIntent-candidate of `None`, terwijl state en continuity bij
`resolve_show_intent(...)` blijven. Ongeldige of onvoldoende required input
mag geen musical meaning fabriceren: de latere interpreter mag `None`
retourneren en de resolver behoudt previous; zonder previous geldt
`ShowIntent("unknown", 0.0)`. `TRACK_BOUNDARY_RESET_POLICY =
NEEDS_PRODUCT_DECISION`; trackwissel, playback-generation en discontinuity
vallen buiten deze foundation.

`INPUT_CONTRACT_IMPLEMENTATION_SAFETY = SAFE_NEW_FILES_ONLY`. De voorgenomen
nieuwe files zijn `show_interpreter_input.py` en
`tests/test_show_interpreter_input.py`; er is geen productionfile of runtime
deployment nodig.

### Show Interpreter Input Contract Foundation

`GEREED — pure offline foundation + tests PASS` — de nieuwe pure module
`show_interpreter_input.py` en testmodule
`tests/test_show_interpreter_input.py` bevatten een immutable
`ShowInterpreterInput` met exact `section_bucket` en `energy_modifier`.
De bestaande bucketset wordt hergebruikt; een ongeldige bucket wordt
`unknown`. De modifier blijft binnen `-0.08 … +0.08`; ongeldige, niet-finite
of boolean invoer wordt `0.0`.

V0 bevat geen optional metadata, Rich Musical Events-dependency, state
ownership of track-resetpolicy. Er is geen ShowIntent-generation en geen
production wiring; geen bestaande productionfile is gewijzigd. De gerichte
suite is `9/9 PASS` en de volledige BeatBeam-suite `128/128 PASS`. Deployment
is niet nodig.

### Show Interpreter Candidate Mapping Audit

`SHOW_INTERPRETER_MAPPING_AUDIT_PASS — READY_FOR_DECISION`.

`INPUT_PRESENCE_OWNERSHIP = UPSTREAM_ADAPTER`: de toekomstige production
adapter/source-validatielaag beslist of voldoende bruikbare actuele broncontext
bestaat om een `ShowInterpreterInput` aan te leveren. Zonder bruikbare context
wordt geen input geconstrueerd en ontvangt de mapper `None`.

`MAPPER_OPTIONAL_INPUT_STATUS = REQUIRED` en `V0_MAPPING_MODEL =
PURE_PASS_THROUGH`: de mapper accepteert `ShowInterpreterInput | None`.
`None` wordt `None`; aanwezige canonical input wordt een nieuwe ShowIntent met
exact dezelfde `section_bucket` en `energy_modifier`, zonder verdere muzikale
interpretatie.

`UNKNOWN_BUCKET_MAPPING_POLICY = PASS_THROUGH`: `unknown` is een geldige
canonical BeatBeam-bucket. `NEUTRAL_VALUE_SUPPRESSION = FORBIDDEN`:
`ShowInterpreterInput("unknown", 0.0)` mag niet op basis van zijn waarden naar
`None` worden onderdrukt. Na normalisatie is raw-validity niet herleidbaar;
`RAW_INVALID_FAIL_CLOSED_OWNER = UPSTREAM_ADAPTER`. De toekomstige flow is:

`raw source → upstream validity check → ShowInterpreterInput | None →
candidate mapper → ShowIntent | None → resolve_show_intent`

Raw invalid/missing wordt dus `None` vóór candidate construction; de continuity
resolver behoudt vervolgens previous en er ontstaat geen gefabriceerde neutrale
candidate.

`STATE_OWNERSHIP_STATUS = CONTINUITY_RESOLVER_ONLY`: de mapper ontvangt geen
previous ShowIntent, bezit geen state, voert geen continuity uit en kent geen
intent lifetime. `TRACK_BOUNDARY_RESET_POLICY = NEEDS_PRODUCT_DECISION`; mapper
v0 kent geen track-id, playback-generation, transportpositie of discontinuity.
`RICH_EVENT_DEPENDENCY_V0 = NONE`; `current_event`, `next_event` en Rich
Musical Events blijven buiten v0.

De nieuwe module is `show_intent_candidate_mapper.py`, bewust geen volledige
Show Interpreter. De pure API is
`map_show_intent_candidate(source: ShowInterpreterInput | None) -> ShowIntent | None`.
`CANDIDATE_MAPPING_IMPLEMENTATION_SAFETY = SAFE_NEW_FILES_ONLY`: alleen
`show_intent_candidate_mapper.py` en
`tests/test_show_intent_candidate_mapper.py` zijn nodig; geen productionfile of
runtime deployment.

### ShowIntent Candidate Mapper Foundation

`GEREED — pure offline mapper + tests PASS` — de nieuwe module
`show_intent_candidate_mapper.py` bevat de pure stateless functie
`map_show_intent_candidate`. Deze accepteert optional `ShowInterpreterInput`:
`None → None`; aanwezige canonical input → exact een nieuwe `ShowIntent`.
`unknown` passeert door en `ShowInterpreterInput("unknown", 0.0)` wordt niet
onderdrukt. Er is geen content-based gating.

Input-presence en raw-validity blijven bij de upstream adapter; de continuity
resolver blijft de enige state-eigenaar. Er zijn geen events, track reset,
fixtures, DMX of production wiring. De gerichte suite is `9/9 PASS` en de
volledige BeatBeam-suite `137/137 PASS`. Deployment is niet nodig.

### ShowIntent Upstream Adapter Contract Audit

`SHOW_INTENT_UPSTREAM_ADAPTER_AUDIT_PASS — READY_FOR_DECISION`.

`LEGACY_FALLBACK_ADAPTER_POLICY = CANONICAL_ONLY`: de bestaande Auto Show
legacy fallback blijft onveranderd voor production-compatibiliteit, maar is
geen ShowInterpreterInput-v0-bron. De finale `auto_show["phrase_bucket"]` kan
immers een canonical mapping, legacy fallback of manual override zijn; manual
override is downstream en geen muzikale input.

`SOURCE_PRESENCE_SIGNAL_STATUS = EXISTING_EXPLICIT_SIGNAL`. Toekomstige
production-validiteit vereist in dezelfde huidige evaluatie `eligible=True`,
`effective_source="song_analyzer"`, exact track match,
`availability="available_current"`, status `in_segment|in_final_segment`, een
geldig huidig segment en een mappable canonical label/bucket. Deze pure
foundation voert die validatie niet uit.

`SECTION_BUCKET_SOURCE_OWNER = AUTO_SHOW_STATE` en
`SECTION_BUCKET_ADAPTER_INPUT_STATUS = SOURCE_VALIDITY_AMBIGUOUS`: zonder
provenance guard is de finale bucket niet veilig te gebruiken. Toekomstige
canonical-only wiring neemt de reeds effectieve canonical bucket vóór
legacy-/override-contaminatie, zonder classificatie te dupliceren.

`ENERGY_MODIFIER_SOURCE_OWNER = AUTO_SHOW_STATE` en
`ENERGY_MODIFIER_ADAPTER_INPUT_STATUS = DIRECTLY_REUSABLE`: in dezelfde
huidige evaluatie is dit al effectief bepaald als canonical finite
`rich_current.energy → clamp(energy * 0.04, -0.08, +0.08)`, anders `0.0`.
De adapter dupliceert deze formule niet.

`INPUT_SNAPSHOT_COHERENCE = POTENTIAL_MIXED_SOURCE_RISK`; met de
canonical-only guard kan een coherente snapshot ontstaan.
`ADAPTER_STRATEGY = WRAP_EXISTING_EFFECTIVE_VALUES`. De nieuwe pure immutable
`ShowInterpreterEffectiveContext` heeft exact `source_is_valid: bool`,
`section_bucket: str` en `energy_modifier: float`; `source_is_valid` is alleen
het upstream-established canonical-validitysignaal en wordt niet uit waarden
afgeleid. De adapter accepteert uitsluitend exact `True`, waarna hij
`ShowInterpreterInput` construeert; `None` of een ongeldige bron geeft `None`.
Een geldige canonical `unknown` en `0.0` passeren door.

De toekomstige flow is `raw/current → validation → effectives → pure context
of None → adapter → input of None → mapper → candidate → resolver`. Raw,
missing, stale, mismatch en legacy-only geven `None`; de resolver behoudt dan
previous en er wordt geen neutrale waarde gefabriceerd.

`TRACK_BOUNDARY_RESET_POLICY = NEEDS_PRODUCT_DECISION`: de pure adapter reset
niet; een toekomstige shadow-state kan bij trackwissel zichtbaar stale blijven.
`RICH_EVENT_DEPENDENCY_V0 = NONE`.
`SHADOW_WIRING_FEASIBILITY = SAFE_WITH_SMALL_EXISTING_FILE_CHANGE`, maar deze
foundation bevat geen wiring. `UPSTREAM_ADAPTER_IMPLEMENTATION_SAFETY =
SAFE_NEW_FILES_ONLY`: uitsluitend `show_interpreter_input_adapter.py` en
`tests/test_show_interpreter_input_adapter.py` zijn nodig; geen deployment.

### ShowInterpreterInput Upstream Adapter Foundation

`GEREED — pure offline adapter + tests PASS` —
`LEGACY_FALLBACK_ADAPTER_POLICY = CANONICAL_ONLY`. De nieuwe immutable
`ShowInterpreterEffectiveContext` bevat exact `source_is_valid`,
`section_bucket` en `energy_modifier`. Alleen `source_is_valid is True` wordt
geaccepteerd; `None` of iedere andere validitywaarde geeft `None`. Een geldige
canonical bron wordt een `ShowInterpreterInput`; `unknown` en `0.0` blijven
geldige aanwezige input.

De adapter hergebruikt uitsluitend de bestaande
`ShowInterpreterInput`-normalisatie. Hij dupliceert geen bucketclassificatie of
energyformule en bezit geen state, events, transport/reset, fixtures/DMX of
production wiring. De gerichte suite is `8/8 PASS`; de volledige BeatBeam-suite
is `145/145 PASS`; deployment is niet nodig.

### ShowIntent Shadow Wiring Contract Audit

`SHOW_INTENT_SHADOW_WIRING_AUDIT_PASS — READY_FOR_DECISION` —
`GEREED — production dataflow/lifecycle audit PASS`.

De authoritative productionflow is `DmxController._send_loop()`: één actuele
OSC/transport-snapshot, één `_auto_show_state()`-evaluatie, render met exact
dat resultaat en daarna DMX-send. `_auto_show_state()` roept eenmaal
`StructureBehaviorBridge.resolve()` aan, verwerkt daarna legacy/manual override
en berekent de bestaande rich-energy-modifier.

`CANONICAL_BUCKET_SHADOW_TAP = DmxController._auto_show_state():
structure_behavior["mapped_behavior_bucket"]`, direct na
`structure_behavior = self._structure_behavior_state(osc)` en vóór
legacy-fallback, `override_phrase` en `osc_effective`-mutatie.
`CANONICAL_BUCKET_TAP_STATUS = REQUIRES_LOCAL_CAPTURE`. De uiteindelijke
`auto_show["phrase_bucket"]` is geen shadow-input omdat die legacy of manual
override kan bevatten.

`ENERGY_MODIFIER_SHADOW_TAP = DmxController._auto_show_state(): de bestaande
lokale song_analyzer_energy_modifier`, na de bestaande validatie en begrenzing.
`ENERGY_TAP_STATUS = CLEAN_EXISTING_VALUE`; er komt geen tweede energyformule.

`CANONICAL_VALIDITY_TAP_STATUS = SMALL_BOOLEAN_PROJECTION`: shadow gebruikt
uitsluitend `structure_behavior["eligible"] is True` én
`structure_behavior["effective_source"] == "song_analyzer"`. De bridge heeft
dan al actieve VirtualDJ-context, exacte track match,
`availability=available_current`, een geldige current projection/segment en
een mappable canonical label fail-closed bewezen. Er komt geen tweede
eligibility-classifier.

`SHADOW_SNAPSHOT_COHERENCE = REQUIRES_NEW_LOCAL_SNAPSHOT`: binnen dezelfde
`_auto_show_state()`-evaluatie wordt conceptueel één local context vastgelegd
uit source validity, de canonical bucket en de bestaande energy modifier. Deze
waarden worden niet tussen evaluaties of ticks gemengd.

`LEGACY_OVERRIDE_ISOLATION_STATUS = CLEANLY_SEPARABLE` en
`LEGACY_FALLBACK_ADAPTER_POLICY = CANONICAL_ONLY`. Production legacy fallback
en manual phrase override blijven ongewijzigd en leidend; shadow blijft
canonical-only. Bij ongeldige canonical source geeft shadow `None`, ook als
production legacy/override `chorus` toont.

`SHADOW_STATE_OWNER = DMX_CONTROLLER_PRIVATE_FIELD`: latere runtime
previous/resolved ShowIntent-state leeft als private DmxController-state onder
de bestaande controller-lock, uitsluitend voor shadow, niet globaal en niet
als fixture-/DMX-renderstate. Hij blijft Debug read-only beschikbaar en later
afzonderlijk resetbaar. Adapter, mapper en resolver blijven stateless volgens
hun bestaande contracten.

Omdat `_auto_show_state()` minstens tien directe/relevante callsites heeft,
geldt `AUTO_SHOW_STATE_MUTATION_SAFETY = MULTIPLE_CALLS_STATE_MUTATION_UNSAFE`.
Shadow-state mag daar niet muteren. Het exacte uitvoerpunt is
`SHADOW_WIRING_EXECUTION_POINT = DmxController._send_loop()`, direct na de ene
authoritative `_auto_show_state()`-evaluatie en vóór `_render_values()`; daar
draait effective context → adapter → candidate mapper → continuity resolver
exact eenmaal per echte DMX-frame.

Shadow wiring krijgt een harde observer-only guard: geen invloed op
`auto_show`, `phrase_current`, `phrase_bucket`, energy, slot selection, fixture
programs, movement, color, dimmer, strobe, manual override, safety,
renderwaarden, `values_for_fixture()` of `DMX.send()`.

`TRACK_BOUNDARY_RESET_POLICY = NEEDS_PRODUCT_DECISION` en
`SHADOW_WITHOUT_TRACK_RESET_STATUS = SAFE_WITH_VISIBLE_STALE_WARNING`.
Zonder reset kan intent A bij track B en tijdelijk ontbrekende canonical source
onbeperkt worden behouden totdat een nieuwe candidate, procesrestart of latere
reset ontstaat. De eerste wiring toont daarom bij `candidate=None` plus
previous expliciet `retained_previous=true` en `stale_warning=true`; dit is
uitsluitend diagnostiek.

`SHADOW_DEBUG_EXPOSURE = BACKEND_DEBUG_ONLY_SUFFICIENT`. De eerste wiring
exposeert alleen via bestaande backend state/API-conventies, bij voorkeur
`DmxController.state()`; native UI-wijziging is niet nodig. Minimale data:
`source_valid`, `input_present`, `candidate_present`,
`input_section_bucket`, `input_energy_modifier`, `resolved_section_bucket`,
`resolved_energy_modifier`, `retained_previous` en `stale_warning`.

`BEATBEAM_APP_DIRTY_OVERLAP = NO_OVERLAP` voor deze route: de bestaande dirty
hunks raken niet `_auto_show_state()`, DmxController-init, `_send_loop()` of
`DmxController.state()`. `beatbeam_debug_state()` blijft in de eerste wiring
ongemoeid wegens bestaande dirty overlap.

`RICH_EVENT_DEPENDENCY_V0 = NONE`: geen `current_event`, `next_event` of Rich
Musical Events. De candidate mapper blijft pure pass-through; shadow voegt
geen drop-, transition-, UPWARD-, tension-, danceability-, event-, fixture- of
DMX-interpretatie toe.

`SHADOW_WIRING_IMPLEMENTATION_SAFETY = SAFE_WITH_SMALL_EXISTING_FILE_CHANGE`.

### ShowIntent Shadow Wiring Foundation

`GEREED — shadow runtime wiring + technical runtime PASS`. `beatbeam_app.py`
captuurt de canonical mapped bucket vóór legacy/override, projecteert alleen
`eligible is True` plus `effective_source == "song_analyzer"`, en hergebruikt
de bestaande lokale `song_analyzer_energy_modifier` in één coherente evaluatie.
De productionvorm van `_auto_show_state()` blijft shadow-state-free; alleen de
authoritative `_send_loop()` verwerkt context → adapter → mapper → resolver,
exact eenmaal per DMX-frame en vóór `_render_values()`.

De private `DmxController`-shadow-state is backend-only beschikbaar als
JSON-safe `show_intent_shadow`, inclusief `retained_previous`/`stale_warning`.
Er is geen track-resetpolicy, Rich Events-input, native UI, fixture-/program-
of render-/DMX-terugkoppeling. Legacy fallback en manual phrase override blijven
production-only. De nieuwe geïsoleerde wiringtests zijn `8/8 PASS`; pure
regressies en packagingtest zijn PASS en de volledige BeatBeam-suite is
`154/154 PASS`. De verse Beta-build/package, hashvergelijking, bundled imports,
arm64/ad-hoc strict signing, fresh restart, health op 8781 en technische
runtime-smoke zijn PASS. Zonder live geldige canonical context blijft de
runtime-debugstate aantoonbaar fail-closed.

#### Packaging prerequisite

`GEREED — BETA_BUNDLE_MISSING_PURE_MODULE_PACKAGING opgelost`. De expliciete
backend-bestandslijst in `build_native_app.sh` bundelt nu naast de bestaande
backend de vier pure modules `show_intent.py`, `show_interpreter_input.py`,
`show_intent_candidate_mapper.py` en `show_interpreter_input_adapter.py`.
Bron- en bundle-SHA-256 zijn per relevante file identiek; de bundled
importsmoke is PASS. Beta build/package, ad-hoc signing, strict codesign
verification, fresh restart en health op poort 8781 zijn PASS. Er is nog geen
shadow wiring. `ShowIntent Shadow Wiring Foundation` blijft `NOG NIET GESTART`
en is `READY TO RESUME`.

### ShowIntent Track Boundary / Continuity Policy Audit

`GEREED — lifecycle/provenance audit + product decision PASS`.

`SHOW_INTENT_TRACK_CONTINUITY_AUDIT_PASS — READY_FOR_DECISION`

`TRACK_IDENTITY_SOURCE = canonical_song_analyzer_track_path(osc["track_path"])`.
Dit is `STABLE_FILE_IDENTITY`: stabiel tijdens normale playback en seek,
beschikbaar vóór geldige SongAnalyzer-projectie, lexicaal genormaliseerd en
geen content-hash. Dezelfde opname via een ander pad is een andere runtime-
identiteit.

`playback_generation` is de bestaande in-memory `TransportController`-teller.
Hij verandert bij actieve bron-, availability-, deck-, trackpad- en
`last_discontinuity`-wijzigingen. `PLAYBACK_GENERATION_POLICY_VALUE =
GENERAL_DISCONTINUITY_SIGNAL`: bruikbaar als lifecycle-resetbewijs, maar niet
zelfstandig voldoende om trackwissel, hard seek of een andere discontinuity te
classificeren; de bestaande reason/provenance blijft leidend.

De vastgelegde v0-policy is:

- `SAME_TRACK_TEMPORARY_SOURCE_GAP_POLICY = RETAIN_PREVIOUS`: bij dezelfde
  bewezen lifecycle en tijdelijk ontbrekende canonical candidate blijven
  previous, `retained_previous=true` en `stale_warning=true` behouden.
- `TRACK_CHANGE_WITH_VALID_CANDIDATE_POLICY = REPLACE_DIRECTLY`.
- `TRACK_CHANGE_WITHOUT_CANDIDATE_POLICY = RESET_TO_NEUTRAL`.
- `SAME_TRACK_HARD_SEEK_POLICY = RESET_BEFORE_NEW_CANDIDATE`; een geldige
  candidate wordt direct overgedragen, zonder neutral flash.
- `PAUSE_POLICY = RETAIN_PREVIOUS`.
- `SAME_TRACK_NEW_PLAYBACK_POLICY = RESET_LIFECYCLE`, uitsluitend bij bewezen
  generation/discontinuity-boundary; nooit op basis van alleen pad, positie,
  bucket of energy.
- `NO_ACTIVE_TRACK_POLICY = RETAIN_PREVIOUS_UNTIL_EXPLICIT_BOUNDARY`.
  `source_unavailable` is ambigu tussen tijdelijke bronuitval, nog niet
  beschikbare transportbron en stop/unload en is op zichzelf geen resetbewijs.
  Een toekomstige expliciete stop/unload → neutral-regel vereist eerst een
  ondubbelzinnig runtime-signaal; geen timeout of N-secondenheuristiek.

`SHOW_INTENT_RESET_OWNER = DMX_CONTROLLER_SEND_LOOP` en
`CONTINUITY_RESOLVER_CHANGE_NEEDED = NO`. Bij een bewezen boundary wordt
conceptueel `previous_for_frame = None` gebruikt vóór de bestaande pure
resolver: met candidate volgt direct de candidate, zonder candidate volgt de
neutrale initial state. `SAME_FRAME_NEW_TRACK_CANDIDATE_HANDOFF =
DIRECT_NO_NEUTRAL_FLASH`.

`SHADOW_LIFECYCLE_DEBUG_REQUIREMENT = ADD_RESET_REASON_FIELDS`: latere shadow
diagnostiek krijgt minimaal `lifecycle_reset` en `lifecycle_reason`, gevoed
door bestaande transport/provenance-reasons. De stale-semantiek is expliciet:
retained same-lifecycle gap → stale; reset zonder candidate → neutral zonder
stale; reset met candidate → directe candidate zonder stale.

`CONTINUITY_POLICY_SCOPE = SHADOW_ONLY_FOR_NOW_BUT_PRODUCTION_COMPATIBLE`.
`RICH_EVENT_DEPENDENCY_V0 = NONE`: lifecycle gebruikt geen bucket, energy,
events, drop, UPWARD, tension, danceability of andere musical semantics.
`TRACK_CONTINUITY_IMPLEMENTATION_SAFETY = SAFE_WITH_SMALL_EXISTING_FILE_CHANGE`.

### ShowIntent Shadow Lifecycle Reset Foundation

`GEREED — shadow lifecycle-reset runtime PASS`.

`DmxController._send_loop()` geeft het authoritative transportsnapshot nu door
aan de private ShowIntent-shadow lifecyclebeslissing. Alleen een canonieke
trackwijziging of de bestaande expliciete reasons `deck_changed`,
`position_jump_backward` en `position_jump_forward` resetten de vorige intent.
Generation is uitsluitend bevestigende provenance; `source_unavailable`, pause
en een generationwijziging zonder expliciete boundary behouden previous. Een
reset met candidate handofft direct zonder neutrale tussenframe; zonder candidate
is de uitkomst `unknown`/`0.0`. De pure resolver en production Auto Show/render/
DMX blijven ongewijzigd. Shadowdebug bevat JSON-safe `lifecycle_reset` en
`lifecycle_reason`; state reads zijn passief.

Targeted lifecycletests, bestaande wiringtests, pure regressies, packaging en
de volledige BeatBeam-suite zijn PASS (162/162). Beta build/package, exacte
bron/bundle-manifestvergelijking, bundled imports, arm64/signing, fresh restart,
health op poort 8781 en runtime-shadowsmoke zijn PASS.

### ShowIntent Shadow Runtime Observation / Promotion Gate Audit

`GEREED — promotion-gate observability audit PASS`.

De audit heeft `SNAPSHOT_ONLY` vastgesteld en een expliciete handmatige,
longitudinale shadowobservatiesessie als kleinste veilige vervolg bepaald.

### ShowIntent Shadow Observation Telemetry Foundation

`GEREED — longitudinal shadow telemetry + technical runtime PASS`.

Private `DmxController`-observatiestate biedt een handmatige, idempotente
start/stop-sessie. Alleen één authoritative `_send_loop()`-frame ná de
shadowupdate accumuleert frame- en monotonic metrics: source/candidate/unknown,
retained/stale en stale episodes met current/total/max duur. Lifecycle-resets
worden totaal, per bestaande reason en als geordend sparse record vastgelegd.
Records gebruiken sessie-scoped opaque `track-####`-keys; volledige paden worden
niet gepubliceerd. `state()`-/API-reads zijn passief en frozen resultaten
blijven stabiel na stop. Er zijn geen thresholds, quality score,
production-authority, render-/fixture-/DMX-terugkoppeling of Rich Events.

Targeted telemetrytests, shadow/pure/packagingregressies en de volledige suite
zijn PASS (172/172). Beta build/package, relevante bron/bundlehashes, bundled
imports, arm64/signing, fresh restart, health en API start/stop-smoke zijn PASS.

### Preview-Only Authoritative Show Frame Foundation

`GEREED — shared render tick + preview-only runtime PASS`.

Een authoritative Show frame is losgekoppeld van physical DMX-send. De gedeelde
renderthread draait ook zonder hardware op de bestaande circa 30 FPS monotonic
cadence en voert precies eenmaal Auto Show, ShowIntent-shadow/lifecycle,
observation en render uit. Physical DMX is een optionele downstream sink;
connected-semantiek blijft behouden, `dmx.connected` blijft truthful en
`last_sent` blijft physical-only. Backendstate bevat `render_active`,
`render_frame_sequence` en `last_rendered`; `slot_previews` en `values` blijven
zonder hardware beschikbaar. Native Preview Map blijft ongewijzigd. Er is geen
ShowIntent-, Rich Events- of production Auto Show-semantic change.

De nieuwe geïsoleerde tests, alle regressies en de volledige suite (182/182)
zijn PASS. Beta build/package, bron/bundlehashes, bundled imports,
arm64/ad-hoc signing, fresh restart, health en preview-only runtime-smoke zijn
PASS; observation accumuleert aantoonbaar zonder fysieke DMX.

### M23B — RME-driven Auto Show Preview Experiment

`SYNTHETIC VISUAL-DIFFERENTIAL PASS / LIVE-RME + HUMAN ACCEPTANCE OPEN` — De eerste RME-consumptie gebruikt
uitsluitend de bestaande, gevalideerde `rich-musical-events`-handoff en werkt
alleen in de Preview Map. De fysieke render en DMX-sink blijven de exacte
baseline Auto Show-frame gebruiken. Een expliciete Preview Map A/B-keuze biedt
`BASELINE` en `RME_ENHANCED`; geen productie-feature-gate, canonical authority
of SongAnalyzer-semantic verandert.

De pure preview-interpreter faalt gesloten bij een ontbrekende, stale of
identity-mismatched handoff en herselecteert context direct op de actuele
playbackpositie. BUILD/BREAK gebruiken intervalprogress; RELEASE/DROP/ARRIVAL/
TRANSITION hebben een begrensde point-context. BUILD verhoogt bestaande energie
en movement geleidelijk, BREAK verlaagt die, DROP krijgt een bestaande sterke
pulse zonder strobe-wijziging, ARRIVAL is bewust geen DROP en TRANSITION wijzigt
alleen bestaande movement. Manual overrides, strobe/movement/dimmer-bounds en
fixture-programkeuze blijven downstream onveranderd leidend.

De vervolgaudit reproduceerde een neutralisatie: een BUILD wijzigde wel de
abstracte RME-showstate maar niet de fixturepreview door bestaande
motion-dimmernormalisatie. De preview-interpreter projecteert daarom een
begrensde, preview-only intensiteitsfactor pas ná die normalisatie; er is geen
DMX-kanaal- of productionwijziging. `rme_preview_differential` rapporteert
mode/context/event/progress/interpretatie, showstate- en fixturedelta en de
bronroute (`preview_auto_show -> slot_previews`). De synthetische BUILD-guard
bewijst `BASE_SHOW != ENHANCED_SHOW`, `BASE_PREVIEW_VALUES !=
ENHANCED_PREVIEW_VALUES` en een ongewijzigde fysieke baselineframe; preview-
projecties muteren geen rhythm-runtime-state. Alle 226 regressies, Beta
build/package/signing, bron/bundle-hashes en een verse runtimerestart zijn PASS.

De live handoff-lacune is onderzocht en opgelost zonder RME-semantiek of
lighting-route te wijzigen: de geïnstalleerde VirtualDJ-bridge van 22 augustus
accepteerde oude `phrase-analysis-v17`-cache zonder `rich-musical-events-v1`.
De bestaande ontwikkelinstaller publiceerde en verifieerde de huidige
self-contained arm64 bridge plus alleen de eigen plugin; een nieuwe bridge-
activatie classificeerde de oude cache als stale en voerde de normale analyse
uit. De echte actieve track `Mart Hoogkamer - Feest In De Tent.flac` publiceert
nu 47 compacte events met exact gematchte analysis hash, waaronder BUILD,
BREAK, RELEASE en ARRIVAL.

`RME_LIVE_PREVIEW_DIFFERENTIAL_PASS` — Tijdens de echte BUILD
138,716–148,108 s bij progress 0,35028 veranderde de gelijktijdig berekende
Preview Map van energy 0,60537 naar 0,73441, head brightness 74 naar 81, par
brightness 70 naar 76 en wall-wash brightness 38 naar 47. De backend hield de
physical route expliciet op `auto_show -> current_values` en de previewroute op
`preview_auto_show -> slot_previews`; er is geen enhanced fysieke renderroute.
De runtime staat op `RME_ENHANCED` voor de eerste menselijke show-quality A/B.
Production promotion blijft buiten scope.

### M23C — Dynamic Show Composition Foundation

`PREVIEW-ONLY TECHNICAL PASS / HUMAN A/B/C OPEN` — De Auto Show-effectpool is
geaudit als bestaande veilige primitive-, capability- en fallback-library:
motion-profielen begrenzen pan/tilt, rendererparameters begrenzen dimmer,
ritme/pulse en kleurgedrag, en fixture-capabilities blijven downstream
authoritair. De pool blijft beschikbaar; er is geen productionele rewrite of
raw-DMX-generator.

De nieuwe pure laag is `ShowIntent/context → FixtureGroupIntent → Dynamic
Composer → bestaande fixture renderer`. `FixtureGroupIntent` is immutable en
begrensd tot activity, intensity, movement amount/speed, color change rate,
palette role, pulse amount en accent strength. `DYNAMIC_COMPOSER` is uitsluitend
een derde Preview Map-route naast `BASELINE` en `RME_ENHANCED`. BUILD werkt met
continue, monotone curves; BREAK verlaagt activity/movement/intensity; DROP is
een begrensd, niet-gelatcht accent; RELEASE hervat een stabiele bestaande
primitive. Keuzes zijn event/context-deterministisch, zonder per-frame random
churn of track-specifieke regels.

De Preview Map exporteert compact base show, dynamic intent, group-intents,
selected primitives, changed dimensions en fixture differential. Missing/stale
RME, ongeldige intenten of manual override vallen gesloten terug naar baseline.
De fysieke route blijft `auto_show -> current_values`; de composerroute blijft
`preview_auto_show -> slot_previews`. De gerichte composer-, RME-preview-,
authoritative-frame- en packagingtests plus de volledige huidige BeatBeam-suite
zijn groen. Beta build/deployment en menselijke vergelijking rond de bewezen
BUILD op 2:19–2:28 staan nog open; production promotion blijft buiten scope.

### M23C vervolg — Actual Preview Show Source / Visible Cue

`DYNAMIC_COMPOSER_TECHNICAL_FOUNDATION = PASS`;
`DYNAMIC_COMPOSER_HUMAN_VISUAL_ACCEPTANCE = HOLD`. De menselijke review rond
2:22,84 in de echte BUILD bewees dat de Native Stage Map weliswaar exact
`slot_previews` rendert, maar dat de eerste composer onvoldoende zichtbare
compositie leverde. Root cause: `BASELINE_SCENE_DOMINATES_DYNAMIC_COMPOSITION`.
De dynamic state kopieerde de production Auto Show en verving alleen moving
motion/intensiteit; de oude scene bleef kleur/look/pulse/wash bepalen.

De bounded correctie behoudt dezelfde renderer- en safetyroute maar maakt
per-group primitives authoritair voor de preview: moving motion, PAR/moving
palette en pulse, en wash palette/cue. Benoemde primitives worden pas in de
bestaande fixture-renderer naar bestaande kleurprofielen, ritmemodi en
wall-wash cues vertaald; de pure composer blijft DMX-vrij. De backend traceert
production source, preview source, application/fallback, baseline-scene reuse,
selected primitives én de daadwerkelijk aan de Native Map geleverde compacte
slot-previewwaarden. De Native Auto Show UI toont bovendien een afzonderlijke
`PREVIEW CUE`; de production CUE blijft production-only. Physical DMX blijft
ongewijzigd `existing_autoshow -> current_values`.

### M23C vervolg — Continuous Musical State Backbone / RME Modulation

`CONTINUOUS_DYNAMIC_COMPOSER_TECHNICAL_PREVIEW = PASS`; live menselijke
show-quality blijft HOLD. De architectuur is aangescherpt tot één showengine:
`ContinuousMusicalState + optional RmeContext → FixtureGroupIntent`. De
continuous state is de doorlopende composerbackbone; sparse Rich Musical Events
zijn tijdelijke modifiers. Afwezigheid van een current RME is dus normale
runtime-state en veroorzaakt geen baseline-fallback meer.

Een read-only bron- en corpusaudit bewees dat de bestaande current/exact
`shadow_analysis` al voldoende software-onafhankelijke evidence levert. De
compacte BeatBeam-projectie gebruikt observation-id, sectietiming en afgeleide
voortgang, `RelativeEnergy`, tekenbehoudend begrensde `energy_rise` en optionele
recurrence/family salience. Er is geen nieuw audiofeature, Essentia-call,
SongAnalyzer-persistence, handoffschema, RME-detectieregel of canonical authority
toegevoegd. Semantische sectielabels, genre, artiest en titel zijn geen input.

De backbone kiest stabiel geseede bestaande motion-, palette-, pulse- en
washprimitives. BUILD/BREAK/DROP/RELEASE veranderen dezelfde group-intents;
event exit retourneert naar de continuous composition. Baseline-fallback blijft
fail-closed voor geen current track, stale/mismatch, ontbrekende essentiële
state, invalid input/composerexception en manual override. De Native UI en
backenddiagnostiek scheiden composerstatus, musical state, RME modifier en
preview cue. De volledige route blijft Preview Map-only; physical production
blijft `existing_autoshow -> current_values` met bestaande capability-, fixture-
en strobe-safety.

De echte 205-track handoff bevat 200 tracks met section-character state. Daarop
is continuous coverage 99,51% van de geanalyseerde playbacktijd tegenover
23,36% current-RME-coverage. `Mart Hoogkamer - Feest In De Tent` meet 98,97%
continuous en 14,51% current RME; offline exact-handoff/rendererchecks op 130 s,
BUILD 143 s en post-BUILD 150 s zijn compositorisch en physical-identity groen.
De verse gesigneerde Beta is gedeployed; omdat VirtualDJ bij de eindcontrole
geen spelende current track had, blijft de vereiste echte live/human A/B/C HOLD.

### M23C vervolg — Musical Event Envelope Foundation

`MUSICAL_EVENT_ENVELOPE_TECHNICAL_PREVIEW = PASS`; menselijke live acceptance
blijft HOLD. Continuous Musical State blijft de permanente backbone. Een
point-RME is voortaan uitsluitend trigger voor een aparte pure
`MusicalEventEnvelope`, die na attack/impact gedurende een bounded settle weer
exact verdwijnt. Daarmee wordt geen SongAnalyzer-eventduur aangepast en bestaat
er geen latched showstate of baselinefallback.

De envelope gebruikt primair bestaande VirtualDJ bar/beat-context uit
`PlaybackClock`; ontbreekt die tijdelijk, dan zet alleen de bestaande BPM de al
bekende elapsed boundarytijd om naar beats. ARRIVAL, RELEASE en TRANSITION
hebben een twee-bar-envelope, DROP anderhalve bar en future-ready FILL twee
beats. Bij gelijke boundary kiest één vaste semantische modifier
`DROP > FILL > RELEASE > ARRIVAL > TRANSITION`; er is geen stacking of nieuwe
ranking-engine. BUILD/BREAK blijven bestaande intervalmodifiers.

De composer vertaalt envelope-strength uitsluitend naar bestaande, begrensde
group-intents en primitives. ARRIVAL gebruikt een release/landing-accent en is
geen DROP; DROP gebruikt een sterker maar bounded impactaccent; RELEASE blendt
naar de destination continuous state. FILL is synthetisch getest als accent
zonder directe strobe- of DMX-semantieken. Bestaande fixture capability,
manual override en strobe-safety blijven downstream authoritair.

Backend en Native Preview CUE tonen nu een afzonderlijke `EVENT ENVELOPE` met
fase, progress en maatlengte. Exact-handoff/rendererchecks op echte tracks
bewezen ARRIVAL `0:09.17`, RELEASE `0:38.48` en DROP `1:26.87` op boundary,
halve maat, één maat en completion, inclusief previewdeltas en physical-frame-
identity. De route blijft volledig Preview Map-only. Pas na positieve human
review volgt een bounded production-promotionontwerp.

### M23C vervolg — Generative Variation + Anti-Repetition Foundation

`DYNAMIC_COMPOSER_VARIATION_TECHNICAL_PREVIEW = PASS`; live menselijke
show-quality blijft HOLD. De bestaande benoemde primitivebibliotheek is bewust
de kleine muzikale basis gebleven. De pure composer voegt uitsluitend
begrensde, fixture-onafhankelijke parameters toe voor motion-range/snelheid/
fase/spreiding/centrum, paletrelatie/-balans, pulse-amount/deelname en
wash-fase. Er zijn geen RGB-randomizer, nieuwe raw-DMX- of productionroute en
geen SongAnalyzer-, analyse-, cache- of handoffwijzigingen.

`CompositionHistory` is niet persistent en scoped op track plus playback
generation. Hij kiest deterministic uit vier parameterkandidaten, bewaart zes
recente signatures, voorkomt exacte recente herhaling en reset bij een nieuwe
track/generation/invalidation. Exacte replay blijft retained; aantoonbare
recurrence mag gecontroleerd het vorige motief hernemen. De leesbare
`CompositionSignature` en selection/history diagnostics staan in de Preview
Cue en differential. In een representatieve 24-sectie shadowreeks steeg de
volledige compositiediversiteit van 16 naar 20 unieke signatures; de vier
overige herhalingen waren expliciete recurrence-reuse en de langste run was 2.

De renderer realiseert die intent uitsluitend bovenop de bestaande motion-,
kleur-, ritme- en wash-profielen en daarna de bestaande capability- en
fixtureclamps. ARRIVAL is begrensd versterkt, maar technisch getoetst boven de
backbone en onder DROP voor PAR-intensity, pulse en accent; de bestaande
twee-bar settle en event-exit blijven intact. Physical output blijft exact
`auto_show -> current_values`; variatie blijft `preview_auto_show ->
slot_previews`. Volgende gate is menselijke vergelijking van minstens drie
structureel vergelijkbare passages; production promotion blijft buiten scope.

### ShowIntent Representative Shadow Observation Run

`GEREED — first representative preview-only observation completed; promotion held for semantic-history + broader lifecycle/stale evidence`.

De handmatige preview-only sessie duurde `2248.506588 s` / `37.475110 min` en
registreerde 58.007 authoritative frames met gemiddeld `25.798012 FPS`.
Source-valid/candidate was 75,9581%; valid canonical unknown bleef 0. Er waren
14 stale episodes (`533.782446 s` totaal, `119.347113 s` maximum) en 13
lifecycle-resets, alle `track_changed`. Runtime integrity is PASS; promotion
blijft HOLD omdat per-frame semantic history ontbreekt en hard-seek/deck/
same-path lifecyclecoverage nog onvolledig is. Geen production authority.

### ShowIntent Semantic Stability Observation Telemetry Foundation

`GEREED — bounded per-frame semantic history + technical runtime PASS`.

History bestaat uitsluitend tijdens een handmatige observation session en
registreert precies één record per authoritative renderframe: input/resolved
bucket + modifier, source/candidate/retained/stale/lifecyclecontext en opaque
track keys. De production cap is 120.000 frames; dropped/truncated status is
expliciet observeerbaar. De volledige history zit niet in `/api/state`, maar
achter een dedicated read-only history endpoint; reads zijn passief en na stop
frozen. Dit blijft preview-only compatibel, zonder runtime quality judgement of
production authority. Tests, build en technische runtime-smoke zijn PASS.

### ShowIntent Targeted Semantic + Lifecycle Observation Run

`GEREED — semantic stability PASS; promotion held for canonical availability +
same-path deck-boundary runtime evidence`.

De gerichte preview-only sessie duurde `1007.924241 s` / `16.798737 min` en
registreerde 26.865 authoritative frames met `26.653789 FPS`.
Source-valid/candidate was 77,5731%; valid canonical unknown bleef 0. Retained/
stale betrof 6.022 frames in 9 episodes (`225.215348 s` totaal,
`135.788383 s` maximum); de chronology is verklaarbaar als loading,
transition of recovery en retained continuity was volledig consistent.
Lifecycle registreerde track_changed 7, position_jump_forward 11 en
position_jump_backward 5 keer; forward en backward seek zijn runtime observed,
same-path deck boundary niet. Semantic stability is PASS; promotion blijft HOLD.

### ShowIntent Same-Path Deck + Canonical Recovery Observation Run

`GEREED — final promotion gates PASS; ready for bounded NO-OP parity design`.

De finale preview-only sessie duurde `714.963242 s` / `11.916054 min` en
registreerde 19.105 semantic-history records. De geldige canonical baseline is
PASS. Twee same-path deck boundaries zijn geobserveerd, beide met `0 s`
candidate/source-recovery en zonder neutral flash; ook twee normale
trackwissels hadden `0 s` recovery. Retained continuity bleef volledig
consistent, input/resolved mismatches waren `0`, en valid canonical unknown was
`0`. Lifecycle-evidence is daarmee compleet voor de promotion gate: Gate A,
Gate B, Gate C, Gate D en Gate E zijn PASS; Gate F is
`READY_FOR_BOUNDED_PROMOTION_DESIGN`. Er is geen production authority
toegevoegd.

### Bounded NO-OP Parity Source Substitution Design Audit

`GEREED — design accepted`.

De eerste promotion blijft `NO_OP_PARITY_SOURCE_SUBSTITUTION`: uitsluitend de
bron van bestaande `section_bucket` / `energy_modifier` kan later begrensd
wisselen. `CURRENT_CANDIDATE_ONLY`, exacte bestaande Auto Show fallback,
unknown/`0.0`, handmatige override-prioriteit en directe same-frame boundaries
zijn contractueel vastgelegd. Er is geen Rich Event-, fixture-, render- of
DMX-authority toegevoegd.

### Bounded NO-OP Parity Diagnostics Foundation

`GEREED — selector present, authority OFF, parity diagnostics runtime PASS`.

De private backend gate staat default `False`, zonder UI, persistence of
runtime-enable endpoint. De lokale selector valt fail-closed terug op het
bestaande Auto Show-pair en gebruikt uitsluitend een actuele candidate wanneer
de gate later expliciet aanstaat. Current parity-debug, begrensde parallelle
history (`120.000` frames) en een passief parity-history endpoint zijn aanwezig;
de volledige history zit niet in `/api/state`. Gate OFF is getest als exacte
production-baseline. Tests, Beta-package, hash/import/signing en een verse
preview-only runtime-smoke zijn PASS; fixture/render/DMX-semantiek bleef
ongewijzigd.

### Bounded NO-OP Parity Runtime Acceptance Run

`GEREED — longitudinal runtime parity PASS; authority remained OFF; ready for bounded enable design decision`.

De preview-only VirtualDJ-observatie duurde `2.050,637 s` (34,177 min) en
bevriest zonder truncation op 50.728 aligned semantic- en parity-records. Van
14.156 canonical eligible comparison frames waren section, energy modifier en
het volledige pair elk exact gelijk (`0` mismatches). Production identity bleef
op alle 50.728 frames `existing_autoshow`; de gate bleef `False`.

Negen `track_changed`/`deck_changed`-boundaries zijn waargenomen: één met
directe same-frame candidate-handoff, zeven met een latere canonical recovery
die weer exact parity leverde, en één terminale wissel zonder recovery vóór
stop. Er waren geen selector failures, geen production ShowIntent-authority en
geen runtime-observeerbare manual override. `BOUNDED_NO_OP_PARITY_CONTRACT =
PASS`; `SHOWINTENT_BOUNDED_PROMOTION_DECISION =
READY_FOR_BOUNDED_ENABLE_DESIGN`. Een mogelijk bounded-enable ontwerp blijft
een afzonderlijke expliciete vervolgbeslissing.

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

# 11. Historische eerstvolgende prioriteiten (SUPERSEDED AS ACTIVE BACKLOG)

Aanbevolen volgorde vanaf de huidige productrichting:

1. `BEZIG` Volledige VirtualDJ-playlist show-readiness, daarna feature freeze.
2. `GEREED` M23A: Rich Musical Events runtime-shadowacceptatie en full-corpus
   fresh/cache availability.
3. `BEZIG` M24A: muzikale shadow-calibratie op een kleine representatieve trackset.
4. `TODO` Verdere hiërarchische analyse pas na show-readiness en alleen vanuit
   bewezen nieuwe evidencebehoefte.
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
