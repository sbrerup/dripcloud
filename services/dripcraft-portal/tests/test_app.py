import unittest

from app import (
    build_service_manifest,
    next_free_port,
    sanitize_hostname,
    sanitize_service_name,
    unique_hostname,
    used_ports,
)


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

    def test_used_ports_includes_server_and_service_targets(self):
        ports = used_ports(
            [{"port": 25565}],
            [{"spec": {"ports": [{"targetPort": 25566}]}}],
        )
        self.assertEqual(ports, {25565, 25566})

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


if __name__ == "__main__":
    unittest.main()
