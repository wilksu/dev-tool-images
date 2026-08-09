#!/usr/bin/env bash
set -euo pipefail

fixture=${1:?usage: verify-tool-image FIXTURE_DIRECTORY}
test -d "$fixture"

for command in \
  buf go golangci-lint goimports oapi-codegen \
  protoc-gen-connect-go protoc-gen-doc protoc-gen-es \
  protoc-gen-go protoc-gen-validate swagger-typescript-api tsc; do
  if ! command -v "$command" >/dev/null; then
    printf 'missing required command: %s\n' "$command" >&2
    exit 1
  fi
done

config=/opt/go-contract-tools/image.json
expected_buf=$(node -p "require('$config').tools.buf_version.replace(/^v/, '')")
expected_golangci=$(node -p "require('$config').tools.golangci_version.replace(/^v/, '')")
expected_go=$(node -p "require('$config').tools.go_version")
actual_buf=$(buf --version)
actual_golangci=$(golangci-lint --version)
actual_go=$(go version)
test "$actual_buf" = "$expected_buf" || {
  printf 'buf version mismatch: expected %s, got %s\n' "$expected_buf" "$actual_buf" >&2
  exit 1
}
printf '%s\n' "$actual_golangci" | grep -F "version $expected_golangci" >/dev/null || {
  printf 'golangci-lint version mismatch: expected %s, got %s\n' "$expected_golangci" "$actual_golangci" >&2
  exit 1
}
printf '%s\n' "$actual_go" | grep -F "go$expected_go" >/dev/null || {
  printf 'Go version mismatch: expected %s, got %s\n' "$expected_go" "$actual_go" >&2
  exit 1
}

work=$(mktemp -d /tmp/go-contract-tools.XXXXXX)
trap 'rm -rf "$work"' EXIT
cp -R "$fixture"/. "$work"/
cd "$work"

export GOPROXY=off GOTOOLCHAIN=local GOWORK=off
printf '%s\n' 'verifying Buf lint and local generation'
buf lint
buf generate
find gen/go -type f -name '*.pb.go' -size +0c -print -quit | grep -q .
find gen/go -type f -name '*.connect.go' -size +0c -print -quit | grep -q .
find gen/ts -type f -name '*_pb.ts' -size +0c -print -quit | grep -q .

mkdir -p gen/openapi gen/client
printf '%s\n' 'verifying OpenAPI generators'
oapi-codegen -generate types -package contractapi -o gen/openapi/types.gen.go openapi.yaml
swagger-typescript-api generate -p openapi.yaml -o gen/client -n contract-api.ts --silent
test -s gen/openapi/types.gen.go
test -s gen/client/contract-api.ts

printf '%s\n' 'verifying Go build, vet, and lint'
go vet ./cmd/check
go build ./cmd/check
golangci-lint run ./cmd/check/...
printf '%s\n' 'verifying TypeScript'
tsc --noEmit --project tsconfig.json
