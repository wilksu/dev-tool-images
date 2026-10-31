#!/usr/bin/env bash
set -euo pipefail

fixture=${1:?usage: verify-tool-image FIXTURE_DIRECTORY}
test -d "$fixture"

for command in \
  buf controller-gen go golangci-lint goimports oapi-codegen protoc \
  protoc-gen-connect-go protoc-gen-doc protoc-gen-es \
  protoc-gen-go protoc-gen-grpc_python protoc-gen-validate \
  swagger-typescript-api tsc; do
  if ! command -v "$command" >/dev/null; then
    printf 'missing required command: %s\n' "$command" >&2
    exit 1
  fi
done

config=/opt/go-contract-tools/image.json
expected_buf=$(node -p "require('$config').inventory.components.find(c => c.id === 'buf').version")
expected_controller_gen=$(node -p "require('$config').inventory.components.find(c => c.id === 'controller-gen').version")
expected_golangci=$(node -p "require('$config').inventory.components.find(c => c.id === 'golangci-lint').version")
expected_go=$(node -p "require('$config').inventory.components.find(c => c.id === 'go').version")
expected_node=$(node -p "require('$config').inventory.components.find(c => c.id === 'node').version")
expected_protoc=$(node -p "require('$config').inventory.components.find(c => c.id === 'protoc').version")
actual_buf=$(buf --version)
actual_controller_gen=$(controller-gen --version)
actual_golangci=$(golangci-lint --version)
actual_go=$(go version)
actual_node=$(node --version)
actual_protoc=$(protoc --version)
test "$actual_buf" = "$expected_buf" || {
  printf 'buf version mismatch: expected %s, got %s\n' "$expected_buf" "$actual_buf" >&2
  exit 1
}
test "$actual_controller_gen" = "Version: v$expected_controller_gen" || {
  printf 'controller-gen version mismatch: expected v%s, got %s\n' "$expected_controller_gen" "$actual_controller_gen" >&2
  exit 1
}
controller_gen_build_info=$(go version -m "$(command -v controller-gen)")
printf '%s\n' "$controller_gen_build_info" | awk -v version="v$expected_controller_gen" '
  $1 == "mod" {
    if (seen++ || NF != 4 || $2 != "sigs.k8s.io/controller-tools" || $3 != version) exit 1
    main_module = 1
    next
  }
  main_module {
    if ($1 == "=>") exit 1
    main_module = 0
  }
  END { if (seen != 1) exit 1 }
' || {
  printf 'controller-gen module mismatch:\n%s\n' "$controller_gen_build_info" >&2
  exit 1
}
printf '%s\n' "$actual_controller_gen"
printf '%s\n' "$controller_gen_build_info" | awk '$1 == "mod" { print }'
printf '%s\n' "$actual_golangci" | grep -F "version $expected_golangci" >/dev/null || {
  printf 'golangci-lint version mismatch: expected %s, got %s\n' "$expected_golangci" "$actual_golangci" >&2
  exit 1
}
printf '%s\n' "$actual_go" | grep -F "go$expected_go" >/dev/null || {
  printf 'Go version mismatch: expected %s, got %s\n' "$expected_go" "$actual_go" >&2
  exit 1
}
test "$actual_node" = "v$expected_node" || {
  printf 'Node version mismatch: expected %s, got %s\n' "$expected_node" "$actual_node" >&2
  exit 1
}
test "$actual_protoc" = "libprotoc $expected_protoc" || {
  printf 'protoc version mismatch: expected %s, got %s\n' "$expected_protoc" "$actual_protoc" >&2
  exit 1
}

work=$(mktemp -d /tmp/go-contract-tools.XXXXXX)
trap 'rm -rf "$work"' EXIT
cp -R "$fixture"/. "$work"/
cd "$work"

export GOPROXY=off GOTOOLCHAIN=local GOWORK=off
printf '%s\n' 'verifying controller-gen DeepCopy generation'
controller-gen object paths=./deepcopy
test -s deepcopy/zz_generated.deepcopy.go
go test ./deepcopy
printf '%s\n' 'verifying Buf lint and local generation'
buf lint
buf generate
find gen/go -type f -name '*.pb.go' -size +0c -print -quit | grep -q .
find gen/go -type f -name '*.connect.go' -size +0c -print -quit | grep -q .
find gen/ts -type f -name '*_pb.ts' -size +0c -print -quit | grep -q .

mkdir -p gen/python
printf '%s\n' 'verifying Protobuf and gRPC Python generation'
protoc \
  --proto_path=proto \
  --python_out=gen/python \
  --pyi_out=gen/python \
  --grpc_python_out=gen/python \
  proto/devtools/v1/echo.proto
test -s gen/python/devtools/v1/echo_pb2.py
test -s gen/python/devtools/v1/echo_pb2.pyi
test -s gen/python/devtools/v1/echo_pb2_grpc.py

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
