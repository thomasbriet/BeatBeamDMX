import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class IpadRemoteV2SourceTests(unittest.TestCase):
    def setUp(self):
        self.models = (ROOT / "ipad-remote/BeatBeamRemote/RemoteModels.swift").read_text(encoding="utf-8")
        self.store = (ROOT / "ipad-remote/BeatBeamRemote/RemoteStore.swift").read_text(encoding="utf-8")
        self.view = (ROOT / "ipad-remote/BeatBeamRemote/ContentView.swift").read_text(encoding="utf-8")

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
        for symbol in ("SINGLE COLORS", "COLOR COMBINATIONS", "ColorComboMatrix", "ColorComboPad", "Rainbow", "ENERGY / PHRASE", "vertical fader", "HOLD EFFECTS", "ONE-SHOT EFFECTS", "EffectDeck", "ColorPerformancePadStyle", "HardwarePerformancePadStyle", 'store.perform("set_color_combo"', 'store.perform("release_all")', 'store.perform("blackout_on")'):
            self.assertIn(symbol, self.view)
        override = self.view[self.view.index("private struct OverrideConsole"):self.view.index("private struct ColorPadMatrix")]
        self.assertNotIn("revert_baseline", override)
        self.assertNotIn("enable_dynamic_composer", override)

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


if __name__ == "__main__":
    unittest.main()
