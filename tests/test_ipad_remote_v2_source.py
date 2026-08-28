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
            "struct RemoteOverrideState", "struct RemoteWarning",
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

    def test_connection_state_and_authoritative_snapshot_reconciliation_exist(self):
        for state in ("notPaired", "connecting", "connected", "reconnecting", "offline", "authFailed", "serverIncompatible"):
            self.assertIn(state, self.store)
        self.assertIn("state.stateRevision > newestRevision", self.store)
        self.assertIn("startEventStream()", self.store)
        self.assertIn("fallbackPollIntervalNanoseconds", self.store)

    def test_qr_scan_starts_the_complete_pairing_exchange(self):
        self.assertIn("Task { await pair(using: configurationURLText, code: pairingCodeText) }", self.store)

    def test_dashboard_is_read_only_and_has_required_live_information(self):
        for text in ("NOW PLAYING", "PRODUCTION", "FRAME", "FALLBACK", "SYSTEM HEALTH", "MUSICAL CONTEXT", "FIXTURE GROUPS", "BLACKOUT ACTIVE", "MANUAL OVERRIDE ACTIVE"):
            self.assertIn(text, self.view)
        self.assertIn("proxy.size.width > proxy.size.height", self.view)
        self.assertIn("UIInterfaceOrientationPortrait", (ROOT / "ipad-remote/BeatBeamRemote/Info.plist").read_text(encoding="utf-8"))
        self.assertNotIn("setBlackoutEnabled", self.view)
        self.assertNotIn("setAutoShowEnabled", self.view)
        for symbol in ("LIVE CONTROL", "BLACKOUT", "RELEASE ALL", "REVERT BASELINE", "ENABLE DYNAMIC", "HOLD EFFECT PADS", "CUE SHOTS", "OverridesControlScreen"):
            self.assertIn(symbol, self.view)


if __name__ == "__main__":
    unittest.main()
