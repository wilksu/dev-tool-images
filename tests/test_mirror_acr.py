"""Exercise skip, update, failure and manifest-preservation behavior without credentials."""

import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
from mirror_acr import Image, Registry, manifest_digest, read_images, synchronize


class MirrorTests(unittest.TestCase):
    def test_list_supports_comments_and_rejects_unsafe_or_duplicate_targets(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "images.txt"
            path.write_text("# comment\ndocker.io/library/nginx:latest nginx:latest # tracked tag\n")
            self.assertEqual(read_images(path), [Image("docker.io/library/nginx:latest", "nginx:latest")])
            for text in (
                "nginx nginx:latest\n",
                "docker.io/library/nginx:latest other/path:latest\n",
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
