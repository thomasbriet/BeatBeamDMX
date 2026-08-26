# Dynamic Composer production promotion design

Status: `IMPLEMENTED_GATE_OFF`. De pure selector en observability zijn aanwezig,
maar de runtime-default blijft de niet-configureerbare interne
`BASELINE_ONLY`; dit document activeert geen production- of fysieke
DMX-authority.

## Kleinste veilige source-selection point

De huidige frameflow bouwt in `_render_tick` eerst `auto_show` met
`_auto_show_evaluation`, rendert dat via `_render_values` naar `current_values`
en bouwt daarna afzonderlijk `preview_auto_show -> slot_previews`. De latere
productieselectie hoort precies tussen show-state-evaluatie en de ene bestaande
renderer:

```text
baseline_auto_show = existing _auto_show_evaluation(...)
composer_candidate = shared dynamic-composer candidate evaluation(...)
selected_auto_show, decision = select_production_show_source(...)
current_values = existing _render_values(..., auto_show=selected_auto_show)
```

`select_production_show_source` wordt één pure, centrale selector die door de
render tick én de synchrone config/preview-updatepaden wordt gebruikt. De
composer levert alleen een composed show state/fixture-group intent; hij krijgt
geen DMX-kanalen en omzeilt `_effective_slot_config`, `_render_slot_values`,
fixture capabilities, clamps, conflictregistratie of blackout nooit.

## Modi

- `BASELINE_ONLY` (persistente default): candidate hoeft niet te worden
  berekend; physical source is altijd baseline.
- `DYNAMIC_COMPOSER_SHADOW`: candidate en eligibility worden berekend en
  vergeleken, maar physical source blijft baseline.
- `DYNAMIC_COMPOSER_ENABLED`: candidate mag alleen bij alle gates physical
  show-state source worden. Deze milestone voegt of activeert deze mode niet.

Er is geen automatische promotie van SHADOW naar ENABLED.

## Eligibility en failback

Alle onderstaande voorwaarden zijn gelijktijdig vereist:

1. mode is expliciet `DYNAMIC_COMPOSER_ENABLED`;
2. VirtualDJ active deck/path is exact dezelfde canonieke track als de current
   SongAnalyzer-handoff;
3. playback generation is positief en exact gelijk aan handoff- en
   composer-lifecycle generation;
4. handoff is current, exact en niet stale of pending;
5. `ContinuousMusicalState` bevat geldige track/observation-identiteit,
   sectietiming en relatieve energie voor de huidige positie;
6. composer retourneert een valide, finite, bounded show state met uitsluitend
   bekende abstracte primitives/group intents;
7. de bestaande renderer is actief en niet in error;
8. er is geen manual override of lifecycle-ambiguïteit.

Een current RME/EventEnvelope is optioneel. Geldige live intensity is eveneens
optioneel; bij missing/stale/mismatch gebruikt de composer exact analyzed-only.

Iedere gate faalt gesloten naar de voor hetzelfde frame reeds berekende
`baseline_auto_show`. Een composerexception, ongeldige composition, track- of
generationmismatch, ontbrekende essentiële continuous state of rendererfout
produceert dus geen zwart/tussenframe en geen gedeeltelijke candidate. De
selector houdt nooit de vorige composed state vast.

## Authority en manual overrides

De feitelijke volgorde voor de latere productieroute wordt:

```text
blackout/safety
> manual override of one-shot (baseline show-state route)
> eligible Dynamic Composer show state
> same-frame baseline failback
> bestaande fixture renderer/capabilities/clamps
> current_values
> DMX sink
```

Blackout blijft de eerste check in `_render_values_with_context`. Voor veilige
en eenduidige precedence maakt elke bestaande phrase-, color-, energy-, manual
strobe-, audience-, all-on-, PAR- of one-shot-override de composer niet
eligible; de baseline state bevat en realiseert die override via de bestaande
renderer. Manual strobe blijft capability-gegate. Een toekomstige FILL of
ander event mag alleen abstract accent/strobe intent leveren; fixture- en
strobe-safety blijven downstream authoritative.

## Observability

De centrale decision exposeert per frame:

- `production_show_mode`, `production_show_source` en `decision_generation`;
- `dynamic_composer_eligible`, `dynamic_composer_active`;
- `fallback_active`, `fallback_reason`;
- `manual_override_active`, `continuous_state_valid`;
- current RME en EventEnvelope-samenvatting;
- analyzed intensity, live-source valid/fallback en effective intensity;
- baseline/candidate composition signatures in SHADOW, zonder raw DMX-diff.

Fallbackredenen zijn vaste enumwaarden, minimaal `mode_baseline`,
`manual_override`, `track_mismatch`, `handoff_not_current`, `generation_mismatch`,
`continuous_state_missing`, `composer_exception`, `composition_invalid` en
`renderer_unhealthy`.

## Rollback

Rollback is één centrale interne modewijziging naar `BASELINE_ONLY`. Dit vereist geen
SongAnalyzer-aanpassing, cache- of databaseschema, migratie, app-reinstall of
stateconversie. Bij een onbekende/ontbrekende mode normaliseert de selector
eveneens naar `BASELINE_ONLY`.

## Vereiste implementatieacceptatie vóór enablement

- pure selectortests voor iedere eligibility- en fallbackreden;
- baseline physical-frame identity in BASELINE en SHADOW;
- exact candidate-frame bewijs in ENABLED onder een test-only expliciete gate;
- exception/invalid/stale/seek/track-switch/generation/manual-override tests;
- blackout, fixture-capability, strobe-safety en rendererclamp regressies;
- live A/B met positieve human acceptance en een afzonderlijke expliciete
  beslissing om de default te wijzigen.
