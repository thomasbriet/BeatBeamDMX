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

`STATUS = NOG NIET GESTART`.

4P wordt uitsluitend read-only uitgevoerd. Vanuit bestaande provenance-clean
raw structural data zoekt de audit blind naar structureel vergelijkbare
boundaries voor afzonderlijke U16-ingrediënten: lange/repeated origin-run,
vertrek bij laatste origin occurrence, non-zero returnafstand, return naar een
gevestigde destination family, family-exit en combinaties daarvan.

Eerst worden bestaande human-reviewed U/M-controls buiten de huidige subset
onderzocht; alleen als die onvoldoende zijn wordt een kleine nieuwe kandidaatset
blind geselecteerd, zonder nieuwe verdicts te verzinnen. Human verdicts worden
pas na structurele selectie gekoppeld. 4P bepaalt of U16's patroon bij meerdere
UPWARD-cases, bij NOT_UPWARD-cases, alleen track-specifiek of als gedeeltelijke
combinatie van ingrediënten voorkomt.

4P mag geen audiofeature, Essentia-call, shadow exposure, productiecode,
tests, gate, threshold, score, classifier, confidence, canonical role of
High/Mid/Low semantic input toevoegen. Geen circulariteit.

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

`NOG NIET GESTART` — immutable pure effective context, strikt
source-validitysignaal, `None`/invalid source naar `None`, valid source naar
`ShowInterpreterInput`, `unknown`/`0.0` pass-through, zonder production imports
of duplicatie van bestaande logica.

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
