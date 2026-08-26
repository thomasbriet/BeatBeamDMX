# SongAnalyzer / BeatBeam — Current Roadmap

## Huidige status

- **SongAnalyzer:** software-onafhankelijke analyse-engine; FILL, shadow-handoff en VirtualDJ-lifecycle zijn lokaal gecheckpoint op `397e071`, `d3fd28f` en `b982211`.
- **BeatBeam:** pure Dynamic Composer-foundation en preview/runtime-diagnostics zijn lokaal gecheckpoint op `84c1779` en `c499a0c`.
- **Continuous state:** 215/215 librarytracks zijn current en usable; 2.203 sectie-observaties leveren 11.741/11.741 geldige composerframes.
- **Cache/handoff:** de vijf voorheen oude phrase-caches zijn via de normale bridge-workerflow heranalyseerd; een tweede vijf-trackpass was volledig cache-hit zonder bestandsmutatie.
- **Production/shadow:** production-selector is technisch gereed maar hard gate-off; runtime blijft `BASELINE_ONLY`.
- **Laatste milestone:** `FULL_CONTINUOUS_STATE_COVERAGE + SAFE_PROTECTED_WORKTREE_CHECKPOINT` — PASS; lokale sourcecheckpoints, geen deployment of push.

## Actieve milestone

**FULL CONTINUOUS-STATE COVERAGE + SAFE CHECKPOINT · PASS / GATE OFF**

Exact vijf stale tracks zijn via normale `analyze`-jobs vernieuwd naar actuele
phrase-analysis v17 en rich-eventprojection v1. De corpussoak telt nu 215/215
current/usable tracks, 2.203 sections en 11.741/11.741 geldige continuous-state-
en composerframes. Alle 5.375 frames zonder current RME en alle 11.741
analyzed-only-intensityframes bleven composer-valid; 1.986/1.986 envelopes
completeerden en alle physical/shadow-safetyinvarianten bleven groen.

De tweede pass over dezelfde vijf tracks voltooide in 309 ms. SHA-256,
`savedAtUtc` en mtime van ieder cachebestand bleven gelijk; de bridge eindigde
met queue/running 0, 10 completed en 0 failed. Dit bewijst current cache- en
handofflifecycle zonder nieuwe audioanalyse.

De protected worktree is uitgevoerd als vijf lokale sourcecheckpoints plus dit
documentatiecheckpoint. Generated soak/reviewaudio blijft lokaal; de onbekende
`BeatBeam.code-workspace` blijft user-owned. SongAnalyzer heeft geen remote en
BeatBeam blijft vanwege de beschermde lokale context `LOCAL_COMMITS_ONLY`.

**DYNAMIC COMPOSER SHADOW SOAK + SELECTOR HARDENING · TECHNICAL PASS / GATE OFF**

`DYNAMIC_COMPOSER_FULL_CORPUS_SHADOW_SOAK_PASS`. Twee onafhankelijke runs over
210/215 current tracks, 2.153 sections en 11.445 frames hadden 11.445 geldige
candidates en hypothetical eligibilities. Alle 5.230 no-current-RME-frames en
alle 11.445 analyzed-only-intensityframes bleven geldig; 1.932/1.932
EventEnvelope completions keerden correct terug naar de backbone. Beide runs
hadden dezelfde digest `e2ab47a5…30be0`, 0 silent invalid states en 0 renderer-
exceptions. Een echte same-boundary envelope-resurrectionbug en directe
recurrence-repeatbug zijn bounded mechanisch gecorrigeerd; directe
opeenvolgende repeats zijn nu 0/210 tracks. Historische recurrence blijft
bewust bestaan en is geen human show-quality PASS.

`PRODUCTION_SELECTOR_FAULT_INJECTION_PASS`. De pure test-only ENABLED-route en
36 faultscenario's dekken stale/missing/mismatch, transport, generation,
malformed candidate/state, exceptions, niet-finite/buiten-bounds primitives,
renderer failure, blackout, manual/one-shot overrides, seek, prewarm en snelle
A→B→A-lifecycle. Iedere fault kiest atomair dezelfde-frame baseline zonder
stale latch of black frame.

`DYNAMIC_COMPOSER_RUNTIME_SOAK_PASS`. De versnelde 100.000-frame lifecycle-run
(55,56 minuten equivalent op 30 fps) had 0 exceptions, invalid physical frames,
identity failures, failback failures of state leaks. Alle 100.000 frames bleven
`BASELINE_ONLY`; RSS-groei was 835.584 bytes en de laatste/eerste-10k
cadansratio 1,0083 zonder degradatie.

`FILL_HUMAN_REVIEW_PACKAGE_READY`. Een deterministisch geblindeerd lokaal
pakket bevat 24 candidates (8 strong, 8 medium, 8 borderline), 12 gemengde
controls en 36 korte AAC-snippets uit 24 tracks. Alle labels zijn `PENDING`;
mapping staat apart. Detectorthresholds en FILL/RME/lighting zijn ongewijzigd.

`PROTECTED_WORKTREE_SAFE_CHECKPOINT_PASS`. De eerdere read-only classificatie
is opnieuw per actuele diff gevalideerd en uitgevoerd zonder reset, restore,
checkout, stash, clean of history rewrite. Zie
`PROTECTED_WORKTREE_CHECKPOINT_PLAN.md` voor commitgrenzen en uitgesloten assets.

**REALTIME BEAT PHASE + LIVE INTENSITY FOUNDATION · TECHNICAL PASS / RUNTIME HOLD**

Beat-root-cause: normale Auto Show-dimmer/pulse-output is al een functie van
de actuele `get_beatpos`-fase via `PlaybackClock`, niet van een verbruikte
beat-edge. N→N+2 polling of een overgeslagen rendererframe verliest dus geen
toekomstige pulse; HALF_TIME, BAR_ACCENT, SUBDIVISION en
INTENTIONALLY_SPARSE zijn compositorisch bedoeld. Read-only debug exposeert
bron, fase, leeftijd en patroonclassificatie. Preview, renderer en fysieke
`auto_show -> current_values` blijven dezelfde phase-locked route.

Live intensity gebruikt uitsluitend `deck N get_level`: deck-scoped en
pre-master. De bridge koppelt de observatie alleen bij exact actieve deck/path
aan lifecycle-generation; BeatBeam vereist verse, advancing,
generation-bound identiteit en valt anders analyzed-only terug. Bestaande
relatieve normalisatie, attack/release en ±0,06 modifier blijven preview/
Dynamic-Composer-only; master-switch en fysieke DMX-authority zijn ongemoeid.
Build/tests zijn groen. Install, veilige VirtualDJ-restart en echte human
beat/intensity acceptance zijn HOLD.

**NATIVE OBSERVABILITY / LOADED DECK UI · RUNTIME PASS**

De rijke `selected_primitives`-payload van Dynamic Composer bevat nested
parameters; de oude Swift decoder verwachtte alleen strings en kon daardoor de
volledige `/api/state` weigeren. De native decoder accepteert nu begrensd
strings, numbers, booleans, objecten en arrays per primitive value, zonder dat
onbekende debugdata de live state blokkeert. De read-only `live_ui.decks`
projection vult niet-actieve loaded decks aan uit bestaande native-plugin
candidates en exact passende prewarmstatus/generation. Dit wijzigt nooit
active track, NOW, transport, composercontext of DMX-authority.

De verse Beta-runtime toont Deck 2 met track en `Ready`; Deck 1 blijft via
`get_activedeck` master/actief. `MASTER_SWITCH_LATENCY_OPTIMIZATION` blijft
open; de volgende live gate is A→B→A-masteracceptatie.

**VDJ PREWARM + MASTER AUTHORITY · LIVE RUNTIME PASS**

In de verse plugin-/bridge-sessie was een loaded non-master Deck 2 zichtbaar
als `Ready` zonder active-track- of NOW-wissel. De live A→B→A-masterwissel
volgde beide keren direct de officiële `get_activedeck`-query: pluginselectie,
IPC-activate, bridge active track, BeatBeam transport/NOW en Dynamic Composer
context schakelden coherent naar de betreffende decktrack en terug. Physical
DMX bleef `auto_show -> current_values`. Exacte knop-tot-ketenlatency is niet
gemeten; versnelling blijft een aparte open todo.

**DYNAMIC COMPOSER — GENERATIVE VARIATION + ANTI-REPETITION FOUNDATION · TECHNICAL PASS / HUMAN VISUAL HOLD**

De Preview Map behoudt de bestaande benoemde veilige motion-, palette-, pulse-
en wash-primitives als muzikale ankers, maar parameteriseert ze nu begrensd:
motion-range/snelheid/fase/spreiding/centrum, paletrelatie en -balans,
pulse-amount/deelname en wash-fase. Er is geen grote nieuwe effectpool,
RGB-randomizer, raw-DMX-pad of SongAnalyzer-wijziging. Alle parameters lopen
uitsluitend via de bestaande profile-renderer, capabilitychecks en clamps.

Een kleine niet-persistente `CompositionHistory` is lokaal aan track + playback
generation. Hij is deterministic/replayable, vermijdt recente exacte
`CompositionSignature`s, reset op lifecyclewijziging en mag bij aantoonbare
recurrence gecontroleerd een eerder motief hernemen. Signature, selectie en
historygrootte zijn leesbaar in Preview Cue/differential. Een representatieve
24-sectie shadowreeks ging van 16/24 unieke benoemde volledige combinaties
(8 exacte herhalingen) naar 20/24 unieke volledige signatures (4 gecontroleerde
recurrence-herhalingen; maximaal 2 aaneengesloten). De benoemde pool blijft
bewust 3 motion, 3 palette, 2 pulse en 2 wash-keuzes per energiebucket.

ARRIVAL heeft een duidelijker bounded landing-accent gekregen, maar blijft in
intensity, pulse en accent onder DROP. De twee-bar attack/settle en de exacte
terugkeer naar de continuous backbone zijn onveranderd. Physical DMX blijft
identiek `auto_show -> current_values`; alleen
`preview_auto_show -> slot_previews` ontvangt variatie.

**VIRTUALDJ DECK PREWARM + MASTER AUTHORITY SYNC — TECHNICAL PASS / LIVE RUNTIME HOLD**

De native VirtualDJ-plugin gebruikt voortaan de directe officiële
`get_activedeck`-query als enige deckautoriteit. Een ontbrekend of ongeldig
mastersignaal is fail-closed (`master_signal_unavailable`); er is geen fallback
naar de oude one-playing/current/recent-loaded-heuristiek. De bridge exposeert
master-query/resultaat, geselecteerd deck, reden, generation, transport en
discontinuity via de bestaande bounded diagnostics.

Een geladen niet-masterdeck start een afzonderlijke `prewarm`: cache-hit voegt
alleen de trackanalyse aan de handoff-index toe; cache-miss analyseert met
normale prioriteit en deduplicatie. Prewarm schrijft nooit `active_track`,
NOW, transport, Auto Show, Dynamic Composer of fysieke DMX. Een deckvervanging
vervangt de bijbehorende prewarm-status; dezelfde path op twee decks blijft
deck-geïsoleerd. De technische tests zijn groen; echte VirtualDJ A→B,
prewarm en gecombineerde runtimeacceptatie blijven HOLD tot beide decks live
beschikbaar zijn.

Na die lifecycleacceptatie keert de productrichting terug naar de bestaande
preview-only human acceptance van de Musical Event Envelope; production
promotion blijft buiten scope.

**M23C — Musical Event Envelope Foundation · TECHNICAL PREVIEW PASS / LIVE HUMAN VISUAL HOLD**

Vast architectuurprincipe: `continuous musical state = backbone`; Rich Musical
Events zijn uitsluitend tijdelijke eventmodifiers. `No current RME` is een
normale toestand en geen composerfout. De read-only audit gaf gate
`A. EXISTING_LIVE_STATE_SUFFICIENT`: de bestaande optionele `shadow_analysis`
in dezelfde current/exact structure-handoff bevat al sectietiming,
`RelativeEnergy`, signed `energy_rise`, recurrence en family salience. Er is
geen SongAnalyzer-, analyse-, cache- of handoffwijziging nodig.

BeatBeam projecteert daaruit een kleine immutable `ContinuousMusicalState`:
observation-id, sectiestart/-einde/-voortgang, relatieve energie en optionele
begrensde signed trajectory, recurrence en family salience. Semantische labels,
canonical roles, genre, artiest en titel zijn geen composerinput. Alleen
sectietiming/voortgang en relatieve energie zijn essentieel; missingness van de
overige velden blijft expliciet.

De Preview Map-route is nu `ContinuousMusicalState + optional RmeContext +
optional MusicalEventEnvelope → FixtureGroupIntent → bestaande veilige
renderer`. De backbone kiest continu en deterministisch eigen moving-, PAR- en
wash-primitives. BUILD/BREAK blijven intervalmodifiers. Punt-RME's ARRIVAL,
DROP, RELEASE en optioneel TRANSITION triggeren een afzonderlijke immutable,
beat-/bar-gebaseerde envelope: attack/impact, settle en daarna exact terug naar
de underlying continuous composition. SongAnalyzer-events worden niet verlengd.
De bounded defaults zijn ARRIVAL/RELEASE/TRANSITION twee bars en DROP anderhalve
bar; toekomstige FILL past als twee-beat accent in hetzelfde model. Per boundary
is één envelope actief met vaste `DROP > FILL > RELEASE > ARRIVAL > TRANSITION`
voorrang; er is geen stacking. Baseline-fallback is beperkt tot geen current
track, stale/mismatch, ontbrekende essentiële state, invalid input,
composerexception of manual override.

Observability scheidt nu `DYNAMIC COMPOSER Active/Fallback`, `MUSICAL STATE`,
`RME MODIFIER`, `EVENT ENVELOPE` en `PREVIEW CUE`. De differential exporteert expliciet
`dynamic_composer_active`, `fallback_to_baseline`, continuous state, current en
next event, envelopefase/-progress/-barlengte, group-intents, primitives, changed dimensions en werkelijk
gerenderde previewslots. Physical DMX blijft exact `auto_show -> current_values`;
alle nieuwe state blijft `preview_auto_show -> slot_previews`.

Coverage op de echte handoff: 200 tracks met section-character state omvatten
36.876,132 van 37.057,654 s (99,51%); current RME omvat 8.656,109 s (23,36%).
Op `Mart Hoogkamer - Feest In De Tent` is dat 198,368/200,435 s (98,97%) versus
29,076 s current RME (14,51%); 169,292 s (84,46%) heeft geldige continuous state
zonder current RME. Offline exact-handoff/rendereracceptatie op 130 s, 143 s
(BUILD 138,716–148,108 s) en 150 s hield de composer in alle drie actief,
toonde telkens eigen fixturewaarden en behield per positie physical-frame-
identity. De verse gesigneerde Beta `1.2.0-beta (120)` is gedeployed met gelijke
bron/bundle-hash. VirtualDJ had bij de eindcontrole geen spelende current track;
een echte live/human A/B/C blijft daarom HOLD. De nieuwe exact-handoff/renderer-
checks bewijzen ARRIVAL op `0:09.17`, RELEASE op `0:38.48` en DROP op `1:26.87`:
boundary, halve maat, één maat en completion tonen ieder bounded settle,
previewdeltas en physical-frame-identity; completion valt terug op continuous
composition zonder baselinefallback.

## Eerstvolgende prioriteiten

1. **FILL thuisreview.** Label de 36 geblindeerde items en noteer gemiste duidelijke fills; pas daarna detectorcalibratie of shadow-eventpromotie overwegen.
2. **Live-intensity human acceptance.** Speel één track met rustige, sustained build, hard/vol, breakdown en terugval; tune alleen bij herhaalbaar bewijs.
3. **Preview beat-pulse en EventEnvelope/variation human retests.** Geen automatische PASS op basis van de technische soak.
4. **Production promotion blijft gate-off.** Een enablementbesluit is een latere, afzonderlijke expliciete milestone.

## Open blockers / beslissingen

`CONTINUOUS_DYNAMIC_COMPOSER_TECHNICAL_PREVIEW = PASS`.
`MUSICAL_EVENT_ENVELOPE_TECHNICAL_PREVIEW = PASS`.
`MUSICAL_EVENT_ENVELOPE_HUMAN_VISUAL_ACCEPTANCE = HOLD` totdat de verse Beta
tijdens echte spelende playback de muzikale duration en natuurlijke settle
bevestigt. Production promotion blijft buiten scope.

`LIVE_INTENSITY_STRUCTURED_TECHNICAL_PASS`.
`LIVE_INTENSITY_FEEDBACK = HOLD_HUMAN_RETEST`.
`BEAT_DIMMER_PHASE_SYNC_TECHNICAL_PASS`.
`FILL_MICRO_EVIDENCE_FOUNDATION = TECHNICAL_PASS`.
`FILL_HUMAN_REVIEW_PACKAGE = READY`.
`FILL_CALIBRATION = HOLD_HUMAN_LABELS`.
`FILL_EVENT_PROMOTION = HOLD_MORE_REVIEW_REQUIRED`.
`DYNAMIC_COMPOSER_PRODUCTION_SELECTOR = TECHNICAL_PASS_GATE_OFF`.
`DYNAMIC_COMPOSER_PRODUCTION_MODE = BASELINE_ONLY`.
`DYNAMIC_COMPOSER_FULL_CORPUS_SHADOW_SOAK = PASS`.
`PRODUCTION_SELECTOR_FAULT_INJECTION = PASS`.
`DYNAMIC_COMPOSER_RUNTIME_SOAK = PASS`.
`PREVIEW_BEAT_PULSE_RENDER_QUALITY = HOLD_HUMAN_RETEST`.

## Niet nu / bewust gesloten

- Canonical production authority niet heropenen zonder wezenlijk nieuwe provenance-clean evidence.
- Rekordbox is legacy context en geen toekomstig doelplatform.
- Rich Musical Events en Dynamic Composer hebben geen physical-DMX- of production-Auto-Show-authority; M23C is uitsluitend Preview Map.
- Geen human Rich Event-tuning zonder concrete hoorbare semantic vraag.

## Roadmapgebruik

- `MASTER_ROADMAP.md` = historische en architecturale source of truth.
- `CURRENT_ROADMAP.md` = compacte actuele status, prioriteiten en blockers.
- Bij iedere relevante milestone worden beide bestanden geraadpleegd en selectief bijgewerkt; oude afgeronde informatie wordt uit deze compacte roadmap verwijderd of samengevat.
