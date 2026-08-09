#!/usr/bin/env bash
set -euo pipefail

fixture=${1:?usage: verify-tool-image FIXTURE_DIRECTORY}
test -d "$fixture"

for command in \
  buf go golangci-lint goimports oapi-codegen \
  protoc-gen-connect-go protoc-gen-doc protoc-gen-es \
  protoc-gen-go protoc-gen-validate swagger-typescript-api tsc; do
  command -v "$command" >/dev/null
done

config=/opt/go-contract-tools/image.json
expected_buf=$(node -p "require('$config').tools.buf_version.replace(/^v/, '')")
expected_golangci=$(node -p "require('$config').tools.golangci_version.replace(/^v/, '')")
expected_go=$(node -p "require('$config').tools.go_version")
test "$(buf --version)" = "$expected_buf"
golangci-lint --version | grep -F "version $expected_golangci" >/dev/null
go version | grep -F "go$expected_go" >/dev/null

work=$(mktemp -d /tmp/go-contract-tools.XXXXXX)
trap 'rm -rf "$work"' EXIT
cp -R "$fixture"/. "$work"/
cd "$work"

export GOPROXY=off GOTOOLCHAIN=local GOWORK=off
buf lint
buf generate
test -s gen/go/devtools/v1/echo.pb.go
test -s gen/go/devtools/v1/echo.connect.go
test -s gen/ts/devtools/v1/echo_pb.ts

mkdir -p gen/openapi gen/client
oapi-codegen -generate types -package contractapi -o gen/openapi/types.gen.go openapi.yaml
swagger-typescript-api generate -p openapi.yaml -o gen/client -n contract-api.ts --silent
test -s gen/openapi/types.gen.go
test -s gen/client/contract-api.ts

go vet ./cmd/check
go build ./cmd/check
golangci-lint run ./cmd/check/...
tsc --noEmit --project tsconfig.json
