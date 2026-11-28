"""Exercise verified-content assembly using tiny, fully hashed OCI images."""

import io
import json
import pathlib
import sys
import tarfile
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from oci_artifacts import INDEX, MANIFEST, blob_path, combine, digest_bytes, encode, read_blob, root_digest, runtime_entries, unpack, verify_candidate
from owned_release import publish_candidates
from resolve_release import resolve_release
from unittest.mock import Mock

REVISION = "a" * 40
NAME = "go-contract-tools"


def fixture(layout, arch="amd64"):
    (layout / "blobs/sha256").mkdir(parents=True)

    def blob(value, media_type):
        raw = value if isinstance(value, bytes) else encode(value)
        digest = digest_bytes(raw)
        blob_path(layout, digest).write_bytes(raw)
        return {"mediaType": media_type, "size": len(raw), "digest": digest}

    config = blob({"architecture": arch, "os": "linux", "config": {"Labels": {
        "org.opencontainers.image.revision": REVISION, "io.starferry.tool.name": NAME}}},
        "application/vnd.oci.image.config.v1+json")
    layer = blob(b"tiny runtime layer " + arch.encode(), "application/vnd.oci.image.layer.v1.tar")
    runtime = blob({"schemaVersion": 2, "mediaType": MANIFEST, "config": config, "layers": [layer]}, MANIFEST)
    runtime["platform"] = {"os": "linux", "architecture": arch}
    proof_config = blob({"architecture": "unknown", "os": "unknown"}, "application/vnd.oci.image.config.v1+json")
    proof = blob({"schemaVersion": 2, "mediaType": MANIFEST, "config": proof_config, "layers": []}, MANIFEST)
    proof["annotations"] = {"vnd.docker.reference.type": "attestation-manifest", "vnd.docker.reference.digest": runtime["digest"]}
    proof["platform"] = {"os": "unknown", "architecture": "unknown"}
    root = blob({"schemaVersion": 2, "mediaType": INDEX, "manifests": [runtime, proof]}, INDEX)
    (layout / "oci-layout").write_bytes(encode({"imageLayoutVersion": "1.0.0"}))
    (layout / "index.json").write_bytes(encode({"schemaVersion": 2, "mediaType": INDEX, "manifests": [root]}))
    receipt = verify_candidate(layout, root["digest"], NAME, REVISION, "linux/" + arch)
    receipt["verified"] = True
    return root["digest"], receipt, runtime, layer


class OCITests(unittest.TestCase):
    def test_buildkit_direct_index_export_is_materialized_again_after_unpack(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory)
            layout = path / "candidate"
            digest, receipt, _, _ = fixture(layout)
            raw = blob_path(layout, digest).read_bytes()
            (layout / "index.json").write_bytes(raw)
            blob_path(layout, digest).unlink()
            # The verifier materializes the missing root in its extracted
            # view, but the original tar sent to publication is unchanged.
            self.assertEqual(root_digest(layout, digest), digest)
            blob_path(layout, digest).unlink()
            self.assertEqual(root_digest(layout), digest)
            blob_path(layout, digest).unlink()
            result = combine([(layout, receipt)], path / "combined", NAME, REVISION, ["linux/amd64"])
            self.assertEqual(set(runtime_entries(path / "combined", result)), {"linux/amd64"})

    def test_merging_keeps_the_tested_runtime_bytes_and_all_attestations(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory)
            candidates = []
            runtimes = {}
            for arch in ("amd64", "arm64"):
                layout = path / arch
                _, receipt, runtime, _ = fixture(layout, arch)
                candidates.append((layout, receipt))
                runtimes["linux/" + arch] = runtime["digest"]
            merged = path / "combined"
            digest = combine(candidates, merged, NAME, REVISION, list(runtimes))
            self.assertEqual(root_digest(merged), digest)
            self.assertEqual({key: item["digest"] for key, item in runtime_entries(merged, digest).items()}, runtimes)
            self.assertEqual(len(read_blob(merged, digest)["manifests"]), 4)
            for layout, receipt in candidates:
                config = receipt["config_digest"]
                self.assertEqual(blob_path(layout, config).read_bytes(), blob_path(merged, config).read_bytes())

    def test_missing_duplicate_or_unverified_candidates_cannot_publish(self):
        for condition in ("missing", "duplicate", "unverified", "receipt"):
            with tempfile.TemporaryDirectory() as directory:
                path = pathlib.Path(directory)
                layout = path / "source"
                _, receipt, _, _ = fixture(layout)
                candidates = [(layout, receipt)]
                if condition == "duplicate": candidates *= 2
                if condition == "unverified": receipt["verified"] = False
                if condition == "receipt": receipt["config_digest"] = "sha256:" + "b" * 64
                with self.subTest(condition=condition), self.assertRaises(ValueError):
                    combine(candidates, path / "dest", NAME, REVISION, ["linux/amd64", "linux/arm64"])

    def test_blob_corruption_and_wrong_source_or_platform_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory)
            root, _, _, layer = fixture(path)
            for revision, platform in (("f" * 40, "linux/amd64"), (REVISION, "linux/arm64")):
                with self.assertRaises(ValueError):
                    verify_candidate(path, root, NAME, revision, platform)
            blob_path(path, layer["digest"]).write_bytes(b"corrupted")
            with self.assertRaises(ValueError):
                verify_candidate(path, root, NAME, REVISION, "linux/amd64")

    def test_tar_unpack_refuses_traversal_and_symlinks(self):
        for name, kind in (("../escape", tarfile.REGTYPE), ("blobs/sha256/link", tarfile.SYMTYPE)):
            with tempfile.TemporaryDirectory() as directory:
                path = pathlib.Path(directory)
                archive = path / "image.tar"
                with tarfile.open(archive, "w") as output:
                    entry = tarfile.TarInfo(name)
                    entry.type = kind
                    entry.linkname = "/etc/passwd" if kind == tarfile.SYMTYPE else ""
                    output.addfile(entry, io.BytesIO())
                with self.assertRaises(ValueError):
                    unpack(archive, path / "dest")

    def test_publication_persists_verified_intent_before_copy_and_reuses_it_on_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory)
            artifacts = path / "artifacts"
            artifacts.mkdir()
            for arch in ("amd64", "arm64"):
                source = path / arch
                _, receipt, _, _ = fixture(source, arch)
                candidate = artifacts / f"candidate-{NAME}-{arch}"
                candidate.mkdir()
                (candidate / "candidate.json").write_text(json.dumps(receipt))
                with tarfile.open(candidate / "image.tar", "w") as archive:
                    for file in source.iterdir(): archive.add(file, arcname=file.name)
            outputs, _ = resolve_release(NAME + "/rev-" + REVISION, REVISION)
            github, registry = Mock(), Mock(authfile=path / "auth.json")
            events = []
            github.save_record.side_effect = lambda value: events.append(("record", value))
            def copy(*args, **kwargs):
                self.assertEqual(events[0][0], "record")
                events.append(("copy", args))
                return Mock(returncode=0)
            registry.run.side_effect = copy
            # Deliberately fail after publication; the durable draft must still
            # identify the original candidates and run for the next attempt.
            registry.inspect.return_value = None
            work = path / "work"
            work.mkdir()
            with self.assertRaisesRegex(ValueError, "published GHCR digest"):
                publish_candidates(registry, github, outputs, artifacts, work, 123, None)
            value = events[0][1]
            registry.inspect.return_value = value["source"].split("@")[1]
            work2 = path / "retry"
            work2.mkdir()
            result = publish_candidates(registry, github, outputs, artifacts, work2, 123, value)
            self.assertEqual(result, value)
            self.assertEqual(result["source_run_id"], 123)


if __name__ == "__main__":
    unittest.main()
