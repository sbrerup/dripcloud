"""Run: python -m unittest discover -s tests (requires PyYAML and kubectl)."""
import pathlib
import subprocess
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
NAMESPACE = "beamray-agent-services"


class WebServicesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rendered = {}
        for app in ("firecrawl", "searxng", "firecrawl-network"):
            text = subprocess.check_output(
                ["kubectl", "kustomize", str(ROOT / "manifests" / app)], text=True
            )
            cls.rendered[app] = list(yaml.safe_load_all(text))

    def test_app_registration(self):
        for name in self.rendered:
            app = yaml.safe_load((ROOT / "apps" / f"{name}.yaml").read_text())
            self.assertEqual(app["spec"]["source"]["path"], f"manifests/{name}")
            self.assertEqual(app["spec"]["destination"]["namespace"], NAMESPACE)
            self.assertTrue(app["spec"]["syncPolicy"]["automated"]["selfHeal"])

    def test_unique_ownership_and_no_plaintext_secrets(self):
        seen = set()
        for resources in self.rendered.values():
            for obj in resources:
                identity = (obj["kind"], obj["metadata"]["name"])
                self.assertNotIn(identity, seen)
                seen.add(identity)
                self.assertEqual(obj["metadata"]["namespace"], NAMESPACE)
                self.assertNotIn(obj["kind"], ("Secret", "Namespace"))
                self.assertNotIn("status", obj)
                if obj["kind"] == "SealedSecret":
                    self.assertTrue(obj["spec"]["encryptedData"])
                    self.assertNotIn("data", obj["spec"]["template"])
                    self.assertNotIn("stringData", obj["spec"]["template"])

    def test_workloads_and_retained_storage(self):
        deployments = []
        claims = []
        for resources in self.rendered.values():
            for obj in resources:
                if obj["kind"] == "Deployment":
                    deployments.append(obj)
                    pod = obj["spec"]["template"]
                    for key, value in obj["spec"]["selector"]["matchLabels"].items():
                        self.assertEqual(pod["metadata"]["labels"][key], value)
                    self.assertFalse(pod["spec"]["automountServiceAccountToken"])
                    for container in pod["spec"]["containers"]:
                        self.assertIn("@sha256:", container["image"])
                if obj["kind"] == "PersistentVolumeClaim":
                    claims.append(obj)
                    self.assertEqual(obj["spec"]["storageClassName"], "local-path-retain")
                    self.assertNotIn("volumeName", obj["spec"])
                    self.assertEqual(obj["metadata"]["annotations"]["argocd.argoproj.io/sync-options"], "Prune=false,Delete=false")
        self.assertEqual(len(deployments), 6)
        self.assertEqual(len(claims), 3)

    def test_network_guards_survive_migration(self):
        policies = {obj["metadata"]["name"]: obj for obj in self.rendered["firecrawl-network"]}
        public = policies["firecrawl-public-web-egress"]["spec"]
        self.assertEqual(public["policyTypes"], ["Egress"])
        self.assertEqual(set(public["podSelector"]["matchExpressions"][0]["values"]), {"firecrawl-api", "firecrawl-playwright"})
        blocks = [peer["ipBlock"] for rule in public["egress"] for peer in rule["to"] if "ipBlock" in peer]
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["cidr"], "0.0.0.0/0")
        self.assertTrue({"10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10", "169.254.0.0/16"}.issubset(blocks[0]["except"]))
        dependencies = policies["firecrawl-api-dependencies-egress"]["spec"]
        self.assertEqual(dependencies["podSelector"]["matchLabels"]["app.kubernetes.io/name"], "firecrawl-api")
        internal = policies["firecrawl-internal-ingress"]["spec"]
        self.assertEqual(internal["policyTypes"], ["Ingress"])
        self.assertEqual(
            set(internal["podSelector"]["matchExpressions"][0]["values"]),
            {"firecrawl-redis", "firecrawl-rabbitmq", "firecrawl-nuq-postgres", "firecrawl-playwright"},
        )
        self.assertEqual(
            [peer["podSelector"]["matchLabels"] for rule in internal["ingress"] for peer in rule["from"]],
            [{"app.kubernetes.io/name": "firecrawl-api"}],
        )


if __name__ == "__main__":
    unittest.main()
