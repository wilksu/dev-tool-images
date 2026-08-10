# dev-tool-images

Public, reproducible development tool images used by Star-Ferry and other
consumers. This repository owns the source configuration and release process;
consumers accept immutable OCI digests instead of rebuilding these toolchains.

## Images

| Logical name | Purpose | Browser binaries |
| --- | --- | --- |
| `go-contract-tools` | Go, Buf, Protobuf/Python gRPC, OpenAPI, and TypeScript contract generation and quality tools | N/A |
| `playwright-client-tools` | Playwright client, Node types, and TypeScript for browserless test discovery and execution | No |

The stable discovery API is [`catalog/v1/images.json`](catalog/v1/images.json),
which also publishes the inventory pointers and their
[`inventory.schema.json`](catalog/v1/inventory.schema.json).
Each catalog entry points to a schema-2 `image.json` that owns base-image and
build versions, supported platforms, capabilities, npm lock location, verifier,
and a normalized `inventory.components` array. Every directly selected runtime,
Go module, npm package, Alpine package, release binary, and source-built tool
has a machine-readable component ID, kind, package name, exact version, and
upstream source. Release binaries also expose per-platform URLs and checksums;
source-built tools expose the exact upstream revision. README prose and
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

Docker Buildx and Python 3 are the only host requirements. Build and verify one
image on the native platform with:

```sh
make build IMAGE=go-contract-tools
make verify IMAGE=go-contract-tools

make build IMAGE=playwright-client-tools
make verify IMAGE=playwright-client-tools
```

Verification runs without network access, with a read-only root filesystem,
without Linux capabilities, and with `no-new-privileges`. The contract fixture
exercises Buf lint/generation, Go and Connect generators, the ES generator,
protoc Python/typing generation, the gRPC Python generator, both OpenAPI
generators, Go build/vet/lint, and TypeScript. The Playwright
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

## Supply-chain boundary

Builds use only public dependencies and do not accept secrets. Do not pass
credentials through build arguments or environment variables: provenance can
record build parameters. Base images, BuildKit, direct Alpine packages, npm
direct dependencies, and Go tool versions are exact. The machine-contract check
requires every `tools` and `packages` build version to have one inventory entry,
requires the npm inventory to equal the exact root manifest and lock, and rejects
un-digested BuildKit configuration. Updating an image means changing its owned
configuration, regenerating the exact npm lock when applicable, passing native
CI, and creating a new image-specific revision tag for the final source commit.

See [SECURITY.md](SECURITY.md) for vulnerability reporting and
[THIRD_PARTY.md](THIRD_PARTY.md) for the direct tool inventory. Published SBOM
attestations are the release-specific transitive inventory.
