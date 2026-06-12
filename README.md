# BeatBeam DMX

Combined local controller for:

- Enttec Open DMX USB output
- Fixture profiles converted from Lightkey
- OSC input from Live BPM Trigger

## Start

```bash
cd /Users/thomasbriet/BeatBeamDMX
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python beatbeam_app.py
```

Open:

```text
http://127.0.0.1:8780
```

## Native macOS App

De native macOS-app bouwt op dezelfde lokale Python-engine, maar zonder browser UI.

Build:

```bash
cd /Users/thomasbriet/BeatBeamDMX
./build_native_app.sh
```

Open:

```bash
open "/Users/thomasbriet/BeatBeamDMX/dist-native-app/BeatBeam DMX.app"
```

De app start zo nodig zelf de lokale backend op `127.0.0.1:8780` en gebruikt:

- Enttec Open DMX USB connect/disconnect
- PAR en moving head tegelijk in 1 universe
- OSC monitor voor Live BPM Trigger
- Live DMX kanaalmonitor

## OSC

BeatBeam start of stopt Live BPM Trigger niet meer. Gebruik de apps los:

1. start `Live BPM Trigger.app`
2. laat die op `4460` luisteren zoals normaal
3. start daarna `BeatBeam DMX.app`

BeatBeam luistert standaard op UDP `4461` en begrijpt dezelfde Rekordbox OSC
berichten als Live BPM Trigger:

- `/bpm/master/current`
- `/beat/master`
- `/master/phrase/current`
- `/master/mood`
- `/master/color_bank`
- `/master/strobe/active`
