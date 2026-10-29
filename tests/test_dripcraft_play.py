"""Run: python -m unittest discover -s tests (requires PyYAML and kubectl)."""
import json
import pathlib
import subprocess
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
NAMESPACE = "dripcraft-play"


class DripcraftPlayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        text = subprocess.check_output(
            ["kubectl", "kustomize", str(ROOT / "manifests" / NAMESPACE)], text=True
        )
        cls.objects = {(obj["kind"], obj["metadata"]["name"]): obj for obj in yaml.safe_load_all(text)}

    def pod(self, name):
        return self.objects[("Deployment", name)]["spec"]["template"]["spec"]

    def host(self, ingress):
        return self.objects[("Ingress", ingress)]["spec"]["rules"][0]["host"]

    def test_app_registration(self):
        app = yaml.safe_load((ROOT / "apps" / f"{NAMESPACE}.yaml").read_text())
        self.assertEqual(app["spec"]["source"]["path"], f"manifests/{NAMESPACE}")
        self.assertEqual(app["spec"]["destination"]["namespace"], NAMESPACE)
        self.assertTrue(app["spec"]["syncPolicy"]["automated"]["selfHeal"])
        for obj in self.objects.values():
            self.assertEqual(obj["metadata"]["namespace"], NAMESPACE)

    def test_client_image_is_the_built_commit(self):
        workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "dripcraft-play-image.yaml").read_text())
        image = self.pod("dripcraft-play")["containers"][0]["image"]
        self.assertEqual(image, f"ghcr.io/sbrerup/dripcraft-play:{workflow['env']['MWC_REF']}")

    def test_client_uses_the_private_relay(self):
        configmap = next(obj for (kind, _), obj in self.objects.items() if kind == "ConfigMap")
        config = json.loads(configmap["data"]["config.json"])
        self.assertTrue(config["defaultProxy"].startswith(f"https://{self.host('dripcraft-relay')}."))
        self.assertEqual(config["defaultProxies"], [config["defaultProxy"]])
        relay = self.pod("dripcraft-relay")["containers"][0]
        env = {item["name"]: item["value"] for item in relay["env"]}
        self.assertIn("@sha256:", relay["image"])
        self.assertEqual(env["DISABLE_SIGNAL"], "true")
        self.assertTrue(env["ALLOW_ORIGIN"].startswith(f"https://{self.host('dripcraft-play')}."))

    def test_owner_only_and_hardened(self):
        for name in ("dripcraft-play", "dripcraft-relay"):
            ingress = self.objects[("Ingress", name)]
            self.assertEqual(ingress["metadata"]["annotations"]["tailscale.com/tags"], "tag:k8s-admin")
            pod = self.pod(name)
            self.assertFalse(pod["automountServiceAccountToken"])
            self.assertTrue(pod["securityContext"]["runAsNonRoot"])
            for container in pod["containers"]:
                self.assertTrue(container["securityContext"]["readOnlyRootFilesystem"])

    def test_relay_egress_stays_off_the_lan(self):
        deny = self.objects[("NetworkPolicy", "default-deny")]["spec"]
        self.assertEqual(deny["podSelector"], {})
        self.assertEqual(set(deny["policyTypes"]), {"Ingress", "Egress"})
        egress = self.objects[("NetworkPolicy", "dripcraft-relay-egress")]["spec"]["egress"]
        blocks = [peer["ipBlock"] for rule in egress for peer in rule["to"] if "ipBlock" in peer]
        self.assertEqual([block["cidr"] for block in blocks], ["0.0.0.0/0"])
        self.assertTrue({"10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10"}.issubset(blocks[0]["except"]))
        crafty = yaml.safe_load_all((ROOT / "manifests" / "crafty" / "network-policies.yaml").read_text())
        ingress = next(obj for obj in crafty if obj["metadata"]["name"] == "crafty-ingress")["spec"]["ingress"]
        peers = [peer.get("podSelector", {}).get("matchLabels") for rule in ingress for peer in rule.get("from", [])]
        self.assertIn({"app.kubernetes.io/name": "dripcraft-relay"}, peers)


if __name__ == "__main__":
    unittest.main()
