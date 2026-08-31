# BeatBeam + SongAnalyzer — Master Backlog

> Levende werkvoorraad per 2026-08-27. Voor historische besluiten en implementatiedetails: `MASTER_ROADMAP.md`. Voor de compacte status: `CURRENT_ROADMAP.md`.

## NOW / HUMAN GATE

| Item | Status | Doel | Blokker / bewijs voor vervolg |
| --- | --- | --- | --- |
| FILL blinded review | `HOLD_HUMAN_LABELS` | Label 36 snippets (`FILL` / `NOT_FILL` / `UNCLEAR`) en noteer gemiste fills. | Menselijke labels ontbreken. |
| Live intensity review | `HOLD_HUMAN_RETEST` | Vergelijk quiet, build, hard/full, breakdown en recovery. | Reproduceerbare passage-evidence ontbreekt. |
| Preview beat pulse | `HOLD_HUMAN_RETEST` | Beoordeel EVERY_BEAT-timing en perceptie. | Technische fase-lock is pass; perceptie nog niet. |
| Event Envelope review | `HOLD_HUMAN_VISUAL_ACCEPTANCE` | Beoordeel ARRIVAL, DROP, RELEASE en transities. | Muzikale timing/duration/settle nog niet live bevestigd. |
| Variation review | `HOLD_HUMAN_VISUAL_ACCEPTANCE` | Beoordeel repeat, variation, recurrence en muzikale fit. | Technisch geen directe repeats; visuele/muzikale acceptatie ontbreekt. |
| Live Show UX V2 review | `HOLD_USER_REVIEW` | Beoordeel scanbaarheid, taal, responsive gedrag en Live/Preview/Manual/Advanced-scheiding in echte bediening. | Technische pass is gereed; uitsluitend menselijke UX-acceptatie ontbreekt. |
| Smart Cue V1 placementreview | `HOLD_HUMAN_REVIEW` | Beoordeel 24 diverse tracks op MIX IN, MAIN, BREAK, MIX OUT en exacte 16/12/8/4-bar aftellingen. | Technische planner/writer-foundation is pass; muzikale plaatsing is niet menselijk geaccepteerd en auto-apply blijft hard uit. |
| Show Simulator V1 review | `HOLD_USER_REVIEW` | Beoordeel timeline, cue/event/section-jumps en de gesimuleerde 2D/3D Preview Map. | Technische pass is gereed; Simulator heeft hard nul fysieke authority. |
| VirtualDJ-native SongAnalyzer V1 review | `HOLD_USER_REVIEW` | Beoordeel SongAnalyzer-kolom en Analyze/Reanalyze/Retry als dagelijkse workflow. | Technische live/headless pass is gereed; bredere usabilityreview ontbreekt. |
| Dynamic Composer advanced effects V2 review | `HOLD_USER_REVIEW` | Beoordeel dimmermotieven, verzadigde paletten, kleur-/participatievariatie en gecontroleerde RETURN-herkenning in Beta-productie. | De productie-gate is lokaal persistent `DYNAMIC_COMPOSER_ENABLED`; manual/blackout en de fail-closed `existing_autoshow`-fallback behouden voorrang. |
| iPad Color-first Override V1 review | `HOLD_USER_REVIEW` | Beoordeel single colors, twee-kleur-combos, verticale Energy-fader, compacte safety-actions en vaste landscape op de fysieke iPad. | Technische route is PASS, inclusief no-DMX Remote V2; menselijke performance/UX-review ontbreekt. |

## NEXT

| Item | Status | Doel | Blokker |
| --- | --- | --- | --- |
| FILL calibration decision | `BLOCKED_ON_HUMAN_LABELS` | Evalueer de gelabelde set; kies bounded kalibratie, shadow-event-experiment of geen promotie. | NOW/FILL-review. |
| FILL shadow-event / envelope decision | `BLOCKED_ON_CALIBRATION_EVIDENCE` | Alleen bij aantoonbaar bewijs bepalen of FILL als bounded micro-event mag worden geprojecteerd. | Kalibratiebesluit; geen directe strobe-regel. |
| Controlled VirtualDJ Smart Cue apply | `BLOCKED_ON_HUMAN_PLACEMENT_REVIEW` | Alleen met expliciete toestemming een write/readback/delete-cyclus op een disposable/testasset uitvoeren. | Smart Cue-human-review; geen normale librarytrack en geen library-wide apply. |

## LATER

| Item | Status | Doel | Blokker |
| --- | --- | --- | --- |
| Andere short accents / micro-events | `EVIDENCE_FIRST` | Onderzoek bounded accents naast FILL. | Nieuwe hoorbare evidence en guards. |
| Risers, downlifters, impacts | `EVIDENCE_FIRST` | Alleen toevoegen wanneer de gewenste showreactie is bewezen. | Corpus- en human evidence. |
| Vocal/percussion/bass entry-removal | `EVIDENCE_FIRST` | Onderzoek alleen als het een bruikbare showbeslissing oplevert. | Productvraag en betrouwbare analyse-evidence. |
| Moving-head speed control | `LATER` | Bounded handmatige snelheidsmodifier boven Auto Show. | UX- en safety-specificatie. |

## DEFERRED

| Item | Status | Doel | Blokker |
| --- | --- | --- | --- |
| Release/distributie | `DEFERRED` | Ondertekende distributie, updatekanaal en eventuele release-automation. | Geen remote/releasekanaal bestaat. |
| VirtualDJ library-wide status/batch | `UNSUPPORTED_OR_DEFERRED` | Alleen via een later officieel ondersteunde arbitrary-track/batchroute. | Huidige officiële API ondersteunt uitsluitend browsed/loaded metadatawrite; geen browserautomatisering of databasehack. |

## DONE RECENTLY

- `FULL_CONTINUOUS_STATE_COVERAGE_PASS`: 215/215 tracks, 2.203 sections en 11.741/11.741 geldige frames.
- RME-foundation: deterministic, provenance-clean, persisted en fail-closed.
- Dynamic Composer continuous backbone, RME-modulation, Event Envelope, generative variation, selector hardening, fault injection en 100k soak.
- `LIVE_INTENSITY_STRUCTURED_TECHNICAL_PASS` en beat/dimmer phase-sync pass.
- `VDJ_DECK_PREWARM_MASTER_SYNC = PASS` en `MASTER_SWITCH_ACTIVATE_LATENCY_OPTIMIZATION_PASS`.
- `ANALYSIS_WORKER_OPERATIONAL_HARDENING_PASS`: expliciete bounded joblifecycle, cancellation/timeout, worker crash isolation en cleanup, stale-pending recovery, atomic cache/handoff publication en operationele diagnostics; 215/215 current bleef behouden.
- `VIRTUALDJ_NATIVE_SONGANALYZER_WORKFLOW_V1_TECHNICAL_PASS`, `SONGANALYZER_HEADLESS_SERVICE_FOUNDATION_PASS` en `VIRTUALDJ_SONGANALYZER_STATUS_COLUMN_PASS`: ownership-safe lazy browsed/loaded statusmirror, exacte Analyze/Reanalyze/Retry, plugin-owned service recovery en live worker/cache/handoff zonder MusicAnalyzer GUI. MusicAnalyzer daily UI is deprecated product direction; human usability blijft HOLD.
- `SONGANALYZER_HEADLESS_PRODUCTIZATION_V1_TECHNICAL_PASS`: reproduceerbare package/install/verify/repair/rollback/status-flow met installatie-manifest, staged ARM64/signing/hashvalidatie, één owned previous installatie, protocolidentity fail-closed en live headless VDJ-smoke. Release/distributie blijft deferred.
- `BEATBEAM_LIVE_SHOW_UX_V2_TECHNICAL_PASS`: Live Show als standaard, aparte Preview/Manual/Advanced, bestaande Preview Map/raw diagnostics behouden en geen wijziging van production authority.
- `SMART_CUE_PLANNER_V1_TECHNICAL_PASS` en `SMART_CUE_VDJ_WRITER_GATE_OFF_PASS`: deterministic 215-track planning, corpus/reviewpackage, read-only native cue-preflight en exact-identity writer/ownership/verify/rollback foundation; `SMART_CUE_AUTO_APPLY_OFF` live bewezen.
- `BEATBEAM_SHOW_SIMULATOR_V1_TECHNICAL_PASS`: musical timeline, cue/event/section navigation, isolated previewframes en native 2D/3D Preview Map datasource; 215-track deterministic corpusprojectie en packaged runtime-smoke groen.
- `DYNAMIC_COMPOSER_ADVANCED_EFFECT_VARIATION_V2_TECHNICAL_PASS`: first-class dimmermotieven, saturated discrete color animation, fixture-participatie en component-aware anti-repeat; 222-track/2.284-section corpus 0 invalid/renderer failures en packaged Beta-smoke groen. De expliciete productie-enablement staat in het volgende checkpoint.
- `DYNAMIC_COMPOSER_BETA_PRODUCTION_ENABLEMENT_PASS` (2026-08-28): Beta lokaal persistent op `DYNAMIC_COMPOSER_ENABLED`; live smoke 161 Dynamic Composer-frames/8 s, geen nieuwe dispatch failures en exacte composer-intent → `current_values` → RGB-DMX presetcongruentie. Baseline-fallback en manual/blackout-precedence beschikbaar.
- `BEATBEAM_MANUAL_COLOR_COMBO_V1_TECHNICAL_PASS` en `BEATBEAM_IPAD_COLOR_FIRST_OVERRIDE_V1_TECHNICAL_PASS`: acht deterministische Manual-presetsparen, exact-preset capability-projectie, mutual exclusion met single color, AUTO/Release All/Blackout semantics, LIVE_CONTROL/Remote V2 en no-DMX runtimeacceptatie. De iPad-layout is Color-first met vaste landscape; human UI review blijft HOLD.
- `BEAMZ_BLAZE_PROFILE_TECHNICAL_PASS` en `MANUAL_COLOR_COMBO_BEAT_SWAP_PASS`: fabrikant-gebaseerd BeamZ BLAZE Series 160.538 / 160.540 / 160.542 8ch-profiel met native 255/255/100-schaling, veilige Fog/Macro-defaults en RGB-manual-compatibiliteit zonder fictief White-kanaal. De stabiele Manual Combo A/B-partities wisselen op de authoritative beat, bevriezen bij stale transport en hervatten zonder vrije timer. No-DMX runtimeacceptatie, blackout/release en source/install-identiteit zijn groen; `BEAMZ_BLAZE_PHYSICAL_OUTPUT = HOLD_HARDWARE_TEST`.
- `BEATBEAM_IPAD_OVERRIDE_REFINEMENT_V2_TECHNICAL_PASS`: 16 exact-preset, backend-authoritatieve Manual Color Combos in een vaste 2×8-bank, Smoke veilig disabled direct naast de Purple/Rainbow-kolom en een custom brede direct-tap/drag Energy-fader. Effects en Release/Blackout zijn compacter zonder lease-, pairing-, Settings- of Status-regressie. De app is gesigneerd, op de fysieke iPad geïnstalleerd en visueel gecontroleerd; human performance/UX-review blijft `HOLD_USER_REVIEW`.
- FILL micro-evidence/tooling en het 36-item blinded reviewpakket.

## LEGACY / CLOSED

- **Rekordbox:** `LEGACY / HISTORICAL / RESEARCH CONTEXT`; geen actieve roadmap.
- **Canonical candidate production authority:** `M24_CANONICAL_AUTHORITY_CLOSEOUT_PASS`; `LEGACY_ONLY_PRODUCTION_CANDIDATE_SHADOW_RETAINED`; `CANONICAL_CANDIDATE_PRODUCTION_AUTHORITY = DISABLED_UNDER_CURRENT_EVIDENCE_CONTRACT`. Niet heropenen met thresholds, whitelist, kleine samples, candidate==legacy of hetzelfde evidencepakket.
- Canonieke section labels zijn geen actieve production-composertruth; de continuous musical state is de backbone.
- FILL heeft geen automatische strobe-authority en is niet gepromoveerd.
- Oude TODO/BEZIG-planning in `MASTER_ROADMAP.md` is historische context, geen actieve backlog tenzij hier expliciet opnieuw opgenomen.
