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


if __name__ == "__main__":
    unittest.main()
