import contextlib
import copy
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import threading
import time
import unittest
import urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import patch

from linkcensus_client import Client, ClientError, __version__
from linkcensus_client import config
from linkcensus_client.cli import main

KEY = "lc_live_fixture_secret_not_real"
PAYLOAD = {
    "api_version": "v1", "relationship": "candidate",
    "selection_reason": "Link-neighborhood similarity, not confirmed product competition",
    "shared_linkers_scope": "among top 200 retained", "edition": "fixture-2026-01",
    "ranking_mode": "embedding", "query": "example.com", "resolved_host": "www.example.com",
    "resolution": "www", "total": 9, "gated": True, "truncated": True, "tier": "free",
    "filters": {"limit": 5, "min_shared": 0, "tld": None, "hub_query": False, "tld_facets": []},
    "quota": {"used": 2, "limit": 15, "resets_at": "2026-11-01T00:00:00Z"},
    "results": [{"domain": "candidate.example", "host": "candidate.example", "similarity": 85,
                 "shared_linkers": 3, "shared_linker_names": ["linker.example"], "tld": "example",
                 "rank_band": "10k-100k", "explanation_kind": "shared_linkers", "suppressed": False}],
}
EDITIONS = {"api_version": "v1", "loaded_edition": "fixture-2026-01",
            "editions": [{"id": "fixture-2026-01", "source": "Common Crawl", "isActive": True}]}
RESOLUTION = {key: PAYLOAD[key] for key in (
    "api_version", "query", "resolved_host", "resolution", "edition", "relationship", "selection_reason",
)}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        self.server.calls.append((self.path, self.headers.get("Authorization"), self.headers.get("Cookie")))
        status, headers, body = self.server.reply_status, dict(self.server.reply_headers), self.server.reply_body
        delay = self.server.reply_delay
        self.send_response(status)
        for key, value in headers.items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            if delay:
                time.sleep(delay)
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            self.server.completed.set()


class ClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=lambda: cls.server.serve_forever(poll_interval=0.01), daemon=True)
        cls.thread.start()
        cls.origin = "http://127.0.0.1:" + str(cls.server.server_port)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def setUp(self):
        self.server.calls = []
        self.server.reply_status = 200
        self.server.reply_headers = {"Content-Type": "application/json"}
        self.server.reply_body = json.dumps(PAYLOAD).encode()
        self.server.reply_delay = 0
        self.server.completed = threading.Event()
        self.client = Client(self.origin, KEY, allow_localhost=True)
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.config_path = Path(self.temporary.name) / "private" / "config.json"

    def cli(self, args, *, key=KEY, stdin=""):
        stdout, stderr = io.StringIO(), io.StringIO()
        env = {"LINKCENSUS_API_KEY": key} if key is not None else {}
        with patch.dict(os.environ, env, clear=True), patch("sys.stdin", io.StringIO(stdin)):
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = main(["--config", str(self.config_path), "--base-url", self.origin,
                             "--allow-localhost", *args])
        return code, stdout.getvalue(), stderr.getvalue()

    def test_neighborhood_json_parity_and_exact_bearer_request(self):
        result = self.client.neighbors("Example.COM.", edition="fixture-2026-01", limit=5, tld="com", min_shared=2)
        self.assertEqual(result, PAYLOAD)
        self.assertEqual(self.server.calls, [(
            "/api/v1/neighbors/example.com?limit=5&min_shared=2&edition=fixture-2026-01&tld=com", "Bearer " + KEY, None,
        )])

    def test_metadata_clients_and_cli_use_versioned_routes(self):
        self.server.reply_body = json.dumps(EDITIONS).encode()
        self.assertEqual(self.client.editions(), EDITIONS)
        code, out, error = self.cli(["editions", "--json"])
        self.assertEqual((code, error, json.loads(out)), (0, "", EDITIONS))
        self.server.reply_body = json.dumps(RESOLUTION).encode()
        self.assertEqual(self.client.resolve("example.com", edition="fixture-2026-01"), RESOLUTION)
        code, out, error = self.cli(["resolve", "example.com", "--edition", "fixture-2026-01"])
        self.assertEqual((code, error), (0, ""))
        self.assertIn("not proof of competition", out)
        self.assertEqual(self.server.calls[0][0], "/api/v1/editions")
        self.assertEqual(self.server.calls[2][0], "/api/v1/resolve/example.com?edition=fixture-2026-01")

    def test_cli_json_before_or_after_command_preserves_all_fields(self):
        for args in (["--json", "neighbors", "example.com"], ["neighbors", "example.com", "--json"]):
            code, out, error = self.cli(args)
            self.assertEqual((code, error, json.loads(out)), (0, "", PAYLOAD))

    def test_human_output_is_candidate_dated_truncated_and_account_metered(self):
        code, out, error = self.cli(["neighbors", "example.com"])
        self.assertEqual((code, error), (0, ""))
        for value in ("not proven competitors", "fixture-2026-01", "truncated: true", "resolution: \"www\"",
                      "2/15", "2026-11-01", "among top 200 retained", "candidate.example", "linker.example"):
            self.assertIn(value, out)
        self.assertNotIn(KEY, out)

    def test_uncovered_and_suppressed_responses_remain_indistinguishable(self):
        empty = {**PAYLOAD, "resolved_host": None, "resolution": "not_covered", "total": 0,
                 "results": [], "gated": False, "truncated": False}
        self.server.reply_body = json.dumps(empty).encode()
        self.assertEqual(self.client.neighbors("example.com"), empty)
        code, out, error = self.cli(["neighbors", "example.com"])
        self.assertEqual((code, error), (0, ""))
        self.assertIn("absence does not establish", out)

    def test_idn_query_normalization(self):
        payload = {**PAYLOAD, "query": "mökki.fi", "resolved_host": "mökki.fi", "resolution": "exact"}
        self.server.reply_body = json.dumps(payload).encode()
        self.client.neighbors("mökki.fi")
        self.assertIn("/xn--mkki-5qa.fi?", self.server.calls[0][0])

    def test_invalid_inputs_make_no_request_and_never_echo_arguments(self):
        for domain in ("127.0.0.1", "https://example.com", "example.com/path", "user:pass@example.com",
                       "bad_.example", "x.123", "a" * 64 + ".com", "example.com\n", None):
            with self.assertRaises(ClientError):
                self.client.neighbors(domain)
        for options in ({"limit": 0}, {"limit": 101}, {"limit": True}, {"min_shared": 201},
                        {"tld": "com/x"}, {"edition": KEY}):
            with self.assertRaises(ClientError):
                self.client.neighbors("example.com", **options)
        for args in (["neighbors", "example.com", "--limit", "101"], ["--json", KEY],
                     ["neighbors", "example.com", "--api-key", KEY]):
            code, out, error = self.cli(args)
            self.assertEqual(code, 2)
            self.assertNotIn(KEY, out + error)
        self.assertEqual(self.server.calls, [])

    def test_origin_credentials_and_timeout_validation(self):
        for value in ("http://example.com", self.origin, "https://user:pass@example.com", "https://example.com/api",
                      "https://example.com?", "https://example.com#", "https://example.com\\evil", "https://example.com\n"):
            with self.assertRaises(ClientError):
                Client(value, KEY)
        for value in (0, -1, 61, True, float("nan"), float("inf")):
            with self.assertRaises(ClientError):
                Client(api_key=KEY, timeout=value)
        for key in (None, "vp_live_other_audience", "lc_live_bad\r\nheader"):
            with self.assertRaises(ClientError):
                Client(api_key=key)
        local = Client("http://localhost:1234", KEY, allow_localhost=True)
        self.assertEqual(local.base_url, "http://127.0.0.1:1234")

    def test_redirect_never_follows_or_forwards_credentials(self):
        self.server.reply_status = 302
        self.server.reply_headers = {"Location": self.origin + "/stolen"}
        with self.assertRaises(ClientError) as caught:
            self.client.neighbors("example.com")
        self.assertEqual(caught.exception.message, "API redirect refused")
        self.assertEqual(len(self.server.calls), 1)

    def test_environment_proxy_is_ignored(self):
        with patch.dict(os.environ, {"http_proxy": "http://127.0.0.1:9", "HTTP_PROXY": "http://127.0.0.1:9", "no_proxy": ""}):
            self.client.neighbors("example.com")
        self.assertEqual(len(self.server.calls), 1)

    def test_statuses_have_stable_exit_codes_and_no_error_body_echo(self):
        for status, expected in ((401, 3), (403, 3), (404, 5), (409, 5), (422, 2), (429, 4), (503, 6), (504, 6)):
            self.server.reply_status = status
            self.server.reply_headers = {"Retry-After": "60"}
            self.server.reply_body = json.dumps({"detail": {"code": "quota_exceeded", "message": KEY}}).encode()
            code, out, error = self.cli(["neighbors", "example.com", "--json"])
            self.assertEqual((code, out), (expected, ""))
            self.assertNotIn(KEY, error)
            self.assertEqual(json.loads(error)["error"]["status"], status)
        self.assertEqual(len(self.server.calls), 8)

    def test_error_code_and_retry_after_cannot_echo_key(self):
        self.server.reply_status = 429
        self.server.reply_headers = {"Retry-After": KEY}
        self.server.reply_body = json.dumps({"detail": {"code": KEY}}).encode()
        code, out, error = self.cli(["neighbors", "example.com", "--json"])
        self.assertEqual((code, out), (4, ""))
        self.assertNotIn(KEY, error)
        self.assertEqual(json.loads(error)["error"]["retry_after"], None)

    def test_escaped_secret_in_success_payload_is_rejected(self):
        for changed in ({**PAYLOAD, "selection_reason": KEY}, {**PAYLOAD, KEY: "echo"}):
            self.server.reply_body = json.dumps(changed).replace("lc_live", "\\u006cc_live").encode()
            code, out, error = self.cli(["neighbors", "example.com", "--json"])
            self.assertEqual((code, out), (6, ""))
            self.assertNotIn(KEY, error)

    def test_transport_exception_is_sanitized_and_not_retried(self):
        with patch.object(self.client._opener, "open", side_effect=urllib.error.URLError(KEY)) as opened:
            with self.assertRaises(ClientError) as caught:
                self.client.neighbors("example.com")
        self.assertEqual(opened.call_count, 1)
        self.assertNotIn(KEY, str(caught.exception))

    def test_finite_socket_timeout_on_loopback_body(self):
        self.server.reply_delay = 0.1
        client = Client(self.origin, KEY, allow_localhost=True, timeout=0.02)
        with self.assertRaises(ClientError) as caught:
            client.neighbors("example.com")
        self.assertEqual(caught.exception.code, "transport")
        self.assertTrue(self.server.completed.wait(timeout=1))
        self.assertEqual(len(self.server.calls), 1)

    def test_response_size_json_schema_and_edition_pin_bounds(self):
        malformed = [b"x" * (512 * 1024 + 1), b"not json", b'{"api_version":"v1","n":NaN}']
        for changed in ({**PAYLOAD, "relationship": "confirmed competitor"}, {**PAYLOAD, "truncated": False},
                        {**PAYLOAD, "total": 0}, {**PAYLOAD, "query": "wrong.example"},
                        {**PAYLOAD, "quota": {}}, {**PAYLOAD, "results": [None]}):
            malformed.append(json.dumps(changed).encode())
        missing = copy.deepcopy(PAYLOAD)
        del missing["resolved_host"]
        malformed.append(json.dumps(missing).encode())
        for body in malformed:
            self.server.reply_body = body
            with self.assertRaises(ClientError):
                self.client.neighbors("example.com")
        self.server.reply_body = json.dumps(PAYLOAD).encode()
        with self.assertRaises(ClientError):
            self.client.neighbors("example.com", edition="different-edition")

    def test_metadata_schema_and_pin_parity(self):
        self.server.reply_body = json.dumps({**EDITIONS, "loaded_edition": None}).encode()
        self.assertIsNone(self.client.editions()["loaded_edition"])
        self.server.reply_body = json.dumps({**RESOLUTION, "resolved_host": None, "resolution": "not_covered"}).encode()
        self.assertEqual(self.client.resolve("example.com")["resolution"], "not_covered")
        with self.assertRaises(ClientError):
            self.client.resolve("example.com", edition="different")
        self.server.reply_body = b'{"api_version":"v1","editions":[null],"loaded_edition":null}'
        with self.assertRaises(ClientError):
            self.client.editions()

    def test_config_is_private_atomic_and_never_calls_server(self):
        code, out, error = self.cli(["configure", "--key-stdin", "--json"], key=None, stdin=KEY + "\n")
        self.assertEqual((code, error), (0, ""))
        self.assertNotIn(KEY, out)
        self.assertEqual(stat.S_IMODE(self.config_path.stat().st_mode), 0o600)
        self.assertEqual(config.load(self.config_path)["api_key"], KEY)
        config.save(self.config_path, api_key="lc_live_rotated_fixture", base_url="https://linkcensus.com")
        self.assertEqual(config.load(self.config_path)["api_key"], "lc_live_rotated_fixture")
        self.assertEqual(list(self.config_path.parent.iterdir()), [self.config_path])
        self.assertEqual(self.server.calls, [])

    def test_config_rejects_permissions_symlinks_fifo_and_bad_json(self):
        config.save(self.config_path, api_key=KEY, base_url="https://linkcensus.com")
        self.config_path.chmod(0o644)
        with self.assertRaises(ClientError):
            config.load(self.config_path)
        self.config_path.chmod(0o600)
        linked = self.config_path.parent / "linked.json"
        linked.symlink_to(self.config_path)
        with self.assertRaises(ClientError):
            config.load(linked)
        with self.assertRaises(ClientError):
            config.save(linked, api_key=KEY, base_url="https://linkcensus.com")
        fifo = self.config_path.parent / "fifo"
        os.mkfifo(fifo, 0o600)
        with self.assertRaises(ClientError):
            config.load(fifo)
        for raw in (KEY, "[" * 4000, "x" * 8193):
            self.config_path.write_text(raw)
            with self.assertRaises(ClientError) as caught:
                config.load(self.config_path)
            self.assertNotIn(KEY, str(caught.exception))

    def test_private_config_auth_env_precedence_and_explicit_local_optin(self):
        config.save(self.config_path, api_key="lc_live_saved_fixture", base_url=self.origin, allow_localhost=True)
        self.assertEqual(self.cli(["neighbors", "example.com"], key=None)[0], 0)
        self.assertEqual(self.server.calls[-1][1], "Bearer lc_live_saved_fixture")
        self.config_path.chmod(0o644)
        self.assertEqual(self.cli(["neighbors", "example.com"])[0], 0)
        self.assertEqual(self.server.calls[-1][1], "Bearer " + KEY)
        with patch.dict(os.environ, {}, clear=True), contextlib.redirect_stderr(io.StringIO()):
            self.config_path.chmod(0o600)
            self.assertEqual(main(["--config", str(self.config_path), "neighbors", "example.com"]), 2)

    def test_human_output_escapes_terminal_controls(self):
        changed = copy.deepcopy(PAYLOAD)
        changed["results"][0]["domain"] = "candidate\u001b[2J.example"
        self.server.reply_body = json.dumps(changed).encode()
        code, out, error = self.cli(["neighbors", "example.com"])
        self.assertEqual((code, error), (0, ""))
        self.assertNotIn("\u001b", out)
        self.assertIn("\\u001b", out)

    def test_help_and_version_never_load_credentials(self):
        for flag in ("--help", "--version"):
            with patch("linkcensus_client.config.load", side_effect=AssertionError("unexpected configuration read")):
                with contextlib.redirect_stdout(io.StringIO()) as out, self.assertRaises(SystemExit) as caught:
                    main([flag])
            self.assertEqual(caught.exception.code, 0)
            if flag == "--version":
                self.assertIn(__version__, out.getvalue())


if __name__ == "__main__":
    unittest.main()
