import SwiftUI
import UIKit

// Temporary internal migration switch. UIKit V1 is the default; the existing
// SwiftUI surface remains a bounded fallback until a separate cleanup closeout.
enum BBRemotePresentationMode {
    case legacySwiftUI
    case uiKitV1

    static let current: BBRemotePresentationMode = .uiKitV1
}

@MainActor
final class BBRemoteActionBridge {
    private unowned let store: RemoteStore

    init(store: RemoteStore) { self.store = store }

    var connectionLabel: String { store.connectionState.label }
    var isConnected: Bool { store.isConnected }
    var hostLabel: String { store.remoteHostLabel }
    func perform(_ action: String, value: String? = nil) { store.perform(action, value: value) }
    func beginMomentary(_ effect: String) { store.beginMomentary(effect) }
    func endMomentary(_ effect: String) { store.endMomentary(effect) }
    func isMomentaryEngaged(_ effect: String) -> Bool { store.isMomentaryEngaged(effect) }
    func releaseMomentaries(reason: String) { store.releaseActiveMomentaries(reason: reason) }
    func reconnect() { store.reconnect() }
    func scanQR() { store.showScanner = true }
    func showPairing() { store.showConfiguration = true }
    func forgetPairing() { store.forgetConnection() }
}

struct UIKitControlSurfaceHost: UIViewControllerRepresentable {
    @ObservedObject var store: RemoteStore
    let state: RemoteLiveStateV2

    func makeUIViewController(context: Context) -> BBRemoteRootViewController {
        BBRemoteRootViewController(actions: BBRemoteActionBridge(store: store), initialState: state)
    }

    func updateUIViewController(_ controller: BBRemoteRootViewController, context: Context) {
        controller.render(state: state)
    }

    static func dismantleUIViewController(_ controller: BBRemoteRootViewController, coordinator: ()) {
        controller.releaseMomentariesForDismissal()
    }
}

private enum BBRemoteTab: String, CaseIterable {
    case live = "LIVE"
    case override = "OVERRIDE"
    case status = "STATUS"
    case settings = "SETTINGS"
}

@MainActor
final class BBRemoteRootViewController: UIViewController {
    private let actions: BBRemoteActionBridge
    private let header: BBConsoleHeaderView
    private let blackoutBanner = UILabel()
    private let content = UIView()
    private var blackoutHeight: NSLayoutConstraint!
    private var selectedTab: BBRemoteTab = .override
    private var currentSurface: (UIView & BBRemoteStateRendering)?
    private var state: RemoteLiveStateV2
    private lazy var surfaces: [BBRemoteTab: UIView & BBRemoteStateRendering] = [
        .live: BBLiveSurface(actions: actions),
        .override: BBOverrideSurface(actions: actions),
        .status: BBStatusSurface(actions: actions),
        .settings: BBSettingsSurface(actions: actions, presenter: self),
    ]

    init(actions: BBRemoteActionBridge, initialState: RemoteLiveStateV2) {
        self.actions = actions
        self.state = initialState
        self.header = BBConsoleHeaderView(actions: actions)
        super.init(nibName: nil, bundle: nil)
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = BBUIKitTokens.background

        header.onSelectTab = { [weak self] tab in self?.select(tab) }
        view.addSubview(header)
        header.translatesAutoresizingMaskIntoConstraints = false

        blackoutBanner.text = "  ● BLACKOUT ACTIVE — physical output is black; preview remains underlying show intent"
        blackoutBanner.font = BBUIKitTokens.labelFont(11)
        blackoutBanner.textColor = .white
        blackoutBanner.backgroundColor = BBUIKitTokens.danger
        blackoutBanner.layer.cornerRadius = 4
        blackoutBanner.clipsToBounds = true
        blackoutBanner.accessibilityLabel = "Blackout active. Physical output is black."
        view.addSubview(blackoutBanner)
        blackoutBanner.translatesAutoresizingMaskIntoConstraints = false

        view.addSubview(content)
        content.translatesAutoresizingMaskIntoConstraints = false
        blackoutHeight = blackoutBanner.heightAnchor.constraint(equalToConstant: 0)
        NSLayoutConstraint.activate([
            header.leadingAnchor.constraint(equalTo: view.safeAreaLayoutGuide.leadingAnchor, constant: BBUIKitTokens.outerMargin),
            header.trailingAnchor.constraint(equalTo: view.safeAreaLayoutGuide.trailingAnchor, constant: -BBUIKitTokens.outerMargin),
            header.topAnchor.constraint(equalTo: view.safeAreaLayoutGuide.topAnchor, constant: BBUIKitTokens.outerMargin),
            header.heightAnchor.constraint(equalToConstant: BBUIKitTokens.headerHeight),
            blackoutBanner.leadingAnchor.constraint(equalTo: header.leadingAnchor),
            blackoutBanner.trailingAnchor.constraint(equalTo: header.trailingAnchor),
            blackoutBanner.topAnchor.constraint(equalTo: header.bottomAnchor, constant: BBUIKitTokens.panelGap),
            blackoutHeight,
            content.leadingAnchor.constraint(equalTo: header.leadingAnchor),
            content.trailingAnchor.constraint(equalTo: header.trailingAnchor),
            content.topAnchor.constraint(equalTo: blackoutBanner.bottomAnchor, constant: BBUIKitTokens.panelGap),
            content.bottomAnchor.constraint(equalTo: view.safeAreaLayoutGuide.bottomAnchor, constant: -BBUIKitTokens.outerMargin),
        ])
        select(.override)
        render(state: state)
    }

    func render(state: RemoteLiveStateV2) {
        self.state = state
        guard isViewLoaded else { return }
        header.render(state: state)
        blackoutBanner.isHidden = !state.overrides.blackout
        blackoutHeight.constant = state.overrides.blackout ? 28 : 0
        currentSurface?.render(state: state)
    }

    func releaseMomentariesForDismissal() { actions.releaseMomentaries(reason: "UIKit root dismissed") }

    private func select(_ tab: BBRemoteTab) {
        if selectedTab != tab { actions.releaseMomentaries(reason: "UIKit tab changed") }
        selectedTab = tab
        header.select(tab)
        currentSurface?.removeFromSuperview()
        guard let surface = surfaces[tab] else { return }
        content.addSubview(surface)
        surface.bbPinEdges(to: content)
        currentSurface = surface
        surface.render(state: state)
    }
}

@MainActor
private protocol BBRemoteStateRendering: AnyObject {
    func render(state: RemoteLiveStateV2)
}

private final class BBConsoleHeaderView: UIView {
    private let actions: BBRemoteActionBridge
    private let connectionDot = UIView()
    private let connectionLabel = UILabel()
    private let targetLabel = UILabel()
    private var tabButtons: [BBRemoteTab: BBHardwareButton] = [:]
    var onSelectTab: ((BBRemoteTab) -> Void)?

    init(actions: BBRemoteActionBridge) {
        self.actions = actions
        super.init(frame: .zero)
        backgroundColor = BBUIKitTokens.panelRaised
        layer.cornerRadius = BBUIKitTokens.panelCornerRadius
        layer.borderWidth = 1
        layer.borderColor = BBUIKitTokens.border.cgColor

        let brand = UILabel()
        brand.text = "▣  BEATBEAM REMOTE"
        brand.font = .systemFont(ofSize: 19, weight: .bold)
        brand.textColor = .white
        brand.accessibilityLabel = "BeatBeam Remote"
        brand.widthAnchor.constraint(equalToConstant: 250).isActive = true

        let tabs = UIStackView()
        tabs.axis = .horizontal; tabs.spacing = 7; tabs.distribution = .fillEqually
        for tab in BBRemoteTab.allCases {
            let button = BBHardwareButton(title: tab.rawValue, accessibilityLabel: "Open \(tab.rawValue)")
            button.widthAnchor.constraint(equalToConstant: 126).isActive = true
            button.addAction(UIAction { [weak self] _ in self?.onSelectTab?(tab) }, for: .touchUpInside)
            tabs.addArrangedSubview(button); tabButtons[tab] = button
        }

        connectionDot.layer.cornerRadius = 5
        connectionDot.widthAnchor.constraint(equalToConstant: 10).isActive = true
        connectionDot.heightAnchor.constraint(equalToConstant: 10).isActive = true
        connectionLabel.font = BBUIKitTokens.labelFont(11)
        connectionLabel.textColor = .white
        targetLabel.font = BBUIKitTokens.labelFont(9)
        targetLabel.textColor = BBUIKitTokens.secondary
        let labels = UIStackView(arrangedSubviews: [connectionLabel, targetLabel])
        labels.axis = .vertical; labels.spacing = 1
        let connection = UIStackView(arrangedSubviews: [connectionDot, labels])
        connection.axis = .horizontal; connection.alignment = .center; connection.spacing = 8
        connection.widthAnchor.constraint(greaterThanOrEqualToConstant: 172).isActive = true

        let qr = BBHardwareButton(title: "⌗", accessibilityLabel: "Scan pairing QR")
        qr.setTitle(nil, for: .normal)
        qr.setImage(UIImage(systemName: "qrcode.viewfinder"), for: .normal)
        qr.tintColor = .white
        qr.widthAnchor.constraint(equalToConstant: 46).isActive = true
        qr.addAction(UIAction { [weak self] _ in self?.actions.scanQR() }, for: .touchUpInside)

        let row = UIStackView(arrangedSubviews: [brand, tabs, UIView(), connection, qr])
        row.axis = .horizontal; row.alignment = .center; row.spacing = 12
        addSubview(row); row.bbPinEdges(to: self, insets: UIEdgeInsets(top: 8, left: 14, bottom: 8, right: 10))
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    func select(_ tab: BBRemoteTab) {
        tabButtons.forEach { $0.value.isIlluminated = $0.key == tab; $0.value.activeColor = BBUIKitTokens.warning }
    }

    func render(state: RemoteLiveStateV2) {
        let connected = actions.isConnected
        connectionDot.backgroundColor = connected ? BBUIKitTokens.healthy : BBUIKitTokens.warning
        connectionLabel.text = actions.connectionLabel.uppercased()
        targetLabel.text = state.dmx.connected ? "BEATBEAM BETA · DMX LIVE" : "BEATBEAM BETA · PREVIEW"
        accessibilityLabel = "BeatBeam Remote. Connection \(actions.connectionLabel)"
    }
}

private final class BBOverrideSurface: UIView, BBRemoteStateRendering {
    private let actions: BBRemoteActionBridge
    private let colorPanel = BBPanelView(title: "SINGLE COLORS")
    private let comboPanel = BBPanelView(title: "COLOR COMBINATIONS")
    private let phraseEnergyPanel = BBPanelView(title: "PHRASE / ENERGY")
    private let effectsPanel = BBPanelView(title: "EFFECTS")
    private let safetyPanel = BBPanelView(title: "CONTROL")
    private var colorButtons: [String: BBHardwareButton] = [:]
    private var comboButtons: [String: BBSplitColorComboPad] = [:]
    private var phraseButtons: [String: BBHardwareButton] = [:]
    private var holdButtons: [String: BBHardwareButton] = [:]
    private var cueButtons: [String: BBHardwareButton] = [:]
    private let smokeButton = BBHardwareButton(title: "☁\nSMOKE\nSETUP PENDING", accessibilityLabel: "Smoke unavailable until DMX channels are configured")
    private let energyFader = BBVerticalEnergyFader()
    private let releaseButton = BBHardwareButton(title: "RELEASE ALL")
    private let blackoutButton = BBHardwareButton(title: "BLACKOUT (HOLD)")
    private var capabilitySignature = ""
    private var currentState: RemoteLiveStateV2?

    init(actions: BBRemoteActionBridge) {
        self.actions = actions
        super.init(frame: .zero)
        backgroundColor = BBUIKitTokens.background
        smokeButton.isEnabled = false
        smokeButton.alpha = 0.68
        blackoutButton.activeColor = BBUIKitTokens.danger
        blackoutButton.normalFaceColor = BBUIKitTokens.danger.withAlphaComponent(0.22)
        releaseButton.addAction(UIAction { [weak self] _ in self?.actions.perform("release_all") }, for: .touchUpInside)
        blackoutButton.addAction(UIAction { [weak self] _ in
            guard let self, let state = self.currentState else { return }
            self.actions.perform(state.overrides.blackout ? "blackout_off" : "blackout_on")
        }, for: .touchUpInside)
        energyFader.addAction(UIAction { [weak self] _ in
            guard let self else { return }
            let id = self.energyFader.level.id
            if (self.currentState?.overrides.energy ?? "none") != id { self.actions.perform("set_energy", value: id) }
        }, for: .valueChanged)
        buildFixedLayout()
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    private func buildFixedLayout() {
        let bottomRight = UIStackView(arrangedSubviews: [effectsPanel, safetyPanel])
        bottomRight.axis = .vertical; bottomRight.spacing = BBUIKitTokens.panelGap
        safetyPanel.heightAnchor.constraint(equalToConstant: 61).isActive = true
        let bottom = UIStackView(arrangedSubviews: [phraseEnergyPanel, bottomRight])
        bottom.axis = .horizontal; bottom.spacing = BBUIKitTokens.panelGap
        let main = UIStackView(arrangedSubviews: [colorPanel, comboPanel, bottom])
        main.axis = .vertical; main.spacing = BBUIKitTokens.panelGap
        addSubview(main); main.bbPinEdges(to: self)
        NSLayoutConstraint.activate([
            phraseEnergyPanel.widthAnchor.constraint(equalTo: widthAnchor, multiplier: 0.225),
            colorPanel.heightAnchor.constraint(equalTo: heightAnchor, multiplier: 0.265),
            comboPanel.heightAnchor.constraint(equalTo: heightAnchor, multiplier: 0.205),
        ])

        let safety = UIStackView(arrangedSubviews: [releaseButton, blackoutButton])
        safety.axis = .horizontal; safety.spacing = BBUIKitTokens.controlGap; safety.distribution = .fillEqually
        safetyPanel.contentView.addSubview(safety); safety.bbPinEdges(to: safetyPanel.contentView)
    }

    func render(state: RemoteLiveStateV2) {
        currentState = state
        let signature = (["auto"] + state.control.colors.map(\.id) + (state.control.colorCombinations ?? []).map(\.id) + state.control.phrases.map(\.id) + state.control.momentaryEffects.map(\.id) + state.control.cueShots.map(\.id)).joined(separator: "|")
        if signature != capabilitySignature { capabilitySignature = signature; rebuildCapabilityControls(state: state) }

        colorButtons.forEach { id, button in
            button.isIlluminated = id == "auto" ? (state.overrides.color == nil && state.overrides.colorCombo == nil) : state.overrides.color == id
        }
        comboButtons.forEach { id, button in button.isIlluminated = state.overrides.colorCombo == id }
        phraseButtons.forEach { id, button in button.isIlluminated = id == "none" ? state.overrides.phrase == nil : state.overrides.phrase == id }
        holdButtons.forEach { id, button in button.isIlluminated = state.overrides.momentaryEffects.contains(id) || actions.isMomentaryEngaged(id) }
        let level = BBVerticalEnergyFader.Level(rawValue: ["low": 1, "mid": 2, "high": 3][state.overrides.energy ?? ""] ?? 0) ?? .automatic
        if !energyFader.isTracking { energyFader.set(level: level, sendEvent: false) }
        blackoutButton.isIlluminated = state.overrides.blackout
        blackoutButton.setTitle(state.overrides.blackout ? "RELEASE BLACKOUT" : "BLACKOUT (HOLD)", for: .normal)
    }

    private func rebuildCapabilityControls(state: RemoteLiveStateV2) {
        colorButtons.removeAll(); comboButtons.removeAll(); phraseButtons.removeAll(); holdButtons.removeAll(); cueButtons.removeAll()
        colorPanel.contentView.subviews.forEach { $0.removeFromSuperview() }
        comboPanel.contentView.subviews.forEach { $0.removeFromSuperview() }
        phraseEnergyPanel.contentView.subviews.forEach { $0.removeFromSuperview() }
        effectsPanel.contentView.subviews.forEach { $0.removeFromSuperview() }

        let colorOrder = ["auto", "red", "yellow", "green", "lime", "purple", "pink", "cyan", "orange", "blue", "white", "rainbow"]
        var options = Dictionary(uniqueKeysWithValues: state.control.colors.map { ($0.id, $0.label) })
        options["auto"] = "Auto"; options["rainbow"] = options["rainbow"] ?? "Rainbow"
        var colorPads: [UIView] = []
        for id in colorOrder {
            let button = BBColorPad(title: (options[id] ?? id).uppercased(), color: bbColor(id == "auto" ? "gray" : id))
            button.addAction(UIAction { [weak self] _ in self?.actions.perform("set_color", value: id == "auto" ? "none" : id) }, for: .touchUpInside)
            colorButtons[id] = button; colorPads.append(button)
        }
        let grid = makeGrid(colorPads, columns: 6)
        let colorsAndSmoke = UIStackView(arrangedSubviews: [grid, smokeButton])
        colorsAndSmoke.axis = .horizontal; colorsAndSmoke.spacing = BBUIKitTokens.controlGap
        smokeButton.widthAnchor.constraint(equalToConstant: 120).isActive = true
        colorPanel.contentView.addSubview(colorsAndSmoke); colorsAndSmoke.bbPinEdges(to: colorPanel.contentView)

        let combos = state.control.colorCombinations ?? []
        var comboPads: [UIView] = []
        for combo in combos {
            let button = BBSplitColorComboPad(title: combo.label.uppercased(), first: bbColor(combo.colors.first ?? ""), second: bbColor(combo.colors.dropFirst().first ?? ""))
            button.isAvailable = combo.available
            if !combo.available { button.accessibilityLabel = "\(combo.label), \(combo.reasonIfUnavailable ?? "unavailable")" }
            button.addAction(UIAction { [weak self] _ in self?.actions.perform("set_color_combo", value: combo.id) }, for: .touchUpInside)
            comboButtons[combo.id] = button; comboPads.append(button)
        }
        let comboGrid = makeGrid(comboPads, columns: 8)
        comboPanel.contentView.addSubview(comboGrid); comboGrid.bbPinEdges(to: comboPanel.contentView)

        var phrasePads: [UIView] = []
        let phraseAuto = BBHardwareButton(title: "AUTO", accessibilityLabel: "Automatic phrase")
        phraseAuto.addAction(UIAction { [weak self] _ in self?.actions.perform("set_phrase", value: "none") }, for: .touchUpInside)
        phraseButtons["none"] = phraseAuto; phrasePads.append(phraseAuto)
        for phrase in state.control.phrases {
            let button = BBHardwareButton(title: phrase.label.uppercased(), accessibilityLabel: "Phrase \(phrase.label)")
            button.addAction(UIAction { [weak self] _ in self?.actions.perform("set_phrase", value: phrase.id) }, for: .touchUpInside)
            phraseButtons[phrase.id] = button; phrasePads.append(button)
        }
        let phraseGrid = makeGrid(phrasePads, columns: 2)
        let phraseEnergy = UIStackView(arrangedSubviews: [phraseGrid, energyFader])
        phraseEnergy.axis = .horizontal; phraseEnergy.spacing = BBUIKitTokens.controlGap; phraseEnergy.distribution = .fill
        energyFader.widthAnchor.constraint(equalToConstant: 128).isActive = true
        phraseEnergyPanel.contentView.addSubview(phraseEnergy); phraseEnergy.bbPinEdges(to: phraseEnergyPanel.contentView)

        let holds = state.control.momentaryEffects.map { effect -> UIView in
            if effect.isAvailable {
                let button = BBHardwareButton(title: effect.label.uppercased(), accessibilityLabel: "Hold \(effect.label)")
                button.addAction(UIAction { [weak self] _ in self?.actions.beginMomentary(effect.id) }, for: .touchDown)
                button.addAction(UIAction { [weak self] _ in self?.actions.endMomentary(effect.id) }, for: [.touchUpInside, .touchUpOutside, .touchCancel])
                holdButtons[effect.id] = button
                return button
            }
            let unavailable = BBHardwareButton(title: "\(effect.label.uppercased())\nUNAVAILABLE")
            unavailable.isEnabled = false
            return unavailable
        }
        let cues = state.control.cueShots.map { effect -> UIView in
            let button = BBHardwareButton(title: effect.label.uppercased(), accessibilityLabel: "One-shot \(effect.label)")
            button.isEnabled = effect.isAvailable
            button.addAction(UIAction { [weak self] _ in self?.actions.perform("trigger_cue", value: effect.id) }, for: .touchUpInside)
            cueButtons[effect.id] = button
            return button
        }
        let holdGrid = makeGrid(holds, columns: max(1, holds.count))
        let cueGrid = makeGrid(cues, columns: max(1, cues.count))
        let effects = UIStackView(arrangedSubviews: [BBSectionHeader("HOLD EFFECTS"), holdGrid, BBSectionHeader("ONE-SHOT EFFECTS"), cueGrid])
        effects.axis = .vertical; effects.spacing = BBUIKitTokens.compactGap; effects.distribution = .fill
        effectsPanel.contentView.addSubview(effects); effects.bbPinEdges(to: effectsPanel.contentView)
        holdGrid.heightAnchor.constraint(equalTo: cueGrid.heightAnchor, multiplier: 1.20).isActive = true
    }
}

private final class BBLiveSurface: UIView, BBRemoteStateRendering {
    private let actions: BBRemoteActionBridge
    private let nowPanel = BBPanelView(title: "NOW PLAYING")
    private let showPanel = BBPanelView(title: "SHOW NOW")
    private let outputPanel = BBPanelView(title: "RENDERED OUTPUT")
    private let warningsPanel = BBPanelView(title: "ACTIVE WARNINGS")
    private let track = BBValueReadout(title: "TRACK")
    private let artist = BBValueReadout(title: "ARTIST")
    private let deck = BBValueReadout(title: "DECK")
    private let bpm = BBValueReadout(title: "BPM")
    private let beat = BBValueReadout(title: "BEAT")
    private let bar = BBValueReadout(title: "BAR")
    private let time = BBValueReadout(title: "TIME")
    private let mode = BBValueReadout(title: "PRODUCTION MODE")
    private let frameSourceReadout = BBValueReadout(title: "ACTUAL FRAME SOURCE")
    private let music = BBValueReadout(title: "MUSICAL STATE")
    private let override = BBValueReadout(title: "MANUAL OVERRIDE")
    private let dmx = BBStatusIndicator(title: "OUTPUT")
    private let fixtureCount = BBValueReadout(title: "FIXTURES")
    private let fixtureGrid = UIStackView()
    private let warnings = UILabel()

    init(actions: BBRemoteActionBridge) {
        self.actions = actions
        super.init(frame: .zero)
        backgroundColor = BBUIKitTokens.background
        buildLayout()
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    private func buildLayout() {
        let primaryTrack = UIStackView(arrangedSubviews: [track, artist]); primaryTrack.axis = .vertical; primaryTrack.spacing = 6
        let metrics = UIStackView(arrangedSubviews: [deck, bpm, beat, bar, time]); metrics.axis = .horizontal; metrics.spacing = 18; metrics.distribution = .fillEqually
        let now = UIStackView(arrangedSubviews: [primaryTrack, metrics]); now.axis = .horizontal; now.spacing = 18
        primaryTrack.widthAnchor.constraint(equalTo: now.widthAnchor, multiplier: 0.50).isActive = true
        nowPanel.contentView.addSubview(now); now.bbPinEdges(to: nowPanel.contentView)

        let show = UIStackView(arrangedSubviews: [mode, frameSourceReadout, music, override]); show.axis = .vertical; show.spacing = 12; show.distribution = .fillEqually
        showPanel.contentView.addSubview(show); show.bbPinEdges(to: showPanel.contentView)

        fixtureGrid.axis = .vertical; fixtureGrid.spacing = BBUIKitTokens.controlGap; fixtureGrid.distribution = .fillEqually
        let outputTop = UIStackView(arrangedSubviews: [dmx, UIView(), fixtureCount]); outputTop.axis = .horizontal; outputTop.spacing = 10
        let output = UIStackView(arrangedSubviews: [outputTop, fixtureGrid]); output.axis = .vertical; output.spacing = 12
        outputPanel.contentView.addSubview(output); output.bbPinEdges(to: outputPanel.contentView)

        warnings.font = BBUIKitTokens.labelFont(11); warnings.textColor = BBUIKitTokens.warning; warnings.numberOfLines = 2
        warningsPanel.contentView.addSubview(warnings); warnings.bbPinEdges(to: warningsPanel.contentView)

        let middle = UIStackView(arrangedSubviews: [showPanel, outputPanel]); middle.axis = .horizontal; middle.spacing = BBUIKitTokens.panelGap
        showPanel.widthAnchor.constraint(equalTo: middle.widthAnchor, multiplier: 0.34).isActive = true
        let main = UIStackView(arrangedSubviews: [nowPanel, middle, warningsPanel]); main.axis = .vertical; main.spacing = BBUIKitTokens.panelGap
        nowPanel.heightAnchor.constraint(equalToConstant: 105).isActive = true
        warningsPanel.heightAnchor.constraint(equalToConstant: 68).isActive = true
        addSubview(main); main.bbPinEdges(to: self)
    }

    func render(state: RemoteLiveStateV2) {
        track.set(state.track.title ?? "(GEEN TRACK)")
        artist.set(state.track.artist ?? "ONBEKEND")
        deck.set(state.track.activeDeck.map(String.init) ?? "—")
        bpm.set(state.track.bpm.map { String(format: "%.1f", $0) } ?? "—")
        beat.set(state.track.beat.map(String.init) ?? "—")
        bar.set(state.track.bar.map(String.init) ?? "—")
        time.set(bbTimestamp(state.track.positionMilliseconds))
        mode.set(bbProductionLabel(state.show.configuredProductionMode), color: BBUIKitTokens.accent)
        let frameTone = state.show.fallbackActive ? BBUIKitTokens.warning : (state.show.dynamicComposerActive ? BBUIKitTokens.healthy : .white)
        frameSourceReadout.set(bbFrameLabel(state.show.physicalFrameSource) + (state.show.fallbackActive ? " · FALLBACK" : ""), color: frameTone)
        let musical = state.musicalState.eventEnvelope.active ? (state.musicalState.eventEnvelope.eventType ?? state.musicalState.eventEnvelope.phase ?? "EVENT") : (state.musicalState.section ?? state.musicalState.currentRme?.type ?? "STEADY")
        music.set(musical.uppercased())
        let summary = ([state.overrides.colorCombo, state.overrides.color, state.overrides.phrase, state.overrides.energy].compactMap { $0 } + state.overrides.momentaryEffects)
        override.set(summary.isEmpty ? "AUTOMATIC" : summary.joined(separator: " · ").uppercased(), color: summary.isEmpty ? BBUIKitTokens.secondary : BBUIKitTokens.warning)
        dmx.set(value: state.dmx.connected ? "PHYSICAL DMX" : "PREVIEW / NO PHYSICAL DMX", healthy: state.dmx.connected, warning: !state.dmx.connected)
        fixtureCount.set("\(state.output?.fixtures.count ?? 0)")
        rebuildFixtureGrid(state.output?.fixtures ?? [], blackout: state.output?.blackout == true)
        warnings.text = state.warnings.isEmpty ? "NO ACTIVE WARNINGS" : state.warnings.prefix(3).map { "● \($0.message)" }.joined(separator: "   ")
        warnings.textColor = state.warnings.isEmpty ? BBUIKitTokens.healthy : BBUIKitTokens.warning
    }

    private func rebuildFixtureGrid(_ fixtures: [RemoteOutputFixture], blackout: Bool) {
        fixtureGrid.arrangedSubviews.forEach { $0.removeFromSuperview() }
        let columns = 6
        for start in stride(from: 0, to: max(fixtures.count, 1), by: columns) {
            let row = UIStackView(); row.axis = .horizontal; row.spacing = BBUIKitTokens.controlGap; row.distribution = .fillEqually
            let slice = fixtures.isEmpty ? [] : Array(fixtures[start..<min(start + columns, fixtures.count)])
            for fixture in slice { row.addArrangedSubview(BBFixtureTile(fixture: fixture, blackout: blackout)) }
            for _ in slice.count..<columns { row.addArrangedSubview(UIView()) }
            fixtureGrid.addArrangedSubview(row)
        }
    }
}

private final class BBFixtureTile: UIView {
    init(fixture: RemoteOutputFixture, blackout: Bool) {
        super.init(frame: .zero)
        let swatch = UIView()
        let white = CGFloat(fixture.white)
        let color = blackout ? UIColor.black : UIColor(red: min(255, CGFloat(fixture.red) + white) / 255, green: min(255, CGFloat(fixture.green) + white) / 255, blue: min(255, CGFloat(fixture.blue) + white) / 255, alpha: max(0.20, CGFloat(fixture.dimmer) / 255))
        swatch.backgroundColor = color
        swatch.layer.cornerRadius = 4; swatch.layer.borderWidth = 1; swatch.layer.borderColor = UIColor.white.withAlphaComponent(0.22).cgColor
        swatch.heightAnchor.constraint(greaterThanOrEqualToConstant: 46).isActive = true
        let title = UILabel(); title.text = fixture.label.uppercased(); title.font = BBUIKitTokens.labelFont(10); title.textColor = .white; title.textAlignment = .center; title.adjustsFontSizeToFitWidth = true
        let value = UILabel(); value.text = blackout ? "BLACKOUT" : "DIM \(fixture.dimmer) · RGB \(fixture.red)/\(fixture.green)/\(fixture.blue)"; value.font = BBUIKitTokens.labelFont(8); value.textColor = BBUIKitTokens.secondary; value.textAlignment = .center; value.adjustsFontSizeToFitWidth = true
        let stack = UIStackView(arrangedSubviews: [swatch, title, value]); stack.axis = .vertical; stack.spacing = 5
        addSubview(stack); stack.bbPinEdges(to: self, insets: UIEdgeInsets(top: 7, left: 7, bottom: 7, right: 7))
        backgroundColor = BBUIKitTokens.recessed; layer.cornerRadius = 5; layer.borderWidth = 1; layer.borderColor = BBUIKitTokens.border.cgColor
        isAccessibilityElement = true; accessibilityLabel = "\(fixture.label), dimmer \(fixture.dimmer), red \(fixture.red), green \(fixture.green), blue \(fixture.blue)"
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }
}

private final class BBStatusSurface: UIView, BBRemoteStateRendering {
    private let actions: BBRemoteActionBridge
    private let connectionPanel = BBPanelView(title: "CONNECTION")
    private let healthPanel = BBPanelView(title: "SYSTEM HEALTH")
    private let runtimePanel = BBPanelView(title: "OUTPUT / RUNTIME")
    private let stateValue = BBStatusIndicator(title: "STATE")
    private let hostValue = BBStatusIndicator(title: "HOST")
    private let protocolValue = BBStatusIndicator(title: "PROTOCOL / SCOPE")
    private let serverStatus = BBStatusIndicator(title: "SERVER")
    private let pairingStatus = BBStatusIndicator(title: "PAIRING")
    private let backend = BBStatusIndicator(title: "BACKEND")
    private let renderer = BBStatusIndicator(title: "RENDERER")
    private let vdj = BBStatusIndicator(title: "VIRTUALDJ")
    private let analyzer = BBStatusIndicator(title: "SONGANALYZER")
    private let dmx = BBStatusIndicator(title: "DMX")
    private let transport = BBStatusIndicator(title: "TRANSPORT")
    private let output = BBStatusIndicator(title: "OUTPUT")
    private let frameSource = BBStatusIndicator(title: "FRAME SOURCE")
    private let frameSequence = BBStatusIndicator(title: "RENDER FRAME")
    private let fixtureCount = BBStatusIndicator(title: "FIXTURE COUNT")
    private let failures = BBStatusIndicator(title: "DISPATCH FAILURES")
    private let revision = BBStatusIndicator(title: "REMOTE REVISION")
    private let rendererState = BBStatusIndicator(title: "RENDER STATE")
    private let outputMode = BBStatusIndicator(title: "OUTPUT MODE")
    private let fallbackReason = BBStatusIndicator(title: "FALLBACK REASON")
    private let lastError = BBStatusIndicator(title: "LAST OUTPUT ERROR")

    init(actions: BBRemoteActionBridge) {
        self.actions = actions
        super.init(frame: .zero)
        backgroundColor = BBUIKitTokens.background
        buildLayout()
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    private func buildLayout() {
        let reconnect = BBHardwareButton(title: "RECONNECT", accessibilityLabel: "Reconnect to BeatBeam")
        let qr = BBHardwareButton(title: "SCAN QR / RE-PAIR", accessibilityLabel: "Scan QR or pair again")
        reconnect.addAction(UIAction { [weak self] _ in self?.actions.reconnect() }, for: .touchUpInside)
        qr.addAction(UIAction { [weak self] _ in self?.actions.scanQR() }, for: .touchUpInside)
        let actionsRow = UIStackView(arrangedSubviews: [reconnect, qr]); actionsRow.axis = .horizontal; actionsRow.spacing = BBUIKitTokens.controlGap; actionsRow.distribution = .fillEqually
        let connection = UIStackView(arrangedSubviews: [stateValue, hostValue, protocolValue, serverStatus, pairingStatus, actionsRow]); connection.axis = .vertical; connection.spacing = 10; connection.distribution = .fillEqually
        connectionPanel.contentView.addSubview(connection); connection.bbPinEdges(to: connectionPanel.contentView)

        let health = UIStackView(arrangedSubviews: [backend, renderer, vdj, analyzer, dmx, transport, output]); health.axis = .vertical; health.spacing = BBUIKitTokens.controlGap; health.distribution = .fillEqually
        healthPanel.contentView.addSubview(health); health.bbPinEdges(to: healthPanel.contentView)

        let runtime = UIStackView(arrangedSubviews: [frameSource, rendererState, outputMode, frameSequence, fixtureCount, failures, revision, fallbackReason, lastError]); runtime.axis = .vertical; runtime.spacing = 10; runtime.distribution = .fillEqually
        runtimePanel.contentView.addSubview(runtime); runtime.bbPinEdges(to: runtimePanel.contentView)

        let main = UIStackView(arrangedSubviews: [connectionPanel, healthPanel, runtimePanel]); main.axis = .horizontal; main.spacing = BBUIKitTokens.panelGap; main.distribution = .fillEqually
        addSubview(main); main.bbPinEdges(to: self)
    }

    func render(state: RemoteLiveStateV2) {
        stateValue.set(value: actions.connectionLabel.uppercased(), healthy: actions.isConnected, warning: !actions.isConnected)
        hostValue.set(value: actions.hostLabel, healthy: actions.isConnected, warning: !actions.isConnected)
        protocolValue.set(value: "V\(state.connection.protocolVersion) · \(state.control.scope)", healthy: state.connection.compatible, warning: !state.connection.compatible)
        serverStatus.set(value: state.connection.server ?? "BEATBEAM", healthy: actions.isConnected)
        pairingStatus.set(value: actions.isConnected ? "SCOPED / AUTHENTICATED" : "RE-PAIR REQUIRED", healthy: actions.isConnected, warning: !actions.isConnected)
        backend.set(value: actions.isConnected ? "CONNECTED" : "OFFLINE", healthy: actions.isConnected)
        renderer.set(value: state.dmx.rendererHealthy ? "HEALTHY" : "UNHEALTHY", healthy: state.dmx.rendererHealthy)
        vdj.set(value: state.track.transportFresh ? "CONNECTED" : "STALE", healthy: state.track.transportFresh, warning: !state.track.transportFresh)
        let ready = state.track.readiness?.uppercased() == "READY"
        analyzer.set(value: state.track.readiness ?? "UNAVAILABLE", healthy: ready, warning: !ready)
        dmx.set(value: state.dmx.connected ? "CONNECTED" : "DISCONNECTED", healthy: state.dmx.connected, warning: !state.dmx.connected)
        transport.set(value: state.track.transportFresh ? "FRESH" : "STALE", healthy: state.track.transportFresh, warning: !state.track.transportFresh)
        output.set(value: state.dmx.physicalOutputAvailable ? "PHYSICAL" : (state.dmx.renderedOutputAvailable == true ? "PREVIEW" : "UNAVAILABLE"), healthy: state.dmx.renderedOutputAvailable == true, warning: !state.dmx.physicalOutputAvailable)
        frameSource.set(value: bbFrameLabel(state.show.physicalFrameSource) + (state.show.fallbackActive ? " · FALLBACK" : ""), healthy: !state.show.fallbackActive, warning: state.show.fallbackActive)
        rendererState.set(value: state.dmx.rendererHealthy ? (state.dmx.rendererActive ? "ACTIVE / HEALTHY" : "READY / INACTIVE") : "UNHEALTHY", healthy: state.dmx.rendererHealthy)
        outputMode.set(value: state.dmx.connected ? "PHYSICAL DMX" : "PREVIEW / NO DMX", healthy: state.dmx.connected, warning: !state.dmx.connected)
        frameSequence.set(value: state.dmx.frameSequence.map(String.init) ?? "—", healthy: state.dmx.frameSequence != nil)
        fixtureCount.set(value: "\(state.output?.fixtures.count ?? 0)", healthy: state.output?.renderedAvailable == true)
        failures.set(value: "\(state.dmx.dispatchFailures ?? 0)", healthy: (state.dmx.dispatchFailures ?? 0) == 0)
        revision.set(value: "\(state.stateRevision) / EVENT \(state.eventSequence)", healthy: true)
        fallbackReason.set(value: state.show.fallbackActive ? (state.show.fallbackReason ?? "ACTIVE") : "NONE", healthy: !state.show.fallbackActive, warning: state.show.fallbackActive)
        lastError.set(value: state.dmx.lastError ?? "NONE", healthy: state.dmx.lastError == nil)
    }
}

private final class BBSettingsSurface: UIView, BBRemoteStateRendering {
    private let actions: BBRemoteActionBridge
    private weak var presenter: UIViewController?
    private let connectionPanel = BBPanelView(title: "CONNECTION PREFERENCES")
    private let remotePanel = BBPanelView(title: "APP / REMOTE")
    private let productionPanel = BBPanelView(title: "PRODUCTION MODE")
    private let host = BBStatusIndicator(title: "HOST")
    private let connection = BBStatusIndicator(title: "AUTOMATIC RECONNECT")
    private let keepAwake = BBStatusIndicator(title: "KEEP AWAKE")
    private let pairing = BBStatusIndicator(title: "PAIRING")
    private let appVersion = BBStatusIndicator(title: "APP VERSION")
    private let protocolVersion = BBStatusIndicator(title: "REMOTE PROTOCOL")
    private let server = BBStatusIndicator(title: "TARGET SERVER")
    private let scope = BBStatusIndicator(title: "PAIRING SCOPE")
    private let compatibility = BBStatusIndicator(title: "COMPATIBILITY")
    private let currentMode = BBStatusIndicator(title: "CURRENT MODE")
    private let frameSource = BBStatusIndicator(title: "ACTUAL FRAME SOURCE")
    private let composerEligibility = BBStatusIndicator(title: "DYNAMIC ELIGIBILITY")
    private let fallback = BBStatusIndicator(title: "FALLBACK")
    private let baselineAvailable = BBStatusIndicator(title: "BASELINE SAFETY")

    init(actions: BBRemoteActionBridge, presenter: UIViewController) {
        self.actions = actions; self.presenter = presenter
        super.init(frame: .zero)
        backgroundColor = BBUIKitTokens.background
        buildLayout()
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    private func buildLayout() {
        let reconnect = BBHardwareButton(title: "RECONNECT NOW", accessibilityLabel: "Reconnect now")
        let pairingButton = BBHardwareButton(title: "PAIR / SCAN QR", accessibilityLabel: "Pair or scan QR")
        reconnect.addAction(UIAction { [weak self] _ in self?.actions.reconnect() }, for: .touchUpInside)
        pairingButton.addAction(UIAction { [weak self] _ in self?.actions.showPairing() }, for: .touchUpInside)
        let connectionActions = UIStackView(arrangedSubviews: [reconnect, pairingButton]); connectionActions.axis = .horizontal; connectionActions.spacing = BBUIKitTokens.controlGap; connectionActions.distribution = .fillEqually
        connectionActions.heightAnchor.constraint(equalToConstant: 62).isActive = true
        let connectionStates = UIStackView(arrangedSubviews: [host, keepAwake, connection, pairing]); connectionStates.axis = .vertical; connectionStates.spacing = 10; connectionStates.distribution = .fillEqually
        let connectionStack = UIStackView(arrangedSubviews: [connectionStates, connectionActions]); connectionStack.axis = .vertical; connectionStack.spacing = 10
        connectionPanel.contentView.addSubview(connectionStack); connectionStack.bbPinEdges(to: connectionPanel.contentView)

        let forget = BBHardwareButton(title: "FORGET THIS PAIRING", accessibilityLabel: "Forget this pairing")
        forget.activeColor = BBUIKitTokens.danger; forget.normalFaceColor = BBUIKitTokens.danger.withAlphaComponent(0.20)
        forget.addAction(UIAction { [weak self] _ in self?.confirmForget() }, for: .touchUpInside)
        forget.heightAnchor.constraint(equalToConstant: 62).isActive = true
        let remoteStates = UIStackView(arrangedSubviews: [appVersion, protocolVersion, server, scope, compatibility]); remoteStates.axis = .vertical; remoteStates.spacing = 10; remoteStates.distribution = .fillEqually
        let remote = UIStackView(arrangedSubviews: [remoteStates, forget]); remote.axis = .vertical; remote.spacing = 10
        remotePanel.contentView.addSubview(remote); remote.bbPinEdges(to: remotePanel.contentView)

        let baseline = BBHardwareButton(title: "REVERT TO BASELINE", accessibilityLabel: "Revert production to Baseline")
        let dynamic = BBHardwareButton(title: "ENABLE DYNAMIC COMPOSER", accessibilityLabel: "Enable Dynamic Composer")
        dynamic.activeColor = BBUIKitTokens.accent
        baseline.addAction(UIAction { [weak self] _ in self?.confirmProduction(title: "Revert to Baseline?", message: "The physical frame returns to the established baseline show. Transport is unchanged.", actionTitle: "Revert", action: "revert_baseline", destructive: true) }, for: .touchUpInside)
        dynamic.addAction(UIAction { [weak self] _ in self?.confirmProduction(title: "Enable Dynamic Composer?", message: "Enable Dynamic Composer deliberately for the current production show.", actionTitle: "Enable Dynamic", action: "enable_dynamic_composer", destructive: false) }, for: .touchUpInside)
        let productionActions = UIStackView(arrangedSubviews: [baseline, dynamic]); productionActions.axis = .vertical; productionActions.spacing = BBUIKitTokens.controlGap; productionActions.distribution = .fillEqually
        productionActions.heightAnchor.constraint(equalToConstant: 125).isActive = true
        let productionStates = UIStackView(arrangedSubviews: [currentMode, frameSource, composerEligibility, fallback, baselineAvailable]); productionStates.axis = .vertical; productionStates.spacing = 10; productionStates.distribution = .fillEqually
        let production = UIStackView(arrangedSubviews: [productionStates, productionActions]); production.axis = .vertical; production.spacing = 10
        productionPanel.contentView.addSubview(production); production.bbPinEdges(to: productionPanel.contentView)

        let main = UIStackView(arrangedSubviews: [connectionPanel, remotePanel, productionPanel]); main.axis = .horizontal; main.spacing = BBUIKitTokens.panelGap; main.distribution = .fillEqually
        addSubview(main); main.bbPinEdges(to: self)
    }

    func render(state: RemoteLiveStateV2) {
        host.set(value: actions.hostLabel, healthy: actions.isConnected, warning: !actions.isConnected)
        keepAwake.set(value: "ACTIVE WHILE OPEN", healthy: true)
        connection.set(value: "AUTOMATIC", healthy: true)
        pairing.set(value: actions.isConnected ? "SCOPED / AUTHENTICATED" : "RE-PAIR REQUIRED", healthy: actions.isConnected, warning: !actions.isConnected)
        let version = Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "1.2"
        let build = Bundle.main.infoDictionary?["CFBundleVersion"] as? String ?? "—"
        appVersion.set(value: "\(version) (\(build))", healthy: true)
        protocolVersion.set(value: "REMOTE LIVE STATE V\(state.connection.protocolVersion)", healthy: state.connection.compatible)
        server.set(value: state.connection.server ?? "BEATBEAM", healthy: actions.isConnected)
        scope.set(value: state.control.scope, healthy: state.control.scope == "LIVE_CONTROL")
        compatibility.set(value: state.connection.compatible ? "COMPATIBLE" : "INCOMPATIBLE", healthy: state.connection.compatible)
        currentMode.set(value: bbProductionLabel(state.show.configuredProductionMode), healthy: true)
        frameSource.set(value: bbFrameLabel(state.show.physicalFrameSource), healthy: !state.show.fallbackActive, warning: state.show.fallbackActive)
        composerEligibility.set(value: state.show.dynamicComposerEligible ? "ELIGIBLE" : "NOT ELIGIBLE", healthy: state.show.dynamicComposerEligible, warning: !state.show.dynamicComposerEligible)
        fallback.set(value: state.show.fallbackActive ? (state.show.fallbackReason ?? "ACTIVE") : "INACTIVE", healthy: !state.show.fallbackActive, warning: state.show.fallbackActive)
        baselineAvailable.set(value: state.show.baselineFallbackAvailable ? "AVAILABLE" : "UNAVAILABLE", healthy: state.show.baselineFallbackAvailable)
    }

    private func confirmForget() {
        let alert = UIAlertController(title: "Forget pairing?", message: "This removes the local BeatBeam credential from this iPad.", preferredStyle: .alert)
        alert.addAction(UIAlertAction(title: "Cancel", style: .cancel))
        alert.addAction(UIAlertAction(title: "Forget", style: .destructive) { [weak self] _ in self?.actions.forgetPairing() })
        presenter?.present(alert, animated: true)
    }

    private func confirmProduction(title: String, message: String, actionTitle: String, action: String, destructive: Bool) {
        let alert = UIAlertController(title: title, message: message, preferredStyle: .alert)
        alert.addAction(UIAlertAction(title: "Cancel", style: .cancel))
        alert.addAction(UIAlertAction(title: actionTitle, style: destructive ? .destructive : .default) { [weak self] _ in self?.actions.perform(action) })
        presenter?.present(alert, animated: true)
    }
}

private func makeGrid(_ views: [UIView], columns: Int) -> UIStackView {
    let grid = UIStackView(); grid.axis = .vertical; grid.spacing = BBUIKitTokens.controlGap; grid.distribution = .fillEqually
    guard columns > 0 else { return grid }
    for start in stride(from: 0, to: views.count, by: columns) {
        let row = UIStackView(); row.axis = .horizontal; row.spacing = BBUIKitTokens.controlGap; row.distribution = .fillEqually
        let slice = Array(views[start..<min(start + columns, views.count)])
        slice.forEach(row.addArrangedSubview)
        for _ in slice.count..<columns { row.addArrangedSubview(UIView()) }
        grid.addArrangedSubview(row)
    }
    return grid
}

private func bbProductionLabel(_ value: String) -> String { value == "DYNAMIC_COMPOSER_ENABLED" ? "DYNAMIC COMPOSER" : "BASELINE" }
private func bbFrameLabel(_ value: String) -> String { value == "dynamic_composer" ? "DYNAMIC COMPOSER" : "BASELINE" }
private func bbTimestamp(_ milliseconds: Int?) -> String { guard let milliseconds else { return "—" }; return String(format: "%d:%02d", milliseconds / 60_000, (milliseconds / 1_000) % 60) }
