# BeatBeam + SongAnalyzer — Master Backlog

> Levende werkvoorraad per 2026-08-26. Voor historische besluiten en implementatiedetails: `MASTER_ROADMAP.md`. Voor de compacte status: `CURRENT_ROADMAP.md`.

## NOW / HUMAN GATE

| Item | Status | Doel | Blokker / bewijs voor vervolg |
| --- | --- | --- | --- |
| FILL blinded review | `HOLD_HUMAN_LABELS` | Label 36 snippets (`FILL` / `NOT_FILL` / `UNCLEAR`) en noteer gemiste fills. | Menselijke labels ontbreken. |
| Live intensity review | `HOLD_HUMAN_RETEST` | Vergelijk quiet, build, hard/full, breakdown en recovery. | Reproduceerbare passage-evidence ontbreekt. |
| Preview beat pulse | `HOLD_HUMAN_RETEST` | Beoordeel EVERY_BEAT-timing en perceptie. | Technische fase-lock is pass; perceptie nog niet. |
| Event Envelope review | `HOLD_HUMAN_VISUAL_ACCEPTANCE` | Beoordeel ARRIVAL, DROP, RELEASE en transities. | Muzikale timing/duration/settle nog niet live bevestigd. |
| Variation review | `HOLD_HUMAN_VISUAL_ACCEPTANCE` | Beoordeel repeat, variation, recurrence en muzikale fit. | Technisch geen directe repeats; visuele/muzikale acceptatie ontbreekt. |

## NEXT

| Item | Status | Doel | Blokker |
| --- | --- | --- | --- |
| FILL calibration decision | `BLOCKED_ON_HUMAN_LABELS` | Evalueer de gelabelde set; kies bounded kalibratie, shadow-event-experiment of geen promotie. | NOW/FILL-review. |
| FILL shadow-event / envelope decision | `BLOCKED_ON_CALIBRATION_EVIDENCE` | Alleen bij aantoonbaar bewijs bepalen of FILL als bounded micro-event mag worden geprojecteerd. | Kalibratiebesluit; geen directe strobe-regel. |
| Dynamic Composer production decision | `GATED_OFF` | Alleen als aparte milestone beoordelen of promotie verantwoord is. | Alle relevante human/safety-gates; huidige runtime blijft `BASELINE_ONLY`. |

## LATER

| Item | Status | Doel | Blokker |
| --- | --- | --- | --- |
| Andere short accents / micro-events | `EVIDENCE_FIRST` | Onderzoek bounded accents naast FILL. | Nieuwe hoorbare evidence en guards. |
| Risers, downlifters, impacts | `EVIDENCE_FIRST` | Alleen toevoegen wanneer de gewenste showreactie is bewezen. | Corpus- en human evidence. |
| Vocal/percussion/bass entry-removal | `EVIDENCE_FIRST` | Onderzoek alleen als het een bruikbare showbeslissing oplevert. | Productvraag en betrouwbare analyse-evidence. |
| Live UI / fixture UX | `LATER` | Polish voor live bedienbaarheid en diagnostics. | Bestaande deck/master/prewarm/preview/composerdiagnostics niet dupliceren. |
| Moving-head speed control | `LATER` | Bounded handmatige snelheidsmodifier boven Auto Show. | UX- en safety-specificatie. |
| Show Simulator | `LATER` | Virtuele fixture-weergave voor analyse/showcontrole. | Apart ontwerp; niet verwarren met Native Preview Map. |

## DEFERRED

| Item | Status | Doel | Blokker |
| --- | --- | --- | --- |
| VirtualDJ workflow / reanalysis UX | `DEFERRED` | Voorbereidings-, batch-, retry- en statuservaring verfijnen. | Productprioriteit en scoped workflow. |
| Smart Hot Cues | `DEFERRED_VIRTUALDJ_ORIENTED` | Eventuele VirtualDJ-georiënteerde cue-ondersteuning. | Productbesluit; geen Rekordbox-outputrichting. |
| Productization | `DEFERRED` | Installer/update, operationele diagnostics, worker crash isolation, cancellation en resourcebeheer. | Expliciete release-/operational milestone. |

## DONE RECENTLY

- `FULL_CONTINUOUS_STATE_COVERAGE_PASS`: 215/215 tracks, 2.203 sections en 11.741/11.741 geldige frames.
- RME-foundation: deterministic, provenance-clean, persisted en fail-closed.
- Dynamic Composer continuous backbone, RME-modulation, Event Envelope, generative variation, selector hardening, fault injection en 100k soak.
- `LIVE_INTENSITY_STRUCTURED_TECHNICAL_PASS` en beat/dimmer phase-sync pass.
- `VDJ_DECK_PREWARM_MASTER_SYNC = PASS` en `MASTER_SWITCH_ACTIVATE_LATENCY_OPTIMIZATION_PASS`.
- FILL micro-evidence/tooling en het 36-item blinded reviewpakket.

## LEGACY / CLOSED

- **Rekordbox:** `LEGACY / HISTORICAL / RESEARCH CONTEXT`; geen actieve roadmap.
- **Canonical candidate production authority:** `M24_CANONICAL_AUTHORITY_CLOSEOUT_PASS`; `LEGACY_ONLY_PRODUCTION_CANDIDATE_SHADOW_RETAINED`; `CANONICAL_CANDIDATE_PRODUCTION_AUTHORITY = DISABLED_UNDER_CURRENT_EVIDENCE_CONTRACT`. Niet heropenen met thresholds, whitelist, kleine samples, candidate==legacy of hetzelfde evidencepakket.
- Canonieke section labels zijn geen actieve production-composertruth; de continuous musical state is de backbone.
- FILL heeft geen automatische strobe-authority en is niet gepromoveerd.
- Oude TODO/BEZIG-planning in `MASTER_ROADMAP.md` is historische context, geen actieve backlog tenzij hier expliciet opnieuw opgenomen.
