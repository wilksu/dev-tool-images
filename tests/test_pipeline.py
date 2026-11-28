"""Regression tests for event routing, immutable publishing and passive delivery."""

import io
import json
import pathlib
import runpy
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import Mock, patch

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from acr_delivery import completed_record, external_requests, notification_record, plan, select_requests
from change_plan import changed_paths, plan_changes
from github_api import GitHub, SafeRedirect
from image_config import ci_matrix, legacy_catalog, load_catalog
from mirror_acr import Image, Registry, SyncRequest, manifest_digest, resolve_image, run_requests, synchronize
from owned_release import probe
from release_records import load_imports, make_record, to_request, validate_record
from resolve_release import resolve_release

REVISION = "a" * 40
DIGEST = "sha256:" + "b" * 64


def record():
    platforms = load_catalog()["images"]["go-contract-tools"]["platforms"]
    raw = json.dumps({"schemaVersion": 2, "mediaType": "application/vnd.oci.image.index.v1+json", "manifests": [
        {"digest": "sha256:" + char * 64, "size": 123,
         "mediaType": "application/vnd.oci.image.manifest.v1+json", "platform": {"os": "linux", "architecture": platform.split('/')[1]}}
        for char, platform in zip("cd", platforms)] + [
        {"digest": "sha256:" + "e" * 64, "annotations": {"vnd.docker.reference.type": "attestation-manifest"},
         "platform": {"os": "unknown", "architecture": "unknown"}}]}).encode()
    return make_record("go-contract-tools", REVISION, manifest_digest(raw), raw, 123), raw


def notification(value, run_id=123):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("delivery.json", json.dumps({"schema": 1, "publisher_run_id": run_id, "record": value}))
    return output.getvalue()


class RoutingTests(unittest.TestCase):
    def test_mirror_and_documentation_changes_never_build_tools(self):
        for paths in (["README.md"], ["mirrors/images.txt"], ["scripts/mirror_acr.py", "scripts/acr_delivery.py"],
                      ["releases/imported.json", ".github/workflows/mirror-acr.yml"],
                      ["images/android-go-tools/README.md"]):
            self.assertEqual(plan_changes(paths)["matrix"], {"include": []})

    def test_owned_changes_route_only_to_their_platforms(self):
        android = plan_changes(["fixtures/android-go/build.gradle.kts"])
        self.assertEqual(android["images"], ["android-go-tools"])
        self.assertEqual([x["platform"] for x in android["matrix"]["include"]], ["linux/amd64"])
        mixed = plan_changes(["images/go-contract-tools/image.json", "fixtures/playwright/test.ts"])
        self.assertEqual(len(mixed["matrix"]["include"]), 4)
        self.assertEqual(plan_changes(["scripts/verify_candidate.py"])["matrix"], ci_matrix(load_catalog()))

    def test_pr_and_push_diffs_include_deletions_and_rename_boundaries(self):
        event = {"pull_request": {"base": {"sha": "a" * 40}, "head": {"sha": "b" * 40}}}
        with patch("change_plan.subprocess.run", return_value=Mock(stdout=b"images/go-contract-tools/old\0images/android-go-tools/new\0")) as run:
            self.assertEqual(len(changed_paths("pull_request", event)), 2)
            self.assertIn("--no-renames", run.call_args.args[0])
            self.assertTrue(run.call_args.args[0][-1].endswith("a" * 40 + "..." + "b" * 40))
            changed_paths("push", {"before": "a" * 40, "after": "b" * 40})
            self.assertIn("..", run.call_args.args[0][-1])
        with self.assertRaises(ValueError):
            changed_paths("push", {"before": "--bad", "after": "b" * 40})

    def test_catalog_keeps_public_v1_contract_and_accepts_android_releases(self):
        self.assertEqual(legacy_catalog(), json.loads((ROOT / "catalog/v1/images.json").read_text()))
        outputs, _ = resolve_release("android-go-tools/rev-" + REVISION, REVISION)
        self.assertEqual(outputs["platforms"], "linux/amd64")
        with self.assertRaises(ValueError):
            resolve_release("android-go-tools/rev-" + REVISION, "f" * 40)

    def test_android_variant_builder_uses_shared_arguments_and_named_inventory(self):
        module = runpy.run_path(str(ROOT / "images/android-go-tools/build.py"))
        with patch("sys.argv", ["build.py", "--oci", "/tmp/variant-oci"]), patch("subprocess.run") as run:
            module["main"]()
        command = run.call_args.args[0]
        arguments = [command[index + 1] for index, item in enumerate(command) if item == "--build-arg"]
        from image_config import build_arguments, load_image
        self.assertEqual(arguments, build_arguments(load_image("android-go-tools")[1]))
        self.assertIn("--build-context", command)
        self.assertNotIn("--push", command)


class RecordTests(unittest.TestCase):
    def test_historical_import_preserves_all_four_original_digests_and_aliases(self):
        imports = load_imports()
        self.assertEqual(len(imports), 4)
        self.assertEqual(len(external_requests()), 48)
        for value in imports:
            request = to_request(value)
            self.assertTrue(request.preserve_index)
            self.assertEqual(request.expected_digest, value["source"].split("@")[1])
        self.assertIn("go-contract-tools:sha-ea884874ca2b", {r["target"] for r in imports})

    def test_generated_record_preserves_runtime_platforms_and_pins_transformed_bytes(self):
        value, _ = record()
        request = to_request(value)
        self.assertNotEqual(value["acr_digest"], value["source"].split("@")[1])
        self.assertEqual(manifest_digest(request.runtime_manifest), value["acr_digest"])
        self.assertEqual(len(json.loads(request.runtime_manifest)["manifests"]), 2)
        self.assertEqual(validate_record(value), value)

    def test_tampered_release_records_are_rejected(self):
        original, _ = record()
        for key, value in (("source", "docker.io/attacker/image@" + DIGEST), ("target", "other:tag"),
                           ("acr_digest", DIGEST), ("revision", "f" * 40), ("platforms", ["linux/amd64"]),
                           ("source_run_id", True), ("acr_manifest", "not-base64"),
                           ("image", []), ("platforms", [{}]), ("acr_digest", None)):
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_record({**original, key: value})

    def test_conflicting_targets_or_unknown_manual_selection_fail(self):
        value, _ = record()
        request = to_request(value)
        self.assertEqual(select_requests([request, request], "go-contract-tools"), [request])
        with self.assertRaises(ValueError):
            select_requests([request, SyncRequest(Image("docker.io/library/node:24", request.image.target))])
        with self.assertRaises(ValueError):
            select_requests([request], "unknown")


class PassiveDeliveryTests(unittest.TestCase):
    def github(self):
        value, _ = record()
        github = Mock(repository="wilksu/dev-tool-images", prefix="/repos/wilksu/dev-tool-images")
        run = {"id": 123, "status": "completed", "conclusion": "success", "event": "push", "head_sha": REVISION,
               "repository": {"full_name": github.repository}, "head_repository": {"full_name": github.repository}, "workflow_id": 99}
        workflow = {"path": ".github/workflows/publish.yml"}
        artifacts = {"artifacts": [{"id": 456, "name": "release-record", "expired": False, "size_in_bytes": 1000}]}
        github.json.side_effect = [run, workflow, artifacts]
        github.request.return_value = notification(value)
        github.tag_revision.return_value = REVISION
        github.release.return_value = {"draft": False}
        github.release_record.return_value = value
        return github, run, workflow, artifacts, value

    def test_successful_notification_copies_only_that_owned_release(self):
        github, _, _, _, value = self.github()
        requests = plan(github, "workflow_run", {"workflow_run": {"id": 123}})
        self.assertEqual(requests, [to_request(value)])
        self.assertIn("/actions/artifacts/456/zip", github.request.call_args.args[1])
        github.pages.assert_not_called()

    def test_wrong_source_workflow_fork_failed_run_and_mismatched_sha_are_rejected(self):
        for mutation in ("failure", "pull_request", "fork", "workflow", "sha"):
            github, run, workflow, _, _ = self.github()
            if mutation == "failure": run["conclusion"] = "failure"
            if mutation == "pull_request": run["event"] = "pull_request"
            if mutation == "fork": run["head_repository"]["full_name"] = "someone/fork"
            if mutation == "workflow": workflow["path"] = ".github/workflows/ci.yml"
            if mutation == "sha": run["head_sha"] = "f" * 40
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                completed_record(github, 123)

    def test_draft_missing_or_changed_release_cannot_notify(self):
        for mutation in ("draft", "missing", "different", "expired"):
            github, _, _, artifacts, _ = self.github()
            if mutation == "draft": github.release.return_value = {"draft": True}
            if mutation == "missing": github.release.return_value = None
            if mutation == "different": github.release_record.return_value = {}
            if mutation == "expired": artifacts["artifacts"][0]["expired"] = True
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                completed_record(github, 123)

    def test_artifact_is_bounded_data_and_run_identity_is_checked(self):
        value, _ = record()
        self.assertEqual(notification_record(notification(value), 123), value)
        for raw in (notification(value, 456), notification({**value, "source_run_id": 456})):
            with self.assertRaises(ValueError):
                notification_record(raw, 123)
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("../delivery.json", "{}")
        with self.assertRaises(ValueError):
            notification_record(output.getvalue(), 123)

    def test_schedule_reconciles_published_records_without_building(self):
        value, _ = record()
        github = Mock()
        github.pages.return_value = [{"tag_name": value["release_tag"], "draft": False}]
        github.release_record.return_value = value
        selected = plan(github, "schedule", {}, value["target"])
        self.assertEqual(selected, [to_request(value)])


class PublicationTests(unittest.TestCase):
    def test_existing_matching_release_is_reused_and_unknown_tags_are_not_overwritten(self):
        value, _ = record()
        outputs, _ = resolve_release(value["release_tag"], REVISION)
        registry, github = Mock(), Mock()
        registry.inspect.return_value = value["source"].split("@")[1]
        self.assertFalse(probe(registry, github, outputs, value))
        with self.assertRaisesRegex(ValueError, "unrecorded"):
            probe(registry, github, outputs, None)
        registry.inspect.return_value = DIGEST
        with self.assertRaisesRegex(ValueError, "immutable"):
            probe(registry, github, outputs, value)
        registry.inspect.return_value = None
        self.assertTrue(probe(registry, github, outputs, value))

    def test_record_asset_is_immutable(self):
        value, _ = record()
        github = GitHub("wilksu/dev-tool-images", token="")
        github.release = Mock(return_value={"id": 7})
        github.release_record = Mock(return_value=value)
        github.request = Mock()
        self.assertEqual(github.save_record(value), {"id": 7})
        with self.assertRaisesRegex(ValueError, "immutable"):
            github.save_record({**value, "acr_digest": DIGEST})
        github.request.assert_not_called()

    def test_github_redirect_drops_credentials_outside_api_host(self):
        import urllib.request
        redirect = SafeRedirect()
        request = urllib.request.Request("https://api.github.com/asset", headers={"Authorization": "Bearer secret"})
        target = redirect.redirect_request(request, None, 302, "", {}, "https://blob.example/file")
        self.assertFalse(target.has_header("Authorization"))
        with self.assertRaises(ValueError):
            redirect.redirect_request(request, None, 302, "", {}, "http://blob.example/file")


class DeliveryEngineTests(unittest.TestCase):
    def test_owned_runtime_index_skip_never_reads_upstream(self):
        value, _ = record()
        request = to_request(value)
        registry = Mock()
        registry.inspect.return_value = request.expected_digest
        self.assertEqual(synchronize(request.image, "acr/ns", registry,
                         expected_digest=request.expected_digest, runtime_manifest=request.runtime_manifest),
                         ("unchanged", request.expected_digest))
        registry.inspect.assert_called_once_with("acr/ns/" + value["target"], destination=True)
        registry.copy.assert_not_called()

    def test_recorded_index_bytes_are_reused_and_source_tampering_is_detected(self):
        value, raw = record()
        request = to_request(value)
        registry = Mock(manifests={request.image.pull_reference: raw})
        registry.inspect.return_value = manifest_digest(raw)
        self.assertEqual(resolve_image(request.image, registry, runtime_manifest=request.runtime_manifest),
                         (request.expected_digest, request.runtime_manifest))
        with self.assertRaises(ValueError):
            resolve_image(request.image, registry, runtime_manifest=b'{"manifests":[]}')

    def test_historical_single_platform_wrapper_is_preserved_exactly(self):
        runtime = {"digest": DIGEST}
        raw = json.dumps({"manifests": [runtime, {"digest": "sha256:" + "c" * 64,
                           "annotations": {"vnd.docker.reference.type": "attestation-manifest"}}]}).encode()
        image = Image("ghcr.io/owner/image@" + manifest_digest(raw), "owned:old")
        registry = Mock(manifests={image.pull_reference: raw})
        registry.inspect.return_value = DIGEST
        self.assertEqual(resolve_image(image, registry, preserve_index=True), (manifest_digest(raw), None))

    def test_failures_do_not_hide_other_results_and_credentials_are_redacted(self):
        requests = [SyncRequest(Image("docker.io/library/nginx:latest", "nginx:latest")),
                    SyncRequest(Image("docker.io/library/redis:7", "redis:7"))]
        secrets = {"ACR_USERNAME": "user", "ACR_PASSWORD": "password", "ACR_REGISTRY": "acr.example", "ACR_NAMESPACE": "namespace"}
        with tempfile.TemporaryDirectory() as directory, patch("mirror_acr.credentials", return_value=secrets), \
                patch.object(Registry, "login"), patch("mirror_acr.synchronize", side_effect=[RuntimeError("password"), ("unchanged", DIGEST)]), \
                patch("sys.stderr", new_callable=io.StringIO) as stderr:
            report = pathlib.Path(directory) / "report.json"
            self.assertEqual(run_requests(requests, report_path=report), 1)
            self.assertNotIn("password", stderr.getvalue())
            self.assertEqual([r["status"] for r in json.loads(report.read_text())], ["failed", "unchanged"])
            self.assertNotIn("acr.example", report.read_text())


def workflow(name):
    document = yaml.safe_load((ROOT / ".github/workflows" / name).read_text())
    # PyYAML follows YAML 1.1; GitHub treats the key `on` as a string.
    document["on"] = document.pop(True, document.get("on"))
    return document


class WorkflowContractTests(unittest.TestCase):
    def test_ci_always_reports_a_gate_and_all_images_share_verification(self):
        ci = workflow("ci.yml")
        for event in ("push", "pull_request"):
            self.assertNotIn("paths-ignore", ci["on"][event])
        self.assertEqual(ci["jobs"]["result"]["if"], "always()")
        self.assertEqual(ci["jobs"]["build-and-verify"]["uses"], "./.github/workflows/build-image.yml")
        self.assertNotIn("packages", ci["permissions"])
        self.assertFalse((ROOT / ".github/workflows/android-go-tools.yml").exists())

    def test_only_revision_tags_publish_and_runtime_gates_precede_upload(self):
        publish = workflow("publish.yml")
        self.assertEqual(publish["on"], {"push": {"tags": ["*/rev-*"]}})
        self.assertEqual(publish["jobs"]["candidate"]["uses"], "./.github/workflows/build-image.yml")
        self.assertEqual(set(publish["jobs"]["publish"]["needs"]), {"prepare", "candidate"})
        self.assertIn("needs.candidate.result == 'success'", publish["jobs"]["publish"]["if"])
        self.assertNotIn("ACR_", (ROOT / ".github/workflows/publish.yml").read_text())
        publication = publish["jobs"]["publish"]["steps"]
        login = next(i for i, step in enumerate(publication) if step.get("uses", "").startswith("docker/login-action@"))
        provenance = next(i for i, step in enumerate(publication) if step.get("uses", "").startswith("actions/attest-build-provenance@"))
        self.assertLess(login, provenance)
        self.assertEqual(publication[login]["with"]["registry"], "ghcr.io")
        candidate = workflow("build-image.yml")
        steps = candidate["jobs"]["verify"]["steps"]
        verify = next(i for i, step in enumerate(steps) if step.get("id") == "verify")
        upload = next(i for i, step in enumerate(steps) if step.get("uses", "").startswith("actions/upload-artifact@"))
        self.assertLess(verify, upload)
        self.assertEqual(steps[upload]["if"], "inputs.release")
        self.assertNotIn("secrets", candidate["on"]["workflow_call"])

    def test_acr_passively_listens_and_all_uploads_use_one_queue(self):
        mirror = workflow("mirror-acr.yml")
        self.assertEqual(mirror["on"]["workflow_run"], {"workflows": ["Publish"], "types": ["completed"]})
        self.assertEqual(set(mirror["on"]["push"]["paths"]), {"mirrors/images.txt", "releases/imported.json"})
        self.assertNotIn("pull_request", mirror["on"])
        sync = mirror["jobs"]["sync"]
        self.assertIn("conclusion == 'success'", sync["if"])
        self.assertIn("github.ref == 'refs/heads/master'", sync["if"])
        self.assertEqual(sync["concurrency"]["queue"], "max")
        self.assertFalse(sync["concurrency"]["cancel-in-progress"])
        checkout = next(step for step in sync["steps"] if step.get("uses", "").startswith("actions/checkout@"))
        self.assertNotIn("ref", checkout["with"])
        self.assertFalse(checkout["with"]["persist-credentials"])


if __name__ == "__main__":
    unittest.main()
