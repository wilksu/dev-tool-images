# Third-party software

The images redistribute third-party software under its own license. The
Apache-2.0 license for this repository does not relicense those components.
The table below records the direct tool inputs; each published image's SBOM is
the authoritative release-specific transitive inventory.

| Component | Version | Upstream source | License |
| --- | --- | --- | --- |
| Go | 1.26.4 | `github.com/golang/go` | BSD-3-Clause |
| Node.js | 24 | `github.com/nodejs/node` | MIT and bundled third-party notices |
| Buf | 1.66.1 | `github.com/bufbuild/buf` | Apache-2.0 |
| golangci-lint | 2.12.0 | `github.com/golangci/golangci-lint` | GPL-3.0-only |
| protoc-gen-go | 1.36.11 | `github.com/protocolbuffers/protobuf-go` | BSD-3-Clause |
| protoc-gen-connect-go | 1.19.1 | `github.com/connectrpc/connect-go` | Apache-2.0 |
| protoc-gen-validate | 1.3.3 | `github.com/envoyproxy/protoc-gen-validate` | Apache-2.0 |
| protoc-gen-doc | 1.5.1 | `github.com/pseudomuto/protoc-gen-doc` | MIT |
| oapi-codegen | 2.6.0 | `github.com/oapi-codegen/oapi-codegen` | Apache-2.0 |
| goimports / Go tools | 0.30.0 | `github.com/golang/tools` | BSD-3-Clause |
| protoc-gen-es | 2.12.0 | `github.com/bufbuild/protobuf-es` | Apache-2.0 |
| swagger-typescript-api | 13.2.16 | `github.com/acacode/swagger-typescript-api` | MIT |
| TypeScript | 5.7.3 | `github.com/microsoft/TypeScript` | Apache-2.0 |
| Playwright | 1.61.0 | `github.com/microsoft/playwright` | Apache-2.0 |
| Node.js type declarations | 24.13.3 | `github.com/DefinitelyTyped/DefinitelyTyped` | MIT |

Exact source versions are retained in each `image.json`, `package.json`, and
`package-lock.json`. Base images additionally contain Alpine packages and their
transitive dependencies; consult the published SBOM before redistribution or
policy admission.
