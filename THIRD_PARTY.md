# Third-party software

The images redistribute third-party software under its own license. The
Apache-2.0 license for this repository does not relicense those components.
The table below adds the license classification that cannot be derived from the
build configuration. Exact versions and upstream sources live only in each
image's machine-readable inventory; each published image's SBOM is the
authoritative release-specific transitive inventory.

| Inventory component | License |
| --- | --- |
| `go` | BSD-3-Clause |
| `node` | MIT and bundled third-party notices |
| `protoc` | BSD-3-Clause |
| `grpc-python-plugin` | Apache-2.0 |
| `protocolbuffers/protobuf` build dependency | BSD-3-Clause |
| `buf` | Apache-2.0 |
| `golangci-lint` | GPL-3.0-only |
| `protoc-gen-go` | BSD-3-Clause |
| `protoc-gen-connect-go` | Apache-2.0 |
| `protoc-gen-validate` | Apache-2.0 |
| `protoc-gen-doc` | MIT |
| `oapi-codegen` | Apache-2.0 |
| `goimports` | BSD-3-Clause |
| `protoc-gen-es` | Apache-2.0 |
| `swagger-typescript-api` | MIT |
| `typescript` | Apache-2.0 |
| `playwright-test` | Apache-2.0 |
| `node-types` | MIT |
| `bash` | GPL-3.0-or-later |
| `gcc` | GPL-3.0-or-later with runtime exception |
| `git` | GPL-2.0-only |
| `make` | GPL-3.0-or-later |
| `musl-dev` | MIT |
| `perl` | Artistic-1.0-Perl OR GPL-1.0-or-later |
| `python3` | Python-2.0 |

Npm entries are cross-checked against `package.json` and `package-lock.json`;
Docker build arguments are generated from the same inventory. Base images and
direct packages add transitive dependencies; consult the published SBOM before
redistribution or policy admission.
