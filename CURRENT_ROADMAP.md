# SongAnalyzer / BeatBeam — Current Roadmap

> Compacte actuele projectstatus. De volledige chronologische architectuur- en
> besluitgeschiedenis staat in `MASTER_ROADMAP.md`; de levende werkvoorraad staat
> in `MASTER_BACKLOG.md`.

## Productrichting

- **VirtualDJ** is de live playback-, deck- en master-authority.
- **SongAnalyzer** levert software-onafhankelijke diepe muziekanalyse en een compact, versioneerbaar runtime-handoff.
- **BeatBeam** vertaalt die live context naar veilige lighting/show-output.
- Composertruth is wat er muzikaal gebeurt: `ContinuousMusicalState`, sectietiming/-voortgang, relatieve energie en traject, recurrence/material return, section character, structurele grenzen en change, met optionele BUILD/BREAK/ARRIVAL/RELEASE/DROP/RETURN/DEPARTURE/TRANSITION-modifiers.
- Rekordbox is uitsluitend `LEGACY / HISTORICAL / RESEARCH CONTEXT`, geen actieve productrichting.

## Current Production State

- Physical output blijft `existing_autoshow -> current_values`.
- `DYNAMIC_COMPOSER_PRODUCTION_MODE = BASELINE_ONLY`; de selector is technisch geïmplementeerd en fail-closed, maar ENABLED bestaat alleen in pure tests.
- Dynamic Composer, live intensity, event envelopes en variatie zijn **Preview Map**-functionaliteit en wijzigen geen fysieke DMX-authority.
- Bestaande handmatige veiligheid (phrase/color/energy/strobe, one-shot, chase, snake, all-on, sweep en blackout) blijft downstream van dezelfde bestaande renderer; dit is geen open infrastructuurtaak.

## Technical PASS

- `FULL_CONTINUOUS_STATE_COVERAGE_PASS`: 215/215 tracks current en usable, 2.203 sectie-observaties, 11.741/11.741 geldige state/composerframes, 0 invalid/exceptions. No-current-RME: 5.375/5.375 geldig.
- RME-foundation: provenance-clean, deterministisch, software-onafhankelijk, fail-closed en compact gepersisteerd naar runtime; RME is een sparse modifier, niet de continuous backbone.
- Dynamic Composer: continuous backbone, optional RME-modulatie, Event Envelope (1.986/1.986 completions), generatieve variatie zonder directe repeats over 215 tracks, selector/fault-injection en 100k-frame lifecycle-soak (0 errors, identity/state leaks; circa 0,8 MiB RSS-groei).
- Live intensity: `LIVE_INTENSITY_STRUCTURED_TECHNICAL_PASS`; attack 0,16 s, release 0,85 s, 5 s baseline en begrensde ±0,06 previewmodifier.
- Beat/dimmer: fase-locked `get_beatpos`-route is technisch pass; EVERY_BEAT, HALF_TIME en BAR_ACCENT zijn expliciete presentatie-intenties.
- VirtualDJ lifecycle: active-deck/master-authority, prewarm, deck/path-generation identity, observability en fast activate-path zijn pass: `VDJ_DECK_PREWARM_MASTER_SYNC = PASS` en `MASTER_SWITCH_ACTIVATE_LATENCY_OPTIMIZATION_PASS`.
- `ANALYSIS_WORKER_OPERATIONAL_HARDENING_PASS`: de bestaande sequential bridgequeue is bounded (128 queued, 256 terminal history), heeft expliciete terminal states, cancellation, een 10-minutentimeout, child-process cleanup, failure isolation, content-/response-identitychecks, restart recovery en operationele diagnostics. De 215/215 current library en bestaande prewarm/master-authority zijn behouden.
- `BEATBEAM_LIVE_SHOW_UX_V2_TECHNICAL_PASS`: de native standaardweergave is nu Live Show met compacte Live/Preview/Manual/Advanced-navigatie. Zij projecteert uitsluitend bestaande typed runtime-state: authoritative playback, decks/readiness, continuous state, intensity, event/envelope, composer/fixture-intent, manual safety en fysieke DMX-status. Raw diagnostics en de bestaande Preview Map zijn behouden; `is_playing` is alleen additief in de bestaande deck-state. Productie blijft `BASELINE_ONLY` en Preview blijft niet-authoritative.
- `SMART_CUE_PLANNER_V1_TECHNICAL_PASS` en `SMART_CUE_VDJ_WRITER_GATE_OFF_PASS`: 215/215 current analyses leveren deterministisch `smart-cue-plan-v1` zonder audioheranalyse; MIX IN/MAIN/BREAK/MIX OUT en MAIN-countdowns zijn provenance-clean en fail-closed. De bestaande VirtualDJ plugin/bridge exposeert plan-, cue-preflight- en conflictstatus read-only. De writer heeft exact deck/file/content/generation-preflight, managed ownership, verify/rollback en transportguards, maar production apply is hard `SMART_CUE_AUTO_APPLY_OFF`.
- `BEATBEAM_SHOW_SIMULATOR_V1_TECHNICAL_PASS`: 215 offline tracks, één simulation playhead met section/RME/event/Smart Cue-timeline, deterministic scrub/jumps en geïsoleerde Dynamic Composer previewframes. De bestaande 2D/3D Preview Map consumeert bij Simulator de afzonderlijke `simulation_slot_previews`; fysieke output blijft hard `NONE`.
- FILL: pre-native micro-evidence, tooling en geblindeerd reviewpakket zijn gereed; 82 candidates in de 24-track diagnose. Geen FILL-promotie.

## Human Holds / thuisreview

1. **FILL:** label 36 geblindeerde snippets als `FILL`, `NOT_FILL` of `UNCLEAR`, inclusief gemiste duidelijke fills.
2. **Live intensity:** vergelijk quiet, sustained build, hard/full, breakdown en recovery in echte playback.
3. **Preview beat pulse:** beoordeel EVERY_BEAT timing/perceptie in de Preview Map.
4. **Event Envelope:** beoordeel ARRIVAL, DROP, RELEASE en transities op muzikale timing, duration en settle.
5. **Variatie:** beoordeel repeat, variation, recurrence en muzikale fit.
6. **Live Show UX V2:** beoordeel de scanbaarheid, taal, compact/breed gedrag en de scheiding Live/Preview/Manual/Advanced tijdens echte bediening.
7. **Smart Cues V1:** beoordeel de 24-track thuisreview op praktische MIX IN-runway, juiste MAIN, bruikbare BREAK/MIX OUT en muzikale 16/12/8/4-bar aftellingen. `SMART_CUE_PLACEMENT = HOLD_HUMAN_REVIEW`.
8. **Show Simulator V1:** beoordeel timeline, navigatie en gesimuleerde 2D/3D Preview Map in de native app. `BEATBEAM_SHOW_SIMULATOR_V1 = HOLD_USER_REVIEW`; dit heeft geen live- of DMX-authority.

## Active / Next

- Lees en documenteer de vijf menselijke reviews; geen parameterwijziging op basis van een enkele indruk.
- Na FILL-labels: kalibratiebesluit op evidence, of expliciet niet promoveren.
- Na consistente human evidence: afzonderlijke beslissing over shadow-event promotie en eventuele envelope-integratie.
- Een eventuele Dynamic Composer-production promotion komt pas ná alle expliciete safety- en human gates; dit is geen huidige enablementtaak.
- Na voldoende Smart Cue-placementreview: een afzonderlijke `CONTROLLED_VDJ_APPLY`-milestone op een expliciet toegestaan disposable/testasset; geen library-wide apply.

## Later / Deferred

- Evidence-first micro-events: andere short accents, risers/downlifters, impact- en vocal/percussion/bass entry/removal-signalen.
- Reële UX-uitbreidingen: fixture/manual UX-polish en moving-head-snelheidsbediening. Live Show UX V2 is technisch gereed en wacht uitsluitend op human review.
- VirtualDJ workflow-/reanalyze-UX en resterende productization (installer, updates en release/distributie) zijn Deferred totdat er productprioriteit en een apart scoped plan is. Smart Hot Cues is niet meer deferred: de technische V1-foundation is gereed en wacht op human placementreview.

## Safety Gates

- `CANONICAL_CANDIDATE_PRODUCTION_AUTHORITY = DISABLED_UNDER_CURRENT_EVIDENCE_CONTRACT`. `M24_CANONICAL_AUTHORITY_CLOSEOUT_PASS` blijft gesloten; `LEGACY_ONLY_PRODUCTION_CANDIDATE_SHADOW_RETAINED` is geen open TODO. Geen heropening via thresholds, whitelist, kleine sample, candidate==legacy of hetzelfde evidencepakket.
- `FILL_EVIDENCE_PROMISING_MORE_REVIEW_REQUIRED` en `FILL_CALIBRATION = HOLD_HUMAN_LABELS`; FILL is nooit een directe “FILL → strobe”-productregel.
- `SMART_CUE_PLACEMENT = HOLD_HUMAN_REVIEW` en `SMART_CUE_AUTO_APPLY = OFF`; geen production- of library-wide cuewrites vóór review plus een apart gecontroleerd applybesluit.
- `MUSICAL_EVENT_ENVELOPE_HUMAN_VISUAL_ACCEPTANCE = HOLD`, `LIVE_INTENSITY_FEEDBACK = HOLD_HUMAN_RETEST`, `PREVIEW_BEAT_PULSE_RENDER_QUALITY = HOLD_HUMAN_RETEST` en `BEATBEAM_LIVE_SHOW_UX_V2 = HOLD_USER_REVIEW`.
- Unknown, stale, mismatch, invalid state, lifecycle discontinuity, renderer failure en manual override vallen same-frame terug naar baseline.

## Git State

- SongAnalyzer-checkpoints: `397e071` (FILL), `d3fd28f` (shadow handoff), `b982211` (VirtualDJ lifecycle), `f6025a1` (analysis-worker operational hardening); geen remote.
- BeatBeam-checkpoints: `84c1779` (composer foundation), `c499a0c` (preview/runtime diagnostics), `ad3dd8a` (continuous coverage/checkpoint), `f7de492` (Live Show UX V2), `5cc3c82` (Show Simulator V1 completion).
- Generated review-/soakartifacts zijn geen source-dirty state. Lokale commits blijven de veilige werkwijze; geen automatische push.
