# Changelog

## [1.2.0-unreleased]

### Added
- Start van de `1.2` ontwikkelcyclus.
- De native macOS build bundelt nu een eigen app-local Python runtime en gebruikt die bij backendstart in plaats van direct te leunen op de lokale `.venv`-Python van de buildmachine.
- Dynamic Composer gebruikt in de Preview Map nu een compacte, software-onafhankelijke continuous musical state met sectievoortgang, relatieve energie, energietraject en optionele structurele recurrence/salience.
- Een pure, beat-/bar-gebaseerde Musical Event Envelope voor ARRIVAL, DROP, RELEASE, TRANSITION en future-ready FILL.
- VirtualDJ deck-prewarm voor geladen niet-masterdecks, met cache-hit/miss-status, normale-prioriteit-deduplicatie en bounded bridge-diagnostics.
- Preview-only Dynamic Composer-variatie met begrensde motion-, kleur-, pulse-
  en washparameters, track-lokale anti-repeat history en leesbare
  composition-signatures.
- Volledige continuous-state shadowdekking voor 215/215 librarytracks na vijf
  gerichte normale cache/lifecycle-heranalyses.
- Een bounded production show-selector met fail-closed same-frame baseline en
  een interne, niet-configureerbare `BASELINE_ONLY` runtime-default.
- Een fabrikant-gebaseerd 8ch fixtureprofiel voor BeamZ BLAZE Series
  160.538 / 160.540 / 160.542 (manual V1.1), met veilige Fog/Macro-defaults,
  native RGBA-maxima en zonder fictief White-kanaal.

### Changed
- Rich Musical Events moduleren de continuous Dynamic Composer-state tijdelijk; zonder current RME blijft de composer actief en valt de Preview Map niet meer terug op de complete baseline-scène.
- De Auto Show-observability toont Dynamic Composer-status, Musical State, RME Modifier en Preview Cue afzonderlijk.
- Point-RME's moduleren de Preview Dynamic Composer nu tijdelijk via attack/impact/settle en keren daarna exact terug naar Continuous Musical State; SongAnalyzer-eventduur en physical DMX blijven ongewijzigd.
- ARRIVAL heeft een sterker maar nog onder-DROP begrensd landing-accent; de
  twee-bar settle blijft ongewijzigd.
- Preview/runtime-observability exposeert continuous state, event envelope,
  live intensity, composition signature en selectorbesluit zonder production-
  of fysieke DMX-authority te wijzigen.
- Manual Color Combos gebruiken nu een stabiele kleurcapabele A/B-partitie die
  alleen op authoritative beat-parity wisselt, bij stale transport bevriest en
  bij verse authority zonder vrije timer hervat.

## [1.2.0-wishlist]

### Wishlist
- Portable beta-distributie voor andere Macs, vervolgstappen:
  - Rekordbox bridge intern bundelen met vooraf gebouwde `rkbx_link`, zodat testers geen Rust toolchain of losse BPM Trigger setup nodig hebben
  - first-run setup wizard voor audio input, DMX, Rekordbox detectie en bridge-status
  - signed/notarized distributie als `dmg` of `pkg`, met optionele advanced helper voor Rekordbox-fixes als dat echt nodig blijkt
- Verbeterde Bee floor-to-beam projectie-overgang: een overtuigender overgang tussen luchtstraal en vloerprojectie, bij voorkeur met target/intersection-logica, fade/hysteresis rond de omslag en een zachtere morph van air glow naar floor pattern in plaats van een harde switch.
- Uitgebreidere Bee Eye fixture-modi naast het huidige 15ch-profiel: echte 23/35/51ch-achtige ondersteuning met shape dimmer, background dimmer, shape fade/transition/offset, foreground/background strobe, zoom en rijkere pixel/ring macro’s zodra de hardware/mode dat echt toelaat.

## [1.1.0] - 2026-07-10

### Added
- Start van de `1.1` ontwikkelcyclus.
- BeatBeam heeft nu een interne transportlaag naast externe OSC, met modi `Auto`, `OSC` en `Tap`.
- Een 4-tap BPM pad kan nu een handmatige clock locken voor live muziek of momenten zonder track-playback.
- De backend levert nu ook synthetische beat-, phrase- en waveform-data in interne clock-modus, zodat Auto Show en preview blijven bewegen zonder externe audiofeed.
- De BeatBeam macOS-app heeft nu ingebouwde live-audio inputselectie en audio-analyse, zodat dynamiek niet meer via een losse BPM Trigger-app hoeft te lopen.
- BeatBeam kan nu ook zelf de Rekordbox-bridge starten en stoppen, zodat BPM Trigger niet meer als aparte bedienings-app open hoeft te staan.
- BeatBeam ondersteunt nu generieke fixture-specifieke extra DMX-controls, zodat fixtures met extra functies buiten de standaard dimmer/strobe/pan/tilt/RGBW-set handmatig toegevoegd en bestuurd kunnen worden.
- Een nieuw fixtureprofiel voor een generieke `Smart Bee Eye + Pattern Moving Head` (15ch) is toegevoegd, inclusief extra controls voor spot dimmer/strobe, color disk, pattern plate, Z-rotation en macro mode.
- De native build ondersteunt nu aparte `release`- en `beta`-varianten, zodat beide apps naast elkaar kunnen bestaan met eigen bundle-id, poorten, configuratie, cache en remote state.
- De map preview heeft nu ook een GPU-gebaseerde 3D-weergave met orbit/pan/zoom en camera-presets voor `Audience`, `Front`, `DJ` en `Top`.
- Het compacte `Now`-venster heeft nu naast `Tap` ook directe start/stop-knoppen voor BPM Trigger / de Rekordbox bridge.

### Changed
- De macOS-app toont nu compacte transportbediening direct in `Now`, met uitgebreidere clock-controls in het `Transport` utility-paneel.
- Minder bron-info staat permanent in het hoofdscherm; de detailstatus zit nu bij `Transport`.
- Interne tap/idle-clock kan nu echte live-audio waveform- en drumdata overnemen zonder per ongeluk over te schakelen naar volledige externe timing.
- De generieke `Smart Bee Eye + Pattern Moving Head` volgt in Auto Show nu ook automatisch de actieve kleur op zijn center spot/color wheel, terwijl de preview center spot en bee-eye wash visueel uit elkaar trekt.
- De preview rendert de Bee Eye nu fixture-specifiek met aparte wash/spot-weergave, color-wheel gedrag, pattern-keuze en zichtbare pattern-rotatie op head en beam-hit.
- Bee Eye triplet-patterns roteren in de preview nu als één cluster in plaats van drie statische posities met alleen losse shape-rotatie.
- Auto Show stuurt de Bee Eye nu ook inhoudelijk aan met automatische pattern-keuze en z-rotation per phrase, energie, beweging en track-thema, in plaats van alleen kleur/dimmer/strobe.
- De nieuwe 3D-preview rendert fixtures nu fixture-specifiek met onderscheid tussen moving heads, bee-eyes, wall wash bars en parren, inclusief selectie-highlights.
- De 3D-preview gebruikt nu volumetrische beams, endpoint-glows en bee pattern-projecties aan het beam-einde in plaats van alleen simpele richtingslijnen.
- De 3D-preview kan nu ook zelfstandig als enige view zichtbaar zijn, zonder verplichte top/front/side fallback.
- De 3D-beams gebruiken nu dichtere volumetrische beam-cards, zachte scatter-sprites en diffuse endpoint-hits, zodat de 3D-map minder blokkerig leest en meer als echte lichtstralen oogt.
- De 3D-preview rendert nu continu met extra camera-bloom, particle-based beam haze en zachter getemperde beam-cores, zodat de beams meer richting een game-engine look gaan en minder als massieve blokken ogen.
- De beam-cones gebruiken nu ook een Metal shader modifier voor source-to-tip falloff, view-dependent intensiteit en subtiele breakup-noise, zodat de cone zelf niet meer overal even sterk rendert.
- De 3D-preview draait in de beta nu op een eigen `MTKView`-renderer met custom camera-controls, stage-grid en tapered beam-ribbons, zodat verdere beam-shaping niet meer vastzit aan SceneKit-geometry.
- De Metal-beams gebruiken nu fixture-specifieke profielen: moving heads renderen ronder en strakker, parren ovaler en zachter, en wall wash bars platter als echte fan/sheet-beams met niet-lineaire spreiding langs de straal.
- Round- en oval-beams krijgen nu ook camera-facing cone-sheets bovenop de hulpribbons, zodat de preview minder losse beam-strepen toont en sterker als gevulde cone leest.
- Round-, oval- en fan-beams stapelen nu meerdere gevulde cone-sheets met grotere eindradius, terwijl ribbons alleen nog als subtiele structuurlaag mee-renderen; daardoor moet de beam-body duidelijker zichtbaar zijn dan de oude streeplook.
- Moving heads en parren gebruiken in de Metal-preview nu een geometrisch afgeleide 40° beam-spreiding; daarnaast renderen beams die de vloer raken ook een zachte ground-footprint als cone-projectie.
- De Metal-preview gebruikt nu ook photometrisch geïnspireerde beam-falloff: een 50%-core op de beam-angle, een bredere 10%-field/haze-shell en zachtere distance decay, zodat cones minder uniform ogen en realistischer in de ruimte wegvallen.
- Nieuwe fixtures landen in de beta-map nu standaard expliciet in het midden van het werkgebied in plaats van direct op een anchor-default, zodat patchen en positioneren sneller begint.
- De 2D top/front/back/side projecties hebben nu een gedeelde zoomstand met out/in/reset, zodat je het werkgebied compacter of juist groter in beeld kunt zetten zonder de 3D-view te beïnvloeden.
- Als in de map nog maar één enkele view zichtbaar is, schaalt die binnen de projection deck nu uit als hoofdview in plaats van als halve tegel, terwijl het assignments-paneel rechts zichtbaar blijft.
- De map-canvases renderen nu alle live fixtures direct op basis van hun world-position, ook als er (nog) geen bruikbare anchor-assignment is; daarnaast is de single-view hero-panel bewust minder hoog gemaakt zodat de rest van de map-tab in beeld blijft.
- Het stage-workgebied in de map en 3D-preview is nu merkbaar groter gemaakt in breedte, diepte en hoogte, zodat er aan alle kanten meer ruimte is om extra fixtures op te hangen zonder direct tegen de randen te zitten.
- De map-tab gebruikt nu zelf de vensterhoogte in plaats van een grote buitenste scroll-content; het assignments-paneel scrollt intern, en de single-view hero schaalt nu mee met de beschikbare hoogte van de app.
- Bee moving heads renderen nu in de Metal 3D-view ook hun pattern-vormen digitaal als texture-based hits op het beam-einde of op de vloer, inclusief rotatie uit de fixturedata, zodat de Bee-look niet meer alleen uit kleur en beams bestaat.
- Bee moving heads gebruiken in de Metal 3D-view nu een ruimere triplet-spreiding en langere spotprojectie, zodat de drie pattern-hits verder uit elkaar liggen en eerder logisch op de vloer landen in plaats van abrupt te wisselen.
- Bee pattern-hits in de 3D-preview schalen nu mee met de effectieve throw distance in plaats van een vaste grootte te houden, zodat projecties verder van de fixture ook zichtbaar groter worden zoals bij echte gobo/projecties.
- Wall wash bars volgen in 2D- en 3D-preview nu daadwerkelijk hun world-yaw rotatie in plaats van een vaste anchor-oriëntatie, en de fixturebody gebruikt nu een realistischer lengte van ongeveer 90 cm met 24 verdeelde LED-punten over de bar.
- Wall wash bars ondersteunen in de beta-map nu ook een aparte roll/mount-rotatie naast yaw, zodat je ze niet alleen in richting maar ook liggend/staand correct kunt oriënteren en die stand in zowel 2D als 3D terugziet.
- Wall wash bars verdelen hun preview-uitvoer nu ook over de echte bar-as: 2D en 3D tekenen meerdere emitterstralen vanuit de geroteerde fixture, en de LED-punten op de bar zijn helderder en duidelijker zichtbaar gemaakt.
- Wall wash bars renderen hun output nu punt-/pixelachtig in plaats van als doorlopende beam-strepen, en 2D/3D nemen nu ook de segmentkleuren per LED/zone over in zowel de fixturebody als de projectiepunten.
- Wall wash bars gebruiken nu een blijvend donkere fixturebody zodat de LED-segmenten zelf domineren; tegelijk zijn zowel fixture-LEDs als hun diffuse projectiepunten merkbaar feller gemaakt en zijn de projectiepunten zachter getuned zodat ze minder als losse LEDs lezen.
- Wall wash bars tonen nu geen losse projectiepunten meer op afstand: de preview houdt de lichtindruk voortaan lokaal rond de fixture-LEDs zelf, zodat er geen schaduw-/ghost-pixels ver weg van de bar blijven hangen.
- Bee Eye pattern-vormen zijn opnieuw afgestemd op de recentere referentie: de 5-arm dubbele spoke-star, 5-petal flower/swirl, radial dotted star, diagonale drop-cluster, triskelion en 5-petal pinwheel-flower zijn nu in zowel de SwiftUI glyphs als de Metal pattern-shader inhoudelijk aangepast.
- Bee Eye pattern-vormen kunnen in de beta-preview nu ook rechtstreeks uit de echte assetbestanden in `assets/` worden geladen; SwiftUI-, SceneKit- en Metal-preview gebruiken die voortaan als primaire bron met fallback naar de oude procedurele vormen.
- Bee Eye Auto Show schakelt nu nadrukkelijker tussen `wash`, `beam` en `fx`, en de preview gebruikt die modus ook voor bredere wash-bodies, strakkere beam-looks, grotere kaleido-spreiding en zachtere shape-transitions in 2D en 3D.

### Fixed
- De native Beta decodeert nested Dynamic Composer-primitives tolerant, zodat
  parameterobservability geen volledige backendstatus-refresh meer blokkeert.
- Loaded non-master VirtualDJ-decks verschijnen nu read-only met hun bestaande
  prewarm-/analysestatus in de Deck UI, zonder master- of show-authority.
- VirtualDJ-masterautoriteit volgt nu de directe `get_activedeck`-query en faalt gesloten wanneer dit signaal ontbreekt; loaded/prewarmdecks kunnen de actieve BeatBeam-track niet meer vervangen.
- De preview gebruikt nu de backend-transportklok als animatiebasis, zodat strobe- en dimmerweergave strakker gelijk lopen met live-output.
- Externe strobe-windows worden in de preview nu als beat-gebonden flash getoond in plaats van als vrije random flicker, en de stage-motion preview draait nu op 30 fps voor betere parity met live-output.
- Auto-show rhythm-wissels worden nu per slot beat-gebonden vastgehouden; daarnaast zijn mover-varianten van `Soft Pulse` en `Alternate Whole` rustiger gemaakt zodat dimmer-FX niet meer te snel of sub-beat stotteren.
- De backend logt nu expliciet voorgestelde versus doorgelaten slot-rhythms, zodat live-output gerichter te finetunen is.
- Rekordbox bridge start/stop gebruikt nu de bestaande passwordless sudo-regel direct, in plaats van een generieke root-shell, zodat de bridge niet meer onnodig om een wachtwoord blijft vragen.
- Bee-shapes in de Metal 3D-preview renderen nu rechtstreeks als shader-vormen in plaats van via een los texture-load pad; tegelijk verdwijnen de ronde floor/end hits zodra een Bee-pattern actief is, zodat de shape-weergave daadwerkelijk zichtbaar blijft.
- De `flower`-shape in de Metal Bee-pattern shader gebruikt nu een correct uitgesneden center-hole in plaats van een omgekeerd alpha-masker, zodat deze niet meer als vierkant vlak rendert.
- Bee pattern-shapes renderen nu tijdelijk alleen nog als vloerprojectie; lucht/eind-hit sprites zijn verwijderd uit de Metal 3D-preview en ook uit de 2D niet-top projecties, zodat de preview consistenter oogt zonder abrupte vloer/air-switches.
- Bee triplet-patterns gebruiken in de preview nu alleen cluster-rotatie en een compactere spreiding, zodat shapes niet meer individueel lijken te spinnen of onnodig ver uit elkaar staan.
- Bee triplet-patterns gedragen zich in de preview nu als een starre groep: de drie projecties verplaatsen en oriënteren samen op dezelfde groepsrotatie, zonder extra losse shape-spin per projectie.
- Bee floor-projecties in de Metal-preview gebruiken nu één centrale group-anchor met drie child-shapes eromheen, zodat de rotatie-as echt in het midden van de triplet ligt in plaats van impliciet per losse beam-hit.
- BeatBeam stopt de Rekordbox/BPM Trigger bridge nu ook expliciet tijdens app-afsluiten, zodat `rkbx_link` niet blijft hangen en de bridge-status bij de volgende start niet onterecht al op actief staat.

## [1.0.0] - 2026-06-29

### Added
- Changelog tracking gestart voor de wijzigingen richting `1.0`.

### Changed
- BeatBeam kan nu preview-cachebestanden lezen met extra `dense_samples` naast de bestaande 8-beat `segments`.
- Track-preview matching gebruikt nu waar beschikbaar half-beat waveform-samples als fijnere matchbron, met fallback naar de oude segment-samenvatting.
- Lookahead-matching voor waveform/bands vergelijkt nu ook tegen die fijnere preview-samples, zodat de geplande show minder grof op 8-beat blokken hoeft te leunen.
- Remote access toont nu ook USB/wired interface-URL's zodra macOS daar een bruikbaar IPv4-adres op heeft, en geeft die voorrang als iPad-remote doel.
- `rkbx_link` schrijft nu preview-cachebestanden met `sample_beats` en `dense_samples` op halve-beat resolutie.
- Dense preview-samples bevatten per meetpunt beat, seconden, phrase, energy, low, mid, high, activity en rise.

### Fixed
- BeatBeam leest preview-caches nu uit zowel het standaardpad als een user-fallbackpad, en kiest per track automatisch de nieuwste cache.
- De native iPad remote gebruikt nu een eigen `URLSession` met `waitsForConnectivity` en ruimere timeouts om minder snel offline te vallen bij korte netwerkhaperingen.
- `rkbx_link` wijkt automatisch uit naar een user-schrijfbaar fallback cachepad als de standaard cachemap niet beschrijfbaar is.

## [0.1] - 2026-06-12

### Added
- Eerste vastgelegde release van BeatBeam DMX (`v0.1`).
