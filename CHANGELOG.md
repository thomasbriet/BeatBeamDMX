# Changelog

## [1.0.0-rc1] - 2026-06-26

### Added
- Changelog tracking gestart voor de wijzigingen richting `1.0`.

### Changed
- BeatBeam kan nu preview-cachebestanden lezen met extra `dense_samples` naast de bestaande 8-beat `segments`.
- Track-preview matching gebruikt nu waar beschikbaar half-beat waveform-samples als fijnere matchbron, met fallback naar de oude segment-samenvatting.
- Lookahead-matching voor waveform/bands vergelijkt nu ook tegen die fijnere preview-samples, zodat de geplande show minder grof op 8-beat blokken hoeft te leunen.
- BeatBeam leest preview-caches nu uit zowel het standaardpad als een user-fallbackpad, en kiest per track automatisch de nieuwste cache.

### BPM Trigger
- `rkbx_link` schrijft nu preview-cachebestanden met `sample_beats` en `dense_samples` op halve-beat resolutie.
- Dense preview-samples bevatten per meetpunt beat, seconden, phrase, energy, low, mid, high, activity en rise.
- `rkbx_link` wijkt automatisch uit naar een user-schrijfbaar fallback cachepad als de standaard cachemap niet beschrijfbaar is.

## [0.1] - 2026-06-12

### Added
- Eerste vastgelegde release van BeatBeam DMX (`v0.1`).
