import SwiftUI

private enum RemoteTheme {
    static let background = Color(red: 0.04, green: 0.05, blue: 0.07)
    static let panel = Color(red: 0.10, green: 0.12, blue: 0.16)
    static let border = Color.white.opacity(0.12)
    static let accent = Color(red: 0.12, green: 0.88, blue: 0.96)
    static let warning = Color.orange
    static let danger = Color.red
}

struct ContentView: View {
    @EnvironmentObject private var store: RemoteStore
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        NavigationStack {
            ZStack {
                LinearGradient(colors: [Color(red: 0.05, green: 0.07, blue: 0.11), RemoteTheme.background], startPoint: .topLeading, endPoint: .bottomTrailing)
                    .ignoresSafeArea()
                if let state = store.liveState {
                    VStack(spacing: 0) {
                        if state.overrides.blackout { BlackoutAuthorityBanner() }
                        TabView {
                            LiveControlScreen(state: state).environmentObject(store)
                                .tabItem { Label("Live", systemImage: "slider.horizontal.3") }
                            OverridesControlScreen(state: state).environmentObject(store)
                                .tabItem { Label("Overrides", systemImage: "hand.raised.fill") }
                            liveDashboard(state)
                                .tabItem { Label("Status", systemImage: "waveform.path.ecg") }
                        }
                        .tint(RemoteTheme.accent)
                    }
                } else { disconnectedDashboard }
            }
            .toolbar(.hidden, for: .navigationBar)
            .sheet(isPresented: $store.showConfiguration) { ConnectionSheet().environmentObject(store) }
            .sheet(isPresented: $store.showScanner) {
                NavigationStack {
                    QRScannerView { store.handleScannedURL($0) }
                        .ignoresSafeArea()
                        .toolbar { ToolbarItem(placement: .topBarTrailing) { Button("Sluit") { store.showScanner = false } } }
                }
            }
            .alert("BeatBeam Remote", isPresented: Binding(get: { store.transientMessage != nil }, set: { if !$0 { store.transientMessage = nil } })) {
                Button("OK", role: .cancel) { store.transientMessage = nil }
            } message: { Text(store.transientMessage ?? "") }
            .onChange(of: scenePhase) { _, phase in
                if phase != .active { store.releaseActiveMomentaries(reason: "app backgrounded") }
            }
        }
    }

    private var disconnectedDashboard: some View {
        VStack(spacing: 18) {
            Image(systemName: "dot.radiowaves.left.and.right")
                .font(.system(size: 46, weight: .medium)).foregroundStyle(RemoteTheme.accent)
            Text("BeatBeam Live")
                .font(.system(size: 30, weight: .bold)).foregroundStyle(.white)
            Text(store.connectionState.label)
                .font(.headline).foregroundStyle(.secondary)
            Text("Deze iPad ontvangt de authoritative Live Show-state en gebruikt alleen scoped Live Control-opdrachten.")
                .multilineTextAlignment(.center).foregroundStyle(.secondary).frame(maxWidth: 420)
            Button(store.connectionState == .notPaired ? "Pair iPad" : "Verbind opnieuw") {
                if store.connectionState == .notPaired { store.showConfiguration = true } else { store.reconnect() }
            }
            .buttonStyle(.borderedProminent).tint(RemoteTheme.accent).accessibilityLabel("Pair of verbind opnieuw met BeatBeam")
        }
        .padding(28)
    }

    private func liveDashboard(_ state: RemoteLiveStateV2) -> some View {
        GeometryReader { proxy in
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    header(state)
                    if !state.overrides.blackout && state.overrides.anyActive { overrideBanner(state.overrides) }
                    warningStack(state.warnings)
                    if proxy.size.width > proxy.size.height {
                        landscapeGrid(state)
                    } else {
                        portraitStack(state)
                    }
                }
                .padding(14)
                .frame(maxWidth: 1180, alignment: .topLeading)
            }
        }
    }

    private func header(_ state: RemoteLiveStateV2) -> some View {
        RemoteCard {
            HStack(alignment: .center, spacing: 14) {
                Image(systemName: "waveform").font(.system(size: 28, weight: .bold)).foregroundStyle(RemoteTheme.accent)
                VStack(alignment: .leading, spacing: 3) {
                    Text("NOW PLAYING").font(.caption.bold().monospaced()).foregroundStyle(.secondary)
                    Text(state.track.title ?? "(geen track)").font(.title2.bold()).foregroundStyle(.white).lineLimit(1)
                    Text(state.track.artist ?? "Onbekend").foregroundStyle(.secondary).lineLimit(1)
                }
                Spacer(minLength: 8)
                HStack(spacing: 8) {
                    Metric(title: "Deck", value: state.track.activeDeck.map(String.init) ?? "—")
                    Metric(title: "BPM", value: state.track.bpm.map { String(format: "%.1f", $0) } ?? "—")
                    Metric(title: "Beat", value: state.track.beat.map(String.init) ?? "—")
                    Metric(title: "Bar", value: state.track.bar.map(String.init) ?? "—")
                    Metric(title: "SA", value: state.track.readiness ?? "—", tone: readinessTone(state.track.readiness))
                }
                StatusBadge(label: store.connectionState.label, tone: store.isConnected ? .green : .orange)
            }
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel("Now playing \(state.track.title ?? "geen track"), master deck \(state.track.activeDeck.map(String.init) ?? "onbekend"), SongAnalyzer \(state.track.readiness ?? "onbekend")")
    }

    private func landscapeGrid(_ state: RemoteLiveStateV2) -> some View {
        HStack(alignment: .top, spacing: 12) {
            VStack(spacing: 12) { productionCard(state); healthCard(state); deckCard(state) }.frame(maxWidth: .infinity)
            VStack(spacing: 12) { musicalCard(state); fixturesCard(state) }.frame(maxWidth: .infinity)
        }
    }

    private func portraitStack(_ state: RemoteLiveStateV2) -> some View {
        VStack(spacing: 12) { productionCard(state); healthCard(state); musicalCard(state); deckCard(state); fixturesCard(state) }
    }

    private func productionCard(_ state: RemoteLiveStateV2) -> some View {
        RemoteCard(title: "PRODUCTION") {
            VStack(spacing: 10) {
                ProductionLine(label: "MODE", value: productionLabel(state.show.configuredProductionMode), tone: .cyan)
                ProductionLine(label: "FRAME", value: frameLabel(state.show.physicalFrameSource), tone: state.show.dynamicComposerActive ? .green : .orange)
                ProductionLine(label: "FALLBACK", value: state.show.fallbackActive ? (state.show.fallbackReason ?? "active") : "Niet actief", tone: state.show.fallbackActive ? .orange : .green)
                if let preview = state.show.previewSource { ProductionLine(label: "PREVIEW", value: preview.replacingOccurrences(of: "_", with: " "), tone: .secondary) }
            }
        }
        .accessibilityLabel("Production: mode \(state.show.configuredProductionMode), physical frame \(state.show.physicalFrameSource), fallback \(state.show.fallbackReason ?? "niet actief")")
    }

    private func healthCard(_ state: RemoteLiveStateV2) -> some View {
        RemoteCard(title: "SYSTEM HEALTH") {
            LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 8) {
                HealthTile(title: "DMX", value: state.dmx.connected ? "CONNECTED" : "DISCONNECTED", healthy: state.dmx.connected)
                HealthTile(title: "RENDERER", value: state.dmx.rendererHealthy ? "HEALTHY" : "UNHEALTHY", healthy: state.dmx.rendererHealthy)
                HealthTile(title: "SONGANALYZER", value: state.track.readiness ?? "UNAVAILABLE", healthy: state.track.readiness?.uppercased() == "READY")
                HealthTile(title: "TRANSPORT", value: state.track.transportFresh ? "FRESH" : "STALE", healthy: state.track.transportFresh)
            }
            if let error = state.dmx.lastError, !error.isEmpty { Text(error).font(.caption).foregroundStyle(.orange).lineLimit(2) }
        }
    }

    private func musicalCard(_ state: RemoteLiveStateV2) -> some View {
        RemoteCard(title: "MUSICAL CONTEXT") {
            VStack(spacing: 9) {
                ProductionLine(label: "SECTION", value: state.musicalState.section ?? "—", tone: .primary)
                ProductionLine(label: "ENERGY", value: percent(state.musicalState.effectiveIntensity), tone: RemoteTheme.accent)
                ProductionLine(label: "TRAJECTORY", value: state.musicalState.energyTrajectory ?? "—", tone: .secondary)
                ProductionLine(label: "RME", value: state.musicalState.currentRme?.type ?? "Geen actief event", tone: .secondary)
                ProductionLine(label: "ENVELOPE", value: state.musicalState.eventEnvelope.active ? (state.musicalState.eventEnvelope.phase ?? "active") : "Niet actief", tone: state.musicalState.eventEnvelope.active ? .cyan : .secondary)
            }
        }
    }

    private func deckCard(_ state: RemoteLiveStateV2) -> some View {
        RemoteCard(title: "DECKS") {
            ForEach(state.decks) { deck in
                HStack(spacing: 8) {
                    Text("D\(deck.number.map(String.init) ?? "?")").font(.headline.monospaced()).foregroundStyle(deck.master ? RemoteTheme.accent : .white)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(deck.loaded ? (deck.title ?? "Loaded track") : "(geen track)").foregroundStyle(.white).lineLimit(1)
                        Text(deck.analysisReadiness ?? "UNAVAILABLE").font(.caption.monospaced()).foregroundStyle(readinessTone(deck.analysisReadiness))
                    }
                    Spacer()
                    if deck.master { StatusBadge(label: "MASTER", tone: .cyan) }
                    if deck.prewarmReadiness?.uppercased() == "READY" { StatusBadge(label: "PREWARM", tone: .green) }
                }
                .padding(.vertical, 3)
            }
        }
    }

    private func fixturesCard(_ state: RemoteLiveStateV2) -> some View {
        RemoteCard(title: "FIXTURE GROUPS") {
            if state.fixtures.isEmpty { Text("Geen runtime fixturegroups beschikbaar.").foregroundStyle(.secondary) }
            else {
                ForEach(state.fixtures) { group in
                    HStack(spacing: 8) {
                        Circle().fill(group.active ? RemoteTheme.accent : Color.secondary).frame(width: 10, height: 10)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(group.label).foregroundStyle(.white)
                            Text("\(group.enabledSlots) slot(s) · \(group.role)\(group.movementActive ? " · moving" : "")")
                                .font(.caption).foregroundStyle(.secondary)
                        }
                        Spacer()
                        Text(percent(group.intensity)).font(.caption.monospaced()).foregroundStyle(.secondary)
                        if let color = group.colorPreset { Text(color.replacingOccurrences(of: "_", with: " ")).font(.caption.monospaced()).foregroundStyle(RemoteTheme.accent) }
                        if group.overrideActive { StatusBadge(label: "OVERRIDE", tone: .orange) }
                    }
                    .accessibilityLabel("\(group.label), \(group.enabledSlots) fixtures, intensity \(percent(group.intensity))")
                }
            }
        }
    }

    private func warningStack(_ warnings: [RemoteWarning]) -> some View {
        VStack(spacing: 7) {
            ForEach(warnings.filter { $0.code != "BLACKOUT_ACTIVE" && $0.code != "MANUAL_OVERRIDE_ACTIVE" }) { warning in
                HStack { Image(systemName: warning.severity == "critical" ? "exclamationmark.octagon.fill" : "exclamationmark.triangle.fill"); Text(warning.message).font(.subheadline.bold()); Spacer() }
                    .foregroundStyle(warning.severity == "critical" ? .white : .black)
                    .padding(11).background(warning.severity == "critical" ? RemoteTheme.danger : RemoteTheme.warning)
                    .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                    .accessibilityLabel("Waarschuwing: \(warning.message)")
            }
        }
    }

    private func overrideBanner(_ overrides: RemoteOverrideState) -> some View {
        let details = [overrides.phrase, overrides.energy, overrides.color, overrides.momentaryEffects.isEmpty ? nil : overrides.momentaryEffects.joined(separator: ", ")].compactMap { $0 }.joined(separator: " · ")
        return HStack { Image(systemName: "hand.raised.fill"); VStack(alignment: .leading) { Text("MANUAL OVERRIDE ACTIVE").font(.headline.bold()); Text(details.isEmpty ? "Automatic frame temporarily overridden" : details).font(.caption) }; Spacer(); Text("LIVE CONTROL").font(.caption.bold().monospaced()) }
            .foregroundStyle(.black).padding(12).background(RemoteTheme.warning).clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
            .accessibilityLabel("Handmatige override actief. \(details)")
    }

    private func readinessTone(_ readiness: String?) -> Color { readiness?.uppercased() == "READY" ? .green : (readiness?.uppercased() == "ANALYZING" || readiness?.uppercased() == "QUEUED" ? .orange : .red) }
    private func productionLabel(_ value: String) -> String { value == "DYNAMIC_COMPOSER_ENABLED" ? "DYNAMIC COMPOSER" : "BASELINE" }
    private func frameLabel(_ value: String) -> String { value == "dynamic_composer" ? "DYNAMIC COMPOSER" : "BASELINE" }
    private func percent(_ value: Double?) -> String { value.map { "\(Int(($0 * 100).rounded()))%" } ?? "—" }
}

private struct LiveControlScreen: View {
    @EnvironmentObject private var store: RemoteStore
    let state: RemoteLiveStateV2
    @State private var confirmBaseline = false
    @State private var confirmDynamic = false

    var body: some View {
        GeometryReader { proxy in
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    liveHeader
                    if !state.dmx.connected { offlineDispatchNotice }
                    if let output = state.output { OutputPreviewCard(output: output) }
                    HStack(spacing: 12) {
                        blackoutControl
                        Button("RELEASE ALL") { store.perform("release_all") }
                            .buttonStyle(LiveActionStyle(tint: .orange))
                            .accessibilityLabel("Release all manual overrides")
                        productionControls
                    }
                    if proxy.size.width > proxy.size.height {
                        HStack(alignment: .top, spacing: 14) {
                            VStack(spacing: 14) { quickColors; phraseEnergy }.frame(maxWidth: .infinity)
                            VStack(spacing: 14) { momentaryPads; cueShots }.frame(maxWidth: .infinity)
                        }
                    } else {
                        quickColors; phraseEnergy; momentaryPads; cueShots
                    }
                }
                .padding(16).frame(maxWidth: 1180, alignment: .leading)
            }
        }
        .alert("Revert to Baseline?", isPresented: $confirmBaseline) {
            Button("Revert", role: .destructive) { store.perform("revert_baseline") }; Button("Cancel", role: .cancel) {}
        } message: { Text("The physical frame will return to the existing baseline show. Transport is unchanged.") }
        .alert("Enable Dynamic Composer?", isPresented: $confirmDynamic) {
            Button("Enable Dynamic") { store.perform("enable_dynamic_composer") }; Button("Cancel", role: .cancel) {}
        } message: { Text("Enable the production Dynamic Composer only after this deliberate confirmation.") }
    }

    private var liveHeader: some View {
        RemoteCard {
            HStack { VStack(alignment: .leading) {
                Text("LIVE CONTROL").font(.caption.bold().monospaced()).foregroundStyle(RemoteTheme.accent)
                Text(state.track.title ?? "(geen track)").font(.title2.bold()).foregroundStyle(.white)
                Text(state.track.artist ?? "Onbekend").foregroundStyle(.secondary)
            }; Spacer(); VStack(alignment: .trailing) {
                Text(state.show.configuredProductionMode == "DYNAMIC_COMPOSER_ENABLED" ? "DYNAMIC" : "BASELINE").font(.headline.monospaced()).foregroundStyle(RemoteTheme.accent)
                Text("FRAME: \(state.show.physicalFrameSource.replacingOccurrences(of: "_", with: " "))").font(.caption.monospaced()).foregroundStyle(state.show.fallbackActive ? .orange : .secondary)
                if state.show.fallbackActive { Text("FALLBACK: \(state.show.fallbackReason ?? "active")").font(.caption.bold()).foregroundStyle(.orange) }
                Button("PAIR / UPGRADE") { store.forgetConnection() }.font(.caption.bold()).buttonStyle(.bordered)
            }}
        }
    }

    private var offlineDispatchNotice: some View {
        HStack(spacing: 8) {
            Image(systemName: "cable.connector.slash")
            Text("DMX DISCONNECTED — Physical output is unavailable. Controls remain enabled for rendered preview and test.")
        }
        .font(.caption.bold()).foregroundStyle(.orange).padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.orange.opacity(0.12)).clipShape(RoundedRectangle(cornerRadius: 10))
        .accessibilityLabel("DMX disconnected. Physical output unavailable. Controls remain enabled for preview and test.")
    }

    private var blackoutControl: some View {
        Group {
            if state.overrides.blackout {
                Text("HOLD TO RELEASE")
                    .frame(maxWidth: .infinity, minHeight: 58).background(RemoteTheme.danger)
                    .clipShape(RoundedRectangle(cornerRadius: 14))
                    .onLongPressGesture(minimumDuration: 1.2) { store.perform("blackout_off") }
            } else {
                Button("BLACKOUT") { store.perform("blackout_on") }.buttonStyle(LiveActionStyle(tint: RemoteTheme.danger))
            }
        }.foregroundStyle(.white).font(.headline.bold()).accessibilityLabel(state.overrides.blackout ? "Hold to release blackout" : "Activate blackout")
    }

    private var productionControls: some View {
        Group {
            if state.show.configuredProductionMode == "DYNAMIC_COMPOSER_ENABLED" {
                Button("REVERT BASELINE") { confirmBaseline = true }.buttonStyle(LiveActionStyle(tint: .purple))
            } else {
                Button("ENABLE DYNAMIC") { confirmDynamic = true }.buttonStyle(LiveActionStyle(tint: .cyan))
            }
        }
    }

    private var quickColors: some View {
        RemoteCard(title: "COLORS") { ColorGrid(state: state).environmentObject(store) }
    }
    private var phraseEnergy: some View {
        RemoteCard(title: "PHRASE / ENERGY") { OverrideChips(state: state).environmentObject(store) }
    }
    private var momentaryPads: some View {
        RemoteCard(title: "HOLD EFFECT PADS") {
            let enabled = state.control.momentaryEffects.filter(\.isAvailable)
            let temporary = state.control.momentaryEffects.filter { !$0.isAvailable && $0.isTemporarilyUnavailable }
            if enabled.isEmpty && temporary.isEmpty { Text("Geen hold-effecten voor deze fixtureopstelling.").foregroundStyle(.secondary) }
            else {
                LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 10) {
                    ForEach(enabled) { effect in MomentaryEffectPad(effect: effect, active: state.overrides.momentaryEffects.contains(effect.id)).environmentObject(store) }
                    ForEach(temporary) { effect in UnavailableEffectPad(effect: effect) }
                }
            }
        }
    }
    private var cueShots: some View {
        RemoteCard(title: "CUE SHOTS") {
            let enabled = state.control.cueShots.filter(\.isAvailable)
            let temporary = state.control.cueShots.filter { !$0.isAvailable && $0.isTemporarilyUnavailable }
            if enabled.isEmpty && temporary.isEmpty { Text("Geen cue-shots voor deze fixtureopstelling.").foregroundStyle(.secondary) }
            else {
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 128))], spacing: 9) {
                    ForEach(enabled) { cue in Button(cue.label) { store.perform("trigger_cue", value: cue.id) }.buttonStyle(LiveActionStyle(tint: .indigo)) }
                    ForEach(temporary) { cue in UnavailableEffectPad(effect: cue) }
                }
            }
        }
    }
}

private struct OverridesControlScreen: View {
    @EnvironmentObject private var store: RemoteStore
    let state: RemoteLiveStateV2
    var body: some View {
        ScrollView { VStack(alignment: .leading, spacing: 14) {
            Text("OVERRIDES").font(.largeTitle.bold()).foregroundStyle(.white)
            if state.overrides.anyActive { Text("ACTIVE: \([state.overrides.color, state.overrides.phrase, state.overrides.energy].compactMap { $0 }.joined(separator: " · "))").foregroundStyle(.orange) }
            Button("RELEASE ALL") { store.perform("release_all") }.buttonStyle(LiveActionStyle(tint: .orange))
            RemoteCard(title: "COLORS") { ColorGrid(state: state).environmentObject(store) }
            RemoteCard(title: "PHRASE / ENERGY") { OverrideChips(state: state).environmentObject(store) }
            RemoteCard(title: "MOMENTARY EFFECTS") { LazyVGrid(columns: [GridItem(.adaptive(minimum: 150))], spacing: 10) { ForEach(state.control.momentaryEffects.filter(\.isAvailable)) { MomentaryEffectPad(effect: $0, active: state.overrides.momentaryEffects.contains($0.id)).environmentObject(store) } } }
            RemoteCard(title: "CUE SHOTS") { LazyVGrid(columns: [GridItem(.adaptive(minimum: 145))], spacing: 10) { ForEach(state.control.cueShots.filter(\.isAvailable)) { cue in Button(cue.label) { store.perform("trigger_cue", value: cue.id) }.buttonStyle(LiveActionStyle(tint: .indigo)) } } }
        }.padding(16).frame(maxWidth: 1000, alignment: .leading) }
    }
}

private struct OutputPreviewCard: View {
    let output: RemoteOutputPreview

    var body: some View {
        RemoteCard(title: "OUTPUT PREVIEW") {
            VStack(alignment: .leading, spacing: 10) {
                HStack {
                    Text(output.blackout ? "BLACKOUT — OUTPUT ZERO" : "AUTHORITATIVE RENDERED OUTPUT")
                        .font(.caption.bold().monospaced())
                        .foregroundStyle(output.blackout ? RemoteTheme.danger : RemoteTheme.accent)
                    Spacer()
                    Text(output.physicalOutputAvailable ? "DMX DISPATCH AVAILABLE" : "PREVIEW / TEST ONLY")
                        .font(.caption2.bold().monospaced())
                        .foregroundStyle(output.physicalOutputAvailable ? .green : .orange)
                }
                if !output.renderedAvailable {
                    Text("Renderer unavailable — output frame cannot be projected.")
                        .font(.caption).foregroundStyle(.orange)
                } else if output.fixtures.isEmpty {
                    Text("No enabled fixtures in the current configuration.")
                        .font(.caption).foregroundStyle(.secondary)
                } else {
                    LazyVGrid(columns: [GridItem(.adaptive(minimum: 116), spacing: 9)], spacing: 9) {
                        ForEach(output.fixtures) { fixture in fixtureTile(fixture) }
                    }
                }
            }
        }
        .accessibilityLabel(output.blackout ? "Output preview: blackout, all output zero" : "Output preview: authoritative rendered fixture output")
    }

    private func fixtureTile(_ fixture: RemoteOutputFixture) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            RoundedRectangle(cornerRadius: 8)
                .fill(outputColor(fixture))
                .frame(height: 28)
                .overlay { Text(fixture.active ? "ACTIVE" : "BLACK").font(.caption2.bold().monospaced()).foregroundStyle(.white) }
            Text(fixture.label).font(.caption.bold()).foregroundStyle(.white).lineLimit(1)
            Text("RGBW \(fixture.red)/\(fixture.green)/\(fixture.blue)/\(fixture.white)")
                .font(.caption2.monospaced()).foregroundStyle(.secondary)
            Text("DIM \(fixture.dimmer)  STR \(fixture.strobe)")
                .font(.caption2.monospaced()).foregroundStyle(.secondary)
            if fixture.role == "moving" {
                Text("PAN \(fixture.pan.map(String.init) ?? "—")  TILT \(fixture.tilt.map(String.init) ?? "—")")
                    .font(.caption2.monospaced()).foregroundStyle(.secondary)
            }
        }
        .padding(9).frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.white.opacity(0.06)).clipShape(RoundedRectangle(cornerRadius: 10))
    }

    private func outputColor(_ fixture: RemoteOutputFixture) -> Color {
        let white = Double(fixture.white)
        let red = min(255, Double(fixture.red) + white) / 255
        let green = min(255, Double(fixture.green) + white) / 255
        let blue = min(255, Double(fixture.blue) + white) / 255
        return Color(red: red, green: green, blue: blue).opacity(max(0.18, Double(fixture.dimmer) / 255))
    }
}

private struct ColorGrid: View {
    @EnvironmentObject private var store: RemoteStore
    let state: RemoteLiveStateV2
    var body: some View {
        LazyVGrid(columns: [GridItem(.adaptive(minimum: 92))], spacing: 8) {
            Button("AUTO") { store.perform("set_color", value: "none") }.buttonStyle(LiveActionStyle(tint: state.overrides.color == nil ? .green : .gray))
            ForEach(state.control.colors) { color in Button(color.label.uppercased()) { store.perform("set_color", value: color.id) }.buttonStyle(LiveActionStyle(tint: colorTint(color.id, active: state.overrides.color == color.id))) }
        }
    }
    private func colorTint(_ value: String, active: Bool) -> Color { if active { return .white }; return ["red": .red, "yellow": .yellow, "green": .green, "lime": .green, "purple": .purple, "pink": .pink, "cyan": .cyan, "orange": .orange, "blue": .blue, "white": .gray][value] ?? .gray }
}

private struct OverrideChips: View {
    @EnvironmentObject private var store: RemoteStore
    let state: RemoteLiveStateV2
    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("PHRASE").font(.caption.bold().monospaced()).foregroundStyle(.secondary)
            ScrollView(.horizontal, showsIndicators: false) { HStack { Button("AUTO") { store.perform("set_phrase", value: "none") }.buttonStyle(ChipStyle(active: state.overrides.phrase == nil)); ForEach(state.control.phrases) { option in Button(option.label) { store.perform("set_phrase", value: option.id) }.buttonStyle(ChipStyle(active: state.overrides.phrase == option.id)) } } }
            Text("ENERGY").font(.caption.bold().monospaced()).foregroundStyle(.secondary)
            HStack { Button("AUTO") { store.perform("set_energy", value: "none") }.buttonStyle(ChipStyle(active: state.overrides.energy == nil)); ForEach(state.control.energies) { option in Button(option.label) { store.perform("set_energy", value: option.id) }.buttonStyle(ChipStyle(active: state.overrides.energy == option.id)) } }
        }
    }
}

private struct MomentaryEffectPad: View {
    @EnvironmentObject private var store: RemoteStore
    let effect: RemoteEffectCapability; let active: Bool
    var body: some View {
        Text(effect.label.uppercased()).font(.headline.bold()).foregroundStyle(.white).frame(maxWidth: .infinity, minHeight: 70)
            .background(active ? RemoteTheme.accent : Color.white.opacity(0.13)).clipShape(RoundedRectangle(cornerRadius: 14))
            .simultaneousGesture(DragGesture(minimumDistance: 0).onChanged { _ in store.beginMomentary(effect.id) }.onEnded { _ in store.endMomentary(effect.id) })
            .onDisappear { store.endMomentary(effect.id) }
            .accessibilityLabel("Hold \(effect.label)")
    }
}

private struct UnavailableEffectPad: View {
    let effect: RemoteEffectCapability
    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(effect.label.uppercased()).font(.caption.bold()).foregroundStyle(.secondary)
            Text(effect.reasonIfUnavailable ?? "Tijdelijk niet beschikbaar").font(.caption2).foregroundStyle(.secondary).lineLimit(2)
        }
        .frame(maxWidth: .infinity, minHeight: 58, alignment: .leading).padding(8)
        .background(Color.white.opacity(0.05)).clipShape(RoundedRectangle(cornerRadius: 12))
        .accessibilityLabel("\(effect.label) niet beschikbaar. \(effect.reasonIfUnavailable ?? "")")
    }
}

private struct BlackoutAuthorityBanner: View {
    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: "moon.fill").font(.title2)
            VStack(alignment: .leading, spacing: 2) {
                Text("BLACKOUT ACTIVE").font(.title2.bold())
                Text("Physical output is blacked out. Preview remains underlying show intent.").font(.caption.bold())
            }
            Spacer()
            Text("HOLD BLACKOUT TO RELEASE").font(.caption2.bold().monospaced())
        }
        .foregroundStyle(.white).padding(14).background(RemoteTheme.danger)
        .accessibilityLabel("Blackout actief. Fysieke output is uit. Preview blijft onderliggende showintentie.")
    }
}

private struct LiveActionStyle: ButtonStyle { let tint: Color; func makeBody(configuration: Configuration) -> some View { configuration.label.frame(maxWidth: .infinity, minHeight: 58).foregroundStyle(.white).background(tint.opacity(configuration.isPressed ? 0.6 : 0.92)).clipShape(RoundedRectangle(cornerRadius: 14)) } }
private struct ChipStyle: ButtonStyle { let active: Bool; func makeBody(configuration: Configuration) -> some View { configuration.label.font(.subheadline.bold()).padding(.horizontal, 13).padding(.vertical, 9).foregroundStyle(active ? .black : .white).background(active ? RemoteTheme.accent : Color.white.opacity(0.12)).clipShape(Capsule()) } }

private struct ConnectionSheet: View {
    @EnvironmentObject private var store: RemoteStore
    var body: some View {
        NavigationStack {
            Form {
                Section("Pair met BeatBeam") {
                    Text("Scan de pairing-QR uit BeatBeam op je Mac, of voer het adres en de zes-cijferige code in. De iPad ontvangt scoped REMOTE_READ en LIVE_CONTROL-credentials.")
                        .font(.footnote).foregroundStyle(.secondary)
                    TextField("BeatBeam-adres", text: $store.configurationURLText).textInputAutocapitalization(.never).autocorrectionDisabled()
                    TextField("Pairingcode", text: $store.pairingCodeText).keyboardType(.numberPad)
                    HStack { Button("Scan QR") { store.showScanner = true }; Spacer(); Button("Pair") { store.saveConfiguration() }.buttonStyle(.borderedProminent) }
                }
                if store.liveState != nil { Section { Button("Vergeet deze iPad-koppeling", role: .destructive) { store.forgetConnection() } } }
            }
            .navigationTitle("BeatBeam Pairing")
            .toolbar { ToolbarItem(placement: .topBarTrailing) { Button("Sluit") { store.showConfiguration = false } } }
        }
    }
}

private struct RemoteCard<Content: View>: View {
    var title: String? = nil
    @ViewBuilder let content: Content
    init(title: String? = nil, @ViewBuilder content: () -> Content) { self.title = title; self.content = content() }
    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            if let title { Text(title).font(.caption.bold().monospaced()).foregroundStyle(.secondary) }
            content
        }.padding(14).frame(maxWidth: .infinity, alignment: .leading).background(RemoteTheme.panel).clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous)).overlay(RoundedRectangle(cornerRadius: 16, style: .continuous).stroke(RemoteTheme.border))
    }
}

private struct Metric: View {
    let title: String; let value: String; var tone: Color = .white
    var body: some View { VStack(spacing: 2) { Text(title).font(.caption2.bold().monospaced()).foregroundStyle(.secondary); Text(value).font(.subheadline.bold().monospaced()).foregroundStyle(tone) }.frame(minWidth: 46) }
}
private struct StatusBadge: View {
    let label: String; let tone: Color
    var body: some View { Text(label).font(.caption2.bold().monospaced()).foregroundStyle(tone).padding(.horizontal, 7).padding(.vertical, 4).background(tone.opacity(0.15)).clipShape(Capsule()) }
}
private struct ProductionLine: View {
    let label: String; let value: String; let tone: Color
    var body: some View { HStack { Text(label).font(.caption.bold().monospaced()).foregroundStyle(.secondary).frame(width: 82, alignment: .leading); Text(value.uppercased()).font(.subheadline.bold()).foregroundStyle(tone); Spacer() } }
}
private struct HealthTile: View {
    let title: String; let value: String; let healthy: Bool
    var body: some View { VStack(alignment: .leading, spacing: 5) { Text(title).font(.caption2.bold().monospaced()).foregroundStyle(.secondary); Text(value).font(.caption.bold().monospaced()).foregroundStyle(healthy ? .green : .red) }.frame(maxWidth: .infinity, alignment: .leading).padding(9).background(Color.white.opacity(0.05)).clipShape(RoundedRectangle(cornerRadius: 9, style: .continuous)) }
}
