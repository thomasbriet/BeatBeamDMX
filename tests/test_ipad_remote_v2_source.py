import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class IpadRemoteV2SourceTests(unittest.TestCase):
    def setUp(self):
        self.models = (ROOT / "ipad-remote/BeatBeamRemote/RemoteModels.swift").read_text(encoding="utf-8")
        self.store = (ROOT / "ipad-remote/BeatBeamRemote/RemoteStore.swift").read_text(encoding="utf-8")
        self.view = (ROOT / "ipad-remote/BeatBeamRemote/ContentView.swift").read_text(encoding="utf-8")
        self.uikit = (ROOT / "ipad-remote/BeatBeamRemote/UIKitControlSurface.swift").read_text(encoding="utf-8")
        self.uikit_design = (ROOT / "ipad-remote/BeatBeamRemote/UIKitDesignSystem.swift").read_text(encoding="utf-8")
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
        self.assertIn("startEventStream()", self.store)
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
        for symbol in ("OverrideLayout", "colorBankHeight", "comboBankHeight", "let columns = 6", "let columns = 8", "SmokeSetupPad().frame(width: OverrideLayout.smokeWidth)"):
            self.assertIn(symbol, override)
        self.assertNotIn("ScrollView", override)
        self.assertIn(".disabled(true)", self.view[self.view.index("private struct SmokeSetupPad"):self.view.index("private struct EffectRow")])

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

    def test_uikit_override_preserves_color_combo_smoke_and_action_parity(self):
        for symbol in (
            'let colorOrder = ["auto", "red", "yellow", "green", "lime", "purple", "pink", "cyan", "orange", "blue", "white", "rainbow"]',
            "makeGrid(colorPads, columns: 6)", "makeGrid(comboPads, columns: 8)",
            'title: "☁\\nSMOKE\\nSETUP PENDING"', "smokeButton.isEnabled = false",
            'perform("set_color"', 'perform("set_color_combo"', 'perform("set_phrase"',
            'perform("set_energy"', 'perform("trigger_cue"', 'perform("release_all")',
            '"blackout_off" : "blackout_on"',
        ):
            self.assertIn(symbol, self.uikit)
        self.assertIn("16 exact combinations", self.parity)
        self.assertIn("right of Purple/Rainbow", self.parity)

    def test_uikit_fader_is_direct_touch_clamped_discrete_and_authoritative(self):
        for symbol in (
            "final class BBVerticalEnergyFader: UIControl", "static func level(for y:",
            "let clamped = min(max(y, top), bottom)", "override func beginTracking",
            "override func continueTracking", "sendActions(for: .valueChanged)",
            "if !energyFader.isTracking", "currentState?.overrides.energy",
        ):
            self.assertIn(symbol, self.uikit_design + self.uikit)
        self.assertNotIn("UISlider", self.uikit_design)

    def test_uikit_hold_pads_release_all_terminal_touch_paths(self):
        self.assertIn('sendControl("momentary_press"', self.store)
        self.assertIn("beginMomentary(effect.id)", self.uikit)
        self.assertIn("endMomentary(effect.id)", self.uikit)
        self.assertIn("for: .touchDown", self.uikit)
        self.assertIn("for: [.touchUpInside, .touchUpOutside, .touchCancel]", self.uikit)
        self.assertIn('releaseMomentaries(reason: "UIKit tab changed")', self.uikit)
        self.assertIn('releaseMomentaries(reason: "UIKit root dismissed")', self.uikit)

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
