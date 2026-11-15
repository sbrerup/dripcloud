"""Run: python -m unittest discover -s tests (requires PyYAML and kubectl)."""
import pathlib
import subprocess
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
NAMESPACE = "daedalus-access"
ACCOUNT = {"kind": "ServiceAccount", "name": "daedalus", "namespace": NAMESPACE}


class DaedalusAccessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        text = subprocess.check_output(
            ["kubectl", "kustomize", str(ROOT / "manifests" / "daedalus-access")], text=True
        )
        cls.rendered = list(yaml.safe_load_all(text))

    def of_kind(self, *kinds):
        return [obj for obj in self.rendered if obj["kind"] in kinds]

    def test_app_registration(self):
        app = yaml.safe_load((ROOT / "apps" / "daedalus-access.yaml").read_text())
        self.assertEqual(app["spec"]["source"]["path"], "manifests/daedalus-access")
        self.assertEqual(app["spec"]["destination"]["namespace"], NAMESPACE)
        self.assertTrue(app["spec"]["syncPolicy"]["automated"]["selfHeal"])

    def test_roles_only_read_and_never_secrets(self):
        roles = self.of_kind("ClusterRole", "Role")
        self.assertTrue(roles)
        for role in roles:
            for rule in role["rules"]:
                self.assertLessEqual(set(rule["verbs"]), {"get", "list", "watch"})
                self.assertNotIn("*", rule["apiGroups"])
                for resource in rule["resources"]:
                    self.assertNotIn(resource, ("*", "secrets"))
                    # No subresources: pods/exec and pods/portforward are how reading turns into doing.
                    self.assertNotIn("/", resource)
                self.assertNotIn("nonResourceURLs", rule)

    def test_the_account_is_bound_to_reading_and_nothing_else(self):
        bindings = self.of_kind("ClusterRoleBinding", "RoleBinding")
        self.assertEqual({b["roleRef"]["name"] for b in bindings}, {"view", "daedalus-read-extra"})
        for binding in bindings:
            self.assertEqual(binding["roleRef"]["kind"], "ClusterRole")
            self.assertEqual(binding["subjects"], [ACCOUNT])

    def test_the_token_is_made_by_the_cluster_and_no_pod_gets_it(self):
        (secret,) = self.of_kind("Secret")
        self.assertEqual(secret["type"], "kubernetes.io/service-account-token")
        self.assertEqual(secret["metadata"]["annotations"]["kubernetes.io/service-account.name"], "daedalus")
        self.assertNotIn("data", secret)
        self.assertNotIn("stringData", secret)
        (account,) = self.of_kind("ServiceAccount")
        self.assertFalse(account["automountServiceAccountToken"])
        self.assertEqual(self.of_kind("Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob", "Pod"), [])


if __name__ == "__main__":
    unittest.main()
