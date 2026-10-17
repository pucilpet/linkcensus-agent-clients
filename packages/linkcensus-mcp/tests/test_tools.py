import contextlib
import copy
import io
import os
import unittest
from unittest.mock import patch

from linkcensus_client import Client, ClientError
from linkcensus_mcp.cli import main
from linkcensus_mcp.runner import SerialRunner
from linkcensus_mcp.tools import MAX_TEXT_BYTES, TOOLS, execute
from test_bounds import EDITIONS, ENVELOPE, RESOLUTION, FakeClient


class ToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_exact_structured_candidates_and_dated_truncation_quota_text(self):
        client = FakeClient()
        payload, text, failed = await execute(client, SerialRunner(), "get_neighbor_candidates", {"domain": "example.com"})
        self.assertIs(payload, ENVELOPE)
        self.assertFalse(failed)
        for value in ("not confirmed competitors", "fixture-2026-01", "among top 200 retained", "truncated: true", "2/15", "2026-11-01", "candidate.example"):
            self.assertIn(value, text)
        self.assertEqual(client.calls, [("neighbors", ("example.com",), {"edition": None, "limit": 5, "min_shared": 0, "tld": None})])

    async def test_three_fixed_tools_and_explicit_filters(self):
        fixtures = (("list_editions", {}, EDITIONS, "editions"),
                    ("resolve_domain", {"domain": "example.com", "edition": "fixture-2026-01"}, RESOLUTION, "resolve"),
                    ("get_neighbor_candidates", {"domain": "example.com", "edition": "fixture-2026-01", "limit": 100,
                        "min_shared": 200, "tld": ".com"}, ENVELOPE, "neighbors"))
        self.assertEqual({row[0] for row in fixtures}, set(TOOLS))
        for name, arguments, expected, method in fixtures:
            client = FakeClient(expected)
            payload, text, failed = await execute(client, SerialRunner(), name, arguments)
            self.assertFalse(failed, name)
            self.assertIs(payload, expected)
            self.assertEqual(client.calls[0][0], method)

    async def test_unknown_fields_authority_and_out_of_bounds_rejected_before_work(self):
        client = FakeClient()
        cases = [("list_editions", {"api_key": "secret"}), ("list_editions", {"base_url": "https://other.example"}),
                 ("get_neighbor_candidates", {"domain": "example.com", "limit": True}),
                 ("get_neighbor_candidates", {"domain": "example.com", "limit": 101}),
                 ("get_neighbor_candidates", {"domain": "example.com", "min_shared": 201}),
                 ("get_neighbor_candidates", {"domain": "example.com", "tld": "com/x"}),
                 ("resolve_domain", {"domain": "example.com", "edition": "../../other"}),
                 ("get_neighbor_candidates", {"domain": "example.com", "confirmed_competitor": True}),
                 ("crawl", {"domain": "example.com"}), ("list_editions", [])]
        for name, arguments in cases:
            payload, _, failed = await execute(client, SerialRunner(), name, arguments)
            self.assertTrue(failed)
            self.assertEqual(payload["error"]["code"], "invalid_input")
        self.assertEqual(client.calls, [])

    async def test_invalid_domains_do_not_issue_real_client_http(self):
        client = Client(api_key="lc_live_synthetic_not_real")
        with patch.object(client, "_request") as request:
            for domain in ("127.0.0.1", "https://example.com", "a@b.example", "x.123", "bad_.example"):
                payload, _, failed = await execute(client, SerialRunner(), "get_neighbor_candidates", {"domain": domain})
                self.assertTrue(failed)
                self.assertEqual(payload["error"]["code"], "input")
            request.assert_not_called()

    async def test_structured_quota_error_is_safe_and_informational(self):
        client = FakeClient()
        def fail():
            raise ClientError("quota_exceeded", "API request limited", status=429, retry_after="60")
        client.editions = fail
        payload, _, failed = await execute(client, SerialRunner(), "list_editions", {})
        self.assertTrue(failed)
        self.assertEqual(payload, {"api_version": "v1", "error": {
            "code": "quota_exceeded", "message": "API request limited", "status": 429, "retry_after": "60"}})

    async def test_text_cap_preserves_complete_structured_payload(self):
        payload = copy.deepcopy(ENVELOPE)
        payload["results"][0]["shared_linker_names"] = ["x" * 12000]
        result, text, failed = await execute(FakeClient(payload), SerialRunner(), "get_neighbor_candidates", {"domain": "example.com"})
        self.assertFalse(failed)
        self.assertIs(result, payload)
        self.assertLessEqual(len(text.encode()), MAX_TEXT_BYTES)
        self.assertIn("Text truncated", text)

    def test_no_vp_credential_or_private_config_read_when_lc_env_is_supplied(self):
        # Force startup to stop after Client construction; no protocol fd claim or network.
        output = io.StringIO()
        with patch.dict(os.environ, {"LINKCENSUS_API_KEY": "lc_live_fixture_not_real", "VERIFIEDPRICING_API_KEY": "vp_live_private_not_real"}, clear=True):
            with patch("importlib.metadata.version", side_effect=lambda name: "2.3.0" if name == "mcp" else "0.1.0"):
                with patch("linkcensus_client.config.load", side_effect=AssertionError("must not load")):
                    with patch("linkcensus_client.Client", side_effect=RuntimeError("stop")) as constructor:
                        with contextlib.redirect_stderr(output):
                            self.assertEqual(main([]), 2)
        self.assertEqual(constructor.call_args.args[1], "lc_live_fixture_not_real")
        self.assertNotIn("lc_live_fixture_not_real", output.getvalue())
        self.assertNotIn("vp_live_private_not_real", output.getvalue())

    def test_parser_errors_do_not_echo_accidental_key_arguments(self):
        output = io.StringIO()
        with contextlib.redirect_stderr(output), self.assertRaises(SystemExit) as caught:
            main(["--api-key", "lc_live_fixture_not_real"])
        self.assertEqual(caught.exception.code, 2)
        self.assertNotIn("lc_live_fixture_not_real", output.getvalue())
