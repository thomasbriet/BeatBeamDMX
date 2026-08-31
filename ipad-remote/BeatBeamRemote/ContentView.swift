import SwiftUI

private enum RemoteTheme {
    static let background = Color(red: 0.025, green: 0.032, blue: 0.047)
    static let panel = Color(red: 0.075, green: 0.090, blue: 0.125)
    static let panelRaised = Color(red: 0.105, green: 0.125, blue: 0.165)
    static let border = Color.white.opacity(0.13)
    static let accent = Color(red: 0.10, green: 0.86, blue: 0.96)
    static let warning = Color(red: 1.0, green: 0.62, blue: 0.08)
    static let danger = Color(red: 0.94, green: 0.20, blue: 0.22)
    static let padOff = Color.white.opacity(0.10)
}

private enum RemoteTab: String, CaseIterable, Identifiable {
    case live = "LIVE", overrides = "OVERRIDE", status = "STATUS", settings = "SETTINGS"
    var id: String { rawValue }
    var icon: String {
        switch self {
        case .live: "dot.radiowaves.left.and.right"
        case .overrides: "hand.raised.fill"
        case .status: "waveform.path.ecg"
        case .settings: "gearshape.fill"
        }
    }
}

struct ContentView: View {
    @EnvironmentObject private var store: RemoteStore
    @Environment(\.scenePhase) private var scenePhase
    @State private var selectedTab: RemoteTab = .overrides

    var body: some View {
        ZStack {
            LinearGradient(colors: [Color(red: 0.045, green: 0.060, blue: 0.090), RemoteTheme.background], startPoint: .topLeading, endPoint: .bottomTrailing).ignoresSafeArea()
            if let state = store.liveState {
                switch BBRemotePresentationMode.current {
                case .legacySwiftUI:
                    ConsoleSurface(state: state, selectedTab: $selectedTab).environmentObject(store)
                case .uiKitV1:
                    UIKitControlSurfaceHost(store: store, state: state)
                        .ignoresSafeArea(.keyboard)
                }
            } else {
                UnpairedSurface().environmentObject(store)
            }
        }
        .sheet(isPresented: $store.showConfiguration) { ConnectionSheet().environmentObject(store) }
        .sheet(isPresented: $store.showScanner) {
            NavigationStack {
                QRScannerView { store.handleScannedURL($0) }.ignoresSafeArea()
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

private struct ConsoleSurface: View {
    @EnvironmentObject private var store: RemoteStore
    let state: RemoteLiveStateV2
    @Binding var selectedTab: RemoteTab

    var body: some View {
        GeometryReader { proxy in
            VStack(spacing: 8) {
                if state.overrides.blackout { BlackoutAuthorityBanner() }
                ConsoleHeader(state: state, selectedTab: $selectedTab)
                if selectedTab != .overrides { LiveStatusStrip(state: state) }
                Group {
                    switch selectedTab {
                    case .live: LiveConsole(state: state)
                    case .overrides: OverrideConsole(state: state)
                    case .status: StatusConsole(state: state)
                    case .settings: SettingsConsole(state: state)
                    }
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
            .padding(8).frame(width: proxy.size.width, height: proxy.size.height, alignment: .top)
        }
    }
}

private struct ConsoleHeader: View {
    @EnvironmentObject private var store: RemoteStore
    let state: RemoteLiveStateV2
    @Binding var selectedTab: RemoteTab
    var body: some View {
        HStack(spacing: 14) {
            HStack(spacing: 8) {
                Image(systemName: "sparkles.tv.fill").foregroundStyle(RemoteTheme.accent)
                Text("BEATBEAM REMOTE").font(.headline.bold().monospaced()).foregroundStyle(.white)
            }
            .frame(minWidth: 245, alignment: .leading)
            ConsoleTabBar(selectedTab: $selectedTab)
            Spacer(minLength: 0)
            VStack(alignment: .leading, spacing: 1) {
                StatusBadge(label: store.connectionState.label.uppercased(), tone: store.isConnected ? .green : RemoteTheme.warning)
                Text(state.dmx.connected ? "BEATBEAM BETA · DMX LIVE" : "BEATBEAM BETA · PREVIEW").font(.caption2.bold().monospaced()).foregroundStyle(.secondary)
            }
            Button { store.showScanner = true } label: {
                Image(systemName: "qrcode.viewfinder").font(.title3.weight(.medium)).frame(width: 44, height: 44)
            }
            .buttonStyle(HardwareButtonStyle(tint: RemoteTheme.panelRaised))
            .accessibilityLabel("Open pairing QR scanner")
        }
        .padding(.horizontal, 14).frame(height: 62).background(RemoteTheme.panelRaised)
        .clipShape(RoundedRectangle(cornerRadius: 9, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 9, style: .continuous).stroke(RemoteTheme.border))
    }
}

private struct ConsoleTabBar: View {
    @Binding var selectedTab: RemoteTab
    var body: some View {
        HStack(spacing: 8) {
            ForEach(RemoteTab.allCases) { tab in
                Button { selectedTab = tab } label: {
                    Text(tab.rawValue).font(.subheadline.bold().monospaced()).frame(width: 126, height: 44)
                }
                .buttonStyle(ConsoleTabStyle(active: selectedTab == tab)).accessibilityLabel("Open \(tab.rawValue)")
            }
        }
    }
}

private struct LiveStatusStrip: View {
    let state: RemoteLiveStateV2
    var body: some View {
        HStack(spacing: 22) {
            HStack(spacing: 11) {
                Image(systemName: "music.note").font(.title3).foregroundStyle(RemoteTheme.accent)
                VStack(alignment: .leading, spacing: 2) {
                    Text(state.track.title ?? "(geen track)").font(.headline.bold()).foregroundStyle(.white).lineLimit(1)
                    Text(state.track.artist ?? "Onbekend").font(.caption).foregroundStyle(.secondary).lineLimit(1)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            Divider().overlay(RemoteTheme.border)
            StripMetric(icon: "metronome", label: "BPM", value: state.track.bpm.map { String(format: "%.1f", $0) } ?? "—")
            Divider().overlay(RemoteTheme.border)
            StripMetric(icon: "chart.bar.fill", label: "PHRASE", value: state.track.bar.map { "\($0) BARS" } ?? "—")
            Divider().overlay(RemoteTheme.border)
            StripMetric(icon: "cube", label: "PRODUCTION MODE", value: productionLabel(state.show.configuredProductionMode), tone: state.show.dynamicComposerEligible ? .purple : RemoteTheme.warning)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
        .padding(.horizontal, 17).frame(height: 86).background(RemoteTheme.panel)
        .clipShape(RoundedRectangle(cornerRadius: 9, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 9, style: .continuous).stroke(RemoteTheme.border))
    }
}

private struct StripMetric: View {
    let icon: String; let label: String; let value: String; var tone: Color = .white
    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: icon).font(.title3).foregroundStyle(tone)
            VStack(alignment: .leading, spacing: 2) {
                Text(label).font(.caption.bold().monospaced()).foregroundStyle(.secondary)
                Text(value).font(.title3.bold()).foregroundStyle(tone).lineLimit(1)
            }
        }
    }
}

private struct LiveConsole: View {
    let state: RemoteLiveStateV2
    var body: some View {
        VStack(spacing: 10) {
            RemoteCard(title: "NOW PLAYING") {
                HStack(spacing: 16) {
                    VStack(alignment: .leading, spacing: 3) {
                        Text(state.track.title ?? "(geen track)").font(.title2.bold()).foregroundStyle(.white).lineLimit(1)
                        Text(state.track.artist ?? "Onbekend").font(.subheadline).foregroundStyle(.secondary).lineLimit(1)
                    }
                    Spacer(minLength: 8)
                    LiveMetric(label: "DECK", value: state.track.activeDeck.map(String.init) ?? "—")
                    LiveMetric(label: "BPM", value: state.track.bpm.map { String(format: "%.1f", $0) } ?? "—")
                    LiveMetric(label: "BEAT", value: state.track.beat.map(String.init) ?? "—")
                    LiveMetric(label: "BAR", value: state.track.bar.map(String.init) ?? "—")
                    LiveMetric(label: "TIME", value: timestamp(state.track.positionMilliseconds))
                }
            }
            HStack(spacing: 10) {
                RemoteCard(title: "SHOW NOW") {
                    VStack(spacing: 13) {
                        ConsoleLine(label: "MODE", value: productionLabel(state.show.configuredProductionMode), tone: .cyan)
                        ConsoleLine(label: "FRAME", value: frameLabel(state.show.physicalFrameSource), tone: state.show.dynamicComposerActive ? .green : RemoteTheme.warning)
                        ConsoleLine(label: "MUSIC", value: musicalMoment, tone: state.musicalState.eventEnvelope.active ? .cyan : .white)
                        ConsoleLine(label: "OVERRIDE", value: activeOverride, tone: state.overrides.anyActive ? RemoteTheme.warning : .secondary)
                    }
                }
                RemoteCard(title: "RENDERED OUTPUT") {
                    VStack(spacing: 12) {
                        HStack {
                            Text(state.output?.blackout == true ? "BLACK / ZERO" : "OUTPUT ACTIVE").font(.title3.bold().monospaced()).foregroundStyle(state.output?.blackout == true ? RemoteTheme.danger : RemoteTheme.accent)
                            Spacer()
                            Text("\(state.output?.fixtures.filter(\.active).count ?? 0) FIXTURES").font(.caption.bold().monospaced()).foregroundStyle(.secondary)
                        }
                        if let output = state.output {
                            HStack(spacing: 7) { ForEach(output.fixtures.prefix(10)) { fixture in RoundedRectangle(cornerRadius: 4).fill(outputColor(fixture)).frame(maxWidth: .infinity, minHeight: 28) } }
                        }
                        Text(state.dmx.connected ? "PHYSICAL DISPATCH AVAILABLE" : "PREVIEW / TEST — NO PHYSICAL DMX").font(.caption.bold().monospaced()).foregroundStyle(state.dmx.connected ? .green : RemoteTheme.warning)
                    }
                }
            }
            .frame(maxHeight: .infinity)
        }
    }
    private var musicalMoment: String {
        if state.musicalState.eventEnvelope.active { return state.musicalState.eventEnvelope.eventType ?? state.musicalState.eventEnvelope.phase ?? "EVENT" }
        return state.musicalState.section ?? state.musicalState.currentRme?.type ?? "STEADY"
    }
    private var activeOverride: String {
        let values = [state.overrides.color, state.overrides.phrase, state.overrides.energy].compactMap { $0 }
        return values.isEmpty && state.overrides.momentaryEffects.isEmpty ? "AUTOMATIC" : (values + state.overrides.momentaryEffects).joined(separator: " · ")
    }
}

private enum OverrideLayout {
    static let panelGap: CGFloat = 7
    static let gridGap: CGFloat = 7
    static let cardInset: CGFloat = 9
    static let smokeWidth: CGFloat = 126
}

private struct OverrideConsole: View {
    @EnvironmentObject private var store: RemoteStore
    let state: RemoteLiveStateV2
    var body: some View {
        GeometryReader { proxy in
            let colorBankHeight = min(244, max(204, proxy.size.height * 0.27))
            let comboBankHeight = min(190, max(150, proxy.size.height * 0.20))
            VStack(spacing: OverrideLayout.panelGap) {
                RemoteCard(title: "SINGLE COLORS") {
                    ColorPadMatrix(state: state).environmentObject(store)
                }
                .frame(height: colorBankHeight)
                RemoteCard(title: "COLOR COMBINATIONS") {
                    ColorComboMatrix(state: state).environmentObject(store)
                }
                .frame(height: comboBankHeight)
                HStack(spacing: OverrideLayout.panelGap) {
                    EnergyOverridePanel(state: state)
                        .environmentObject(store)
                        .frame(width: min(318, max(254, proxy.size.width * 0.22)))
                    VStack(spacing: OverrideLayout.panelGap) {
                        EffectDeck(state: state).environmentObject(store)
                        CompactMasterActions(state: state)
                            .environmentObject(store)
                            .frame(height: 62)
                    }
                }
                .frame(maxHeight: .infinity)
            }
        }
    }
}

private struct ColorPadMatrix: View {
    @EnvironmentObject private var store: RemoteStore
    let state: RemoteLiveStateV2
    private var colors: [RemoteControlOption] { state.control.colors.contains(where: { $0.id == "rainbow" }) ? state.control.colors : state.control.colors + [RemoteControlOption(id: "rainbow", label: "Rainbow")] }
    var body: some View {
        GeometryReader { proxy in
            let colorCount = colors.count + 1
            let columns = 6
            let rowCount = max(1, Int(ceil(Double(colorCount) / Double(columns))))
            let gridWidth = max(0, proxy.size.width - OverrideLayout.smokeWidth - OverrideLayout.gridGap)
            let padHeight = min(
                (gridWidth - CGFloat(columns - 1) * OverrideLayout.gridGap) / CGFloat(columns),
                (proxy.size.height - CGFloat(rowCount - 1) * OverrideLayout.gridGap) / CGFloat(rowCount)
            )
            HStack(spacing: OverrideLayout.gridGap) {
                LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: OverrideLayout.gridGap), count: columns), spacing: OverrideLayout.gridGap) {
                    ConsoleColorPad(label: "AUTO", tint: .gray, active: state.overrides.color == nil && state.overrides.colorCombo == nil, height: padHeight) { store.perform("set_color", value: "none") }
                    ForEach(colors) { color in
                        ConsoleColorPad(label: color.label.uppercased(), tint: colorTint(color.id), active: state.overrides.color == color.id, height: padHeight) {
                            store.perform("set_color", value: color.id)
                        }
                    }
                }
                .frame(width: gridWidth)
                SmokeSetupPad().frame(width: OverrideLayout.smokeWidth).frame(maxHeight: .infinity)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
    }
}

private struct ColorComboMatrix: View {
    @EnvironmentObject private var store: RemoteStore
    let state: RemoteLiveStateV2
    var body: some View {
        GeometryReader { proxy in
            let combos = state.control.colorCombinations ?? []
            let columns = 8
            let rowCount = max(1, Int(ceil(Double(combos.count) / Double(columns))))
            let gridWidth = proxy.size.width
            let padHeight = min(
                (gridWidth - CGFloat(columns - 1) * OverrideLayout.gridGap) / CGFloat(columns),
                (proxy.size.height - CGFloat(rowCount - 1) * OverrideLayout.gridGap) / CGFloat(rowCount)
            )
            VStack {
                Spacer(minLength: 0)
                LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: OverrideLayout.gridGap), count: columns), spacing: OverrideLayout.gridGap) {
                    ForEach(combos) { combo in
                        ColorComboPad(combo: combo, active: state.overrides.colorCombo == combo.id, height: padHeight) {
                            store.perform("set_color_combo", value: combo.id)
                        }
                        .disabled(!combo.available)
                    }
                }
                .frame(width: gridWidth)
                Spacer(minLength: 0)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
    }
}

private struct ColorComboPad: View {
    let combo: RemoteColorComboCapability; let active: Bool; let height: CGFloat; let action: () -> Void
    var body: some View {
        Button(action: action) {
            ZStack {
                GeometryReader { proxy in
                    HStack(spacing: 0) {
                        colorTint(combo.colors.first ?? "").frame(width: proxy.size.width / 2)
                        colorTint(combo.colors.dropFirst().first ?? "").frame(width: proxy.size.width / 2)
                    }
                }
                Color.black.opacity(0.17)
                Text(combo.label.uppercased()).font(.caption2.bold().monospaced()).minimumScaleFactor(0.7).lineLimit(1).foregroundStyle(.white).shadow(color: .black, radius: 2)
            }
            .frame(maxWidth: .infinity, minHeight: height, maxHeight: height)
            .clipShape(RoundedRectangle(cornerRadius: 7))
            .overlay(RoundedRectangle(cornerRadius: 7).stroke(active ? .white : RemoteTheme.border, lineWidth: active ? 3 : 1))
            .shadow(color: active ? .white.opacity(0.38) : .black.opacity(0.25), radius: active ? 7 : 2, y: 2)
        }
        .opacity(combo.available ? 1 : 0.36)
        .accessibilityLabel(combo.available ? combo.label : "\(combo.label), \(combo.reasonIfUnavailable ?? "unavailable")")
    }
}

private struct PhrasePadMatrix: View {
    @EnvironmentObject private var store: RemoteStore
    let state: RemoteLiveStateV2
    var body: some View {
        LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 8), count: 2), spacing: 8) {
            ConsoleMiniPad(label: "AUTO", active: state.overrides.phrase == nil) { store.perform("set_phrase", value: "none") }
            ForEach(state.control.phrases) { phrase in ConsoleMiniPad(label: phrase.label.uppercased(), active: state.overrides.phrase == phrase.id) { store.perform("set_phrase", value: phrase.id) } }
        }
    }
}

private struct EnergyFader: View {
    @EnvironmentObject private var store: RemoteStore
    let state: RemoteLiveStateV2
    @State private var displayedLevel: Double?
    @State private var isTracking = false
    private var authoritativeLevel: Double { ["low": 1.0, "mid": 2.0, "high": 3.0][state.overrides.energy ?? ""] ?? 0 }
    private var level: Double { displayedLevel ?? authoritativeLevel }
    var body: some View {
        GeometryReader { proxy in
            let railHeight = max(168, proxy.size.height - 60)
            let capSize: CGFloat = 36
            let capPosition = capSize / 2 + (1 - level / 3) * (railHeight - capSize)
            VStack(spacing: 5) {
                HStack(spacing: 5) {
                    Text("ENERGY").font(.caption.bold().monospaced()).foregroundStyle(.secondary)
                    Spacer(minLength: 0)
                    Text(state.overrides.energy?.uppercased() ?? "AUTO").font(.caption.bold().monospaced()).foregroundStyle(RemoteTheme.warning)
                }
                ZStack(alignment: .top) {
                    RoundedRectangle(cornerRadius: 12).fill(RemoteTheme.background).overlay(RoundedRectangle(cornerRadius: 12).stroke(RemoteTheme.border))
                    VStack(spacing: 0) {
                        Text("HIGH").font(.caption2.bold().monospaced()).foregroundStyle(.secondary)
                        Spacer()
                        Text("MID").font(.caption2.bold().monospaced()).foregroundStyle(.secondary)
                        Spacer()
                        Text("LOW").font(.caption2.bold().monospaced()).foregroundStyle(.secondary)
                        Spacer()
                        Text("AUTO").font(.caption2.bold().monospaced()).foregroundStyle(.secondary)
                    }
                    .padding(.vertical, 8)
                    .padding(.leading, 10)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    Capsule().fill(RemoteTheme.warning.opacity(0.28)).frame(width: 8, height: railHeight - 28).padding(.top, 14)
                    Circle().fill(LinearGradient(colors: [.white, RemoteTheme.warning], startPoint: .top, endPoint: .bottom))
                        .overlay(Circle().stroke(.black.opacity(0.55), lineWidth: 2))
                        .shadow(color: .black.opacity(0.55), radius: 3, y: 2)
                        .frame(width: capSize, height: capSize).position(x: proxy.size.width / 2, y: capPosition)
                }
                .frame(height: railHeight)
                .contentShape(Rectangle())
                .gesture(DragGesture(minimumDistance: 0).onChanged { value in
                    isTracking = true
                    setLevel(for: value.location.y, railHeight: railHeight)
                }.onEnded { value in
                    setLevel(for: value.location.y, railHeight: railHeight)
                    isTracking = false
                    displayedLevel = nil
                })
                .accessibilityLabel("Energy override custom vertical fader")
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
    }
    private func setLevel(for y: CGFloat, railHeight: CGFloat) {
        let clamped = min(max(y, 0), railHeight)
        let next = Double(Int(((1 - clamped / railHeight) * 3).rounded()))
        guard displayedLevel != next else { return }
        displayedLevel = next
        let id = ["none", "low", "mid", "high"][Int(next)]
        if (state.overrides.energy ?? "none") != id { store.perform("set_energy", value: id) }
    }
}

private struct EnergyOverridePanel: View {
    @EnvironmentObject private var store: RemoteStore
    let state: RemoteLiveStateV2
    var body: some View {
        RemoteCard(title: "ENERGY / PHRASE") {
            HStack(spacing: OverrideLayout.gridGap) {
                PhrasePadMatrix(state: state).environmentObject(store).frame(maxWidth: .infinity, maxHeight: .infinity)
                EnergyFader(state: state).environmentObject(store).frame(width: 142)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

private struct CompactMasterActions: View {
    @EnvironmentObject private var store: RemoteStore
    let state: RemoteLiveStateV2
    var body: some View {
        RemoteCard(title: "CONTROL") {
            HStack(spacing: OverrideLayout.gridGap) {
                Button("RELEASE ALL") { store.perform("release_all") }.buttonStyle(ConsoleActionStyle(tint: .gray))
                if state.overrides.blackout { Button("RELEASE BLACKOUT") { store.perform("blackout_off") }.buttonStyle(ConsoleActionStyle(tint: RemoteTheme.danger)) }
                else { Button("BLACKOUT (HOLD)") { store.perform("blackout_on") }.buttonStyle(ConsoleActionStyle(tint: RemoteTheme.danger)) }
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

private struct EffectDeck: View {
    @EnvironmentObject private var store: RemoteStore
    let state: RemoteLiveStateV2
    var body: some View {
        RemoteCard(title: "EFFECTS") {
            VStack(spacing: 6) {
                EffectRow(title: "HOLD EFFECTS", effects: state.control.momentaryEffects, activeIDs: state.overrides.momentaryEffects, hold: true, compact: true)
                    .environmentObject(store)
                    .frame(maxHeight: .infinity)
                HStack(spacing: OverrideLayout.gridGap) {
                    Rectangle().fill(RemoteTheme.border).frame(height: 1)
                    Text("ONE-SHOT EFFECTS").font(.caption.bold().monospaced()).foregroundStyle(.secondary).fixedSize()
                    Rectangle().fill(RemoteTheme.border).frame(height: 1)
                }
                EffectRow(title: nil, effects: state.control.cueShots, activeIDs: [], hold: false, compact: true)
                    .environmentObject(store)
                    .frame(maxHeight: .infinity)
            }
        }
    }
}

private struct SmokeSetupPad: View {
    var body: some View {
        Button(action: {}) {
            VStack(spacing: 7) {
                Image(systemName: "cloud.fill").font(.title2)
                Text("SMOKE").font(.headline.bold().monospaced())
                Text("SETUP\nPENDING").font(.caption2.bold().monospaced()).multilineTextAlignment(.center).foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
        .buttonStyle(HardwarePerformancePadStyle(active: false))
        .disabled(true)
        .opacity(0.68)
        .accessibilityLabel("Smoke unavailable until DMX channels are configured")
    }
}

private struct EffectRow: View {
    @EnvironmentObject private var store: RemoteStore
    let title: String?; let effects: [RemoteEffectCapability]; let activeIDs: [String]; let hold: Bool; let compact: Bool
    var body: some View {
        VStack(spacing: 5) {
            if let title { Text(title).font(.caption.bold().monospaced()).foregroundStyle(.secondary) }
            HStack(spacing: OverrideLayout.gridGap) {
                ForEach(effects) { effect in
                    if effect.isAvailable {
                        if hold { MomentaryEffectPad(effect: effect, active: activeIDs.contains(effect.id) || store.isMomentaryEngaged(effect.id), compact: compact).environmentObject(store) }
                        else { Button { store.perform("trigger_cue", value: effect.id) } label: { EffectPadFace(effect: effect, active: false, compact: compact) }.buttonStyle(HardwarePerformancePadStyle(active: false)) }
                    } else { UnavailableEffectPad(effect: effect) }
                }
            }
            .frame(maxHeight: .infinity)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

private struct StatusConsole: View {
    @EnvironmentObject private var store: RemoteStore
    let state: RemoteLiveStateV2
    var body: some View {
        VStack(spacing: 10) {
            HStack(spacing: 10) {
                RemoteCard(title: "BEATBEAM CONNECTION") {
                    VStack(alignment: .leading, spacing: 12) {
                        ConsoleLine(label: "STATE", value: store.connectionState.label, tone: store.isConnected ? .green : RemoteTheme.warning)
                        ConsoleLine(label: "HOST", value: store.remoteHostLabel, tone: .white)
                        ConsoleLine(label: "PROTOCOL", value: "V\(state.connection.protocolVersion) · \(state.connection.compatible ? "COMPATIBLE" : "CHECK")", tone: state.connection.compatible ? .green : RemoteTheme.warning)
                        HStack(spacing: 8) {
                            Button("RECONNECT") { store.reconnect() }.buttonStyle(ConsoleActionStyle(tint: RemoteTheme.accent))
                            Button("SCAN QR") { store.showScanner = true }.buttonStyle(ConsoleActionStyle(tint: .indigo))
                            Button("PAIR / RE-PAIR") { store.showConfiguration = true }.buttonStyle(ConsoleActionStyle(tint: .gray))
                        }
                    }
                }
                RemoteCard(title: "SYSTEM") {
                    LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 8), count: 2), spacing: 8) {
                        HealthTile(title: "BACKEND", value: store.isConnected ? "CONNECTED" : "OFFLINE", healthy: store.isConnected)
                        HealthTile(title: "DMX", value: state.dmx.connected ? "CONNECTED" : "DISCONNECTED", healthy: state.dmx.connected)
                        HealthTile(title: "RENDERER", value: state.dmx.rendererHealthy ? "HEALTHY" : "UNHEALTHY", healthy: state.dmx.rendererHealthy)
                        HealthTile(title: "TRANSPORT", value: state.track.transportFresh ? "FRESH" : "STALE", healthy: state.track.transportFresh)
                        HealthTile(title: "SONGANALYZER", value: state.track.readiness ?? "UNAVAILABLE", healthy: state.track.readiness?.uppercased() == "READY")
                        HealthTile(title: "OUTPUT", value: state.dmx.physicalOutputAvailable ? "PHYSICAL" : "PREVIEW", healthy: state.dmx.renderedOutputAvailable == true)
                    }
                }
            }
            RemoteCard(title: "OPERATIONAL STATUS") {
                HStack(spacing: 18) {
                    ConsoleLine(label: "VIRTUALDJ", value: state.track.transportFresh ? "LIVE TRANSPORT" : "WAITING / STALE", tone: state.track.transportFresh ? .green : RemoteTheme.warning)
                    ConsoleLine(label: "PAIRING", value: store.isConnected ? "SCOPED CONNECTED" : "RE-PAIR REQUIRED", tone: store.isConnected ? .green : RemoteTheme.warning)
                    ConsoleLine(label: "RENDER FRAME", value: state.dmx.frameSequence.map(String.init) ?? "—", tone: .white)
                }
                if let warning = state.warnings.first(where: { $0.severity == "critical" }) { Text(warning.message).font(.caption.bold()).foregroundStyle(RemoteTheme.warning).padding(.top, 5) }
            }
        }.frame(maxHeight: .infinity)
    }
}

private struct SettingsConsole: View {
    @EnvironmentObject private var store: RemoteStore
    let state: RemoteLiveStateV2
    @State private var confirmBaseline = false
    @State private var confirmDynamic = false
    var body: some View {
        HStack(spacing: 10) {
            RemoteCard(title: "CONNECTION PREFERENCES") {
                VStack(alignment: .leading, spacing: 14) {
                    ConsoleLine(label: "HOST", value: store.remoteHostLabel, tone: .white)
                    ConsoleLine(label: "KEEP AWAKE", value: "ACTIVE WHILE OPEN", tone: .green)
                    ConsoleLine(label: "RECONNECT", value: "AUTOMATIC", tone: .green)
                    HStack(spacing: 8) {
                        Button("RECONNECT NOW") { store.reconnect() }.buttonStyle(ConsoleActionStyle(tint: RemoteTheme.accent))
                        Button("PAIR / SCAN QR") { store.showConfiguration = true }.buttonStyle(ConsoleActionStyle(tint: .indigo))
                    }
                }
            }
            RemoteCard(title: "REMOTE") {
                VStack(alignment: .leading, spacing: 14) {
                    ConsoleLine(label: "APP", value: "BEATBEAM REMOTE 1.2", tone: .white)
                    ConsoleLine(label: "PROTOCOL", value: "REMOTE LIVE STATE V\(state.connection.protocolVersion)", tone: .cyan)
                    ConsoleLine(label: "SCOPE", value: state.control.scope, tone: .green)
                    Button("FORGET THIS PAIRING", role: .destructive) { store.forgetConnection() }.buttonStyle(ConsoleActionStyle(tint: RemoteTheme.danger))
                }
            }
            RemoteCard(title: "PRODUCTION MODE") {
                VStack(alignment: .leading, spacing: 14) {
                    ConsoleLine(label: "CURRENT", value: productionLabel(state.show.configuredProductionMode), tone: state.show.dynamicComposerActive ? .green : RemoteTheme.warning)
                    Button("REVERT TO BASELINE") { confirmBaseline = true }.buttonStyle(ConsoleActionStyle(tint: .gray))
                    Button("ENABLE DYNAMIC COMPOSER") { confirmDynamic = true }.buttonStyle(ConsoleActionStyle(tint: RemoteTheme.accent))
                }
            }
        }
        .frame(maxHeight: .infinity)
        .alert("Revert to Baseline?", isPresented: $confirmBaseline) { Button("Revert", role: .destructive) { store.perform("revert_baseline") }; Button("Cancel", role: .cancel) {} } message: { Text("The physical frame returns to the established baseline show. Transport is unchanged.") }
        .alert("Enable Dynamic Composer?", isPresented: $confirmDynamic) { Button("Enable Dynamic") { store.perform("enable_dynamic_composer") }; Button("Cancel", role: .cancel) {} } message: { Text("Enable Dynamic Composer deliberately for the current production show.") }
    }
}

private struct UnpairedSurface: View {
    @EnvironmentObject private var store: RemoteStore
    var body: some View {
        VStack(spacing: 18) {
            Image(systemName: "dot.radiowaves.left.and.right").font(.system(size: 48, weight: .medium)).foregroundStyle(RemoteTheme.accent)
            Text("BEATBEAM LIVE REMOTE").font(.title.bold().monospaced()).foregroundStyle(.white)
            Text(store.connectionState.label).font(.headline).foregroundStyle(.secondary)
            Text("Pair deze vaste landscape control-surface met BeatBeam om de actuele show en veilige live controls te openen.").multilineTextAlignment(.center).foregroundStyle(.secondary).frame(maxWidth: 470)
            HStack(spacing: 10) {
                Button("SCAN QR") { store.showScanner = true }.buttonStyle(ConsoleActionStyle(tint: .indigo))
                Button(store.connectionState == .notPaired ? "PAIR IPAD" : "RECONNECT") { store.showConfiguration = true }.buttonStyle(ConsoleActionStyle(tint: RemoteTheme.accent))
            }
        }.padding(28).frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

private struct MomentaryEffectPad: View {
    @EnvironmentObject private var store: RemoteStore
    let effect: RemoteEffectCapability; let active: Bool; let compact: Bool
    var body: some View {
        EffectPadFace(effect: effect, active: active, compact: compact)
            .background(active ? RemoteTheme.accent.opacity(0.24) : RemoteTheme.padOff)
            .clipShape(RoundedRectangle(cornerRadius: 8))
            .overlay(RoundedRectangle(cornerRadius: 8).stroke(active ? RemoteTheme.accent : RemoteTheme.border, lineWidth: active ? 2 : 1))
            .contentShape(Rectangle())
            .onLongPressGesture(minimumDuration: 0, maximumDistance: .infinity, pressing: { pressed in
                if pressed { store.beginMomentary(effect.id) }
                else { store.endMomentary(effect.id) }
            }, perform: {})
            .onDisappear { store.endMomentary(effect.id) }.accessibilityLabel("Hold \(effect.label)")
    }
}

private struct EffectPadFace: View {
    let effect: RemoteEffectCapability; let active: Bool; let compact: Bool
    var body: some View {
        VStack(spacing: compact ? 4 : 8) {
            Text(effect.label.uppercased().replacingOccurrences(of: " ", with: "\n"))
                .font(.subheadline.bold().monospaced()).multilineTextAlignment(.center).lineLimit(2)
            Image(systemName: effectIcon(effect.id)).font(compact ? .body : .title2).foregroundStyle(active ? RemoteTheme.accent : .white.opacity(0.88))
        }
            .foregroundStyle(.white).frame(maxWidth: .infinity, minHeight: compact ? 38 : 74)
    }
}

private struct UnavailableEffectPad: View {
    let effect: RemoteEffectCapability
    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(effect.label.uppercased()).font(.caption.bold()).foregroundStyle(.secondary)
            Text(effect.reasonIfUnavailable ?? "Niet beschikbaar").font(.caption2).foregroundStyle(.secondary).lineLimit(2)
        }.padding(8).frame(maxWidth: .infinity, minHeight: 58, alignment: .leading).background(Color.white.opacity(0.04)).clipShape(RoundedRectangle(cornerRadius: 10))
    }
}

private struct ConsoleColorPad: View {
    let label: String; let tint: Color; let active: Bool; let height: CGFloat; let action: () -> Void
    var body: some View { Button(action: action) { Text(label).font(.caption.bold().monospaced()).frame(maxWidth: .infinity, minHeight: height, maxHeight: height) }.buttonStyle(ColorPerformancePadStyle(tint: tint, active: active)) }
}
private struct ConsoleMiniPad: View {
    let label: String; let active: Bool; let action: () -> Void
    var body: some View { Button(action: action) { Text(label).font(.caption.bold().monospaced()).lineLimit(1).minimumScaleFactor(0.72).frame(maxWidth: .infinity, minHeight: 44, maxHeight: .infinity) }.buttonStyle(HardwarePerformancePadStyle(active: active)) }
}
private struct BlackoutAuthorityBanner: View {
    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: "moon.fill").foregroundStyle(.white)
            Text("BLACKOUT ACTIVE").font(.caption.bold().monospaced())
            Text("Physical output is blacked out. Preview remains underlying show intent.").font(.caption).foregroundStyle(.white.opacity(0.84))
            Spacer()
        }.foregroundStyle(.white).padding(.horizontal, 12).frame(height: 30).background(RemoteTheme.danger).clipShape(RoundedRectangle(cornerRadius: 9))
    }
}

private struct RemoteCard<Content: View>: View {
    var title: String? = nil
    @ViewBuilder let content: Content
    init(title: String? = nil, @ViewBuilder content: () -> Content) { self.title = title; self.content = content() }
    var body: some View {
        VStack(alignment: .leading, spacing: 6) { if let title { Text(title).font(.caption.bold().monospaced()).foregroundStyle(.secondary) }; content }
            .padding(OverrideLayout.cardInset).frame(maxWidth: .infinity, alignment: .leading)
            .background(LinearGradient(colors: [RemoteTheme.panelRaised.opacity(0.72), RemoteTheme.panel], startPoint: .top, endPoint: .bottom))
            .clipShape(RoundedRectangle(cornerRadius: 9, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 9, style: .continuous).stroke(RemoteTheme.border))
            .shadow(color: .black.opacity(0.28), radius: 4, y: 2)
    }
}
private struct LiveMetric: View {
    let label: String; let value: String
    var body: some View { VStack(spacing: 2) { Text(label).font(.caption2.bold().monospaced()).foregroundStyle(.secondary); Text(value).font(.headline.bold().monospaced()).foregroundStyle(.white) }.frame(minWidth: 50) }
}
private struct StatusBadge: View {
    let label: String; let tone: Color
    var body: some View { Text(label).font(.caption2.bold().monospaced()).foregroundStyle(tone).padding(.horizontal, 7).padding(.vertical, 4).background(tone.opacity(0.14)).clipShape(Capsule()) }
}
private struct ConsoleLine: View {
    let label: String; let value: String; let tone: Color
    var body: some View { HStack { Text(label).font(.caption.bold().monospaced()).foregroundStyle(.secondary).frame(width: 74, alignment: .leading); Text(value.uppercased()).font(.subheadline.bold()).foregroundStyle(tone).lineLimit(1); Spacer(minLength: 0) } }
}
private struct HealthTile: View {
    let title: String; let value: String; let healthy: Bool
    var body: some View { VStack(alignment: .leading, spacing: 5) { Text(title).font(.caption2.bold().monospaced()).foregroundStyle(.secondary); Text(value).font(.caption.bold().monospaced()).foregroundStyle(healthy ? .green : RemoteTheme.warning).lineLimit(1) }.frame(maxWidth: .infinity, alignment: .leading).padding(9).background(Color.white.opacity(0.05)).clipShape(RoundedRectangle(cornerRadius: 8)) }
}
private struct ConsoleTabStyle: ButtonStyle {
    let active: Bool
    func makeBody(configuration: Configuration) -> some View {
        configuration.label.foregroundStyle(.white)
            .background(active ? RemoteTheme.warning.opacity(configuration.isPressed ? 0.65 : 0.88) : RemoteTheme.background.opacity(configuration.isPressed ? 0.6 : 1))
            .clipShape(RoundedRectangle(cornerRadius: 7))
            .overlay(RoundedRectangle(cornerRadius: 7).stroke(active ? RemoteTheme.warning : RemoteTheme.border, lineWidth: active ? 2 : 1))
    }
}
private struct ColorPerformancePadStyle: ButtonStyle {
    let tint: Color; let active: Bool
    func makeBody(configuration: Configuration) -> some View {
        configuration.label.foregroundStyle(tint == .yellow || tint == .white ? .black : .white)
            .background(LinearGradient(colors: [tint.opacity(configuration.isPressed ? 0.58 : 0.95), tint.opacity(0.48)], startPoint: .top, endPoint: .bottom))
            .clipShape(RoundedRectangle(cornerRadius: 7))
            .overlay(RoundedRectangle(cornerRadius: 7).stroke(active ? .white : tint.opacity(0.82), lineWidth: active ? 2 : 1))
            .shadow(color: tint.opacity(0.35), radius: active ? 7 : 3)
    }
}
private struct HardwarePerformancePadStyle: ButtonStyle {
    let active: Bool
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .background(LinearGradient(colors: [RemoteTheme.panelRaised, RemoteTheme.background], startPoint: .top, endPoint: .bottom))
            .clipShape(RoundedRectangle(cornerRadius: 8))
            .overlay(RoundedRectangle(cornerRadius: 8).stroke(active ? RemoteTheme.accent : RemoteTheme.border, lineWidth: active ? 2 : 1))
            .shadow(color: .black.opacity(0.42), radius: 3, y: 2)
            .opacity(configuration.isPressed ? 0.66 : 1)
    }
}
private struct HardwareButtonStyle: ButtonStyle {
    let tint: Color
    func makeBody(configuration: Configuration) -> some View {
        configuration.label.foregroundStyle(.white)
            .background(LinearGradient(colors: [tint.opacity(0.96), RemoteTheme.background], startPoint: .top, endPoint: .bottom))
            .clipShape(RoundedRectangle(cornerRadius: 7))
            .overlay(RoundedRectangle(cornerRadius: 7).stroke(RemoteTheme.border))
            .opacity(configuration.isPressed ? 0.65 : 1)
    }
}
private struct ConsoleActionStyle: ButtonStyle {
    let tint: Color
    func makeBody(configuration: Configuration) -> some View {
        configuration.label.font(.subheadline.bold().monospaced()).multilineTextAlignment(.center).frame(maxWidth: .infinity, maxHeight: .infinity).foregroundStyle(tint == .gray ? .white : tint)
            .background(LinearGradient(colors: [tint == .gray ? RemoteTheme.panelRaised : tint.opacity(0.38), RemoteTheme.background], startPoint: .top, endPoint: .bottom))
            .clipShape(RoundedRectangle(cornerRadius: 8))
            .overlay(RoundedRectangle(cornerRadius: 8).stroke(tint == .gray ? RemoteTheme.border : tint, lineWidth: 1.5))
            .shadow(color: .black.opacity(0.38), radius: 3, y: 2)
            .opacity(configuration.isPressed ? 0.65 : 1)
    }
}

private func productionLabel(_ value: String) -> String { value == "DYNAMIC_COMPOSER_ENABLED" ? "DYNAMIC COMPOSER" : "BASELINE" }
private func frameLabel(_ value: String) -> String { value == "dynamic_composer" ? "DYNAMIC COMPOSER" : "BASELINE" }
private func timestamp(_ milliseconds: Int?) -> String { guard let milliseconds else { return "—" }; return String(format: "%d:%02d", milliseconds / 60_000, (milliseconds / 1_000) % 60) }
private func colorTint(_ value: String) -> Color {
    switch value {
    case "red": .red; case "yellow": .yellow; case "green", "lime": .green; case "cyan": .cyan; case "blue": .blue; case "purple": .purple; case "pink": .pink; case "orange": .orange; case "white": .gray; case "rainbow": RemoteTheme.accent; default: .gray
    }
}
private func effectIcon(_ id: String) -> String {
    switch id {
    case "manual_strobe", "all_on": "sun.max"
    case "audience_sweep": "arcade.stick.console"
    case "par_chase", "par_chase_burst": "arrow.right.to.line.compact"
    case "par_snake": "waveform.path"
    case "audience_riser": "chart.bar.fill"
    case "white_hit": "sparkle"
    case "color_burst": "circle.hexagongrid"
    case "snap_fan": "fanblades"
    case "mirror_bounce": "arrow.up.left.and.arrow.down.right"
    default: "bolt.fill"
    }
}
private func outputColor(_ fixture: RemoteOutputFixture) -> Color {
    let white = Double(fixture.white)
    return Color(red: min(255, Double(fixture.red) + white) / 255, green: min(255, Double(fixture.green) + white) / 255, blue: min(255, Double(fixture.blue) + white) / 255).opacity(max(0.18, Double(fixture.dimmer) / 255))
}

private struct ConnectionSheet: View {
    @EnvironmentObject private var store: RemoteStore
    var body: some View {
        NavigationStack {
            Form {
                Section("Pair met BeatBeam") {
                    Text("Scan de pairing-QR uit BeatBeam op je Mac, of voer het adres en de zes-cijferige code in. De iPad ontvangt scoped REMOTE_READ en LIVE_CONTROL-credentials.").font(.footnote).foregroundStyle(.secondary)
                    TextField("BeatBeam-adres", text: $store.configurationURLText).textInputAutocapitalization(.never).autocorrectionDisabled()
                    TextField("Pairingcode", text: $store.pairingCodeText).keyboardType(.numberPad)
                    HStack { Button("Scan QR") { store.showScanner = true }; Spacer(); Button("Pair") { store.saveConfiguration() }.buttonStyle(.borderedProminent) }
                }
                if store.liveState != nil { Section { Button("Vergeet deze iPad-koppeling", role: .destructive) { store.forgetConnection() } } }
            }.navigationTitle("BeatBeam Pairing").toolbar { ToolbarItem(placement: .topBarTrailing) { Button("Sluit") { store.showConfiguration = false } } }
        }
    }
}
