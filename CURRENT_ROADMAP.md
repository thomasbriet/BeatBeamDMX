# SongAnalyzer / BeatBeam — Current Roadmap

## Huidige status

- **SongAnalyzer:** software-onafhankelijke analyse-engine; M23A-cache/lifecycle-oplossing staat op `d8bc313`.
- **BeatBeam:** lighting/show engine; compacte Rich Musical Events worden ontvangen en gevalideerd.
- **VirtualDJ/live-integratie:** playback- en live-integratielaag blijft leidend en ongewijzigd.
- **Rich Musical Events:** 173/173 corpustracks beschikbaar na fresh én cache-hit; 6.594 events totaal.
- **Production/shadow:** BeatBeam blijft `SHADOW_ONLY`; production lighting, Auto Show en DMX gebruiken deze events niet.
- **Laatste milestone:** `M23A_RUNTIME_SHADOW_FULL_CORPUS_PASS` — afgesloten.

## Actieve milestone

**Status: NOG TE SELECTEREN**

M23A is afgesloten. MASTER_ROADMAP.md wijst show-readiness als volgende productrichting aan; een nieuwe formele milestone moet nog expliciet worden gekozen.

## Eerstvolgende prioriteiten

1. **VirtualDJ-playlist show-readiness afronden.** Analyseer de volledige relevante playlist, herstel resterende runner/analyzer- of stale-problemen en ga daarna naar feature freeze.
2. **Live betrouwbaarheid afronden.** Behoud veilige queueing en voeg alleen bewezen noodzakelijke robuustheid toe rond CPU-belasting, foutisolatie, atomische cachewrites, outputvalidatie en veilige fallback.
3. **Verdere hiërarchische analyse pas na show-readiness.** Alleen starten bij een aantoonbare nieuwe evidencebehoefte.

## Open blockers / beslissingen

Geen actuele technische blocker. De volgende formele milestone en scope moeten nog worden geselecteerd uit de bestaande show-readinessprioriteiten.

## Niet nu / bewust gesloten

- Canonical production authority niet heropenen zonder wezenlijk nieuwe provenance-clean evidence.
- Rekordbox is legacy context en geen toekomstig doelplatform.
- Rich Musical Events blijven `SHADOW_ONLY` totdat een expliciete latere production milestone dit wijzigt.
- Geen human Rich Event-tuning zonder concrete hoorbare semantic vraag.

## Roadmapgebruik

- `MASTER_ROADMAP.md` = historische en architecturale source of truth.
- `CURRENT_ROADMAP.md` = compacte actuele status, prioriteiten en blockers.
- Bij iedere relevante milestone worden beide bestanden geraadpleegd en selectief bijgewerkt; oude afgeronde informatie wordt uit deze compacte roadmap verwijderd of samengevat.
