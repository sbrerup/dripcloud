"""Run: python -m unittest discover -s tests (requires PyYAML)."""
import json
import pathlib
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
FOLDER = ROOT / "manifests" / "local-path-provisioner"


class DataDiskTrimTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.objects = [
            obj for file in sorted(FOLDER.glob("*.yaml")) for obj in yaml.safe_load_all(file.read_text()) if obj
        ]
        (cls.cronjob,) = [obj for obj in cls.objects if obj["kind"] == "CronJob"]
        cls.pod = cls.cronjob["spec"]["jobTemplate"]["spec"]["template"]["spec"]
        (cls.container,) = cls.pod["containers"]

    def test_it_trims_the_folder_the_provisioner_puts_volumes_in(self):
        config = next(obj for obj in self.objects if obj["kind"] == "ConfigMap")
        paths = [path for node in json.loads(config["data"]["config.json"])["nodePathMap"] for path in node["paths"]]
        (volume,) = self.pod["volumes"]
        self.assertEqual([volume["hostPath"]["path"]], paths)

    def test_it_can_trim_and_nothing_more(self):
        context = self.container["securityContext"]
        self.assertNotIn("privileged", context)
        self.assertEqual(context["capabilities"], {"drop": ["ALL"], "add": ["SYS_ADMIN"]})
        self.assertIs(context["allowPrivilegeEscalation"], False)
        self.assertIs(context["readOnlyRootFilesystem"], True)
        # Read-only, so the job cannot change a file on any volume.
        (mount,) = self.container["volumeMounts"]
        self.assertIs(mount["readOnly"], True)
        self.assertIs(self.pod["automountServiceAccountToken"], False)

    def test_its_namespace_lets_the_capability_through(self):
        namespace = next(obj for obj in self.objects if obj["kind"] == "Namespace")
        self.assertEqual(self.cronjob["metadata"]["namespace"], namespace["metadata"]["name"])
        self.assertEqual(namespace["metadata"]["labels"]["pod-security.kubernetes.io/enforce"], "privileged")

    def test_it_runs_once_a_week_before_the_nightly_backup_of_the_vm(self):
        minute, hour, day, month, weekday = self.cronjob["spec"]["schedule"].split()
        self.assertEqual((day, month), ("*", "*"))
        self.assertRegex(weekday, r"^[0-7]$")
        # The backup starts at 03:30 on the host, in the same time zone.
        self.assertEqual(self.cronjob["spec"]["timeZone"], "Europe/Copenhagen")
        self.assertLess((int(hour), int(minute)), (3, 30))

    def test_a_run_never_overlaps_or_repeats(self):
        self.assertEqual(self.cronjob["spec"]["concurrencyPolicy"], "Forbid")
        self.assertEqual(self.cronjob["spec"]["jobTemplate"]["spec"]["backoffLimit"], 0)

    def test_the_image_is_pinned_by_digest(self):
        self.assertRegex(self.container["image"], r":[\w.-]+@sha256:[0-9a-f]{64}$")


if __name__ == "__main__":
    unittest.main()
