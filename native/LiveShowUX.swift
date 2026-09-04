import SwiftUI

// MARK: - Live Show presentation

/// Presentation-only live console. It renders the backend's typed state and
/// deliberately never re-evaluates musical, composer, production or safety
/// eligibility in Swift.
struct LiveShowWorkspaceView: View {
    @EnvironmentObject private var model: AppModel

    private var decks: [LiveDeckState] {
        (model.liveUiState?.decks ?? []).sorted { ($0.deckNumber ?? .max) < ($1.deckNumber ?? .max) }
    }

    private var activeDeck: LiveDeckState? {
        decks.first(where: { $0.isActive == true })
    }

    private var operationalWarnings: [LiveOperationalNotice] {
        var notices: [LiveOperationalNotice] = []
        if !model.errorText.isEmpty {
            notices.append(.init(title: "BACKEND", detail: model.errorText, severity: .error))
        }
        if let error = model.physicalDmxError, !error.isEmpty {
            notices.append(.init(title: "DMX", detail: error, severity: .error))
        }
        if let bridge = model.debugState?.bridgeDiagnostics,
           bridge.status != nil, bridge.status != "connected" {
            notices.append(.init(title: "BRIDGE", detail: bridge.error ?? "SongAnalyzer bridge is niet verbonden.", severity: .error))
        }
        if let activeDeck, activeDeck.isLoaded == true,
           liveAnalysisState(activeDeck).title == "FAILED" {
            notices.append(.init(title: "ANALYSE", detail: "Authoritative track is niet klaar voor analyse.", severity: .warning))
        }
        if let activeDeck, activeDeck.isLoaded == true,
           model.debugState?.activeTrack?.status == "unavailable" {
            notices.append(.init(title: "HANDOFF", detail: "Authoritative track is unavailable in the current handoff.", severity: .warning))
        }
        if let live = model.liveUiState, live.availability == "unavailable", !decks.isEmpty {
            notices.append(.init(title: "PLAYBACK", detail: "Een deck is geladen, maar er is geen authoritative playback.", severity: .neutral))
        }
        return notices
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            LiveAuthorityCard(activeDeck: activeDeck)

            if !operationalWarnings.isEmpty {
                VStack(spacing: 8) {
                    ForEach(operationalWarnings) { notice in
                        LiveOperationalNoticeView(notice: notice)
                    }
                }
            }

            ViewThatFits(in: .horizontal) {
                HStack(alignment: .top, spacing: 14) {
                    LiveDecksCard(decks: decks)
                    LiveMusicalStateCard()
                }
                VStack(spacing: 14) {
                    LiveDecksCard(decks: decks)
                    LiveMusicalStateCard()
                }
            }

            ViewThatFits(in: .horizontal) {
                HStack(alignment: .top, spacing: 14) {
                    LiveIntensityCard()
                    LiveEventEnvelopeCard()
                    LiveComposerSummaryCard()
                }
                VStack(spacing: 14) {
                    LiveIntensityCard()
                    LiveEventEnvelopeCard()
                    LiveComposerSummaryCard()
                }
            }

            ViewThatFits(in: .horizontal) {
                HStack(alignment: .top, spacing: 14) {
                    LiveDmxConnectionCard()
                    LiveFixtureGroupsCard()
                    LiveSafetyAndPhysicalCard()
                }
                VStack(spacing: 14) {
                    LiveDmxConnectionCard()
                    LiveFixtureGroupsCard()
                    LiveSafetyAndPhysicalCard()
                }
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityLabel("BeatBeam Live Show")
    }
}

private struct LiveDmxConnectionCard: View {
    @EnvironmentObject private var model: AppModel

    private var selectedDevice: String {
        model.selectedPortLabel.isEmpty ? "Geen interface geselecteerd" : model.selectedPortLabel
    }

    private var connectionDetail: String {
        if model.physicalDmxConnected {
            return model.dmxStatus
        }
        if let error = model.physicalDmxError, !error.isEmpty {
            return error
        }
        if model.errorText.localizedCaseInsensitiveContains("DMX") {
            return model.errorText
        }
        if model.ports.isEmpty {
            return "Geen DMX-interface gevonden. Sluit de interface aan en vernieuw."
        }
        return "Geselecteerd: \(selectedDevice)"
    }

    var body: some View {
        PanelSurface(title: "Physical DMX", compact: true) {
            VStack(alignment: .leading, spacing: 10) {
                HStack(spacing: 8) {
                    LiveStatusBadge(
                        text: model.physicalDmxConnected ? "DMX CONNECTED" : "DMX DISCONNECTED",
                        tone: model.physicalDmxConnected ? .active : .neutral
                    )
                    Text(connectionDetail)
                        .font(.system(size: 10, weight: .medium))
                        .foregroundStyle(BeatBeamPalette.secondaryText)
                        .lineLimit(2)
                }

                Picker("DMX interface", selection: $model.selectedPortLabel) {
                    Text("Selecteer interface").tag("")
                    ForEach(model.ports, id: \.device) { port in
                        Text(port.label).tag(port.label)
                    }
                }
                .pickerStyle(.menu)
                .disabled(model.ports.isEmpty)

                HStack(spacing: 8) {
                    Button("REFRESH") { model.refreshPorts() }
                        .buttonStyle(.bordered)

                    if model.physicalDmxConnected {
                        Button("RECONNECT") { model.reconnectDMX() }
                            .buttonStyle(.borderedProminent)
                        Button("DISCONNECT") { model.disconnectDMX() }
                            .buttonStyle(.bordered)
                    } else {
                        Button("CONNECT DMX") { model.connectDMX() }
                            .buttonStyle(.borderedProminent)
                            .disabled(model.selectedPortLabel.isEmpty)
                    }
                }

                Text("Connection controls do not change production authority.")
                    .font(.system(size: 9, weight: .medium))
                    .foregroundStyle(BeatBeamPalette.secondaryText)
            }
        }
    }
}

private struct LiveAuthorityCard: View {
    @EnvironmentObject private var model: AppModel
    let activeDeck: LiveDeckState?
    @State private var confirmEnable = false
    @State private var confirmRevert = false

    private var dynamicMode: Bool { model.productionShowMode == "DYNAMIC_COMPOSER_ENABLED" }

    private var deckNumber: String {
        activeDeck?.deckNumber.map { "DECK \($0)" } ?? "NO MASTER"
    }

    private var readiness: LiveAnalysisPresentation {
        activeDeck.map(liveAnalysisState) ?? .unavailable
    }

    private var title: String {
        guard activeDeck?.isLoaded == true else { return "Geen authoritative playback" }
        return liveDisplay(activeDeck?.trackTitle, fallback: "Onbekende track")
    }

    private var artist: String {
        guard activeDeck?.isLoaded == true else { return "Start playback in VirtualDJ om een master te kiezen." }
        return liveDisplay(activeDeck?.trackArtist, fallback: "Artist onbekend")
    }

    var body: some View {
        PanelSurface(title: "Live Show", compact: false) {
            VStack(alignment: .leading, spacing: 12) {
                HStack(alignment: .top, spacing: 16) {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("NOW PLAYING / MASTER")
                            .font(.system(size: 11, weight: .bold, design: .monospaced))
                            .foregroundStyle(BeatBeamPalette.brandCyan)
                        Text(title)
                            .font(.system(size: 27, weight: .bold))
                            .lineLimit(2)
                        Text(artist)
                            .font(.system(size: 14, weight: .medium))
                            .foregroundStyle(BeatBeamPalette.secondaryText)
                            .lineLimit(1)
                    }
                    Spacer(minLength: 12)
                    VStack(alignment: .trailing, spacing: 7) {
                        LiveStatusBadge(text: deckNumber, tone: activeDeck == nil ? .neutral : .active)
                        LiveStatusBadge(text: readiness.title, tone: readiness.tone)
                    }
                }

                HStack(spacing: 8) {
                    LiveKeyMetric(title: "BPM", value: model.bpmValue)
                    LiveKeyMetric(title: "BEAT", value: model.beatValue)
                    LiveKeyMetric(title: "BAR", value: model.barValue)
                    LiveKeyMetric(title: "TIME", value: model.timeValue)
                    LiveKeyMetric(title: "ANALYSIS", value: readiness.title)
                }

                Divider()

                HStack(spacing: 10) {
                    LiveSourceBadge(title: "PRODUCTION", value: productionModeDisplay(model.productionShowMode), tone: dynamicMode ? .active : .neutral)
                    LiveSourceBadge(title: "FRAME", value: productionDisplay(model.productionShowSource), tone: model.productionFallbackActive ? .warning : .neutral)
                    LiveSourceBadge(title: "PREVIEW", value: previewDisplay(model.previewComposition?.mode), tone: .active)
                    Spacer(minLength: 0)
                    Text("Physical: \(model.physicalOutputSource)")
                        .font(.system(size: 10, weight: .medium, design: .monospaced))
                        .foregroundStyle(BeatBeamPalette.secondaryText)
                        .lineLimit(1)
                }

                if dynamicMode, model.productionFallbackActive {
                    Text("DYNAMIC COMPOSER · Fallback: BASELINE · \(model.productionFallbackReason ?? "unknown")")
                        .font(.system(size: 10, weight: .medium, design: .monospaced))
                        .foregroundStyle(BeatBeamPalette.brandAmber)
                }

                HStack(spacing: 10) {
                    if dynamicMode {
                        Button("REVERT TO BASELINE") { confirmRevert = true }
                            .buttonStyle(.borderedProminent)
                            .tint(.orange)
                    } else {
                        Button("ENABLE DYNAMIC COMPOSER") { confirmEnable = true }
                            .buttonStyle(.borderedProminent)
                            .tint(BeatBeamPalette.brandCyan)
                    }
                    Text("Fallback available · Manual and blackout always win")
                        .font(.system(size: 10, weight: .medium))
                        .foregroundStyle(BeatBeamPalette.secondaryText)
                }
            }
        }
        .confirmationDialog("Enable Dynamic Composer for physical production?", isPresented: $confirmEnable, titleVisibility: .visible) {
            Button("ENABLE DYNAMIC COMPOSER", role: .destructive) { model.enableDynamicComposerProduction() }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("Baseline remains available for immediate revert.")
        }
        .confirmationDialog("Revert physical production to baseline Auto Show?", isPresented: $confirmRevert, titleVisibility: .visible) {
            Button("REVERT TO BASELINE", role: .destructive) { model.revertProductionToBaseline() }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("This takes effect immediately and will not auto-enable again.")
        }
        .accessibilityLabel("Authoritative playback: \(deckNumber), \(title), \(readiness.title)")
    }
}

private struct LiveDecksCard: View {
    let decks: [LiveDeckState]

    var body: some View {
        PanelSurface(title: "Decks", compact: true) {
            if decks.isEmpty {
                LiveEmptyState(icon: "rectangle.stack.badge.questionmark", text: "Geen deckstatus beschikbaar")
            } else {
                ViewThatFits(in: .horizontal) {
                    HStack(spacing: 10) {
                        ForEach(decks, id: \.deckNumber) { deck in LiveDeckCard(deck: deck) }
                    }
                    VStack(spacing: 10) {
                        ForEach(decks, id: \.deckNumber) { deck in LiveDeckCard(deck: deck) }
                    }
                }
            }
        }
    }
}

private struct LiveDeckCard: View {
    let deck: LiveDeckState

    private var presentation: LiveAnalysisPresentation { liveAnalysisState(deck) }
    private var number: Int { deck.deckNumber ?? 0 }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text("DECK \(number)")
                    .font(.system(size: 11, weight: .bold, design: .monospaced))
                    .foregroundStyle(deck.isMaster == true ? BeatBeamPalette.brandCyan : BeatBeamPalette.secondaryText)
                Spacer(minLength: 4)
                if deck.isMaster == true {
                    LiveStatusBadge(text: "MASTER", tone: .active, compact: true)
                } else if deck.isActive == true {
                    LiveStatusBadge(text: "AUTHORITATIVE", tone: .active, compact: true)
                }
            }

            if deck.isLoaded == true {
                Text(liveDisplay(deck.trackTitle, fallback: "Onbekende track"))
                    .font(.system(size: 14, weight: .semibold))
                    .lineLimit(2)
                Text(liveDisplay(deck.trackArtist, fallback: "Artist onbekend"))
                    .font(.system(size: 11, weight: .medium))
                    .foregroundStyle(BeatBeamPalette.secondaryText)
                    .lineLimit(1)
                HStack(spacing: 6) {
                    Text(deck.isPlaying == true ? "PLAYING" : "LOADED")
                    Text(deck.bpm.map { String(format: "%.1f BPM", $0) } ?? "BPM —")
                }
                .font(.system(size: 10, weight: .medium, design: .monospaced))
                .foregroundStyle(BeatBeamPalette.secondaryText)
            } else {
                Text("(geen track)")
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundStyle(BeatBeamPalette.secondaryText)
                Text("Deck is leeg")
                    .font(.system(size: 11))
                    .foregroundStyle(BeatBeamPalette.secondaryText)
            }

            HStack(spacing: 6) {
                LiveStatusBadge(text: presentation.title, tone: presentation.tone, compact: true)
                if let generation = deck.generation {
                    Text("g\(generation)")
                        .font(.system(size: 10, weight: .medium, design: .monospaced))
                        .foregroundStyle(BeatBeamPalette.secondaryText)
                }
            }
        }
        .padding(10)
        .frame(maxWidth: .infinity, minHeight: 150, alignment: .topLeading)
        .background(
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .fill(deck.isMaster == true || deck.isActive == true ? BeatBeamPalette.utilityGradient : BeatBeamPalette.raisedGradient)
        )
        .overlay(
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .stroke(deck.isMaster == true || deck.isActive == true ? BeatBeamPalette.brandCyan.opacity(0.72) : BeatBeamPalette.border, lineWidth: 1)
        )
        .accessibilityLabel("Deck \(number), \(deck.isLoaded == true ? liveDisplay(deck.trackTitle, fallback: "onbekende track") : "leeg"), \(presentation.title)")
    }
}

private struct LiveMusicalStateCard: View {
    @EnvironmentObject private var model: AppModel

    private var state: PreviewContinuousMusicalState? { model.previewComposition?.continuousMusicalState }

    var body: some View {
        PanelSurface(title: "Musical State", compact: true) {
            VStack(alignment: .leading, spacing: 12) {
                HStack(alignment: .firstTextBaseline) {
                    VStack(alignment: .leading, spacing: 3) {
                        Text("CONTINUOUS BACKBONE")
                            .font(.system(size: 10, weight: .bold, design: .monospaced))
                            .foregroundStyle(BeatBeamPalette.brandCyan)
                        Text(model.phraseCurrentValue == "-" ? "Current structure unavailable" : model.phraseCurrentValue)
                            .font(.system(size: 17, weight: .semibold))
                        Text("Contextual phrase display — not a production authority label")
                            .font(.system(size: 10))
                            .foregroundStyle(BeatBeamPalette.secondaryText)
                    }
                    Spacer(minLength: 8)
                    if let next = nonPlaceholder(model.phraseNextValue) {
                        Text("NEXT · \(next)")
                            .font(.system(size: 10, weight: .bold, design: .monospaced))
                            .foregroundStyle(BeatBeamPalette.secondaryText)
                            .lineLimit(2)
                            .multilineTextAlignment(.trailing)
                    }
                }

                LiveProgressBar(value: state?.sectionProgress, label: "SECTION PROGRESS")

                HStack(spacing: 8) {
                    LiveKeyMetric(title: "RELATIVE ENERGY", value: livePercent(state?.relativeEnergy))
                    LiveKeyMetric(title: "TRAJECTORY", value: trajectoryDisplay(state?.energyTrajectory))
                    LiveKeyMetric(title: "RECURRENCE", value: livePercent(state?.recurrenceStrength))
                }
                Text(model.phraseNextValue == "-" ? "No transition countdown available" : "Transition · \(model.phraseNextValue)")
                    .font(.system(size: 11, weight: .medium))
                    .foregroundStyle(BeatBeamPalette.secondaryText)
            }
        }
    }
}

private struct LiveIntensityCard: View {
    @EnvironmentObject private var model: AppModel

    private var intensity: LiveIntensityState? { model.liveIntensityState }

    var body: some View {
        PanelSurface(title: "Intensity", compact: true) {
            VStack(alignment: .leading, spacing: 10) {
                Text("EFFECTIVE INTENSITY")
                    .font(.system(size: 10, weight: .bold, design: .monospaced))
                    .foregroundStyle(BeatBeamPalette.brandCyan)
                Text(livePercent(intensity?.effectiveIntensity ?? intensity?.analyzedIntensity))
                    .font(.system(size: 30, weight: .bold, design: .rounded))
                LiveProgressBar(value: intensity?.effectiveIntensity ?? intensity?.analyzedIntensity, label: "CURRENT SHOW LEVEL")
                HStack(spacing: 8) {
                    LiveKeyMetric(title: "ANALYZED", value: livePercent(intensity?.analyzedIntensity))
                    LiveKeyMetric(title: "LIVE", value: intensity?.sourceValid == true ? livePercent(intensity?.liveIntensity) : "Analyzed only")
                    LiveKeyMetric(title: "MODIFIER", value: signedPercent(intensity?.liveModifier))
                }
                Text(intensity?.sourceValid == true
                    ? "Live source: Deck \(intensity?.sourceDeck.map(String.init) ?? "—")"
                    : "Live intensity unavailable — analyzed intensity remains normal.")
                    .font(.system(size: 10, weight: .medium))
                    .foregroundStyle(BeatBeamPalette.secondaryText)
            }
        }
    }
}

private struct LiveEventEnvelopeCard: View {
    @EnvironmentObject private var model: AppModel

    private var preview: PreviewCompositionState? { model.previewComposition }
    private var envelope: PreviewMusicalEventEnvelope? { preview?.eventEnvelope }

    var body: some View {
        PanelSurface(title: "Current Event", compact: true) {
            VStack(alignment: .leading, spacing: 10) {
                if let event = nonPlaceholder(preview?.event?.type) {
                    Text(event.uppercased())
                        .font(.system(size: 24, weight: .bold, design: .rounded))
                        .foregroundStyle(BeatBeamPalette.brandMagenta)
                    if envelope?.active == true {
                        HStack {
                            LiveStatusBadge(text: envelope?.phase?.uppercased() ?? "ACTIVE", tone: .event)
                            Spacer()
                            Text(livePercent(envelope?.progress))
                                .font(.system(size: 12, weight: .bold, design: .monospaced))
                        }
                        LiveProgressBar(value: envelope?.progress, label: "EVENT ENVELOPE")
                    } else {
                        Text("Current musical event — no active envelope phase.")
                            .font(.system(size: 11))
                            .foregroundStyle(BeatBeamPalette.secondaryText)
                    }
                } else {
                    LiveEmptyState(icon: "waveform.path.ecg", text: "No current musical event. Continuous state remains active.")
                }
            }
        }
    }
}

private struct LiveComposerSummaryCard: View {
    @EnvironmentObject private var model: AppModel

    private var preview: PreviewCompositionState? { model.previewComposition }

    var body: some View {
        PanelSurface(title: "Dynamic Composer", compact: true) {
            VStack(alignment: .leading, spacing: 10) {
                HStack {
                    LiveStatusBadge(text: previewDisplay(preview?.mode), tone: .active)
                    Spacer()
                    Text(preview?.dynamicComposerActive == true ? "ACTIVE" : "PREVIEW ONLY")
                        .font(.system(size: 10, weight: .bold, design: .monospaced))
                        .foregroundStyle(BeatBeamPalette.secondaryText)
                }
                Text(preview?.previewCue ?? "Preview composition unavailable")
                    .font(.system(size: 13, weight: .semibold))
                    .lineLimit(2)
                if preview?.dynamicCompositionApplied == true {
                    LivePrimitiveSummary(role: "MOVEMENT", values: preview?.selectedPrimitives?["moving"])
                    LivePrimitiveSummary(role: "COLOR / PALETTE", values: preview?.selectedPrimitives?["par"])
                    LivePrimitiveSummary(role: "PULSE / WASH", values: preview?.selectedPrimitives?["wash"])
                    if let changed = preview?.changedDimensions, !changed.isEmpty {
                        Text("Variation change · \(changed.joined(separator: ", "))")
                            .font(.system(size: 10, weight: .medium, design: .monospaced))
                            .foregroundStyle(BeatBeamPalette.secondaryText)
                            .lineLimit(2)
                    }
                } else {
                    Text("Preview currently reuses the safe baseline scene.")
                        .font(.system(size: 11))
                        .foregroundStyle(BeatBeamPalette.secondaryText)
                }
            }
        }
    }
}

private struct LiveFixtureGroupsCard: View {
    @EnvironmentObject private var model: AppModel

    private var groups: [String: PreviewFixtureGroupIntent] {
        model.previewComposition?.fixtureGroupIntents ?? [:]
    }

    var body: some View {
        PanelSurface(title: "Fixture Groups", compact: true) {
            VStack(alignment: .leading, spacing: 9) {
                Text("PREVIEW INTENT")
                    .font(.system(size: 10, weight: .bold, design: .monospaced))
                    .foregroundStyle(BeatBeamPalette.brandCyan)
                if groups.isEmpty {
                    LiveEmptyState(icon: "lightbulb.2", text: "No fixture-group intent in the current preview.")
                } else {
                    ForEach(["moving", "par", "wash"], id: \.self) { role in
                        LiveFixtureGroupRow(
                            title: role == "par" ? "PAR" : role.capitalized,
                            intent: groups[role],
                            primitives: model.previewComposition?.selectedPrimitives?[role]
                        )
                    }
                }
            }
        }
    }
}

private struct LiveSafetyAndPhysicalCard: View {
    @EnvironmentObject private var model: AppModel

    private var overrides: [String] {
        [
            model.liveOverrideColor != "none" ? model.liveOverrideColorLabel : nil,
            model.liveOverrideManualStrobe ? "Manual strobe" : nil,
            model.liveOverrideAudienceSweep ? "Audience sweep" : nil,
            model.liveOverrideAllOn ? "All on" : nil,
            model.liveOverrideParChase ? "PAR chase" : nil,
            model.liveOverrideParSnake ? "PAR snake" : nil,
            model.liveOneShotCue != "none" ? model.liveOneShotCueLabel : nil,
        ].compactMap { $0 }
    }

    var body: some View {
        PanelSurface(title: "Manual / Safety", compact: true) {
            VStack(alignment: .leading, spacing: 10) {
                HStack(alignment: .center, spacing: 10) {
                    Button {
                        model.blackout()
                    } label: {
                        Label(model.blackoutActive ? "BLACKOUT ACTIVE" : "BLACKOUT", systemImage: "lightbulb.slash.fill")
                            .font(.system(size: 13, weight: .bold))
                            .padding(.horizontal, 14)
                            .padding(.vertical, 11)
                            .frame(maxWidth: .infinity)
                            .background(model.blackoutActive ? Color.red.opacity(0.92) : Color.red.opacity(0.72))
                            .foregroundStyle(.white)
                            .clipShape(RoundedRectangle(cornerRadius: 9, style: .continuous))
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel(model.blackoutActive ? "Blackout active" : "Activate blackout")

                    VStack(alignment: .leading, spacing: 3) {
                        Text(overrides.isEmpty ? "AUTO SHOW IN CONTROL" : "MANUAL OVERRIDE ACTIVE")
                            .font(.system(size: 10, weight: .bold, design: .monospaced))
                            .foregroundStyle(overrides.isEmpty ? BeatBeamPalette.secondaryText : Color.orange)
                        Text(overrides.isEmpty ? "No manual override" : overrides.joined(separator: " · "))
                            .font(.system(size: 11, weight: .medium))
                            .foregroundStyle(BeatBeamPalette.secondaryText)
                            .lineLimit(2)
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }

                Divider()

                HStack(spacing: 8) {
                    LiveStatusBadge(text: model.physicalDmxConnected ? "DMX CONNECTED" : "PHYSICAL DISCONNECTED", tone: model.physicalDmxConnected ? .active : .neutral)
                    Text(model.physicalDmxConnected ? model.dmxStatus : "Preview remains usable")
                        .font(.system(size: 10, weight: .medium))
                        .foregroundStyle(BeatBeamPalette.secondaryText)
                        .lineLimit(2)
                }
            }
        }
    }
}

// MARK: - Preview and advanced workspaces

struct PreviewComposerWorkspaceView: View {
    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            PanelSurface(title: "Stage Map", compact: true) {
                Text("Venue layout stays preview-only. Explicit Physical Aim and Move controls can lease bounded Pan/Tilt when DMX safety gates pass.")
                    .font(.system(size: 12, weight: .medium))
                    .foregroundStyle(BeatBeamPalette.secondaryText)
            }
            MapWorkspaceView()
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
    }
}

struct AutoShowWorkspaceView: View {
    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            PanelSurface(title: "Auto Show", compact: true) {
                Text("Musical style, Preview Composer and Audience PAN settings live here. Stage Map and fixture calibration stay separate.")
                    .font(.system(size: 12, weight: .medium))
                    .foregroundStyle(BeatBeamPalette.secondaryText)
            }
            AutoShowControlView()
        }
    }
}

struct AdvancedOperationsWorkspaceView: View {
    let fixtureBank: AnyView
    let selectedEditor: SlotEditor?
    @State private var section: AdvancedSection = .diagnostics

    private enum AdvancedSection: String, CaseIterable, Identifiable {
        case diagnostics = "Diagnostics"
        case fixtures = "Fixtures"
        case map = "Map"
        var id: String { rawValue }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Picker("Advanced section", selection: $section) {
                ForEach(AdvancedSection.allCases) { item in Text(item.rawValue).tag(item) }
            }
            .pickerStyle(.segmented)
            Text("Developer and operational detail. Live Show remains the primary performance view.")
                .font(.system(size: 11, weight: .medium))
                .foregroundStyle(BeatBeamPalette.secondaryText)

            switch section {
            case .diagnostics:
                DebugInspectorView()
            case .fixtures:
                VStack(alignment: .leading, spacing: 12) {
                    fixtureBank
                    if let selectedEditor {
                        ScrollView { SlotPanelView(editor: selectedEditor).padding(.bottom, 32) }
                    } else {
                        LiveEmptyState(icon: "lightbulb.slash", text: "Geen fixture geselecteerd")
                    }
                }
            case .map:
                MapWorkspaceView()
            }
        }
    }
}

// MARK: - Small presentation building blocks

private enum LiveStatusTone { case active, warning, error, event, neutral }

private struct LiveAnalysisPresentation {
    let title: String
    let tone: LiveStatusTone

    static let ready = Self(title: "READY", tone: .active)
    static let analyzing = Self(title: "ANALYZING", tone: .warning)
    static let prewarming = Self(title: "PREWARMING", tone: .warning)
    static let waiting = Self(title: "WAITING", tone: .neutral)
    static let failed = Self(title: "FAILED", tone: .error)
    static let loaded = Self(title: "LOADED", tone: .neutral)
    static let unavailable = Self(title: "UNAVAILABLE", tone: .neutral)
}

private struct LiveOperationalNotice: Identifiable {
    let title: String
    let detail: String
    let severity: LiveStatusTone
    var id: String { "\(title)-\(detail)" }
}

private struct LiveOperationalNoticeView: View {
    let notice: LiveOperationalNotice

    var body: some View {
        HStack(spacing: 9) {
            Image(systemName: notice.severity == .error ? "exclamationmark.triangle.fill" : "info.circle.fill")
                .foregroundStyle(liveToneColor(notice.severity))
            Text(notice.title)
                .font(.system(size: 10, weight: .bold, design: .monospaced))
            Text(notice.detail)
                .font(.system(size: 12, weight: .medium))
                .lineLimit(2)
            Spacer(minLength: 0)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 9)
        .background(liveToneColor(notice.severity).opacity(0.12))
        .overlay(RoundedRectangle(cornerRadius: 8, style: .continuous).stroke(liveToneColor(notice.severity).opacity(0.38), lineWidth: 1))
        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
    }
}

private struct LiveStatusBadge: View {
    let text: String
    let tone: LiveStatusTone
    var compact = false

    var body: some View {
        Text(text)
            .font(.system(size: compact ? 9 : 10, weight: .bold, design: .monospaced))
            .padding(.horizontal, compact ? 6 : 8)
            .padding(.vertical, compact ? 4 : 5)
            .foregroundStyle(liveToneColor(tone))
            .background(liveToneColor(tone).opacity(0.14))
            .overlay(RoundedRectangle(cornerRadius: 6, style: .continuous).stroke(liveToneColor(tone).opacity(0.46), lineWidth: 1))
            .clipShape(RoundedRectangle(cornerRadius: 6, style: .continuous))
    }
}

private struct LiveSourceBadge: View {
    let title: String
    let value: String
    let tone: LiveStatusTone

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(title)
                .font(.system(size: 9, weight: .bold, design: .monospaced))
                .foregroundStyle(BeatBeamPalette.secondaryText)
            Text(value)
                .font(.system(size: 11, weight: .bold, design: .monospaced))
                .foregroundStyle(liveToneColor(tone))
        }
        .padding(.horizontal, 8)
        .padding(.vertical, 6)
        .background(BeatBeamPalette.raisedBackground)
        .clipShape(RoundedRectangle(cornerRadius: 7, style: .continuous))
    }
}

private struct LiveKeyMetric: View {
    let title: String
    let value: String

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(title)
                .font(.system(size: 9, weight: .bold, design: .monospaced))
                .foregroundStyle(BeatBeamPalette.secondaryText)
            Text(value)
                .font(.system(size: 12, weight: .semibold, design: .monospaced))
                .foregroundStyle(.white)
                .lineLimit(2)
        }
        .padding(.horizontal, 8)
        .padding(.vertical, 7)
        .frame(maxWidth: .infinity, minHeight: 48, alignment: .leading)
        .background(BeatBeamPalette.raisedBackground)
        .clipShape(RoundedRectangle(cornerRadius: 7, style: .continuous))
    }
}

private struct LiveProgressBar: View {
    let value: Double?
    let label: String

    private var clamped: Double { min(1, max(0, value ?? 0)) }

    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            HStack {
                Text(label)
                    .font(.system(size: 9, weight: .bold, design: .monospaced))
                    .foregroundStyle(BeatBeamPalette.secondaryText)
                Spacer()
                Text(value == nil ? "—" : livePercent(value))
                    .font(.system(size: 10, weight: .bold, design: .monospaced))
                    .foregroundStyle(BeatBeamPalette.secondaryText)
            }
            GeometryReader { proxy in
                ZStack(alignment: .leading) {
                    Capsule().fill(BeatBeamPalette.mutedBackground)
                    Capsule().fill(BeatBeamPalette.activeGradient).frame(width: proxy.size.width * clamped)
                }
            }
            .frame(height: 7)
        }
    }
}

private struct LivePrimitiveSummary: View {
    let role: String
    let values: [String: PreviewPrimitiveValue]?

    private var text: String {
        let entries = (values ?? [:]).keys.sorted().compactMap { key -> String? in
            guard let value = values?[key]?.displayText else { return nil }
            return "\(key.replacingOccurrences(of: "_", with: " ")): \(value)"
        }
        return entries.isEmpty ? "neutral" : entries.joined(separator: " · ")
    }

    var body: some View {
        HStack(alignment: .top, spacing: 8) {
            Text(role)
                .font(.system(size: 9, weight: .bold, design: .monospaced))
                .foregroundStyle(BeatBeamPalette.secondaryText)
                .frame(width: 112, alignment: .leading)
            Text(text)
                .font(.system(size: 10, weight: .medium, design: .monospaced))
                .foregroundStyle(.white.opacity(0.86))
                .lineLimit(2)
        }
    }
}

private struct LiveFixtureGroupRow: View {
    let title: String
    let intent: PreviewFixtureGroupIntent?
    let primitives: [String: PreviewPrimitiveValue]?

    private var summary: String {
        let values = (primitives ?? [:]).keys.sorted().compactMap { key -> String? in
            guard let value = primitives?[key]?.displayText else { return nil }
            return "\(key): \(value)"
        }
        return values.isEmpty ? "neutral" : values.joined(separator: " · ")
    }

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            VStack(alignment: .leading, spacing: 2) {
                Text(title.uppercased())
                    .font(.system(size: 10, weight: .bold, design: .monospaced))
                Text("\(livePercent(intent?.intensity)) intensity · \(livePercent(intent?.movementAmount)) move")
                    .font(.system(size: 10, weight: .medium, design: .monospaced))
                    .foregroundStyle(BeatBeamPalette.secondaryText)
            }
            .frame(width: 126, alignment: .leading)
            Text(summary)
                .font(.system(size: 10, weight: .medium, design: .monospaced))
                .foregroundStyle(.white.opacity(0.88))
                .lineLimit(2)
            Spacer(minLength: 0)
        }
        .padding(8)
        .background(BeatBeamPalette.raisedBackground)
        .clipShape(RoundedRectangle(cornerRadius: 7, style: .continuous))
    }
}

private struct LiveEmptyState: View {
    let icon: String
    let text: String

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: icon).foregroundStyle(BeatBeamPalette.secondaryText)
            Text(text)
                .font(.system(size: 11, weight: .medium))
                .foregroundStyle(BeatBeamPalette.secondaryText)
                .fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.vertical, 8)
    }
}

private func liveAnalysisState(_ deck: LiveDeckState) -> LiveAnalysisPresentation {
    guard deck.isLoaded == true else { return .unavailable }
    let value = (deck.prewarmStatus ?? deck.analysisStatus ?? "loaded").lowercased()
    if value.contains("ready") || value.contains("current") || value.contains("complete") { return .ready }
    if value.contains("prewarm") { return .prewarming }
    if value.contains("analy") || value.contains("running") { return .analyzing }
    if value.contains("queue") || value.contains("wait") || value.contains("pending") { return .waiting }
    if value.contains("unavailable") { return .unavailable }
    if value.contains("fail") || value.contains("error") { return .failed }
    return .loaded
}

private func liveToneColor(_ tone: LiveStatusTone) -> Color {
    switch tone {
    case .active: return BeatBeamPalette.brandCyan
    case .warning: return .orange
    case .error: return .red
    case .event: return BeatBeamPalette.brandMagenta
    case .neutral: return BeatBeamPalette.secondaryText
    }
}

private func liveDisplay(_ value: String?, fallback: String) -> String {
    guard let value else { return fallback }
    let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
    return trimmed.isEmpty || trimmed == "-" ? fallback : trimmed
}

private func nonPlaceholder(_ value: String?) -> String? {
    guard let value else { return nil }
    let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
    return trimmed.isEmpty || trimmed == "-" ? nil : trimmed
}

private func livePercent(_ value: Double?) -> String {
    guard let value else { return "—" }
    return "\(Int((min(1, max(0, value)) * 100).rounded()))%"
}

private func signedPercent(_ value: Double?) -> String {
    guard let value else { return "—" }
    return String(format: "%+.0f%%", value * 100)
}

private func trajectoryDisplay(_ value: Double?) -> String {
    guard let value else { return "Stable" }
    if value > 0.08 { return "Rising" }
    if value < -0.08 { return "Falling" }
    return "Stable"
}

private func productionDisplay(_ value: String) -> String {
    value == "existing_autoshow" ? "BASELINE" : value.replacingOccurrences(of: "_", with: " ").uppercased()
}

private func productionModeDisplay(_ value: String) -> String {
    value == "DYNAMIC_COMPOSER_ENABLED" ? "DYNAMIC COMPOSER" : "BASELINE AUTO SHOW"
}

private func previewDisplay(_ value: String?) -> String {
    switch value {
    case "DYNAMIC_COMPOSER": return "DYNAMIC COMPOSER"
    case "RME_ENHANCED": return "RME ENHANCED"
    default: return "BASELINE PREVIEW"
    }
}
