import SwiftUI

private enum RemoteTheme {
    static let background = Color(red: 0.04, green: 0.05, blue: 0.07)
    static let panel = Color(red: 0.09, green: 0.10, blue: 0.14)
    static let panelAlt = Color(red: 0.13, green: 0.15, blue: 0.20)
    static let border = Color.white.opacity(0.10)
    static let text = Color.white
    static let secondary = Color.white.opacity(0.72)
    static let muted = Color.white.opacity(0.55)
    static let accent = Color(red: 0.12, green: 0.88, blue: 0.96)
    static let secondaryAccent = Color(red: 0.93, green: 0.17, blue: 0.70)
    static let warmAccent = Color(red: 1.00, green: 0.72, blue: 0.10)

    static var backgroundGradient: LinearGradient {
        LinearGradient(
            colors: [
                Color(red: 0.05, green: 0.07, blue: 0.11),
                Color(red: 0.04, green: 0.05, blue: 0.07),
                Color(red: 0.07, green: 0.05, blue: 0.10)
            ],
            startPoint: .topLeading,
            endPoint: .bottomTrailing
        )
    }

    static var panelGradient: LinearGradient {
        LinearGradient(
            colors: [
                Color(red: 0.12, green: 0.14, blue: 0.19),
                Color(red: 0.09, green: 0.10, blue: 0.14)
            ],
            startPoint: .topLeading,
            endPoint: .bottomTrailing
        )
    }

    static var accentGradient: LinearGradient {
        LinearGradient(
            colors: [accent, Color(red: 0.05, green: 0.62, blue: 0.86)],
            startPoint: .topLeading,
            endPoint: .bottomTrailing
        )
    }

    static var secondaryGradient: LinearGradient {
        LinearGradient(
            colors: [secondaryAccent, Color(red: 0.48, green: 0.12, blue: 0.74)],
            startPoint: .topLeading,
            endPoint: .bottomTrailing
        )
    }
}

private struct RemoteBrandChip: View {
    var body: some View {
        HStack(spacing: 10) {
            Image("BrandMark")
                .resizable()
                .interpolation(.high)
                .scaledToFit()
                .frame(width: 36, height: 36)
                .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))

            VStack(alignment: .leading, spacing: 2) {
                Text("BeatBeam")
                    .font(.system(size: 15, weight: .bold))
                    .foregroundStyle(RemoteTheme.text)
                Text("Remote")
                    .font(.system(size: 10, weight: .medium, design: .monospaced))
                    .foregroundStyle(RemoteTheme.secondaryAccent)
            }
        }
    }
}

struct ContentView: View {
    @EnvironmentObject private var store: RemoteStore
    @State private var showSideMenu = false

    var body: some View {
        NavigationStack {
            GeometryReader { proxy in
                let topHeight = max(66, proxy.size.height * 0.085)
                let phraseHeight = max(74, proxy.size.height * 0.095)
                let autoWidth = max(258, proxy.size.width * 0.22)
                let effectsWidth = max(275, proxy.size.width * 0.21)
                let footerHeight = max(68, proxy.size.height * 0.088)
                let menuWidth = min(380, proxy.size.width * 0.34)

                ZStack {
                    RemoteTheme.backgroundGradient.ignoresSafeArea()

                    VStack(spacing: 10) {
                        topBar
                            .frame(height: topHeight)

                        phraseCard
                            .frame(height: phraseHeight)

                        HStack(spacing: 10) {
                            autoShowCard
                                .frame(width: autoWidth)
                                .frame(maxHeight: .infinity)

                            VStack(spacing: 10) {
                                HStack(spacing: 10) {
                                    colorCard
                                        .frame(maxWidth: .infinity, maxHeight: .infinity)

                                    effectsCard
                                        .frame(width: effectsWidth)
                                        .frame(maxHeight: .infinity)
                                }

                                masterActionsCard
                                    .frame(height: footerHeight)
                            }
                        }
                        .frame(maxHeight: .infinity)
                    }
                    .padding(10)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)

                    if showSideMenu {
                        Color.black.opacity(0.45)
                            .ignoresSafeArea()
                            .onTapGesture {
                                withAnimation(.easeInOut(duration: 0.2)) {
                                    showSideMenu = false
                                }
                            }

                        HStack(spacing: 0) {
                            sideMenu(width: menuWidth)
                            Spacer(minLength: 0)
                        }
                        .transition(.move(edge: .leading))
                    }
                }
            }
            .toolbar(.hidden, for: .navigationBar)
            .sheet(isPresented: $store.showConfiguration) {
                ConnectionSheet()
                    .environmentObject(store)
            }
            .sheet(isPresented: $store.showScanner) {
                NavigationStack {
                    QRScannerView { value in
                        store.handleScannedURL(value)
                    }
                    .ignoresSafeArea()
                    .toolbar {
                        ToolbarItem(placement: .topBarTrailing) {
                            Button("Close") {
                                store.showScanner = false
                            }
                        }
                    }
                }
            }
            .alert("Remote melding", isPresented: Binding(
                get: { store.transientMessage != nil },
                set: { if !$0 { store.transientMessage = nil } }
            )) {
                Button("OK", role: .cancel) {
                    store.transientMessage = nil
                }
            } message: {
                Text(store.transientMessage ?? "")
            }
        }
    }

    private var topBar: some View {
        CardView {
            HStack(spacing: 12) {
                Button {
                    withAnimation(.easeInOut(duration: 0.2)) {
                        showSideMenu.toggle()
                    }
                } label: {
                    Image(systemName: "line.3.horizontal")
                        .font(.system(size: 18, weight: .semibold))
                        .foregroundStyle(RemoteTheme.text)
                        .frame(width: 48, height: 48)
                        .background(RemoteTheme.panelAlt)
                        .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
                }
                .buttonStyle(.plain)

                RemoteBrandChip()

                VStack(alignment: .leading, spacing: 7) {
                    Text(store.trackTitle)
                        .font(.system(size: 18, weight: .semibold))
                        .foregroundStyle(RemoteTheme.text)
                        .lineLimit(1)
                        .minimumScaleFactor(0.78)

                    Text(store.currentCue)
                        .font(.system(size: 10, weight: .semibold, design: .monospaced))
                        .foregroundStyle(RemoteTheme.secondaryAccent)
                        .lineLimit(1)
                        .padding(.horizontal, 9)
                        .padding(.vertical, 5)
                        .background(RemoteTheme.secondaryAccent.opacity(0.15))
                        .clipShape(Capsule())
                }

                Spacer(minLength: 10)

                HStack(spacing: 10) {
                    CompactMetricPill(title: "BPM", value: formatBPM(store.appState?.osc.bpm))
                    CompactMetricPill(title: "Beat", value: formatBeat(store.appState?.osc.beatDisplay))
                    CompactMetricPill(title: "Phrase", value: store.appState?.osc.phraseCurrent ?? "-")
                    CompactMetricPill(title: "Next", value: store.appState?.osc.phraseNext ?? "-")
                }

                VStack(alignment: .trailing, spacing: 10) {
                    StatusPill(title: "Remote", value: store.connectionState.label, tone: store.isConnected ? .green : .orange)
                    if let state = store.appState {
                        StatusPill(title: "DMX", value: state.dmx.connected ? "Live" : "Off", tone: state.dmx.connected ? .green : .red)
                    }
                }
            }
        }
    }

    private var masterActionsCard: some View {
        CardView(title: "Live") {
            VStack(alignment: .leading, spacing: 6) {
                Text("Current Cue")
                    .font(.system(size: 11, weight: .medium, design: .monospaced))
                    .foregroundStyle(RemoteTheme.muted)

                Text(store.currentCue)
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundStyle(RemoteTheme.text)
                    .lineLimit(2)
                    .minimumScaleFactor(0.8)

                Text(store.trackArtist)
                    .font(.system(size: 13, weight: .medium))
                    .foregroundStyle(RemoteTheme.secondary)
                    .lineLimit(1)
            }
        }
    }

    private var autoShowCard: some View {
        CardView(title: "Auto Show") {
            VStack(alignment: .leading, spacing: 8) {
                HStack(spacing: 12) {
                    Toggle(isOn: Binding(
                        get: { store.appState?.dmx.autoShow.enabled ?? false },
                        set: { value in Task { await store.setAutoShowEnabled(value) } }
                    )) {
                        Text("Enabled")
                        .font(.system(size: 16, weight: .semibold))
                        .foregroundStyle(RemoteTheme.text)
                    }
                    .tint(RemoteTheme.accent)

                    Spacer(minLength: 12)

                    Text(store.appState?.dmx.autoShow.style.capitalized ?? "Adaptive")
                        .font(.system(size: 12, weight: .semibold, design: .monospaced))
                        .foregroundStyle(RemoteTheme.accent)
                        .padding(.horizontal, 9)
                        .padding(.vertical, 6)
                        .background(RemoteTheme.accent.opacity(0.16))
                        .clipShape(Capsule())
                }

                VStack(alignment: .leading, spacing: 8) {
                    Text("Energy")
                        .font(.system(size: 11, weight: .medium, design: .monospaced))
                        .foregroundStyle(RemoteTheme.muted)

                    LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 8), count: 2), spacing: 8) {
                        ForEach(store.energyOptions) { option in
                            MiniOptionButton(
                                title: option.title,
                                isActive: (store.appState?.dmx.autoShow.overrideEnergy ?? "none") == option.value,
                                accentTone: energyAccent(for: option.value)
                            ) {
                                Task { await store.setEnergyOverride(option.value) }
                            }
                            .frame(minHeight: 60)
                        }
                    }
                }

                LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 8), count: 2), spacing: 8) {
                    ForEach(store.styles) { option in
                        BigToggleButton(
                            title: option.title,
                            subtitle: store.appState?.dmx.autoShow.style == option.value ? "Active" : "Set",
                            systemImage: styleSymbol(option.value),
                            isActive: store.appState?.dmx.autoShow.style == option.value,
                            accentTone: RemoteTheme.secondaryAccent
                        ) {
                            Task { await store.setStyle(option.value) }
                        }
                        .frame(minHeight: 60)
                    }
                }
            }
        }
    }

    private var phraseCard: some View {
        CardView(title: "Phrase Override") {
                HStack(spacing: 8) {
                HStack(spacing: 8) {
                    Text("Live")
                        .font(.system(size: 11, weight: .medium, design: .monospaced))
                        .foregroundStyle(RemoteTheme.muted)
                    Text(store.appState?.osc.phraseCurrent ?? "-")
                        .font(.system(size: 16, weight: .semibold))
                        .foregroundStyle(RemoteTheme.text)
                        .lineLimit(1)
                }
                .frame(width: 104, alignment: .leading)

                ForEach(store.phraseOptions) { option in
                    CompactOverrideChip(
                        title: option.title,
                        isActive: (store.appState?.dmx.autoShow.overridePhrase ?? "none") == option.value
                    ) {
                        Task { await store.setPhraseOverride(option.value) }
                    }
                }
            }
        }
    }

    private var colorCard: some View {
        CardView(title: "Color") {
            LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 8), count: 4), spacing: 8) {
                ForEach(store.colors) { option in
                    ColorButton(
                        option: option,
                        isSelected: (store.appState?.dmx.autoShow.overrideColor ?? "none") == option.value
                    ) {
                        Task { await store.setColor(option.value) }
                    }
                }
            }
        }
    }

    private var effectsCard: some View {
        CardView(title: "Effects") {
            LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 8), count: 2), spacing: 8) {
                ForEach(store.effects) { option in
                    MomentaryEffectButton(
                        title: option.title,
                        systemImage: option.symbol,
                        isActive: store.isEffectEnabled(option.key),
                        accentTone: effectAccent(for: option.key)
                    ) { pressed in
                        Task { await store.setEffect(option.key, enabled: pressed) }
                    }
                    .aspectRatio(1, contentMode: .fit)
                }

                MomentaryEffectButton(
                    title: "Blackout",
                    systemImage: "moon.fill",
                    isActive: false,
                    accentTone: .red
                ) { pressed in
                    Task { await store.setBlackoutEnabled(pressed) }
                }
                .aspectRatio(1, contentMode: .fit)
            }
        }
    }

    private func sessionRow(label: String, value: String) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(label.uppercased())
                .font(.system(size: 11, weight: .medium, design: .monospaced))
                .foregroundStyle(RemoteTheme.muted)
            Text(value)
                .font(.system(size: 14, weight: .medium))
                .foregroundStyle(RemoteTheme.text)
                .lineLimit(1)
                .minimumScaleFactor(0.75)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(10)
        .background(RemoteTheme.panelAlt)
        .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
    }

    private func formatBPM(_ value: Double?) -> String {
        guard let value else { return "-" }
        return String(format: "%.2f", value)
    }

    private func formatBeat(_ value: Double?) -> String {
        guard let value else { return "-" }
        return String(Int(floor(value)))
    }

    private func energyAccent(for value: String) -> Color {
        switch value {
        case "low":
            return RemoteTheme.accent
        case "mid":
            return RemoteTheme.secondaryAccent
        case "high":
            return RemoteTheme.warmAccent
        default:
            return RemoteTheme.accent
        }
    }

    private func effectAccent(for key: String) -> Color {
        switch key {
        case "manual_strobe":
            return RemoteTheme.secondaryAccent
        case "audience_sweep":
            return RemoteTheme.accent
        case "all_on":
            return RemoteTheme.warmAccent
        case "override_par_chase":
            return RemoteTheme.accent
        case "override_par_snake":
            return RemoteTheme.secondaryAccent
        default:
            return RemoteTheme.accent
        }
    }

    private func styleSymbol(_ value: String) -> String {
        switch value {
        case "club": return "music.note.list"
        case "cinematic": return "film.stack"
        case "warm": return "sun.max.fill"
        case "festival": return "bolt.fill"
        case "minimal": return "moon.fill"
        default: return "sparkles"
        }
    }

    private func sideMenu(width: CGFloat) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                Text("Session")
                    .font(.system(size: 22, weight: .semibold))
                    .foregroundStyle(RemoteTheme.text)
                Spacer(minLength: 0)
                Button {
                    withAnimation(.easeInOut(duration: 0.2)) {
                        showSideMenu = false
                    }
                } label: {
                    Image(systemName: "xmark")
                        .font(.system(size: 16, weight: .semibold))
                        .foregroundStyle(RemoteTheme.text)
                        .frame(width: 34, height: 34)
                        .background(RemoteTheme.panelAlt)
                        .clipShape(Circle())
                }
                .buttonStyle(.plain)
            }

            VStack(alignment: .leading, spacing: 10) {
                sessionRow(label: "Remote", value: store.remoteHostLabel)
                sessionRow(label: "Connection", value: store.connectionState.label)
                sessionRow(label: "Track", value: store.trackTitle)
                sessionRow(label: "Artist", value: store.trackArtist)
                sessionRow(label: "Cue", value: store.currentCue)
            }

            VStack(spacing: 10) {
                Button {
                    store.showConfiguration = true
                } label: {
                    Label("Edit URL", systemImage: "pencil")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(RemoteActionButtonStyle(background: RemoteTheme.panelAlt))

                Button {
                    store.showScanner = true
                } label: {
                    Label("Scan QR", systemImage: "qrcode.viewfinder")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(RemoteActionButtonStyle(background: RemoteTheme.accent.opacity(0.9)))

                Button {
                    store.reconnect()
                } label: {
                    Label("Refresh", systemImage: "arrow.clockwise")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(RemoteActionButtonStyle(background: RemoteTheme.panelAlt))

                Button {
                    store.disconnect()
                    withAnimation(.easeInOut(duration: 0.2)) {
                        showSideMenu = false
                    }
                } label: {
                    Label("Disconnect", systemImage: "bolt.horizontal.circle")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(RemoteActionButtonStyle(background: RemoteTheme.panelAlt))
            }

            Spacer(minLength: 0)
        }
        .padding(16)
        .frame(width: width, alignment: .topLeading)
        .frame(maxHeight: .infinity, alignment: .topLeading)
        .background(RemoteTheme.panel)
        .overlay(alignment: .trailing) {
            Rectangle()
                .fill(RemoteTheme.border)
                .frame(width: 1)
        }
    }
}

private struct ConnectionSheet: View {
    @EnvironmentObject private var store: RemoteStore
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            Form {
                Section("BeatBeam Remote URL") {
                    TextField("http://100.x.x.x:8780/remote?token=...", text: $store.configurationURLText, axis: .vertical)
                        .textInputAutocapitalization(.never)
                        .keyboardType(.URL)
                        .autocorrectionDisabled()

                    HStack {
                        Button("Paste") {
                            store.pasteFromClipboard()
                        }
                        Button("Scan QR") {
                            store.showScanner = true
                        }
                    }
                }

                Section("Gedrag") {
                    Text("Deze app draait als vaste landscape remote en houdt het scherm wakker zolang hij actief op de voorgrond staat.")
                        .font(.footnote)
                        .foregroundStyle(RemoteTheme.secondary)
                }
            }
            .navigationTitle("Connect")
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("Close") { dismiss() }
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Save") {
                        store.saveConfiguration()
                        dismiss()
                    }
                }
            }
        }
    }
}

private struct CardView<Content: View>: View {
    let title: String?
    @ViewBuilder let content: Content

    init(title: String? = nil, @ViewBuilder content: () -> Content) {
        self.title = title
        self.content = content()
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            if let title {
                Text(title)
                    .font(.system(size: 11, weight: .medium, design: .monospaced))
                    .foregroundStyle(RemoteTheme.secondaryAccent.opacity(0.86))
            }
            content
        }
        .padding(.horizontal, 4)
        .padding(.vertical, 2)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
    }
}

private struct CompactMetricPill: View {
    let title: String
    let value: String

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title)
                .font(.system(size: 10, weight: .medium, design: .monospaced))
                .foregroundStyle(RemoteTheme.muted)
            Text(value)
                .font(.system(size: 16, weight: .semibold, design: .rounded))
                .foregroundStyle(RemoteTheme.text)
                .lineLimit(1)
                .minimumScaleFactor(0.72)
        }
        .frame(minWidth: 78, alignment: .leading)
        .padding(.horizontal, 10)
        .padding(.vertical, 8)
        .background(RemoteTheme.panelGradient)
        .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .stroke(RemoteTheme.border, lineWidth: 1)
        )
    }
}

private struct StatusPill: View {
    let title: String
    let value: String
    let tone: Color

    var body: some View {
        VStack(alignment: .trailing, spacing: 4) {
            Text(title)
                .font(.system(size: 10, weight: .medium, design: .monospaced))
                .foregroundStyle(RemoteTheme.muted)
            Text(value)
                .font(.system(size: 12, weight: .semibold))
                .foregroundStyle(tone)
                .padding(.horizontal, 9)
                .padding(.vertical, 7)
                .background(tone.opacity(0.18))
                .clipShape(Capsule())
                .lineLimit(1)
                .minimumScaleFactor(0.7)
        }
    }
}

private struct BigToggleButton: View {
    let title: String
    let subtitle: String
    let systemImage: String
    let isActive: Bool
    let accentTone: Color
    let action: () -> Void

    @State private var isPressed = false
    @State private var didTrigger = false

    var body: some View {
        let highlighted = isActive || isPressed

        VStack(alignment: .leading, spacing: 8) {
            Image(systemName: systemImage)
                .font(.system(size: 18, weight: .semibold))
                .foregroundStyle(highlighted ? accentTone : RemoteTheme.text)
                .frame(width: 34, height: 34)
                .background(highlighted ? accentTone.opacity(0.18) : Color.white.opacity(0.05))
                .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))

            Spacer(minLength: 0)

            Text(title)
                .font(.system(size: 15, weight: .semibold))
                .foregroundStyle(RemoteTheme.text)
                .lineLimit(1)
                .minimumScaleFactor(0.75)

            Text(subtitle)
                .font(.system(size: 11, weight: .medium, design: .monospaced))
                .foregroundStyle(highlighted ? RemoteTheme.text.opacity(0.8) : RemoteTheme.secondary)
                .lineLimit(1)
                .minimumScaleFactor(0.8)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .padding(12)
        .background(
            ZStack {
                RoundedRectangle(cornerRadius: 10, style: .continuous)
                    .fill(highlighted ? accentTone.opacity(isPressed ? 0.30 : 0.22) : RemoteTheme.panelAlt)
                if highlighted {
                    RoundedRectangle(cornerRadius: 10, style: .continuous)
                        .fill(
                            LinearGradient(
                                colors: [accentTone.opacity(isPressed ? 0.36 : 0.28), Color.clear],
                                startPoint: .topLeading,
                                endPoint: .bottomTrailing
                            )
                        )
                }
            }
        )
        .overlay(
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .stroke(highlighted ? accentTone.opacity(0.75) : RemoteTheme.border, lineWidth: highlighted ? 2 : 1)
        )
        .shadow(color: highlighted ? accentTone.opacity(isPressed ? 0.38 : 0.28) : .clear, radius: isPressed ? 18 : 12, y: 0)
        .scaleEffect(isPressed ? 0.985 : 1.0)
        .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
        .contentShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
        .animation(.easeOut(duration: 0.10), value: isPressed)
        .gesture(
            DragGesture(minimumDistance: 0)
                .onChanged { _ in
                    if !isPressed { isPressed = true }
                    guard !didTrigger else { return }
                    didTrigger = true
                    action()
                }
                .onEnded { _ in
                    isPressed = false
                    didTrigger = false
                }
        )
    }
}

private struct ColorButton: View {
    let option: RemoteStore.ColorOption
    let isSelected: Bool
    let action: () -> Void

    @State private var isPressed = false
    @State private var didTrigger = false

    var body: some View {
        let isAuto = option.value == "none"
        let highlighted = isSelected || isPressed

        ZStack(alignment: .topTrailing) {
            RoundedRectangle(cornerRadius: 18, style: .continuous)
                .fill(RemoteTheme.panelAlt)
                .overlay(
                    RoundedRectangle(cornerRadius: 18, style: .continuous)
                        .stroke(Color.white.opacity(0.06), lineWidth: 1)
                )

            Group {
                if isAuto {
                    RoundedRectangle(cornerRadius: 14, style: .continuous)
                        .fill(RemoteTheme.panel)
                } else if let secondary = option.secondary {
                    RoundedRectangle(cornerRadius: 14, style: .continuous)
                        .fill(
                            LinearGradient(
                                colors: [option.color, secondary],
                                startPoint: .topLeading,
                                endPoint: .bottomTrailing
                            )
                        )
                } else {
                    RoundedRectangle(cornerRadius: 14, style: .continuous)
                        .fill(option.color)
                }
            }
            .padding(6)
            .overlay {
                RoundedRectangle(cornerRadius: 14, style: .continuous)
                    .fill(
                        LinearGradient(
                            colors: [Color.white.opacity(isPressed ? 0.24 : 0.16), Color.clear],
                            startPoint: .topLeading,
                            endPoint: .bottomTrailing
                        )
                    )
                    .padding(6)
            }

            if isAuto {
                VStack(spacing: 8) {
                    Image(systemName: "sparkles")
                        .font(.system(size: 26, weight: .semibold))
                        .foregroundStyle(RemoteTheme.accent)

                    Text("Auto")
                        .font(.system(size: 18, weight: .semibold))
                        .foregroundStyle(RemoteTheme.text)
                }
            }

            if highlighted {
                Circle()
                    .fill(isAuto ? RemoteTheme.accent : Color.white)
                    .frame(width: 14, height: 14)
                    .padding(12)
                    .shadow(color: (isAuto ? RemoteTheme.accent : Color.white).opacity(0.6), radius: 8, y: 0)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .aspectRatio(1, contentMode: .fit)
        .overlay(
            RoundedRectangle(cornerRadius: 18, style: .continuous)
                .stroke(highlighted ? RemoteTheme.accent.opacity(0.95) : RemoteTheme.border, lineWidth: highlighted ? 2.5 : 1)
        )
        .shadow(color: Color.black.opacity(0.24), radius: 8, y: 4)
        .shadow(color: highlighted ? RemoteTheme.accent.opacity(isPressed ? 0.42 : 0.30) : .clear, radius: isPressed ? 24 : 18, y: 0)
        .scaleEffect(isPressed ? 0.985 : 1.0)
        .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
        .contentShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
        .animation(.easeOut(duration: 0.10), value: isPressed)
        .gesture(
            DragGesture(minimumDistance: 0)
                .onChanged { _ in
                    if !isPressed { isPressed = true }
                    guard !didTrigger else { return }
                    didTrigger = true
                    action()
                }
                .onEnded { _ in
                    isPressed = false
                    didTrigger = false
                }
        )
    }
}

private struct MomentaryEffectButton: View {
    let title: String
    let systemImage: String
    let isActive: Bool
    let accentTone: Color
    let onPressChanged: (Bool) -> Void

    @State private var isPressed = false

    init(
        title: String,
        systemImage: String,
        isActive: Bool,
        accentTone: Color = RemoteTheme.accent,
        onPressChanged: @escaping (Bool) -> Void
    ) {
        self.title = title
        self.systemImage = systemImage
        self.isActive = isActive
        self.accentTone = accentTone
        self.onPressChanged = onPressChanged
    }

    var body: some View {
        let active = isPressed || isActive

        ZStack(alignment: .topTrailing) {
            RoundedRectangle(cornerRadius: 16, style: .continuous)
                .fill(active ? accentTone.opacity(0.20) : RemoteTheme.panelAlt)
                .overlay(
                    RoundedRectangle(cornerRadius: 16, style: .continuous)
                        .fill(
                            LinearGradient(
                                colors: [
                                    Color.white.opacity(active ? 0.18 : 0.08),
                                    Color.clear
                                ],
                                startPoint: .topLeading,
                                endPoint: .bottomTrailing
                            )
                        )
                )
                .overlay(
                    RoundedRectangle(cornerRadius: 16, style: .continuous)
                        .stroke(active ? accentTone.opacity(0.88) : RemoteTheme.border, lineWidth: active ? 2.2 : 1)
                )
                .shadow(color: active ? accentTone.opacity(0.26) : .clear, radius: 14, y: 0)

            VStack(spacing: 0) {
                Spacer(minLength: 0)

                Image(systemName: systemImage)
                    .font(.system(size: 34, weight: .semibold))
                    .foregroundStyle(active ? Color.black : RemoteTheme.text)
                    .frame(width: 70, height: 70)
                    .background(active ? accentTone : Color.white.opacity(0.06))
                    .clipShape(RoundedRectangle(cornerRadius: 20, style: .continuous))
                    .shadow(color: active ? accentTone.opacity(0.58) : .clear, radius: 14, y: 0)

                Spacer(minLength: 0)
            }
            .padding(14)
            .frame(maxWidth: .infinity, maxHeight: .infinity)

            Circle()
                .fill(active ? accentTone : Color.white.opacity(0.12))
                .frame(width: 12, height: 12)
                .padding(12)
                .shadow(color: active ? accentTone.opacity(0.65) : .clear, radius: 8, y: 0)
        }
        .contentShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
        .accessibilityLabel(title)
        .gesture(
            DragGesture(minimumDistance: 0)
                .onChanged { _ in
                    guard !isPressed else { return }
                    isPressed = true
                    onPressChanged(true)
                }
                .onEnded { _ in
                    guard isPressed else { return }
                    isPressed = false
                    onPressChanged(false)
                }
        )
    }
}

private struct ImmediateActionButton: View {
    let title: String
    let systemImage: String
    let background: Color
    let action: () -> Void

    @State private var isPressed = false
    @State private var didTrigger = false

    var body: some View {
        Label(title, systemImage: systemImage)
            .frame(maxWidth: .infinity)
            .font(.system(size: 16, weight: .semibold))
            .padding(.horizontal, 16)
            .padding(.vertical, 12)
            .background(background.opacity(isPressed ? 0.82 : 1.0))
            .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 10, style: .continuous)
                    .stroke(Color.white.opacity(0.08), lineWidth: 1)
            )
            .scaleEffect(isPressed ? 0.985 : 1.0)
            .foregroundStyle(RemoteTheme.text)
            .contentShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
            .animation(.easeOut(duration: 0.10), value: isPressed)
            .gesture(
                DragGesture(minimumDistance: 0)
                    .onChanged { _ in
                        if !isPressed { isPressed = true }
                        guard !didTrigger else { return }
                        didTrigger = true
                        action()
                    }
                    .onEnded { _ in
                        isPressed = false
                        didTrigger = false
                    }
            )
    }
}

private struct MomentaryCommandButton: View {
    let title: String
    let systemImage: String
    let background: Color
    let onPressChanged: (Bool) -> Void

    @State private var isPressed = false

    var body: some View {
        Label(title, systemImage: systemImage)
            .frame(maxWidth: .infinity)
            .font(.system(size: 16, weight: .semibold))
            .padding(.horizontal, 16)
            .padding(.vertical, 12)
            .background(background.opacity(isPressed ? 0.82 : 1.0))
            .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 10, style: .continuous)
                    .stroke(Color.white.opacity(0.08), lineWidth: 1)
            )
            .scaleEffect(isPressed ? 0.985 : 1.0)
            .foregroundStyle(RemoteTheme.text)
            .contentShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
            .animation(.easeOut(duration: 0.10), value: isPressed)
            .gesture(
                DragGesture(minimumDistance: 0)
                    .onChanged { _ in
                        guard !isPressed else { return }
                        isPressed = true
                        onPressChanged(true)
                    }
                    .onEnded { _ in
                        guard isPressed else { return }
                        isPressed = false
                        onPressChanged(false)
                    }
            )
    }
}

private struct RemoteActionButtonStyle: ButtonStyle {
    let background: Color

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 17, weight: .semibold))
            .padding(.horizontal, 18)
            .padding(.vertical, 14)
            .background(background.opacity(configuration.isPressed ? 0.80 : 1.0))
            .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 10, style: .continuous)
                    .stroke(Color.white.opacity(0.08), lineWidth: 1)
            )
            .scaleEffect(configuration.isPressed ? 0.985 : 1.0)
            .foregroundStyle(RemoteTheme.text)
    }
}

private struct CompactOverrideChip: View {
    let title: String
    let isActive: Bool
    let action: () -> Void

    @State private var isPressed = false
    @State private var didTrigger = false

    var body: some View {
        let highlighted = isActive || isPressed

        Text(title)
            .font(.system(size: 13, weight: .semibold))
            .foregroundStyle(highlighted ? Color.black : RemoteTheme.text)
            .frame(maxWidth: .infinity)
            .padding(.vertical, 11)
            .background(
                RoundedRectangle(cornerRadius: 12, style: .continuous)
                    .fill(highlighted ? RemoteTheme.secondaryAccent.opacity(isPressed ? 0.92 : 0.82) : RemoteTheme.panelAlt)
            )
            .overlay(
                RoundedRectangle(cornerRadius: 12, style: .continuous)
                    .stroke(highlighted ? RemoteTheme.secondaryAccent.opacity(0.98) : RemoteTheme.border, lineWidth: highlighted ? 2 : 1)
            )
            .shadow(color: highlighted ? RemoteTheme.secondaryAccent.opacity(isPressed ? 0.28 : 0.20) : .clear, radius: 10, y: 0)
            .scaleEffect(isPressed ? 0.985 : 1.0)
            .contentShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
            .animation(.easeOut(duration: 0.10), value: isPressed)
            .gesture(
                DragGesture(minimumDistance: 0)
                    .onChanged { _ in
                        if !isPressed { isPressed = true }
                        guard !didTrigger else { return }
                        didTrigger = true
                        action()
                    }
                    .onEnded { _ in
                        isPressed = false
                        didTrigger = false
                    }
            )
    }
}

private struct MiniOptionButton: View {
    let title: String
    let isActive: Bool
    let accentTone: Color
    let action: () -> Void

    @State private var isPressed = false
    @State private var didTrigger = false

    var body: some View {
        let highlighted = isActive || isPressed

        ZStack(alignment: .topTrailing) {
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .fill(highlighted ? accentTone.opacity(isPressed ? 0.30 : 0.24) : RemoteTheme.panelAlt)
                .overlay {
                    RoundedRectangle(cornerRadius: 14, style: .continuous)
                        .fill(
                            LinearGradient(
                                colors: highlighted
                                    ? [accentTone.opacity(isPressed ? 0.42 : 0.34), Color.clear]
                                    : [Color.white.opacity(0.08), Color.clear],
                                startPoint: .topLeading,
                                endPoint: .bottomTrailing
                            )
                        )
                }

            if highlighted {
                Circle()
                    .fill(accentTone)
                    .frame(width: 10, height: 10)
                    .padding(10)
                    .shadow(color: accentTone.opacity(0.7), radius: 8, y: 0)
            }

            Text(title)
                .font(.system(size: 17, weight: .semibold))
                .foregroundStyle(highlighted ? Color.black : RemoteTheme.text)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
        .overlay(
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .stroke(highlighted ? accentTone.opacity(0.95) : RemoteTheme.border, lineWidth: highlighted ? 2 : 1)
        )
        .shadow(color: highlighted ? accentTone.opacity(isPressed ? 0.38 : 0.30) : .clear, radius: 14, y: 0)
        .scaleEffect(isPressed ? 0.985 : 1.0)
        .contentShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
        .animation(.easeOut(duration: 0.10), value: isPressed)
        .gesture(
            DragGesture(minimumDistance: 0)
                .onChanged { _ in
                    if !isPressed { isPressed = true }
                    guard !didTrigger else { return }
                    didTrigger = true
                    action()
                }
                .onEnded { _ in
                    isPressed = false
                    didTrigger = false
                }
        )
    }
}

private struct RemoteCapsuleButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 13, weight: .semibold))
            .foregroundStyle(RemoteTheme.text)
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
            .background(RemoteTheme.panelAlt.opacity(configuration.isPressed ? 0.85 : 1.0))
            .clipShape(Capsule())
            .overlay(
                Capsule()
                    .stroke(RemoteTheme.border, lineWidth: 1)
            )
    }
}
