"""Exercise skip, update, failure and manifest-preservation behavior without credentials."""

import pathlib
import json
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
from mirror_acr import Image, Registry, check_mirror, manifest_digest, read_images, runtime_index, source_digest, synchronize


class MirrorTests(unittest.TestCase):
    def test_status_checks_never_copy_missing_or_existing_images(self):
        digest = "sha256:" + "a" * 64
        image = Image(f"docker.io/library/redis@{digest}", "redis:7.4-alpine")
        for existing, expected in ((None, ("missing", "—")), (digest, ("present", digest))):
            registry = Mock()
            registry.inspect.return_value = existing
            self.assertEqual(check_mirror(image, "acr/ns", registry), expected)
            registry.inspect.assert_called_once_with("acr/ns/redis:7.4-alpine", destination=True)
            registry.copy.assert_not_called()
            registry.copy_runtime_index.assert_not_called()

    def test_runtime_only_keeps_all_platform_manifests_and_is_idempotent(self):
        platforms = [{"digest": "sha256:" + character * 64, "platform": {"os": "linux", "architecture": architecture}}
                     for character, architecture in (("a", "amd64"), ("b", "arm64"))]
        proof = {"digest": "sha256:" + "c" * 64, "annotations": {"vnd.docker.reference.type": "attestation-manifest"}}
        original = json.dumps({"schemaVersion": 2, "mediaType": "application/vnd.oci.image.index.v1+json", "manifests": [*platforms, proof]}).encode()
        filtered = runtime_index(original)
        self.assertEqual(json.loads(filtered)["manifests"], platforms)
        self.assertEqual(runtime_index(filtered), filtered)
        registry = Mock()
        source = "docker.io/moby/buildkit@sha256:" + "d" * 64
        registry.manifests = {source: original}
        registry.inspect.side_effect = [None, manifest_digest(original), manifest_digest(filtered)]
        self.assertEqual(synchronize(Image(source, "buildkit:v1", True), "acr/ns", registry), ("copied", manifest_digest(filtered)))
        registry.copy_runtime_index.assert_called_once_with("docker.io/moby/buildkit", filtered, "acr/ns/buildkit:v1")
        registry.copy.assert_not_called()
        registry.reset_mock()
        registry.inspect.side_effect = [manifest_digest(filtered), manifest_digest(original)]
        self.assertEqual(synchronize(Image(source, "buildkit:v1", True), "acr/ns", registry), ("unchanged", manifest_digest(filtered)))
        registry.copy_runtime_index.assert_not_called()

    def test_runtime_index_publication_reuses_existing_children_and_pushes_index_only(self):
        digest = "sha256:" + "a" * 64
        raw = json.dumps({"schemaVersion": 2, "manifests": [{"digest": digest}]}).encode()
        registry = Registry(pathlib.Path("/tmp/auth.json"), {})
        registry.inspect = Mock(return_value=digest)
        registry.copy = Mock()
        registry.run = Mock(return_value=subprocess.CompletedProcess([], 0, b"", b""))
        registry.copy_runtime_index("docker.io/moby/buildkit", raw, "acr/ns/buildkit:v1")
        registry.inspect.assert_called_once_with(f"acr/ns/buildkit@{digest}", destination=True)
        registry.copy.assert_not_called()
        self.assertIn("index-only", registry.run.call_args.args)
        self.assertIn("--preserve-digests", registry.run.call_args.args)

    def test_throttling_retries_with_backoff_but_authentication_does_not(self):
        throttled = subprocess.CompletedProcess([], 1, b"", b"TOOMANYREQUESTS: concurrent operation limit")
        success = subprocess.CompletedProcess([], 0, b"{}", b"")
        denied = subprocess.CompletedProcess([], 1, b"", b"unauthorized: invalid credentials")
        registry = Registry(pathlib.Path("/tmp/auth.json"), {})
        with patch("subprocess.run", side_effect=[throttled, throttled, success]) as run, patch("time.sleep") as sleep:
            self.assertEqual(registry.run("inspect").returncode, 0)
            self.assertEqual(run.call_count, 3)
            self.assertEqual(sleep.call_count, 2)
            self.assertLess(sleep.call_args_list[0].args[0], sleep.call_args_list[1].args[0])
        with patch("subprocess.run", return_value=denied) as run, patch("time.sleep") as sleep:
            self.assertEqual(registry.run("login").returncode, 1)
            run.assert_called_once()
            sleep.assert_not_called()

    def test_retry_budget_is_bounded_and_timeouts_retry(self):
        failure = subprocess.CompletedProcess([], 1, b"", b"503 Service Unavailable")
        registry = Registry(pathlib.Path("/tmp/auth.json"), {})
        with patch("subprocess.run", return_value=failure) as run, patch("time.sleep"):
            self.assertEqual(registry.run("copy").returncode, 1)
            self.assertEqual(run.call_count, 4)
        with patch("subprocess.run", side_effect=[subprocess.TimeoutExpired("skopeo", 1), subprocess.CompletedProcess([], 0, b"{}", b"")]) as run, patch("time.sleep"):
            self.assertEqual(registry.run("inspect").returncode, 0)
            self.assertEqual(run.call_count, 2)

    def test_pinned_sources_keep_digest_and_remove_tag_for_skopeo(self):
        digest = "sha256:" + "a" * 64
        for source in (f"docker.io/library/redis:7.4-alpine@{digest}", f"docker.io/library/redis@{digest}"):
            with self.subTest(source=source):
                image = Image(source, "redis:7.4-alpine")
                self.assertEqual(image.repository, "docker.io/library/redis")
                self.assertEqual(image.pull_reference, f"docker.io/library/redis@{digest}")
                registry = Mock()
                registry.inspect.side_effect = [None, digest, digest]
                synchronize(image, "acr/ns", registry)
                self.assertEqual(registry.inspect.call_args_list[1].args, (f"docker.io/library/redis@{digest}",))
        image = Image("registry.example:5000/ns/image:tag", "image:tag")
        self.assertEqual(image.repository, "registry.example:5000/ns/image")
        self.assertEqual(image.pull_reference, image.source)

    def test_existing_pinned_mirror_does_not_require_upstream_access(self):
        digest = "sha256:" + "a" * 64
        registry = Mock()
        registry.inspect.return_value = digest
        image = Image(f"docker.io/library/redis:7.4-alpine@{digest}", "redis:7.4-alpine")
        self.assertEqual(synchronize(image, "acr/ns", registry), ("unchanged", digest))
        registry.inspect.assert_called_once_with("acr/ns/redis:7.4-alpine", destination=True)
        registry.copy.assert_not_called()

    def test_single_platform_attestation_index_uses_the_runtime_digest(self):
        runtime = {"digest": "sha256:" + "a" * 64, "platform": {"os": "linux", "architecture": "amd64"}}
        attestation = {"digest": "sha256:" + "b" * 64, "annotations": {"vnd.docker.reference.type": "attestation-manifest"}}
        raw = json.dumps({"manifests": [runtime, attestation]}).encode()
        self.assertEqual(source_digest(raw), runtime["digest"])
        multi_platform = json.dumps({"manifests": [runtime, {"digest": "sha256:" + "c" * 64, "platform": {"os": "linux", "architecture": "arm64"}}, attestation]}).encode()
        self.assertEqual(source_digest(multi_platform), manifest_digest(multi_platform))

    def test_list_supports_comments_and_rejects_unsafe_or_duplicate_targets(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "images.txt"
            path.write_text("# comment\ndocker.io/library/nginx:latest nginx:latest # tracked tag\n")
            self.assertEqual(read_images(path), [Image("docker.io/library/nginx:latest", "nginx:latest")])
            path.write_text("docker.io/moby/buildkit:v1 buildkit:v1 runtime-only\n")
            self.assertEqual(read_images(path), [Image("docker.io/moby/buildkit:v1", "buildkit:v1", True)])
            for text in (
                "nginx nginx:latest\n",
                "docker.io/library/nginx:latest other/path:latest\n",
                "docker.io/library/nginx:latest nginx:latest arbitrary-option\n",
                "docker.io/library/nginx:latest nginx:latest\ndocker.io/library/httpd:latest nginx:latest\n",
            ):
                path.write_text(text)
                with self.assertRaises(ValueError):
                    read_images(path)

    def test_unchanged_image_is_not_copied(self):
        registry = Mock()
        registry.inspect.side_effect = ["sha256:abc", "sha256:abc"]
        self.assertEqual(synchronize(Image("docker.io/library/nginx:latest", "nginx:latest"), "acr/ns", registry), ("unchanged", "sha256:abc"))
        registry.copy.assert_not_called()

    def test_missing_and_updated_images_copy_the_resolved_digest_and_verify(self):
        for previous in (None, "sha256:old"):
            with self.subTest(previous=previous):
                registry = Mock()
                registry.inspect.side_effect = ["sha256:new", previous, "sha256:new"]
                self.assertEqual(synchronize(Image("docker.io/library/nginx:latest", "nginx:latest"), "acr/ns", registry), ("copied", "sha256:new"))
                registry.copy.assert_called_once_with("docker.io/library/nginx@sha256:new", "acr/ns/nginx:latest")

    def test_digest_mismatch_fails(self):
        registry = Mock()
        registry.inspect.side_effect = ["sha256:new", None, "sha256:wrong"]
        with self.assertRaisesRegex(RuntimeError, "destination digest"):
            synchronize(Image("docker.io/library/nginx:latest", "nginx:latest"), "acr/ns", registry)

    def test_only_explicit_not_found_is_treated_as_missing(self):
        registry = Registry(pathlib.Path("/tmp/auth.json"), {"ACR_PASSWORD": "sensitive-password"})
        for error in (b"manifest unknown", b"MANIFEST_UNKNOWN", b"name unknown"):
            registry.run = Mock(return_value=subprocess.CompletedProcess([], 1, b"", error))
            self.assertIsNone(registry.inspect("acr/ns/nginx:latest", destination=True))
            with self.assertRaises(RuntimeError):
                registry.inspect("docker.io/library/nginx:latest")
        for error in (b"unauthorized: sensitive-password", b"denied", b"429 Too Many Requests", b"TLS handshake timeout"):
            registry.run = Mock(return_value=subprocess.CompletedProcess([], 1, b"", error))
            with self.assertRaises(RuntimeError) as caught:
                registry.inspect("acr/ns/nginx:latest", destination=True)
            self.assertNotIn("sensitive-password", str(caught.exception))

    def test_raw_index_digest_and_copy_flags_preserve_all_platforms(self):
        raw = b'{"schemaVersion":2,"manifests":[]}'
        registry = Registry(pathlib.Path("/tmp/auth.json"), {})
        registry.run = Mock(return_value=subprocess.CompletedProcess([], 0, raw, b""))
        self.assertEqual(registry.inspect("docker.io/library/nginx:latest"), manifest_digest(raw))
        registry.copy("docker.io/library/nginx@sha256:abc", "acr/ns/nginx:latest")
        arguments = registry.run.call_args.args
        self.assertIn("--all", arguments)
        self.assertIn("--preserve-digests", arguments)
        self.assertIn("--src-no-creds", arguments)

    def test_subprocesses_do_not_inherit_secrets_and_password_uses_stdin(self):
        secrets = {"ACR_USERNAME": "test-user", "ACR_PASSWORD": "test-password", "ACR_REGISTRY": "test.example", "ACR_NAMESPACE": "test-ns"}
        with patch.dict("os.environ", secrets), patch("subprocess.run") as run:
            run.return_value = subprocess.CompletedProcess([], 0, b"", b"")
            registry = Registry(pathlib.Path("/tmp/auth.json"), secrets)
            registry.login()
            arguments, options = run.call_args
            self.assertNotIn("test-password", arguments[0])
            self.assertEqual(options["input"], b"test-password")
            self.assertTrue(set(secrets).isdisjoint(options["env"]))


if __name__ == "__main__":
    unittest.main()
