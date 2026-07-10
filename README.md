# BeatBeam DMX

BeatBeam DMX is een lokale macOS lighting controller voor een enkel DMX-universe, met:

- Enttec Open DMX USB output
- fixtureprofielen en handmatige fixture-controls
- Auto Show op basis van Rekordbox OSC, live audio of handmatige tap-clock
- 2D- en GPU-gebaseerde 3D-preview
- ingebouwde iPad remote via webremote
- een aparte native iPad remote app in `ipad-remote/`

De huidige ontwikkellijn is `1.2`. De stabiele macOS release staat op `1.1.0`.

## Huidige opzet

De repo bevat drie relevante lagen:

1. `beatbeam_app.py`
   De lokale Python backend met DMX, transport, Auto Show, remote endpoints en fixturelogica.

2. `native/BeatBeamDMXApp.swift`
   De native macOS app. Deze start de backend zo nodig zelf op en is de hoofd-UI voor live gebruik.

3. `ipad-remote/`
   Een aparte native iPad remote app die met dezelfde BeatBeam remote endpoints praat.

## Functies

- DMX output via Enttec Open DMX USB
- transportmodi `Auto`, `OSC` en `Tap`
- ingebouwde live audio-analyse
- start/stop van de Rekordbox bridge vanuit BeatBeam
- fixture-specifieke preview voor moving heads, parren, wall wash bars en Bee fixtures
- handmatige overrides voor kleur, effecten, phrase en show-stijl
- remote bediening via browser of native iPad app

## Vereisten

- macOS
- Python 3
- een lokale virtualenv in `.venv`
- voor de native macOS build: Swift toolchain / Xcode command line tools
- voor Rekordbox-bridge integratie: een werkende `start_bridge.sh` uit de BPM Trigger setup

De bridge wordt standaard gezocht op:

```text
~/BPM Trigger/start_bridge.sh
```

## Python backend direct starten

Voor development of browsergebruik zonder native app:

```bash
cd /Users/thomasbriet/BeatBeamDMX
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python beatbeam_app.py
```

Open daarna:

```text
http://127.0.0.1:8780
```

## Native macOS app bouwen

De buildscript ondersteunt aparte `release` en `beta` varianten.

### Release build

```bash
cd /Users/thomasbriet/BeatBeamDMX
./build_native_app.sh release
open "dist-native-app/BeatBeam DMX.app"
```

- appnaam: `BeatBeam DMX`
- backendpoort: `8780`
- OSC-poort: `4461`
- versie: `1.1.0`

### Beta build

```bash
cd /Users/thomasbriet/BeatBeamDMX
./build_native_app.sh beta
open "dist-native-app/BeatBeam DMX Beta.app"
```

- appnaam: `BeatBeam DMX Beta`
- backendpoort: `8781`
- OSC-poort: `4462`
- versie: `1.2.0-beta`

### Beide bouwen

```bash
./build_native_app.sh both
```

De native app:

- start de backend automatisch als die nog niet draait
- kan de Rekordbox bridge starten en stoppen
- kan live audio direct als input gebruiken
- stopt de bridge bij afsluiten weer netjes

## Rekordbox / BPM Trigger

BeatBeam ondersteunt twee paden:

1. externe OSC van Rekordbox / bestaande BPM Trigger setup
2. de geïntegreerde BeatBeam bridge-besturing via `start_bridge.sh`

BeatBeam begrijpt onder andere:

- `/bpm/master/current`
- `/beat/master`
- `/master/phrase/current`
- `/master/mood`
- `/master/color_bank`
- `/master/strobe/active`
- waveform- en previewdata uit de Rekordbox bridge

Daarnaast kan BeatBeam zonder externe trackplayback blijven werken via:

- handmatige tap-BPM
- idle animatie
- live audio-analyse

## Remote

### Browser remote

De backend exposeert een remote op:

```text
/remote
```

De macOS app toont automatisch de juiste URL, inclusief:

- lokaal adres
- LAN-adres
- Tailscale-adres
- USB/wired remote URL als beschikbaar

### Native iPad app

De native iPad remote staat in:

```text
ipad-remote/BeatBeamRemote.xcodeproj
```

Die app:

- scant de BeatBeam QR-code
- draait in landscape
- houdt het scherm wakker zolang hij op de voorgrond actief is

## Preview

BeatBeam heeft:

- 2D top/front/back/side map views
- een GPU-gebaseerde 3D stage preview
- fixture-specifieke rendering voor beams, wall washes en Bee patterns

De 3D preview is bedoeld als live feedback, niet als photorealistische render-engine.

## Belangrijke bestanden

```text
beatbeam_app.py                 Python backend
native/BeatBeamDMXApp.swift     Native macOS app
fixtures.json                   Fixture library
beatbeam_config.json            Basisconfiguratie
beatbeam_transport.json         Transport state/config
beatbeam_remote.json            Remote access state/config
build_native_app.sh             Release/beta buildscript
assets/                         Bee pattern assets en andere preview-assets
ipad-remote/                    Native iPad remote app
CHANGELOG.md                    Wijzigingen per versie
releases/                       Release notes
```

## Versies

- `main` volgt de actuele stabiele release-lijn
- `beta/1.2` is de actieve ontwikkelbranch
- `v1.1.0` is de huidige GitHub release tag

## Bekende workflow

Voor live gebruik is dit de praktische volgorde:

1. open de native macOS app
2. verbind DMX
3. start indien nodig de Rekordbox bridge vanuit `Now` of `Transport`
4. controleer de preview en transportstatus
5. open eventueel de iPad remote
