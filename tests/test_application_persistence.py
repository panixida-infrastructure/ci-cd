import subprocess
import unittest
from pathlib import Path

import yaml


CHART = Path(__file__).resolve().parents[1] / "charts" / "application"


def render(*values, namespace="development", release="example"):
    return subprocess.run(
        [
            "helm", "template", release, str(CHART), "--namespace", namespace,
            "--set", "image.repository=ghcr.io/example/api", "--set", "image.tag=1",
            *[argument for value in values for argument in ("--set", value)],
        ],
        capture_output=True, text=True, check=False,
    )


class ApplicationPersistenceTests(unittest.TestCase):
    def test_default_deployment_does_not_require_storage(self):
        result = render()
        self.assertEqual(result.returncode, 0, result.stderr)
        resources = list(yaml.safe_load_all(result.stdout))
        self.assertFalse(any(item["kind"] == "PersistentVolumeClaim" for item in resources))
        deployment = next(item for item in resources if item["kind"] == "Deployment")
        self.assertNotIn("strategy", deployment["spec"])
        self.assertNotIn("volumes", deployment["spec"]["template"]["spec"])

    def test_persistent_deployment_reuses_a_retained_claim_in_each_namespace(self):
        for namespace in ("development", "production"):
            with self.subTest(namespace=namespace):
                result = render(
                    "persistence.enabled=true", "persistence.mountPath=/keys",
                    "persistence.size=10Gi", "persistence.storageClass=example-storage",
                    "podSecurityContext.fsGroup=1654", namespace=namespace,
                    release=f"example-{namespace}",
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                resources = list(yaml.safe_load_all(result.stdout))
                claim = next(item for item in resources if item["kind"] == "PersistentVolumeClaim")
                deployment = next(item for item in resources if item["kind"] == "Deployment")
                pod = deployment["spec"]["template"]["spec"]
                self.assertEqual(deployment["spec"]["strategy"], {"type": "Recreate", "rollingUpdate": None})
                self.assertIn(namespace, claim["metadata"]["name"])
                self.assertEqual(claim["spec"]["accessModes"], ["ReadWriteOnce"])
                self.assertEqual(claim["spec"]["resources"]["requests"]["storage"], "10Gi")
                self.assertEqual(claim["spec"]["storageClassName"], "example-storage")
                self.assertEqual(claim["metadata"]["annotations"]["helm.sh/resource-policy"], "keep")
                self.assertEqual(claim["metadata"]["annotations"]["argocd.argoproj.io/sync-wave"], "0")
                self.assertEqual(claim["metadata"]["annotations"]["argocd.argoproj.io/sync-options"], "Prune=false,Delete=false")
                self.assertEqual(pod["volumes"][0]["persistentVolumeClaim"]["claimName"], claim["metadata"]["name"])
                self.assertEqual(pod["containers"][0]["volumeMounts"][0]["mountPath"], "/keys")
                self.assertEqual(pod["securityContext"]["fsGroup"], 1654)

    def test_persistence_rejects_multiple_replicas(self):
        result = render("persistence.enabled=true", "persistence.mountPath=/keys", "replicaCount=2")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("requires replicaCount=1", result.stderr)

    def test_persistence_requires_a_mount_path(self):
        result = render("persistence.enabled=true")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("persistence.mountPath is required", result.stderr)

    def test_long_release_name_keeps_a_valid_matching_claim_name(self):
        result = render("persistence.enabled=true", "persistence.mountPath=/keys", "fullnameOverride=" + "a" * 63)
        self.assertEqual(result.returncode, 0, result.stderr)
        resources = list(yaml.safe_load_all(result.stdout))
        claim = next(item for item in resources if item["kind"] == "PersistentVolumeClaim")
        deployment = next(item for item in resources if item["kind"] == "Deployment")
        name = claim["metadata"]["name"]
        self.assertLessEqual(len(name), 63)
        self.assertEqual(deployment["spec"]["template"]["spec"]["volumes"][0]["persistentVolumeClaim"]["claimName"], name)


if __name__ == "__main__":
    unittest.main()
