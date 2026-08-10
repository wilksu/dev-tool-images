ARG GO_BASE_IMAGE=scratch
ARG NODE_BASE_IMAGE=scratch

FROM ${GO_BASE_IMAGE} AS go-tools

ARG BUF_VERSION
ARG GOLANGCI_VERSION
ARG OAPI_CODEGEN_VERSION
ARG PROTOC_GEN_GO_VERSION
ARG PROTOC_GEN_CONNECT_GO_VERSION
ARG PROTOC_GEN_VALIDATE_VERSION
ARG PROTOC_GEN_DOC_VERSION
ARG GOIMPORTS_VERSION

ENV GOBIN=/out \
    GOPROXY=https://proxy.golang.org,direct \
    GOWORK=off

RUN go install "github.com/bufbuild/buf/cmd/buf@${BUF_VERSION}" && \
    go install "github.com/golangci/golangci-lint/v2/cmd/golangci-lint@${GOLANGCI_VERSION}" && \
    go install "google.golang.org/protobuf/cmd/protoc-gen-go@${PROTOC_GEN_GO_VERSION}" && \
    go install "connectrpc.com/connect/cmd/protoc-gen-connect-go@${PROTOC_GEN_CONNECT_GO_VERSION}" && \
    go install "github.com/envoyproxy/protoc-gen-validate@${PROTOC_GEN_VALIDATE_VERSION}" && \
    go install "github.com/pseudomuto/protoc-gen-doc/cmd/protoc-gen-doc@${PROTOC_GEN_DOC_VERSION}" && \
    go install "github.com/oapi-codegen/oapi-codegen/v2/cmd/oapi-codegen@${OAPI_CODEGEN_VERSION}" && \
    go install "golang.org/x/tools/cmd/goimports@${GOIMPORTS_VERSION}"

FROM ${NODE_BASE_IMAGE} AS protoc-tools

ARG TARGETARCH
ARG PROTOC_VERSION
ARG PROTOC_LINUX_AMD64_SHA256
ARG PROTOC_LINUX_ARM64_SHA256
RUN set -eu; \
    case "${TARGETARCH}" in \
      amd64) archive_arch=x86_64; expected="${PROTOC_LINUX_AMD64_SHA256}" ;; \
      arm64) archive_arch=aarch_64; expected="${PROTOC_LINUX_ARM64_SHA256}" ;; \
      *) printf 'unsupported protoc architecture: %s\n' "${TARGETARCH}" >&2; exit 1 ;; \
    esac; \
    archive="protoc-${PROTOC_VERSION}-linux-${archive_arch}.zip"; \
    wget -q "https://github.com/protocolbuffers/protobuf/releases/download/v${PROTOC_VERSION}/${archive}"; \
    printf '%s  %s\n' "${expected}" "${archive}" | sha256sum -c -; \
    mkdir /opt/protoc; \
    unzip -q "${archive}" -d /opt/protoc; \
    /opt/protoc/bin/protoc --version | grep -Fx "libprotoc ${PROTOC_VERSION}"

FROM ${NODE_BASE_IMAGE} AS grpc-python-tools

ARG GRPC_PYTHON_PLUGIN_VERSION
ARG GRPC_PYTHON_PLUGIN_REVISION
RUN apk add --no-cache \
      "g++=15.2.0-r5" \
      "git=2.54.0-r0" \
      "protobuf-dev=31.1-r1"
RUN set -eu; \
    git init /tmp/grpc; \
    cd /tmp/grpc; \
    git remote add origin https://github.com/grpc/grpc.git; \
    git fetch --depth 1 origin "${GRPC_PYTHON_PLUGIN_REVISION}"; \
    git checkout --detach FETCH_HEAD; \
    test "$(git rev-parse HEAD)" = "${GRPC_PYTHON_PLUGIN_REVISION}"; \
    grep -Fx "VERSION = '${GRPC_PYTHON_PLUGIN_VERSION}'" src/python/grpcio/grpc_version.py; \
    g++ -std=c++17 -O2 -s -static -I. \
      src/compiler/python_plugin.cc \
      src/compiler/python_generator.cc \
      src/compiler/proto_parser_helper.cc \
      -lprotoc $(pkg-config --static --libs protobuf) -pthread \
      -o /usr/local/bin/protoc-gen-grpc_python

FROM ${NODE_BASE_IMAGE}

ARG ALPINE_GIT_VERSION
ARG ALPINE_GCC_VERSION
ARG ALPINE_BASH_VERSION
ARG ALPINE_MAKE_VERSION
ARG ALPINE_MUSL_DEV_VERSION
ARG ALPINE_PERL_VERSION
ARG ALPINE_PYTHON3_VERSION
RUN apk add --no-cache \
      "bash=${ALPINE_BASH_VERSION}" \
      "gcc=${ALPINE_GCC_VERSION}" \
      "git=${ALPINE_GIT_VERSION}" \
      "make=${ALPINE_MAKE_VERSION}" \
      "musl-dev=${ALPINE_MUSL_DEV_VERSION}" \
      "perl=${ALPINE_PERL_VERSION}" \
      "python3=${ALPINE_PYTHON3_VERSION}"

WORKDIR /opt/go-contract-tools
COPY package.json package-lock.json image.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund && npm cache clean --force

COPY --from=go-tools /out/ /usr/local/bin/
COPY --from=go-tools /usr/local/go/ /usr/local/go/
COPY --from=protoc-tools /opt/protoc/bin/protoc /usr/local/bin/protoc
COPY --from=protoc-tools /opt/protoc/include/ /usr/local/include/
COPY --from=grpc-python-tools /usr/local/bin/protoc-gen-grpc_python /usr/local/bin/protoc-gen-grpc_python
COPY verify.sh /usr/local/bin/verify-tool-image

ARG GO_VERSION
ARG NODE_VERSION
ARG SOURCE_REVISION=unknown
LABEL org.opencontainers.image.title="go-contract-tools" \
      org.opencontainers.image.description="Pinned Go, Protobuf, Python gRPC, OpenAPI, and TypeScript contract toolchain" \
      org.opencontainers.image.source="https://github.com/wilksu/dev-tool-images" \
      org.opencontainers.image.revision="${SOURCE_REVISION}" \
      org.opencontainers.image.licenses="Apache-2.0" \
      io.starferry.tool.schema="2" \
      io.starferry.tool.name="go-contract-tools" \
      io.starferry.tool.inventory-path="images/go-contract-tools/image.json#inventory" \
      io.starferry.tool.go-version="${GO_VERSION}" \
      io.starferry.tool.node-version="${NODE_VERSION}"

ENV GOROOT=/usr/local/go \
    HOME=/tmp/home \
    NODE_PATH=/opt/go-contract-tools/node_modules \
    PATH=/opt/go-contract-tools/node_modules/.bin:/usr/local/go/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
WORKDIR /workspace
