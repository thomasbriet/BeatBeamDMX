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

    var body: some View {
        NavigationStack {
            ZStack {
                LinearGradient(colors: [Color(red: 0.05, green: 0.07, blue: 0.11), RemoteTheme.background], startPoint: .topLeading, endPoint: .bottomTrailing)
                    .ignoresSafeArea()
                if let state = store.liveState { liveDashboard(state) } else { disconnectedDashboard }
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
            Text("Deze iPad leest uitsluitend de authoritative Live Show-state. Showbediening is in deze versie bewust niet beschikbaar.")
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
                    if state.overrides.blackout { blackoutBanner }
                    else if state.overrides.anyActive { overrideBanner(state.overrides) }
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

    private var blackoutBanner: some View {
        HStack { Image(systemName: "moon.fill").font(.title2); Text("BLACKOUT ACTIVE").font(.title2.bold()); Spacer(); Text("READ-ONLY").font(.caption.bold().monospaced()) }
            .foregroundStyle(.white).padding(14).background(RemoteTheme.danger).clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
            .accessibilityLabel("Blackout actief. Deze remote is alleen lezen.")
    }

    private func overrideBanner(_ overrides: RemoteOverrideState) -> some View {
        let details = [overrides.phrase, overrides.energy, overrides.color, overrides.momentaryEffects.isEmpty ? nil : overrides.momentaryEffects.joined(separator: ", ")].compactMap { $0 }.joined(separator: " · ")
        return HStack { Image(systemName: "hand.raised.fill"); VStack(alignment: .leading) { Text("MANUAL OVERRIDE ACTIVE").font(.headline.bold()); Text(details.isEmpty ? "Automatic frame temporarily overridden" : details).font(.caption) }; Spacer(); Text("READ-ONLY").font(.caption.bold().monospaced()) }
            .foregroundStyle(.black).padding(12).background(RemoteTheme.warning).clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
            .accessibilityLabel("Handmatige override actief. \(details)")
    }

    private func readinessTone(_ readiness: String?) -> Color { readiness?.uppercased() == "READY" ? .green : (readiness?.uppercased() == "ANALYZING" || readiness?.uppercased() == "QUEUED" ? .orange : .red) }
    private func productionLabel(_ value: String) -> String { value == "DYNAMIC_COMPOSER_ENABLED" ? "DYNAMIC COMPOSER" : "BASELINE" }
    private func frameLabel(_ value: String) -> String { value == "dynamic_composer" ? "DYNAMIC COMPOSER" : "BASELINE" }
    private func percent(_ value: Double?) -> String { value.map { "\(Int(($0 * 100).rounded()))%" } ?? "—" }
}

private struct ConnectionSheet: View {
    @EnvironmentObject private var store: RemoteStore
    var body: some View {
        NavigationStack {
            Form {
                Section("Pair met BeatBeam") {
                    Text("Scan de pairing-QR uit BeatBeam op je Mac, of voer het adres en de zes-cijferige code in. De iPad ontvangt uitsluitend een REMOTE_READ-credential.")
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
