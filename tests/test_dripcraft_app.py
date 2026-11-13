"""Run: python -m unittest discover -s tests (requires PyYAML and kubectl)."""
import pathlib
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]


class DripcraftAppTests(unittest.TestCase):
    def test_app_is_deployed_from_its_own_repository(self):
        app = yaml.safe_load((ROOT / "apps" / "dripcraft-public.yaml").read_text())
        self.assertEqual(app["spec"]["source"]["repoURL"], "https://github.com/sbrerup/dripcraft.git")
        self.assertEqual(app["spec"]["source"]["path"], "manifests")
        self.assertEqual(app["spec"]["destination"]["namespace"], "dripcraft-public")
        self.assertTrue(app["spec"]["syncPolicy"]["automated"]["selfHeal"])

    def test_admin_panel_is_deployed_from_its_own_repository(self):
        app = yaml.safe_load((ROOT / "apps" / "dripcraft-admin.yaml").read_text())
        self.assertEqual(app["spec"]["source"]["repoURL"], "https://github.com/sbrerup/mc-server-ui.git")
        self.assertEqual(app["spec"]["source"]["path"], "manifests")
        self.assertEqual(app["spec"]["destination"]["namespace"], "dripcraft-admin")
        self.assertTrue(app["spec"]["syncPolicy"]["automated"]["selfHeal"])

    def test_ledger_is_deployed_from_its_own_private_repository(self):
        text = (ROOT / "apps" / "dripcraft-ledger.yaml").read_text()
        app = yaml.safe_load(text)
        self.assertEqual(app["spec"]["source"]["repoURL"], "https://github.com/sbrerup/dripcraft-ledger.git")
        self.assertEqual(app["spec"]["source"]["path"], "manifests")
        self.assertEqual(app["spec"]["destination"]["namespace"], "dripcraft-ledger")
        self.assertTrue(app["spec"]["syncPolicy"]["automated"]["selfHeal"])
        # What lets Argo CD read the private repository lives only in the cluster.
        for word in ("password", "token", "sshPrivateKey", "username"):
            self.assertNotIn(word, text)


if __name__ == "__main__":
    unittest.main()
