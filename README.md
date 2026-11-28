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

[`catalog/images.json`](catalog/images.json) is the internal authority for all
three tools, their own platform sets, build drivers, fixtures and change inputs.
Android keeps its [SDK configuration and tests](images/android-go-tools/README.md)
and supports only `linux/amd64`; Go and Playwright support both `linux/amd64`
and `linux/arm64`. All three use the same verification and release pipeline.
The compatible discovery API for existing Go and Playwright consumers remains
[`catalog/v1/images.json`](catalog/v1/images.json),
which also publishes the inventory pointers and their
[`inventory.schema.json`](catalog/v1/inventory.schema.json).
That v1 API is validated against a projection of the internal catalog. Its
existing two-image structure is unchanged. Go and Playwright entries point to
a schema-3 `image.json` with a schema-2 inventory. Each image file owns its base images,
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

The repository has these responsibilities:

1. The internal catalog owns tool discovery, platforms, change routing and
   release policy; the public v1 catalog preserves the existing consumer API.
2. `image.json` plus exact npm manifests own source/build configuration.
3. the published OCI manifest owns released binary identity, platform
   manifests, OCI labels, SBOM, and provenance;
4. each consumer lock owns the exact digest and source revision it has accepted.

The ACR delivery pipeline copies declared external dependencies and completed
tool releases. It does not build applications, choose dependency upgrades,
deploy containers or update consumer locks. Intermediate build stages and
project application images do not belong in the external mirror list.

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

Docker Buildx, Python 3.12+, Make, and the pinned `requirements-ci.txt` validators
are the host requirements. CI installs the Python validator only on the hosted
runner; this repository does not require host Go, Node, npm, or project Python
packages. Build and verify one image on the native platform with:

```sh
make build IMAGE=go-contract-tools
make verify IMAGE=go-contract-tools

make build IMAGE=playwright-client-tools
make verify IMAGE=playwright-client-tools

make build IMAGE=android-go-tools
make verify IMAGE=android-go-tools
```

Go and Playwright verification runs without network access, with a read-only root filesystem,
without Linux capabilities, and with `no-new-privileges`. The contract fixture
exercises controller-gen DeepCopy generation, Buf lint/generation, Go and Connect generators, the ES generator,
protoc Python/typing generation, the gRPC Python generator, both OpenAPI
generators, Go build/vet/lint, TypeScript, and Prettier formatting. The Playwright
fixture proves client loading, type checking, and test discovery without
installing or launching a browser.

Android verification first warms Gradle dependencies, then repeats APK builds,
unit tests and lint without networking and checks both APK ABIs and ownership.
Its CI also verifies component-layer reuse. Docker Buildx and Skopeo are required
for CI candidate verification; local `make check` requires Make, Python and the
pinned requirements. `make verify` uses Docker and, for Android, curl and unzip.

CI always runs contract and pipeline regression checks on pull requests and
`master`. [`scripts/change_plan.py`](scripts/change_plan.py) then selects builds:

| Changed input | Native runtime verification |
| --- | --- |
| One tool's source/configuration/fixture | Only that tool's declared platforms |
| Shared build or verification code / internal catalog | All tools |
| External mirror list, delivery/publish code, imported records, documentation | Contract and pipeline checks only |
| Manual CI, `images=all` or comma-separated tool names | Selected tools; no publication |

Android is included in pull-request verification. Deleted files and moves
between tool directories are included in routing. The stable **CI result** job
requires all selected checks to pass and also reports success when no build is
needed. Configure this check as the branch-protection requirement if desired.
Actions use exact commit SHAs; the shared Buildx daemon is pinned by digest.

## Releases

One Git tag releases exactly one image from the commit named in the tag:

```text
go-contract-tools/rev-<40-hex-source-revision>
playwright-client-tools/rev-<40-hex-source-revision>
android-go-tools/rev-<40-hex-source-revision>
```

The **Publish** workflow checks the catalog, exact commit, actual Git tag and
commit ancestry on `master`. Branch pushes never publish. Each platform is
built once on a native runner into an OCI archive with SBOM and max-mode
provenance. The fixture runs against that archive's runtime content; a receipt
is emitted only after successful verification. Publication verifies the complete
blob graph, receipts, platform coverage and source labels, combines those same
runtime manifests and proofs, and copies them to GHCR without rebuilding.
Only the `:sha-<revision>` discovery tag is written. GitHub build provenance and
an anonymous GHCR digest/platform check must also pass.

A generated `release.json` asset on the matching GitHub Release records the
source digest, platforms, revision, source run, ACR alias and expected ACR digest.
The workflow first saves it in a draft release before writing the GHCR tag, then
completes the release after publication checks. The record is immutable: a
retry reuses the recorded candidate or existing GHCR digest, and refuses to
overwrite an unrecorded or changed revision tag. Release candidate artifacts
are retained for 90 days; an interrupted first upload needs those original
artifacts while its draft is pending. If they expire, publication fails rather
than rebuilding different content under an existing identity. Completed releases
and subsequent ACR repairs do not depend on those temporary artifacts.

After **Publish** succeeds, a `workflow_run` event wakes **Mirror images to ACR**.
The listener uses delivery code from the default branch, reads only bounded JSON
from that exact run's `release-record` artifact, and verifies the canonical
repository, workflow path, successful push run, tag, revision, mainline ancestry
and completed durable record before logging into ACR. It never executes code
from the notification. ACR failure leaves the GHCR release intact; retry ACR
alone without rebuilding. No additional secret or personal access token is
needed. The workflows do not commit state back to Git.

New owned releases preserve every runtime platform in ACR while omitting
incompatible BuildKit attestation descriptors. Their ACR index digest can differ
from GHCR; the exact transformed bytes and digest are captured in `release.json`.
The runtime manifests remain unchanged. Use the registry-specific digest in
consumer locks. GHCR retains SBOM and provenance; ACR serves runtime images.

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
and tool-image lock. The external list contains 48 entries for runtime services,
test/observability services, upstream build bases and delivery tools. Four
already accepted owned tool-image versions/aliases were moved into
[`releases/imported.json`](releases/imported.json), preserving their exact
source/ACR digests and existing aliases. This is a one-time historical archive;
new owned releases are discovered from generated GitHub Release records and
must not be added to the external list. Local build stages, generated application images and
placeholder references are excluded. Different configured versions remain
separate entries; upstream registry proxies are normalized to their origin.
MinIO is an explicit exception: its original registries currently reject
anonymous reads, so the list uses the community archive `ghcr.io/netvark/minio`
([archive source](https://github.com/netvark/minio-docker-build#image-mirrors)).
Its index digest and all three runtime manifests (amd64, arm64 and ppc64le)
match the original project pin. The DaoCloud cache was incomplete and is no
longer used. The workflow preserves the original digest and platforms rather
than substituting another release or rebuilding it.

Version policy: `@sha256:...` is authoritative even when a tag precedes it.
Without a digest, an explicit version follows only that exact tag, never a
newer version. A bare `:latest` deliberately opts into rolling updates. The
committed dependency snapshot pins resolved digests, including the previously
requested `latest` aliases, so scheduled runs repair missing mirrors without
upgrading dependencies. To upgrade, edit the list explicitly. Mirroring does
not deploy or restart applications or rewrite Star-Ferry's consumer locks.

The **Mirror images to ACR** workflow has four entry points:

| Trigger | Scope |
| --- | --- |
| A successful **Publish** completes | Only the release recorded by that run |
| External list or imported archive changes on `master` | External list and historical imports |
| Daily at 01:23 UTC (09:23 Asia/Kuala_Lumpur) | External list, imports and all completed generated releases |
| **Actions → Mirror images to ACR → Run workflow** | Same reconciliation, with optional target filter/status mode |

Changing synchronization scripts, workflow files or documentation runs CI
checks without launching a copy. Pull requests never enter the ACR workflow or
receive its credentials. Manual delivery requires `master`. Schedules repair
missing content and catch missed notifications; they do not build or upgrade.
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

All upload triggers share the job-level `acr-delivery` concurrency group.
`queue: max` retains up to 100 pending runs instead of replacing an earlier
pending notification; the daily reconciliation recovers missed/overflowed
notifications from durable records. See
[GitHub concurrency queues](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency).
Within a run,
only one image is copied at a time; the hosted Skopeo version limits concurrent
blob transfers to six, leaving room below ACR's ten-operation limit. Throttling,
temporary network errors and server errors use bounded exponential backoff with
jitter (four outer attempts, plus Skopeo's transport retries). Invalid credentials
and missing source manifests fail promptly. Each copy attempt is bounded to ten
minutes, so a stalled transfer can retry and reuse already uploaded layers.
An individual image failure does not
prevent the remaining list from being processed; the run fails if any image still
fails after retries, and the Summary identifies the failed entries.
If an anonymous Docker Hub source hits its pull quota, immutable digest reads
can retry through the project's existing `mirror.gcr.io` cache. The source
manifest hash is verified before use; destination addresses and moving tag
lookups are never redirected. A missing cache entry remains a reported failure.

Pinned entries check ACR first and skip matching digests without contacting the
upstream, so a saved snapshot remains usable during an upstream outage. Other
entries compare the resolved upstream and ACR manifest digests. Matching images are
skipped; absent or changed images are copied by their resolved digest with all
upstream platforms preserved, then checked again at ACR. Authentication, network,
or rate-limit errors fail the run rather than being treated as missing images.
Generated records declare desired versions; ACR's remote digests determine
actual synchronization state, so there is no mutable status file to commit back.
Each run's **Summary** records upstream, target repository/tag, result, digest,
and check time without exposing the ACR hostname, namespace, or credentials.
The `acr-results` artifact also contains relative aliases and target digests.
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
python3 -m pip install -r requirements-ci.txt
make check
```

GitHub scheduled runs can be delayed, and scheduled workflows in public
repositories are automatically disabled after 60 days without repository activity.
See [GitHub schedule behavior](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).

For workflow linting, `actionlint` 1.7.12 needs the narrow option
`-ignore 'unexpected key "queue" for "concurrency" section'` because that
release predates support for GitHub's documented queue setting. The pipeline
tests independently check the queue and cancellation contract.

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
