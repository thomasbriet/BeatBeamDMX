import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class IpadRemoteV2SourceTests(unittest.TestCase):
    def setUp(self):
        self.models = (ROOT / "ipad-remote/BeatBeamRemote/RemoteModels.swift").read_text(encoding="utf-8")
        self.store = (ROOT / "ipad-remote/BeatBeamRemote/RemoteStore.swift").read_text(encoding="utf-8")
        self.view = (ROOT / "ipad-remote/BeatBeamRemote/ContentView.swift").read_text(encoding="utf-8")
        self.app = (ROOT / "ipad-remote/BeatBeamRemote/BeatBeamRemoteApp.swift").read_text(encoding="utf-8")
        self.shell = (ROOT / "ipad-remote/BeatBeamRemote/UIKitApplicationShell.swift").read_text(encoding="utf-8")
        self.uikit = (ROOT / "ipad-remote/BeatBeamRemote/UIKitControlSurface.swift").read_text(encoding="utf-8")
        self.uikit_design = (ROOT / "ipad-remote/BeatBeamRemote/UIKitDesignSystem.swift").read_text(encoding="utf-8")
        self.scanner = (ROOT / "ipad-remote/BeatBeamRemote/QRScannerView.swift").read_text(encoding="utf-8")
        self.info_plist = (ROOT / "ipad-remote/BeatBeamRemote/Info.plist").read_text(encoding="utf-8")
        self.backend = (ROOT / "beatbeam_app.py").read_text(encoding="utf-8")
        self.native = (ROOT / "native/BeatBeamDMXApp.swift").read_text(encoding="utf-8")
        self.parity = (ROOT / "ipad-remote/UIKIT_V1_PARITY.md").read_text(encoding="utf-8")

    def test_v2_dto_is_typed_and_tolerates_additive_server_fields(self):
        for symbol in (
            "struct RemoteLiveStateV2", "let stateRevision: Int", "let eventSequence: Int",
            "struct RemoteShowState", "struct RemoteDmxHealth", "struct RemoteFixtureGroup",
            "struct RemoteOverrideState", "RemoteColorComboCapability", "colorCombinations", "struct RemoteWarning",
        ):
            self.assertIn(symbol, self.models)
        self.assertIn("decoder.keyDecodingStrategy = .convertFromSnakeCase", self.store)

    def test_store_uses_v2_read_endpoints_and_keychain_not_tokenized_urls(self):
        self.assertIn('"/api/remote-v2/state"', self.store)
        self.assertIn('"/api/remote-v2/events"', self.store)
        self.assertIn('"/api/remote-v2/pair"', self.store)
        self.assertIn("SecItemAdd", self.store)
        self.assertIn("REMOTE_READ", self.store)
        self.assertNotIn("URLQueryItem(name: \"token\"", self.store)
        self.assertNotIn('"/api/dmx/update"', self.store)
        self.assertNotIn('"/api/dmx/blackout"', self.store)

    def test_simulator_pairing_fallback_does_not_replace_device_keychain_storage(self):
        self.assertIn("#if targetEnvironment(simulator)", self.store)
        self.assertIn("SimulatorCredential", self.store)
        self.assertIn("UserDefaults.standard.set(value", self.store)
        self.assertIn("#else\n        let data = Data(value.utf8)", self.store)
        self.assertIn("SecItemAdd", self.store)
        self.assertIn("kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly", self.store)

    def test_control_surface_uses_only_scoped_acknowledged_live_commands(self):
        self.assertIn('"/api/remote-v2/control"', self.store)
        self.assertIn("RemoteControlAcknowledgement", self.store)
        self.assertIn("beginMomentary", self.store)
        self.assertIn("releaseActiveMomentaries", self.store)
        self.assertIn("LIVE_CONTROL", self.store)

    def test_momentary_hold_lifecycle_is_single_flight_lease_identified_and_non_modal_for_cleanup(self):
        for symbol in (
            "momentaryStarts", "momentaryLeaseIDs", "momentaryReleasePending",
            "completeMomentaryStart", "releaseMomentary", "renewMomentary",
            '"lease_id"', "suppressBenignMomentaryError",
            "shouldSuppressMomentaryLifecycleError", "momentary effect has no active lease",
        ):
            self.assertIn(symbol, self.store)
        self.assertIn("guard momentaryStarts.insert(effect).inserted else { return }", self.store)
        self.assertIn("if momentaryReleasePending.remove(effect) != nil", self.store)
        self.assertIn("guard outcome.accepted, outcome.momentaryLease?.active == true else", self.store)
        self.assertIn("RemoteMomentaryLease", self.models)

    def test_momentary_holds_use_the_responsive_input_and_control_transport_path(self):
        for symbol in (
            "controlSession", "networkServiceType = .responsiveData",
            "locallyPressedMomentaryEffects", "isMomentaryEngaged",
        ):
            self.assertIn(symbol, self.store)
        self.assertIn("onLongPressGesture(minimumDuration: 0", self.view)
        self.assertIn("store.isMomentaryEngaged(effect.id)", self.view)
        self.assertNotIn("simultaneousGesture(DragGesture", self.view)

    def test_connection_state_and_authoritative_snapshot_reconciliation_exist(self):
        for state in ("notPaired", "connecting", "connected", "reconnecting", "offline", "authFailed", "serverIncompatible"):
            self.assertIn(state, self.store)
        self.assertIn("state.stateRevision > newestRevision", self.store)
        self.assertIn("startEventStream(generation:", self.store)
        self.assertIn("fallbackPollIntervalNanoseconds", self.store)

    def test_decode_and_http_failures_are_diagnostic_and_never_decoded_as_success(self):
        self.assertIn("decodingDiagnostic", self.store)
        self.assertIn("typeMismatch", self.store)
        self.assertIn("codingPath", self.store)
        self.assertIn("RemoteHTTPError, http.statusCode == 401 || http.statusCode == 403", self.store)
        self.assertIn("if http.statusCode == 409", self.store)
        self.assertIn("RemoteControlRejection", self.store)
        self.assertIn("try validateHTTP(http, data: data)", self.store)

    def test_qr_scan_starts_the_complete_pairing_exchange(self):
        self.assertIn("Task { await pair(using: configurationURLText, code: pairingCodeText) }", self.store)

    def test_native_remote_panel_exposes_a_dedicated_tailscale_pairing_route(self):
        # The backend deliberately keeps LAN as the normal preferred route, so
        # the native UI must separately expose the detected overlay URL/QR.
        self.assertIn('@Published var remoteTailscaleURLText = "-"', self.native)
        self.assertIn("remoteTailscaleURLText = remote.tailscaleUrl ?? \"-\"", self.native)
        self.assertIn("func copyTailscaleRemoteURL()", self.native)
        self.assertIn('Text("Tailscale URL")', self.native)
        self.assertIn('label: "Scan with iPad via Tailscale"', self.native)

    def test_fixed_landscape_console_has_exact_tabs_and_no_main_scroll(self):
        for text in ("LIVE", "OVERRIDE", "STATUS", "SETTINGS", "ConsoleTabBar", "ConsoleSurface", "ConsoleHeader", "LiveStatusStrip", "LiveConsole", "OverrideConsole", "StatusConsole", "SettingsConsole"):
            self.assertIn(text, self.view)
        self.assertNotIn("ScrollView", self.view)
        surface = self.view[self.view.index("private struct ConsoleSurface"):self.view.index("private struct ConsoleHeader")]
        self.assertLess(surface.index("ConsoleHeader"), surface.index("LiveStatusStrip"))
        self.assertEqual(1, self.view.count("ConsoleTabBar(selectedTab: $selectedTab)"))
        self.assertIn("if selectedTab != .overrides { LiveStatusStrip(state: state) }", self.view)
        orientations = (ROOT / "ipad-remote/BeatBeamRemote/Info.plist").read_text(encoding="utf-8")
        self.assertIn("UIInterfaceOrientationLandscapeLeft", orientations)
        self.assertIn("UIInterfaceOrientationLandscapeRight", orientations)
        self.assertNotIn("UIInterfaceOrientationPortrait", orientations)

    def test_live_is_observation_only_and_override_contains_existing_controls(self):
        for text in ("NOW PLAYING", "SHOW NOW", "RENDERED OUTPUT", "MODE", "FRAME", "MUSIC", "OVERRIDE"):
            self.assertIn(text, self.view)
        self.assertNotIn("setBlackoutEnabled", self.view)
        self.assertNotIn("setAutoShowEnabled", self.view)
        for symbol in ("SINGLE COLORS", "COLOR COMBINATIONS", "ColorComboMatrix", "ColorComboPad", "gridWidth", "Rainbow", "ENERGY / PHRASE", "vertical fader", "HOLD EFFECTS", "ONE-SHOT EFFECTS", "SmokeSetupPad", "SMOKE", "EffectDeck", "ColorPerformancePadStyle", "HardwarePerformancePadStyle", 'store.perform("set_color_combo"', 'store.perform("release_all")', 'store.perform("blackout_on")'):
            self.assertIn(symbol, self.view)
        override = self.view[self.view.index("private struct OverrideConsole"):self.view.index("private struct ColorPadMatrix")]
        self.assertNotIn("revert_baseline", override)
        self.assertNotIn("enable_dynamic_composer", override)

    def test_override_uses_a_fixed_dense_color_console_with_adjacent_safe_smoke_pad(self):
        override = self.view[self.view.index("private struct OverrideConsole"):self.view.index("private struct PhrasePadMatrix")]
        for symbol in ("OverrideLayout", "colorBankHeight", "comboBankHeight", "let columns = 6", "let columns = 8", "SmokeSetupPad(smoke: state.smoke).frame(width: OverrideLayout.smokeWidth)"):
            self.assertIn(symbol, override)
        self.assertNotIn("ScrollView", override)
        smoke = self.view[self.view.index("private struct SmokeSetupPad"):self.view.index("private struct EffectRow")]
        for symbol in ("store.beginSmokeHold()", "store.endSmokeHold()", "DragGesture(minimumDistance: 0)", ".disabled(smoke?.supported != true)"):
            self.assertIn(symbol, smoke)

    def test_energy_control_is_custom_vertical_fader_with_direct_clamped_drag(self):
        fader = self.view[self.view.index("private struct EnergyFader"):self.view.index("private struct EnergyOverridePanel")]
        for symbol in ("DragGesture(minimumDistance: 0)", "setLevel(for:", "let clamped", "min(max(y, 0), railHeight)", "accessibilityLabel(\"Energy override custom vertical fader\")"):
            self.assertIn(symbol, fader)
        self.assertNotIn("Slider(", fader)

    def test_status_and_settings_keep_reconnect_and_pairing_operational(self):
        for symbol in ("BEATBEAM CONNECTION", "RECONNECT", "SCAN QR", "PAIR / RE-PAIR", "SYSTEM", "VIRTUALDJ", "SONGANALYZER", "CONNECTION PREFERENCES", "FORGET THIS PAIRING", "PRODUCTION MODE", "REVERT TO BASELINE", "ENABLE DYNAMIC COMPOSER"):
            self.assertIn(symbol, self.view)
        self.assertIn("store.showConfiguration = true", self.view)
        self.assertIn("store.showScanner = true", self.view)

    def test_effect_pads_are_backend_capability_driven_and_blackout_is_authoritative(self):
        self.assertIn("struct RemoteEffectCapability", self.models)
        self.assertIn("isAvailable", self.models)
        self.assertIn("isTemporarilyUnavailable", self.models)
        self.assertIn("if effect.isAvailable", self.view)
        self.assertIn("UnavailableEffectPad", self.view)
        self.assertIn("BlackoutAuthorityBanner", self.view)
        self.assertIn("Physical output is blacked out", self.view)
        self.assertIn("Preview remains underlying show intent", self.view)

    def test_uikit_v1_is_default_with_bounded_legacy_swiftui_fallback(self):
        self.assertIn("enum BBRemotePresentationMode", self.uikit)
        self.assertIn("case legacySwiftUI", self.uikit)
        self.assertIn("case uiKitV1", self.uikit)
        self.assertIn("static let current: BBRemotePresentationMode = .uiKitV1", self.uikit)
        self.assertIn("UIKitControlSurfaceHost(store: store, state: state)", self.view)
        self.assertIn("ConsoleSurface(state: state", self.view)
        self.assertIn("BBRemoteApplicationViewController", self.shell)
        self.assertIn("BBRemotePresentationMode.current == .legacySwiftUI", self.shell)
        self.assertIn("UIHostingController(rootView: ContentView().environmentObject(store))", self.shell)

    def test_normal_application_lifecycle_is_full_uikit_and_owns_one_remote_store(self):
        for symbol in (
            "@main", "UIApplicationDelegate", "BeatBeamSceneDelegate", "UIWindowSceneDelegate",
            "private let store = RemoteStore()", "UIWindow(windowScene: windowScene)",
            "BBRemoteApplicationViewController(store: store)", "store.bootstrap()",
            "UIApplication.shared.isIdleTimerDisabled = true", "store.resumePolling()",
            'store.releaseActiveMomentaries(reason: "app backgrounded")', "store.pausePolling()",
        ):
            self.assertIn(symbol, self.app)
        self.assertNotIn("WindowGroup", self.app)
        self.assertNotIn("struct BeatBeamRemoteApp: App", self.app)
        self.assertIn("UISceneConfigurations", self.info_plist)
        self.assertIn("BeatBeamSceneDelegate", self.info_plist)

    def test_usb_transport_is_bounded_versioned_and_routes_through_one_store(self):
        usb = (ROOT / "ipad-remote/BeatBeamRemote/USBTransportPOCListener.swift").read_text(encoding="utf-8")
        for symbol in (
            '"beatbeam-usb-remote-v1"', "maximumFrameBytes = 64 * 1024",
            'case "hello"', 'case "state"', 'case "ack"', 'case "ping"',
            "sendCommand(action:", "pendingAcks", "closeConnection(notify: true)",
        ):
            self.assertIn(symbol, usb)
        for symbol in (
            "enum ActiveTransport", "case lan = \"LAN\"", "case usb = \"USB\"",
            "attachUSBTransport", "sendUSBControl", "usbDisconnected", "connectionLabel",
            "Never retry this command over LAN",
        ):
            self.assertIn(symbol, self.store)
        self.assertIn("store.attachUSBTransport(usbTransportPOCListener)", self.app)

    def test_usb_to_lan_failover_restarts_a_fresh_generation_without_repairing(self):
        for symbol in (
            "restartNetworkTransport", "networkGenerationGate", "restartLAN()",
            "isCurrentNetworkGeneration", "invalidateLAN()",
            "startEventStream(generation: generation)",
            "restartNetworkTransport()\n    }\n\n    private func validate",
        ):
            self.assertIn(symbol, self.store)
        self.assertIn("RemoteTransportGenerationGate", self.models)

    def test_normal_pairing_qr_and_alert_routes_are_uikit(self):
        for symbol in (
            "BBUnpairedViewController", "BBPairingViewController", "BBPairingNavigationController",
            "BBScannerNavigationController", "QRScannerViewController()", "UIAlertController",
            "present(navigation, animated: true)", "store.showConfiguration = false",
            "store.showScanner = false", "navigation.isModalInPresentation = true",
        ):
            self.assertIn(symbol, self.shell)
        self.assertIn("AVCaptureMetadataOutputObjectsDelegate", self.scanner)
        self.assertNotIn("URLSession", self.shell)
        self.assertNotIn('"/api/remote-v2/', self.shell)

    def test_uikit_uses_one_remotestore_action_bridge_and_no_network_stack(self):
        for symbol in (
            "final class BBRemoteActionBridge", "private unowned let store: RemoteStore",
            "store.perform(action, value: value)", "store.beginMomentary(effect)",
            "store.endMomentary(effect)", "store.reconnect()", "store.showScanner = true",
            "@ObservedObject var store: RemoteStore", "controller.render(state: state)",
        ):
            self.assertIn(symbol, self.uikit)
        for forbidden in ("URLSession", '"/api/remote-v2/', "Timer.scheduledTimer"):
            self.assertNotIn(forbidden, self.uikit)

    def test_uikit_has_one_fixed_top_shell_and_all_four_surfaces_without_scrolling(self):
        for symbol in (
            "BBConsoleHeaderView", 'case live = "LIVE"', 'case override = "OVERRIDE"',
            'case status = "STATUS"', 'case settings = "SETTINGS"',
            "BBLiveSurface", "BBOverrideSurface", "BBStatusSurface", "BBSettingsSurface",
        ):
            self.assertIn(symbol, self.uikit)
        self.assertEqual(1, self.uikit.count("BBConsoleHeaderView(actions: actions)"))
        self.assertNotIn("UIScrollView", self.uikit)
        self.assertNotIn("UICollectionView", self.uikit)

    def test_uikit_design_system_centralizes_hardware_components_and_tokens(self):
        for symbol in (
            "enum BBUIKitTokens", "outerMargin", "panelGap", "panelPadding", "controlGap",
            "borderWidth", "cornerRadius", "minimumTouchHeight", "BBPanelView",
            "BBSectionHeader", "BBHardwareButton", "BBColorPad", "BBSplitColorComboPad",
            "BBStatusIndicator", "BBValueReadout", "BBVerticalEnergyFader",
        ):
            self.assertIn(symbol, self.uikit_design)

    def test_active_selectable_controls_share_a_clearly_stronger_component_border(self):
        self.assertIn("static let activeBorderWidth: CGFloat = 4", self.uikit_design)
        self.assertIn("layer.borderWidth = isIlluminated ? BBUIKitTokens.activeBorderWidth", self.uikit_design)
        self.assertIn("activeBorderColor = BBUIKitTokens.activeRing(for: color)", self.uikit_design)
        self.assertIn("activeBorderColor = BBUIKitTokens.activeRing(for: first, second)", self.uikit_design)
        self.assertIn("static func activeRing(for color: UIColor", self.uikit_design)

    def test_uikit_override_preserves_color_combo_smoke_and_action_parity(self):
        for symbol in (
            'let colorOrder = ["auto", "red", "yellow", "green", "lime", "purple", "pink", "cyan", "orange", "blue", "white", "rainbow"]',
            "makeGrid(colorPads, columns: 6)", "makeGrid(comboPads, columns: 8)",
            'BBHardwareButton(symbol: "cloud.fill"', 'BBLabeledControl(label: "SMOKE HOLD", detail: "0–100%"',
            'actions.beginSmokeHold()', 'actions.endSmokeHold()', 'for: [.touchUpInside, .touchUpOutside, .touchCancel]',
            'perform("set_smoke_output"', "smokeButton.isEnabled = smoke?.supported == true",
            'perform("set_color"', 'perform("set_color_combo"', 'perform("set_phrase"',
            'perform("set_energy"', 'perform("trigger_cue"', 'perform("release_all")',
            '"blackout_off" : "blackout_on"',
        ):
            self.assertIn(symbol, self.uikit)
        self.assertIn("16 exact combinations", self.parity)
        self.assertIn("right of Purple/Rainbow", self.parity)

    def test_uikit_combo_faces_and_external_labels_are_passive_above_one_authoritative_action(self):
        combo = self.uikit_design[self.uikit_design.index("final class BBSplitColorComboPad"):self.uikit_design.index("final class BBLabeledControl")]
        self.assertIn("halves.isUserInteractionEnabled = false", combo)
        self.assertIn("leftView.isUserInteractionEnabled = false", combo)
        self.assertIn("rightView.isUserInteractionEnabled = false", combo)
        self.assertIn("override func hitTest", self.uikit_design)
        override = self.uikit[self.uikit.index("private final class BBOverrideSurface"):self.uikit.index("private final class BBLiveSurface")]
        self.assertIn('actions.perform("set_color_combo", value: combo.id)', override)
        self.assertIn("button.isIlluminated = state.overrides.colorCombo == id", override)
        self.assertNotIn("Timer", override)

    def test_uikit_fader_is_direct_touch_clamped_discrete_and_authoritative(self):
        for symbol in (
            "class BBVerticalHardwareFader: UIControl", "final class BBVerticalEnergyFader: BBVerticalHardwareFader",
            "let clamped = min(max(y, topCenter), bottomCenter)", "override func beginTracking",
            "override func continueTracking", "sendActions(for: .valueChanged)",
            "if !energyFader.isTracking", "currentState?.overrides.energy",
        ):
            self.assertIn(symbol, self.uikit_design + self.uikit)
        self.assertNotIn("UISlider", self.uikit_design)

    def test_uikit_energy_fader_keeps_its_wide_interaction_semantics_while_using_hardware_layers(self):
        energy = self.uikit_design[self.uikit_design.index("class BBVerticalHardwareFader"):self.uikit_design.index("private final class BBBrushedMetalFaceplate")]
        for symbol in (
            "BBBrushedMetalFaceplate", "BBChannelFaderSlot", "BBChannelFaderScale", "BBChannelFaderCap",
            "override func beginTracking", "override func continueTracking", "override func endTracking",
            "setNormalizedValue(normalizedValue(for: touch.location(in: self).y, height: bounds.height), sendEvent: true)",
            "let clamped = min(max(y, topCenter), bottomCenter)", "capSize = CGSize(width: 36, height: 76)",
            "let capCenterY = visualCenterY(for: normalizedValue, height: bounds.height)",
            "let labelY = visualCenterY(for: labelValue, height: bounds.height)",
            "accessibilityIncrement", "accessibilityDecrement",
        ):
            self.assertIn(symbol, energy)
        self.assertIn("BBBrushedMetalFaceplate", self.uikit_design)
        self.assertIn("for index in stride", self.uikit_design)
        self.assertIn("for y in stride", self.uikit_design)
        self.assertNotIn("UISlider", energy)

    def test_uikit_master_control_bank_has_three_matched_faders_and_authoritative_routes(self):
        for symbol in (
            "BBVerticalEnergyFader", "BBVerticalFxSpeedFader", "BBVerticalMasterDimmerFader",
            'BBSectionHeader("MASTER CONTROL")', 'BBLabeledControl(label: "ENERGY"',
            'BBLabeledControl(label: "FX SPEED"', 'BBLabeledControl(label: "MASTER DIMMER"',
            'actions.perform("set_fx_speed"', "actions.queueMasterDimmer", "actions.commitMasterDimmer",
            "if !fxSpeedFader.isTracking", "if !masterDimmerFader.isTracking",
        ):
            self.assertIn(symbol, self.uikit_design + self.uikit)
        self.assertIn('super.init(scaleTitles: ["FAST", "MID", "SLOW", "AUTO"]', self.uikit_design)
        self.assertIn('super.init(scaleTitles: ["100", "75", "50", "25", "0"]', self.uikit_design)
        self.assertIn("scale.majorCount = max(2, scaleTitles.count)", self.uikit_design)
        self.assertIn("masterDimmerCoalescingTask", self.store)
        self.assertIn("70_000_000", self.store)
        self.assertIn('sendControl("set_master_dimmer"', self.store)
        self.assertIn("phraseMasterPanel.widthAnchor.constraint(equalTo: widthAnchor, multiplier: 0.40)", self.uikit)
        self.assertNotIn("UIScrollView", self.uikit)

    def test_live_rendered_output_uses_shared_effective_intensity_as_a_bottom_up_fill(self):
        fixture_tile = self.uikit[self.uikit.index("private final class BBFixtureTile"):self.uikit.index("private final class BBStatusSurface")]
        for symbol in (
            "fixture.effectiveIntensity ?? Double(fixture.dimmer) / 255",
            "fill.bottomAnchor.constraint(equalTo: meter.bottomAnchor)",
            "fill.heightAnchor.constraint(equalTo: meter.heightAnchor, multiplier: intensity)",
            "meter.backgroundColor = BBUIKitTokens.recessed",
            "meter.clipsToBounds = true",
            "fixture.resolvedRed ?? fixture.red",
        ):
            self.assertIn(symbol, fixture_tile)
        self.assertNotIn("max(0.20", fixture_tile)

    def test_shared_rendered_intensity_projection_is_additive_and_color_independent(self):
        for symbol in (
            '"effective_intensity"', "current_rendered_slot_intensities",
            '"resolved_red"', "include_effective_intensity=True",
        ):
            self.assertIn(symbol, self.backend)
        self.assertIn("let effectiveIntensity: Double?", self.models)
        self.assertIn("let resolvedRed: Int?", self.models)
        native = (ROOT / "native/BeatBeamDMXApp.swift").read_text(encoding="utf-8")
        self.assertIn("let effectiveIntensity: Double?", native)
        self.assertIn("slotPreviewBaseColor(preview).opacity(slotBrightnessFraction(preview))", native)
        self.assertNotIn("opacity(max(0.20, slotBrightnessFraction(preview)))", native)

    def test_uikit_hold_pads_release_all_terminal_touch_paths(self):
        self.assertIn('sendControl("momentary_press"', self.store)
        self.assertIn("beginMomentary(effect.id)", self.uikit)
        self.assertIn("endMomentary(effect.id)", self.uikit)
        self.assertIn("for: .touchDown", self.uikit)
        self.assertIn("for: [.touchUpInside, .touchUpOutside, .touchCancel]", self.uikit)
        self.assertIn('releaseMomentaries(reason: "UIKit tab changed")', self.uikit)
        self.assertIn('releaseMomentaries(reason: "UIKit root dismissed")', self.uikit)

    def test_uikit_hold_pads_use_only_press_and_terminal_release_events(self):
        override = self.uikit[self.uikit.index("let holds = state.control.momentaryEffects"):self.uikit.index("let cues = state.control.cueShots")]
        self.assertIn("for: .touchDown", override)
        self.assertIn("for: [.touchUpInside, .touchUpOutside, .touchCancel]", override)
        self.assertIn("actions.beginMomentary(effect.id)", override)
        self.assertIn("actions.endMomentary(effect.id)", override)
        self.assertNotIn("trigger_cue", override)
        self.assertNotIn("touchDragExit", self.uikit_design[self.uikit_design.index("class BBHardwareButton"):self.uikit_design.index("final class BBColorPad")])

    def test_one_shot_progress_is_read_only_authoritative_state_not_a_client_lifetime(self):
        for symbol in (
            "struct RemoteOneShotState", "let oneShot: RemoteOneShotState?", "final class BBOneShotProgressButton",
            "setRemainingFraction", "state.overrides.oneShot", "actions.isConnected",
        ):
            self.assertIn(symbol, self.models + self.uikit_design + self.uikit)
        self.assertIn('"one_shot": _remote_live_one_shot_state(auto_show)', self.backend)
        self.assertIn("duration_beats", self.backend)
        self.assertIn("remaining_beats", self.backend)
        self.assertNotIn("Timer.scheduledTimer", self.uikit_design + self.uikit)

    def test_uikit_root_uses_stable_child_controller_containment(self):
        for symbol in (
            "private lazy var surfaces", "BBRemoteSurfaceViewController", "willMove(toParent: nil)",
            "removeFromParent()", "addChild(controller)", "controller.didMove(toParent: self)",
        ):
            self.assertIn(symbol, self.uikit)

    def test_hardware_function_labels_are_external_except_top_navigation(self):
        self.assertIn("final class BBLabeledControl", self.uikit_design)
        self.assertEqual(1, self.uikit.count("BBHardwareButton(title:"))
        header = self.uikit[self.uikit.index("private final class BBConsoleHeaderView"):self.uikit.index("private final class BBOverrideSurface")]
        self.assertIn("BBHardwareButton(title: tab.rawValue", header)
        override = self.uikit[self.uikit.index("private final class BBOverrideSurface"):self.uikit.index("private final class BBLiveSurface")]
        self.assertNotIn("BBHardwareButton(title:", override)
        for external_label in (
            'BBLabeledControl(label: "SMOKE HOLD"', 'BBLabeledControl(label: "RELEASE ALL"',
            'BBLabeledControl(label: "BLACKOUT"', 'BBLabeledControl(label: effect.label',
        ):
            self.assertIn(external_label, override)
        self.assertNotIn("setTitle", self.uikit_design[self.uikit_design.index("final class BBColorPad"):])

    def test_uikit_live_status_settings_have_exact_information_roles(self):
        for symbol in (
            "NOW PLAYING", "SHOW NOW", "ACTUAL FRAME SOURCE", "RENDERED OUTPUT",
            "PREVIEW / NO PHYSICAL DMX", "ACTIVE WARNINGS", "BBFixtureTile",
            "CONNECTION", "SYSTEM HEALTH", "OUTPUT / RUNTIME", "SONGANALYZER",
            "CONNECTION PREFERENCES", "APP / REMOTE", "PRODUCTION MODE",
            "FORGET THIS PAIRING", "REVERT TO BASELINE", "ENABLE DYNAMIC COMPOSER",
        ):
            self.assertIn(symbol, self.uikit)

    def test_uikit_controls_are_not_gated_by_dmx_connection(self):
        override = self.uikit[self.uikit.index("private final class BBOverrideSurface"):self.uikit.index("private final class BBLiveSurface")]
        self.assertNotIn("dmx.connected", override)
        self.assertIn("connectivity as a control availability gate", self.parity)

    def test_uikit_parity_matrix_covers_every_surface_contract(self):
        for symbol in (
            "track / artist", "production mode", "actual frame / fallback", "rendered output",
            "Auto + 10 exact colors + Rainbow", "16 exact combinations", "five hold effects",
            "six one-shots", "Release All", "Blackout", "Backend/Renderer/VDJ/SongAnalyzer/DMX/Transport/Output",
            "forget pairing", "Revert Baseline", "Enable Dynamic Composer",
        ):
            self.assertIn(symbol, self.parity)


if __name__ == "__main__":
    unittest.main()
