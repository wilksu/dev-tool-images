# dev-tool-images

Public, reproducible development tool images used by Star-Ferry and other
consumers. This repository owns the source configuration and release process;
consumers accept immutable OCI digests instead of rebuilding these toolchains.

## Images

| Logical name | Purpose | Browser binaries |
| --- | --- | --- |
| `go-contract-tools` | Go, controller-gen, Buf, Protobuf/Python gRPC, OpenAPI, TypeScript, and Prettier tools | N/A |
| `playwright-client-tools` | Playwright client, Node types, and TypeScript for browserless test discovery and execution | No |
| `android-go-tools` | JDK, Go, Android SDK and NDK for Hermes APK builds; Linux amd64 host | N/A |

The Android image uses its dedicated [configuration and release workflow](images/android-go-tools/README.md).
Its existing published revision is `d6127ae7de088d8b93782b03b0c849322e0383d2`;
the restored source is maintained here and builds on Android-specific changes
and revision tags. The stable discovery API for the Go and Playwright images is
[`catalog/v1/images.json`](catalog/v1/images.json),
which also publishes the inventory pointers and their
[`inventory.schema.json`](catalog/v1/inventory.schema.json).
Each catalog entry points to a schema-3 `image.json` with a schema-2 inventory.
The catalog owns shared
platforms and verification fixtures; each image file owns its base images,
constraints, npm lock location, verifier, and normalized
`inventory.components` array. Every directly selected runtime,
Go module, npm package, Alpine package, release binary, and source-built tool
has a machine-readable component ID, kind, package name, exact version, and
upstream source. Release binaries also expose per-platform URLs and checksums;
source-built tools expose the exact upstream revision. Component versions,
source revisions, and artifact checksums appear once in the inventory; build
arguments are projections generated from the adjacent `*_arg` names. README prose and
`THIRD_PARTY.md` are human projections, not machine interfaces.

For example, consumers and update automation can enumerate the Contract tools
without parsing a Dockerfile or Markdown:

```sh
jq '.inventory.components[] | {id, kind, package, version}' \
  images/go-contract-tools/image.json
```

The committed inventory intentionally covers direct inputs. Release-specific
transitive packages are authoritative in the published SBOM attestation.

## Identity model

The repository deliberately has four non-overlapping authorities:

1. The public catalog owns logical discovery, registry paths, tag namespaces,
   and configuration paths.
2. `image.json` plus exact npm manifests own source/build configuration.
3. the published OCI manifest owns released binary identity, platform
   manifests, OCI labels, SBOM, and provenance;
4. each consumer lock owns the exact digest and source revision it has accepted.

Source revisions are the release identity. Git revision tags and OCI
`sha-<revision>` tags are discovery handles only. Runtime and CI consumers must
use a manifest digest:

```text
ghcr.io/wilksu/dev-tool-images/go-contract-tools@sha256:<digest>
ghcr.io/wilksu/dev-tool-images/playwright-client-tools@sha256:<digest>
```

The catalog stores no released digest: accepting a release is a consumer-owned
decision. Normal consumer CI must never resolve public `master` or a discovery
tag dynamically.

## Local development

Docker Buildx, Python 3, and the pinned `requirements-ci.txt` schema validator
are the host requirements. CI installs the Python validator only on the hosted
runner; this repository does not require host Go, Node, npm, or project Python
packages. Build and verify one image on the native platform with:

```sh
make build IMAGE=go-contract-tools
make verify IMAGE=go-contract-tools

make build IMAGE=playwright-client-tools
make verify IMAGE=playwright-client-tools
```

Verification runs without network access, with a read-only root filesystem,
without Linux capabilities, and with `no-new-privileges`. The contract fixture
exercises controller-gen DeepCopy generation, Buf lint/generation, Go and Connect generators, the ES generator,
protoc Python/typing generation, the gRPC Python generator, both OpenAPI
generators, Go build/vet/lint, TypeScript, and Prettier formatting. The Playwright
fixture proves client loading, type checking, and test discovery without
installing or launching a browser.

Pull requests and `master` build and execute both images on native
`linux/amd64` and `linux/arm64` hosted runners. Exact action commit SHAs are
used throughout the workflows. The official BuildKit daemon image used by the
Buildx container driver is also fixed by OCI digest in every workflow.

## Releases

One Git tag releases exactly one image from the commit named in the tag:

```text
go-contract-tools/rev-<40-hex-source-revision>
playwright-client-tools/rev-<40-hex-source-revision>
```

The publish workflow resolves the tag through the catalog and rejects it unless
the embedded revision is exactly the checked-out commit. It builds a multi-
platform image, publishes only the `:sha-<revision>` discovery tag, emits
BuildKit SBOM and max-mode provenance attestations, and records GitHub build
provenance. Its final check uses the anonymous GHCR token flow to prove the
published digest and both required platforms without relying on the workflow's
registry login. The workflow never writes back to the repository.

The first publish of each GHCR package is a bootstrap operation. The OCI source
label links the package to this public repository, and the release must prove an
anonymous manifest read after publishing. If a package does not inherit public
visibility, an administrator must correct that through the package settings; the
workflow intentionally does not have or seek permission to change visibility.

## Public image mirrors in ACR

[`mirrors/images.txt`](mirrors/images.txt) lists public upstream images and their
target `repository:tag` within the configured ACR namespace, one pair per line.
The source accepts a tag, a digest, or a readable tag plus a digest. An optional
third field, `runtime-only`, handles the ACR attestation compatibility exception:

```text
docker.io/library/redis:7.4-alpine@sha256:<64-hex-digest> redis:7.4-alpine
ghcr.io/owner/image@sha256:<64-hex-digest> image:sha-<revision>
docker.io/moby/buildkit:v0.30.0@sha256:<64-hex-digest> buildkit:v0.30.0 runtime-only
```

The dependency snapshot comes from Star-Ferry's release contract, development
and test Compose files, Kubernetes/Helm definitions, Dockerfiles, tool versions,
and tool-image lock. It includes runtime services, test/observability services,
upstream build bases and delivery tools, and the published Go, Playwright and
Android tool images. Local build stages, generated application images and
placeholder references are excluded. Different configured versions remain
separate entries; upstream registry proxies are normalized to their origin.
MinIO is an explicit exception: its origin currently returns 401, so the list
uses the DaoCloud cache after verifying the exact project-pinned digest there.

Version policy: `@sha256:...` is authoritative even when a tag precedes it.
Without a digest, an explicit version follows only that exact tag, never a
newer version. A bare `:latest` deliberately opts into rolling updates. The
committed dependency snapshot pins resolved digests, including the previously
requested `latest` aliases, so scheduled runs repair missing mirrors without
upgrading dependencies. To upgrade, edit the list explicitly. Mirroring does
not deploy or restart applications or rewrite Star-Ferry's consumer locks.

The **Mirror images to ACR** workflow runs when this list or its synchronization
code changes on `master`, manually through **Actions → Mirror images to ACR →
Run workflow**, and daily at 01:23 UTC (09:23 Asia/Kuala_Lumpur). Pull requests
only validate the list and run tests; they never receive ACR credentials. Manual
synchronization also requires `master`.
The optional manual `images` field selects comma-separated target repository
names or exact `repository:tag` values, so a failed subset can be retried.
Select **check_only** to inspect remote state without copying. This read-only
mode reports `present`, `missing`, or `different`; missing entries are inventory
results rather than failed copy operations. One status workflow may run alongside
the serialized upload workflow, adding only one sequential registry request.

Configure all four values as repository **Actions Secrets**: `ACR_USERNAME`,
`ACR_PASSWORD`, `ACR_REGISTRY`, and `ACR_NAMESPACE`. Use the Registry fixed password
and the public registry hostname without a scheme or path. Pre-create the
namespace and target repositories, and grant the dedicated RAM account pull/push
access to those repositories. Targets must already exist or the namespace must
permit automatic repository creation on push. The workflow does not call ACR
management APIs or change visibility.

Runs are serialized across push, manual and scheduled triggers. Within a run,
only one image is copied at a time; the hosted Skopeo version limits concurrent
blob transfers to six, leaving room below ACR's ten-operation limit. Throttling,
temporary network errors and server errors use bounded exponential backoff with
jitter (four outer attempts, plus Skopeo's transport retries). Invalid credentials
and missing source manifests fail promptly. An individual image failure does not
prevent the remaining list from being processed; the run fails if any image still
fails after retries, and the Summary identifies the failed entries.

Pinned entries check ACR first and skip matching digests without contacting the
upstream, so a saved snapshot remains usable during an upstream outage. Other
entries compare the resolved upstream and ACR manifest digests. Matching images are
skipped; absent or changed images are copied by their resolved digest with all
upstream platforms preserved, then checked again at ACR. Authentication, network,
or rate-limit errors fail the run rather than being treated as missing images.
The remote registry is the sync state, so there is no status file to commit back.
Each run's **Summary** records upstream, target repository/tag, result, digest,
and check time without exposing the ACR hostname, namespace, or credentials.
An unchanged digest means no image layers are copied. Successful images remain
available if another image fails; rerunning skips them.

For an upstream index containing just one runnable image plus attestations
(currently Mattermost), synchronization copies that runtime manifest directly.
Its digest is recorded in the Summary; the attestation wrapper is omitted because
ACR Personal rejects Mattermost's OCI-empty attestation config. For multi-platform
entries marked `runtime-only` (BuildKit and the current Dockerfile frontend), the
copy retains every runtime platform and its original manifest digest, omits the
incompatible attestation descriptors, then publishes and verifies a new index.
Existing runtime manifests from a partial copy are reused without temporary
platform tags. The resulting **index digest differs from upstream**: use the
target digest in the Summary or the configured target tag when consuming it.
Other multi-platform indexes such as nginx are kept intact. Mirror-only changes do not trigger the
development tool images' build CI.

Validate locally without credentials or registry access:

```sh
python3 scripts/mirror_acr.py --check
python3 -m unittest discover -s tests -v
```

GitHub scheduled runs can be delayed, and scheduled workflows in public
repositories are automatically disabled after 60 days without repository activity.
See [GitHub schedule behavior](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).

## Supply-chain boundary

Builds use only public dependencies and do not accept secrets. Do not pass
credentials through build arguments or environment variables: provenance can
record build parameters. Base images, BuildKit, direct Alpine packages, npm
direct dependencies, and Go tool versions are exact. The machine-contract check
derives Docker build arguments from inventory values, requires the npm inventory
to equal the exact root manifest and lock, validates inventory against the
published JSON Schema, and rejects un-digested or divergent BuildKit
configuration. Updating an image means changing its owned inventory,
regenerating the exact npm lock when applicable, passing native CI, and creating
a new image-specific revision tag for the final source commit.

See [SECURITY.md](SECURITY.md) for vulnerability reporting and
[THIRD_PARTY.md](THIRD_PARTY.md) for the direct tool inventory. Published SBOM
attestations are the release-specific transitive inventory.
