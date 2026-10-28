import http.client
import json
import os
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import app as portal
from app import (
    build_service_manifest,
    find_created_server,
    jar_options,
    next_free_port,
    origin_matches_host,
    resolve_jar_selection,
    sanitize_hostname,
    sanitize_service_name,
    unique_hostname,
    used_ports,
)


STATIC_ROOT = Path(portal.__file__).resolve().parent / "static"
TOKEN = "correct-horse-battery-staple"
SERVER_ID = "3f0c1d9e-8a4b-4c2d-9e1f-0a1b2c3d4e5f"
OTHER_SERVER_ID = "9b7e6d5c-4a3b-4c2d-8e1f-123456789abc"
JAR_CACHE = {"mc_java_servers": {"types": {"paper": {"versions": {"1.21.8": {}}}}}}


def make_config(**env: str | None) -> portal.Config:
    values = {
        "POD_NAMESPACE": "dripcraft",
        "PORTAL_TOKEN": TOKEN,
        "CRAFTY_API_TOKEN": "crafty-token",
        **env,
    }
    values = {key: value for key, value in values.items() if value is not None}
    with mock.patch.dict(os.environ, values, clear=True):
        return portal.Config.from_env()


class FakeCrafty:
    def __init__(self):
        self.calls = []
        self.servers = [{"id": SERVER_ID, "name": "Skyblock", "port": 25566, "raw": {}}]

    def list_servers(self):
        self.calls.append(("list",))
        return [dict(server) for server in self.servers]

    def jar_cache(self):
        return JAR_CACHE

    def create_java_server(self, request, port):
        self.calls.append(("create", request["name"], port))
        return OTHER_SERVER_ID

    def patch_server_config(self, server_id, payload):
        self.calls.append(("patch", server_id))

    def start_server(self, server_id):
        self.calls.append(("start", server_id))

    def delete_server(self, server_id, remove_files):
        self.calls.append(("delete", server_id, remove_files))


class FakeKube:
    available = True

    def __init__(self):
        self.calls = []

    def list_managed_services(self):
        return []

    def create_or_update_service(self, **kwargs):
        self.calls.append(("upsert", kwargs))
        return build_service_manifest(
            name=sanitize_service_name(kwargs["hostname"]),
            namespace="dripcraft",
            **kwargs,
        )

    def delete_service_for_server(self, server_id):
        self.calls.append(("delete", server_id))
        return True


class PortalServerTestCase(unittest.TestCase):
    env: dict[str, str | None] = {}

    def setUp(self):
        self.app = portal.App(make_config(**self.env))
        self.app.crafty = FakeCrafty()
        self.app.kube = FakeKube()
        handler = type(
            "TestHandler",
            (portal.PortalHandler,),
            {"app": self.app, "static_root": STATIC_ROOT, "log_message": lambda *args: None},
        )
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        log_patch = mock.patch.object(portal, "log_json")
        self.logged = log_patch.start()
        self.addCleanup(log_patch.stop)

    @property
    def origin(self) -> str:
        return f"http://127.0.0.1:{self.server.server_port}"

    def request(self, method, path, *, json_body=None, body=None, headers=None, token=TOKEN):
        request_headers = {}
        if token is not None:
            request_headers["X-Portal-Token"] = token
        if json_body is not None:
            body = json.dumps(json_body).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        request_headers.update(headers or {})
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=10)
        try:
            connection.request(method, path, body=body, headers=request_headers)
            response = connection.getresponse()
            raw = response.read()
        finally:
            connection.close()
        payload = raw
        if (response.getheader("Content-Type") or "").startswith("application/json"):
            payload = json.loads(raw)
        return response, payload


class PortalHelpersTest(unittest.TestCase):
    def test_sanitize_hostname(self):
        self.assertEqual(sanitize_hostname("Sky Block!"), "sky-block")
        self.assertEqual(sanitize_hostname("  creative---test  "), "creative-test")

    def test_sanitize_hostname_rejects_empty(self):
        with self.assertRaises(Exception):
            sanitize_hostname("!!!")

    def test_service_name_is_limited(self):
        name = sanitize_service_name("a" * 80)
        self.assertLessEqual(len(name), 63)
        self.assertTrue(name.startswith("minecraft-"))

    def test_unique_hostname_appends_server_id_on_conflict(self):
        used = {"skyblock"}
        self.assertEqual(unique_hostname("Skyblock", used, "abc12345-def"), "skyblock-abc12345")
        self.assertIn("skyblock-abc12345", used)

    def test_next_free_port(self):
        self.assertEqual(next_free_port(25565, 25567, {25565, 25567}), 25566)

    def test_resolve_jar_selection_is_case_insensitive_for_ids(self):
        cache = {
            "mc_java_servers": {
                "types": {
                    "paper": {
                        "versions": {
                            "1.21.8": {},
                        }
                    }
                }
            }
        }
        self.assertEqual(
            resolve_jar_selection(cache, "Mc_java_servers", "Paper", "1.21.8"),
            ("mc_java_servers", "paper", "1.21.8"),
        )

    def test_jar_options_summarizes_cache(self):
        cache = {
            "mc_java_servers": {
                "types": {
                    "paper": {
                        "friendly_name": "Paper",
                        "versions": {
                            "1.21.8": {},
                        },
                    }
                }
            }
        }
        self.assertEqual(
            jar_options(cache, "mc_java_servers"),
            {
                "category": "mc_java_servers",
                "types": [
                    {
                        "id": "paper",
                        "name": "Paper",
                        "versions": ["1.21.8"],
                    }
                ],
            },
        )

    def test_used_ports_includes_server_and_service_targets(self):
        ports = used_ports(
            [{"port": 25565}],
            [{"spec": {"ports": [{"targetPort": 25566}]}}],
        )
        self.assertEqual(ports, {25565, 25566})

    def test_find_created_server_matches_new_name_and_port(self):
        before = [{"id": "old", "name": "Old", "port": 25565}]
        after = [
            {"id": "old", "name": "Old", "port": 25565},
            {"id": "new", "name": "DripBlock", "port": 25566},
        ]
        self.assertEqual(
            find_created_server(before, after, "DripBlock", 25566),
            {"id": "new", "name": "DripBlock", "port": 25566},
        )

    def test_service_manifest_targets_crafty(self):
        manifest = build_service_manifest(
            name="minecraft-skyblock",
            namespace="dripcraft",
            server_id="abc-123",
            server_name="Skyblock",
            hostname="skyblock",
            target_port=25566,
            external_port=25565,
        )
        self.assertEqual(manifest["spec"]["loadBalancerClass"], "tailscale")
        self.assertEqual(manifest["spec"]["selector"]["app.kubernetes.io/name"], "crafty")
        self.assertEqual(manifest["spec"]["ports"][0]["port"], 25565)
        self.assertEqual(manifest["spec"]["ports"][0]["targetPort"], 25566)
        self.assertEqual(manifest["metadata"]["annotations"]["tailscale.com/hostname"], "skyblock")

    def test_origin_matches_host(self):
        self.assertTrue(origin_matches_host("https://dripcraft.tail1234.ts.net", "dripcraft.tail1234.ts.net"))
        self.assertTrue(origin_matches_host("https://dripcraft.tail1234.ts.net", "Dripcraft.tail1234.ts.net:443"))
        self.assertTrue(origin_matches_host("http://localhost:8080", "localhost:8080"))
        self.assertFalse(origin_matches_host("https://evil.example", "dripcraft.tail1234.ts.net"))
        self.assertFalse(origin_matches_host("http://localhost:8081", "localhost:8080"))
        self.assertFalse(origin_matches_host("null", "localhost:8080"))
        self.assertFalse(origin_matches_host("https://dripcraft", ""))


class FailClosedAuthTest(PortalServerTestCase):
    env = {"PORTAL_TOKEN": None}

    def test_api_returns_503_when_token_unset(self):
        for method, path in (
            ("GET", "/api/config"),
            ("GET", "/api/servers"),
            ("POST", "/api/sync"),
            ("DELETE", f"/api/servers/{SERVER_ID}?files=true"),
        ):
            with self.subTest(method=method, path=path):
                response, payload = self.request(method, path, token=None)
                self.assertEqual(response.status, 503)
                self.assertEqual(payload["error"], "PORTAL_TOKEN_NOT_CONFIGURED")
                self.assertIn("portal token not configured", payload["message"].lower())
        self.assertEqual(self.app.crafty.calls, [])
        self.assertEqual(self.app.kube.calls, [])

    def test_any_supplied_token_is_rejected_when_unset(self):
        response, payload = self.request("GET", "/api/servers", token="")
        self.assertEqual(response.status, 503)
        response, payload = self.request("GET", "/api/servers", token="guess")
        self.assertEqual(response.status, 503)

    def test_health_and_static_still_work(self):
        response, payload = self.request("GET", "/healthz", token=None)
        self.assertEqual(response.status, 200)
        self.assertEqual(payload, {"status": "ok"})
        response, body = self.request("GET", "/", token=None)
        self.assertEqual(response.status, 200)
        self.assertIn(b"Dripcraft", body)
        response, body = self.request("GET", "/static/app.js", token=None)
        self.assertEqual(response.status, 200)
        self.assertTrue(response.getheader("Content-Type").startswith("application/javascript"))


class BlankTokenTest(PortalServerTestCase):
    env = {"PORTAL_TOKEN": "   "}

    def test_blank_token_counts_as_unset(self):
        self.assertIsNone(self.app.config.portal_token)
        response, payload = self.request("GET", "/api/servers", token="   ")
        self.assertEqual(response.status, 503)


class TokenAuthTest(PortalServerTestCase):
    def test_missing_token_is_rejected(self):
        response, payload = self.request("GET", "/api/servers", token=None)
        self.assertEqual(response.status, 401)
        self.assertEqual(payload["error"], "UNAUTHORIZED")

    def test_wrong_token_is_rejected(self):
        for token in ("", "wrong", TOKEN + "x", TOKEN[:-1], "é" * 4):
            with self.subTest(token=token):
                response, payload = self.request("GET", "/api/servers", token=token)
                self.assertEqual(response.status, 401)
        self.assertEqual(self.app.crafty.calls, [])

    def test_config_requires_token(self):
        response, payload = self.request("GET", "/api/config", token=None)
        self.assertEqual(response.status, 401)

    def test_right_token_is_accepted(self):
        response, payload = self.request("GET", "/api/servers")
        self.assertEqual(response.status, 200)
        self.assertEqual(payload["data"]["servers"][0]["id"], SERVER_ID)
        response, payload = self.request("GET", "/api/config")
        self.assertEqual(response.status, 200)
        self.assertTrue(payload["data"]["authRequired"])

    def test_token_is_compared_in_constant_time(self):
        with mock.patch.object(portal.hmac, "compare_digest", wraps=portal.hmac.compare_digest) as compare:
            response, payload = self.request("GET", "/api/servers")
        self.assertEqual(response.status, 200)
        compare.assert_called_once_with(TOKEN.encode("utf-8"), TOKEN.encode("utf-8"))


class CrossSiteProtectionTest(PortalServerTestCase):
    def test_foreign_origin_is_rejected(self):
        for origin in ("https://evil.example", "null", "http://127.0.0.1:1"):
            with self.subTest(origin=origin):
                response, payload = self.request("POST", "/api/sync", headers={"Origin": origin})
                self.assertEqual(response.status, 403)
                self.assertEqual(payload["error"], "CROSS_ORIGIN_REJECTED")
        response, payload = self.request(
            "DELETE",
            f"/api/servers/{SERVER_ID}?files=true",
            headers={"Origin": "https://evil.example"},
        )
        self.assertEqual(response.status, 403)
        self.assertEqual(self.app.crafty.calls, [])

    def test_same_origin_is_allowed(self):
        response, payload = self.request("POST", "/api/sync", headers={"Origin": self.origin})
        self.assertEqual(response.status, 200)

    def test_missing_origin_is_allowed_with_token(self):
        response, payload = self.request("POST", "/api/sync")
        self.assertEqual(response.status, 200)

    def test_cross_site_fetch_is_rejected(self):
        response, payload = self.request(
            "POST",
            "/api/sync",
            headers={"Origin": self.origin, "Sec-Fetch-Site": "cross-site"},
        )
        self.assertEqual(response.status, 403)
        self.assertEqual(payload["error"], "CROSS_SITE_REJECTED")
        for site in ("same-origin", "none"):
            with self.subTest(site=site):
                response, payload = self.request("POST", "/api/sync", headers={"Sec-Fetch-Site": site})
                self.assertEqual(response.status, 200)

    def test_reads_are_not_origin_checked(self):
        response, payload = self.request("GET", "/api/servers", headers={"Origin": "https://evil.example"})
        self.assertEqual(response.status, 200)

    def test_body_requires_json_content_type(self):
        body = json.dumps({"serverId": SERVER_ID, "port": 25566, "hostname": "sky"}).encode("utf-8")
        for content_type in (None, "text/plain", "application/x-www-form-urlencoded", "multipart/form-data"):
            with self.subTest(content_type=content_type):
                headers = {"Content-Type": content_type} if content_type else {}
                response, payload = self.request("POST", "/api/exposures", body=body, headers=headers)
                self.assertEqual(response.status, 415)
                self.assertEqual(payload["error"], "UNSUPPORTED_MEDIA_TYPE")
        self.assertEqual(self.app.kube.calls, [])
        response, payload = self.request(
            "POST",
            "/api/exposures",
            body=body,
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        self.assertEqual(response.status, 201)

    def test_non_api_writes_are_not_allowed(self):
        response, payload = self.request("POST", "/", json_body={})
        self.assertEqual(response.status, 405)


class BodyLimitTest(PortalServerTestCase):
    def raw_request(self, method, path, headers):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=10)
        try:
            connection.putrequest(method, path)
            for name, value in {"X-Portal-Token": TOKEN, **headers}.items():
                connection.putheader(name, value)
            connection.endheaders()
            response = connection.getresponse()
            return response, json.loads(response.read())
        finally:
            connection.close()

    def test_oversized_body_is_rejected_before_reading(self):
        response, payload = self.raw_request(
            "POST",
            "/api/exposures",
            {"Content-Type": "application/json", "Content-Length": str(portal.MAX_BODY_BYTES + 1)},
        )
        self.assertEqual(response.status, 413)
        self.assertEqual(payload["error"], "PAYLOAD_TOO_LARGE")
        self.assertEqual(self.app.kube.calls, [])

    def test_body_at_limit_is_read(self):
        body = json.dumps({"serverId": SERVER_ID, "port": 25566, "hostname": "sky", "pad": ""})
        body = body.replace('"pad": ""', '"pad": "' + "x" * (portal.MAX_BODY_BYTES - len(body)) + '"')
        self.assertEqual(len(body), portal.MAX_BODY_BYTES)
        response, payload = self.request(
            "POST",
            "/api/exposures",
            body=body.encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(response.status, 201)

    def test_invalid_or_chunked_length_is_rejected(self):
        response, payload = self.raw_request("POST", "/api/sync", {"Content-Length": "1_0"})
        self.assertEqual(response.status, 400)
        response, payload = self.raw_request("POST", "/api/sync", {"Content-Length": "-1"})
        self.assertEqual(response.status, 400)
        response, payload = self.raw_request("POST", "/api/sync", {"Transfer-Encoding": "chunked"})
        self.assertEqual(response.status, 411)


class SecurityHeadersTest(PortalServerTestCase):
    def assert_security_headers(self, response):
        csp = response.getheader("Content-Security-Policy") or ""
        self.assertIn("default-src 'self'", csp)
        self.assertIn("frame-ancestors 'none'", csp)
        self.assertEqual(response.getheader("X-Content-Type-Options"), "nosniff")
        self.assertEqual(response.getheader("Referrer-Policy"), "no-referrer")
        self.assertEqual(response.getheader("X-Frame-Options"), "DENY")

    def test_headers_on_every_kind_of_response(self):
        for method, path, token in (
            ("GET", "/", None),
            ("GET", "/static/styles.css", None),
            ("GET", "/healthz", None),
            ("GET", "/api/servers", TOKEN),
            ("GET", "/api/servers", None),
            ("GET", "/api/nope", TOKEN),
            ("OPTIONS", "/api/servers", None),
        ):
            with self.subTest(method=method, path=path, token=bool(token)):
                response, _ = self.request(method, path, token=token)
                self.assert_security_headers(response)

    def test_api_responses_are_not_cached(self):
        response, _ = self.request("GET", "/api/servers")
        self.assertEqual(response.getheader("Cache-Control"), "no-store")

    def test_index_has_no_inline_script_or_style(self):
        html = (STATIC_ROOT / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("<style", html)
        self.assertNotIn("style=", html)
        self.assertNotRegex(html, r"<script(?![^>]*\bsrc=)")


class ServerIdValidationTest(unittest.TestCase):
    def test_accepts_crafty_uuids(self):
        self.assertEqual(portal.validate_server_id(SERVER_ID), SERVER_ID)
        self.assertEqual(portal.validate_server_id(SERVER_ID.upper()), SERVER_ID.upper())

    def test_rejects_anything_else(self):
        for value in (
            "",
            None,
            "1",
            "abc-123",
            "../../api/v2/users",
            "..%2F..%2Fapi",
            f"{SERVER_ID}/../users",
            f"{SERVER_ID}?files=true",
            f"{SERVER_ID}\n",
            f" {SERVER_ID}",
            SERVER_ID.replace("-", ""),
        ):
            with self.subTest(value=value):
                with self.assertRaises(portal.ValidationError):
                    portal.validate_server_id(value)

    def test_crafty_paths_are_validated_and_fully_escaped(self):
        crafty = portal.CraftyClient(make_config())
        calls = []
        crafty.request = lambda method, path, body=None: calls.append((method, path, body))
        crafty.delete_server(SERVER_ID, True)
        crafty.start_server(SERVER_ID)
        crafty.patch_server_config(SERVER_ID, {"auto_start": True})
        self.assertEqual(
            calls,
            [
                ("DELETE", f"/api/v2/servers/{SERVER_ID}?files=true", None),
                ("POST", f"/api/v2/servers/{SERVER_ID}/action/start_server", None),
                ("PATCH", f"/api/v2/servers/{SERVER_ID}", {"auto_start": True}),
            ],
        )
        with self.assertRaises(portal.ValidationError):
            crafty.delete_server("../../api/v2/users", True)
        with self.assertRaises(portal.ValidationError):
            crafty.get_server("a/b")
        self.assertEqual(len(calls), 3)


class PathSafetyTest(PortalServerTestCase):
    def setUp(self):
        super().setUp()
        # Real Crafty client with only the HTTP call stubbed, to see the upstream path.
        self.crafty_paths = []
        self.app.crafty = portal.CraftyClient(self.app.config)
        self.app.crafty.request = lambda method, path, body=None: self.crafty_paths.append((method, path))

    def test_delete_uses_validated_id(self):
        response, payload = self.request("DELETE", f"/api/servers/{SERVER_ID}?files=true")
        self.assertEqual(response.status, 200)
        self.assertEqual(self.crafty_paths, [("DELETE", f"/api/v2/servers/{SERVER_ID}?files=true")])

    def test_encoded_traversal_is_rejected(self):
        for path in (
            "/api/servers/..%2F..%2Fapi%2Fv2%2Fusers?files=true",
            "/api/servers/..%2f?files=true",
            f"/api/servers/{SERVER_ID}%2F..%2F..%2Fusers?files=true",
            "/api/servers/%2e%2e?files=true",
            "/api/servers/1?files=true",
            "/api/exposures/..%2F..%2Fapi%2Fv2%2Fusers",
        ):
            with self.subTest(path=path):
                response, payload = self.request("DELETE", path)
                self.assertEqual(response.status, 400)
                self.assertEqual(payload["error"], "VALIDATION_ERROR")
        response, payload = self.request("DELETE", "/api/servers/../users?files=true")
        self.assertEqual(response.status, 404)
        self.assertEqual(self.crafty_paths, [])
        self.assertEqual(self.app.kube.calls, [])

    def test_expose_rejects_bad_server_id(self):
        response, payload = self.request(
            "POST",
            "/api/exposures",
            json_body={"serverId": "../x", "hostname": "sky", "port": 25566},
        )
        self.assertEqual(response.status, 400)
        self.assertEqual(self.app.kube.calls, [])


class PortAllowlistTest(unittest.TestCase):
    def test_parse_port_ranges(self):
        self.assertEqual(
            portal.parse_port_ranges("25565-25600, 8100 ,"),
            ((25565, 25600), (8100, 8100)),
        )
        for value in ("", ",", "abc", "0-10", "10-5", "25565-70000", "1-2-3"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    portal.parse_port_ranges(value)

    def test_default_allows_only_minecraft_range(self):
        ranges = make_config().expose_port_ranges
        for port in (25565, 25585, 25665):
            self.assertTrue(portal.port_allowed(port, ranges), port)
        for port in (8443, 8000, 8100, 8123, 19132, 22, 6443, 25564, 25666):
            self.assertFalse(portal.port_allowed(port, ranges), port)

    def test_crafty_panel_ports_are_never_allowed(self):
        ranges = make_config(EXPOSE_ALLOWED_PORTS="1-65535").expose_port_ranges
        self.assertFalse(portal.port_allowed(8443, ranges))
        self.assertFalse(portal.port_allowed(8000, ranges))
        self.assertTrue(portal.port_allowed(8100, ranges))

    def test_invalid_allowlist_fails_at_startup(self):
        with self.assertRaises(ValueError):
            make_config(EXPOSE_ALLOWED_PORTS="minecraft")

    def test_create_checks_port_before_calling_crafty(self):
        app = portal.App(make_config(PORT_RANGE_START="8443", PORT_RANGE_END="8443"))
        app.crafty = FakeCrafty()
        app.kube = FakeKube()
        with self.assertRaises(portal.ValidationError):
            app.create_server({"name": "Sky", "version": "1.21.8", "agreeToEula": True})
        self.assertNotIn("create", [call[0] for call in app.crafty.calls])
        self.assertEqual(app.kube.calls, [])


class ExposurePortTest(PortalServerTestCase):
    def expose(self, port):
        return self.request(
            "POST",
            "/api/exposures",
            json_body={"serverId": SERVER_ID, "name": "Skyblock", "hostname": "sky", "port": port},
        )

    def test_non_minecraft_ports_are_refused(self):
        for port in (8443, 8000, 8100, 8123, 22, 65535):
            with self.subTest(port=port):
                response, payload = self.expose(port)
                self.assertEqual(response.status, 400)
        self.assertEqual(self.app.kube.calls, [])

    def test_minecraft_port_is_exposed(self):
        response, payload = self.expose(25570)
        self.assertEqual(response.status, 201)
        self.assertEqual(self.app.kube.calls[0][1]["target_port"], 25570)

    def test_sync_skips_disallowed_ports(self):
        self.app.crafty.servers = [
            {"id": SERVER_ID, "name": "Panel", "port": 8443},
            {"id": OTHER_SERVER_ID, "name": "Skyblock", "port": 25566},
        ]
        response, payload = self.request("POST", "/api/sync")
        self.assertEqual(response.status, 200)
        self.assertEqual(payload["data"]["createdCount"], 1)
        self.assertEqual(payload["data"]["skipped"][0]["reason"], "port_not_allowed")
        self.assertEqual([call[1]["target_port"] for call in self.app.kube.calls], [25566])


class ConfiguredExposurePortTest(ExposurePortTest):
    env = {"EXPOSE_ALLOWED_PORTS": "25565-25570,8100"}

    def test_non_minecraft_ports_are_refused(self):
        response, payload = self.expose(8100)
        self.assertEqual(response.status, 201)
        for port in (8443, 25571):
            with self.subTest(port=port):
                response, payload = self.expose(port)
                self.assertEqual(response.status, 400)


if __name__ == "__main__":
    unittest.main()
