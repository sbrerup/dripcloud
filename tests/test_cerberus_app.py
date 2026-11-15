"""Run: python -m unittest discover -s tests (requires PyYAML and kubectl)."""
import pathlib
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]


class CerberusAppTests(unittest.TestCase):
    def test_app_is_deployed_from_its_own_repository(self):
        app = yaml.safe_load((ROOT / "apps" / "cerberus.yaml").read_text())
        self.assertEqual(app["spec"]["source"]["repoURL"], "https://github.com/sbrerup/cerberus.git")
        self.assertEqual(app["spec"]["source"]["path"], "manifests")
        self.assertEqual(app["spec"]["destination"]["namespace"], "cerberus")
        self.assertTrue(app["spec"]["syncPolicy"]["automated"]["selfHeal"])

    def test_daedalus_gets_no_more_than_reading_from_this_repository(self):
        # cerberus lets daedalus file requests, and that binding lives with cerberus.
        # Nothing here may hand the account anything on top of it.
        text = "".join(path.read_text() for path in (ROOT / "manifests" / "daedalus-access").glob("*.yaml"))
        self.assertNotIn("cerberus", text)
        self.assertNotIn("commandrequests", text)


if __name__ == "__main__":
    unittest.main()
