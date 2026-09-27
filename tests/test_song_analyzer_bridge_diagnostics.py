import json
import unittest

from beatbeam_app import SongAnalyzerBridgeDiagnostics


class FragmentedSocket:
    def __init__(self, payload, fragment_size=8192):
        self.payload = payload
        self.fragment_size = fragment_size

    def recv(self, maximum):
        if not self.payload:
            return b""
        size = min(maximum, self.fragment_size, len(self.payload))
        chunk, self.payload = self.payload[:size], self.payload[size:]
        return chunk


class SongAnalyzerBridgeDiagnosticsTests(unittest.TestCase):
    def test_fragmented_json_line_is_read_until_newline(self):
        expected = {
            "protocolVersion": 1,
            "requestId": "beatbeam-debug",
            "success": True,
            "status": "diagnostics",
            "diagnostics": {"recentFailures": [{"message": "x" * 9000}]},
        }
        payload = (json.dumps(expected, separators=(",", ":")) + "\n").encode("utf-8")
        first_fragment = payload[:8192]

        with self.assertRaises(json.JSONDecodeError):
            json.loads(first_fragment.decode("utf-8"))

        actual = SongAnalyzerBridgeDiagnostics._receive_response(FragmentedSocket(payload))

        self.assertEqual(expected, actual)

    def test_empty_response_fails_before_json_decode(self):
        with self.assertRaisesRegex(EOFError, "before its newline delimiter"):
            SongAnalyzerBridgeDiagnostics._receive_response(FragmentedSocket(b""))


if __name__ == "__main__":
    unittest.main()
