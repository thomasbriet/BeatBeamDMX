import unittest

import beatbeam_app


def handler_with_headers(headers):
    handler = object.__new__(beatbeam_app.AppHandler)
    handler.client_address = ("127.0.0.1", 51234)
    handler.headers = headers
    return handler


class LoopbackCrossOriginTests(unittest.TestCase):
    def test_native_and_same_origin_clients_are_accepted(self):
        self.assertTrue(handler_with_headers({}).request_origin_is_same_site())
        self.assertTrue(
            handler_with_headers({
                "Origin": "http://127.0.0.1:8781",
                "Host": "127.0.0.1:8781",
            }).request_origin_is_same_site()
        )

    def test_foreign_browser_page_cannot_reuse_the_loopback_session(self):
        for origin in ("http://evil.example", "http://localhost:3000", "null"):
            with self.subTest(origin=origin):
                self.assertFalse(
                    handler_with_headers({
                        "Origin": origin,
                        "Host": "127.0.0.1:8781",
                    }).request_origin_is_same_site()
                )

    def test_cross_origin_post_is_rejected_before_any_command_runs(self):
        responses = []
        handler = handler_with_headers({
            "Origin": "http://evil.example",
            "Host": "127.0.0.1:8781",
        })
        handler.path = "/api/dmx/blackout"
        handler.send_json = lambda payload, status=200: responses.append((status, payload))
        handler.read_json = lambda: self.fail("payload read despite cross-origin rejection")
        handler.do_POST()
        self.assertEqual(403, responses[0][0])

    def test_loopback_token_comparison_is_constant_time_and_exact(self):
        original = beatbeam_app.REMOTE_ACCESS_CONFIG
        beatbeam_app.REMOTE_ACCESS_CONFIG = {"token": "secret-token", "require_token": True}
        try:
            handler = handler_with_headers({"X-BeatBeam-Token": "secret-token"})
            handler.client_address = ("192.0.2.44", 1234)
            self.assertTrue(handler.is_authorized_remote_request({}))
            handler.headers = {"X-BeatBeam-Token": "secret-token-x"}
            self.assertFalse(handler.is_authorized_remote_request({}))
        finally:
            beatbeam_app.REMOTE_ACCESS_CONFIG = original


if __name__ == "__main__":
    unittest.main()
