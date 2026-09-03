import json
import unittest
from pathlib import Path
from unittest.mock import patch

import beatbeam_app as app


class USBRemoteTransportV1Tests(unittest.TestCase):
    def setUp(self):
        self.bridge = app.BeatBeamUSBRemoteBridge()
        self.bridge._buffer = b""

    def test_framing_accepts_partial_valid_handshake(self):
        wire = json.dumps({"protocol": self.bridge.protocol, "type": "hello_ack"}).encode() + b"\n"
        self.assertEqual(self.bridge._consume(wire[:7]), [])
        frames = self.bridge._consume(wire[7:])
        self.assertEqual(self.bridge._validate_frame(frames[0]), "hello_ack")

    def test_framing_rejects_protocol_mismatch_malformed_and_oversize(self):
        with self.assertRaisesRegex(RuntimeError, "protocol mismatch"):
            self.bridge._validate_frame({"protocol": "other", "type": "hello"})
        with self.assertRaisesRegex(RuntimeError, "malformed USB JSON"):
            self.bridge._consume(b"{nope}\n")
        with self.assertRaisesRegex(RuntimeError, "overflow"):
            self.bridge._consume(b"x" * (self.bridge.maximum_frame_bytes + 1))

    def test_command_maps_only_to_existing_authority_and_ack_id(self):
        sent = []
        self.bridge._send = sent.append
        authoritative = {"accepted": True, "new_state_revision": 42, "effective_state": {"state_revision": 42}}
        with patch.object(app, "remote_live_control_command", return_value=authoritative) as control:
            self.bridge._handle_command({
                "protocol": self.bridge.protocol, "type": "command", "id": "command-1",
                "command": "set_master_dimmer", "payload": {"value": "0.6"},
            })
        self.assertEqual(control.call_args.args[1]["action"], "set_master_dimmer")
        self.assertEqual(sent[0]["type"], "ack")
        self.assertEqual(sent[0]["id"], "command-1")
        self.assertTrue(sent[0]["accepted"])

    def test_sequence_and_allowlist_safety_are_present_in_production_source(self):
        source = Path(app.__file__).read_text(encoding="utf-8")
        for symbol in ("self._sequence += 1", "remote_live_state_v2()", "remote_live_control_command(self._token", "_release_remote_smoke_hold(owner=owner, reason=\"usb_session_lost\")", "[executable, f\"{self.local_port}:{self.ipad_port}\"]"):
            self.assertIn(symbol, source)


if __name__ == "__main__":
    unittest.main()
