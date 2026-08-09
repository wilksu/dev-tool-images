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

FROM ${NODE_BASE_IMAGE}

ARG ALPINE_GIT_VERSION
ARG ALPINE_GCC_VERSION
ARG ALPINE_MUSL_DEV_VERSION
RUN apk add --no-cache \
      bash \
      "gcc=${ALPINE_GCC_VERSION}" \
      "git=${ALPINE_GIT_VERSION}" \
      make \
      "musl-dev=${ALPINE_MUSL_DEV_VERSION}" \
      perl \
      python3

WORKDIR /opt/go-contract-tools
COPY package.json package-lock.json image.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund && npm cache clean --force

COPY --from=go-tools /out/ /usr/local/bin/
COPY --from=go-tools /usr/local/go/ /usr/local/go/
COPY verify.sh /usr/local/bin/verify-tool-image

ARG GO_VERSION
ARG IMAGE_VERSION=unreleased
ARG SOURCE_REVISION=unknown
LABEL org.opencontainers.image.title="go-contract-tools" \
      org.opencontainers.image.description="Pinned Go, Proto, OpenAPI, and TypeScript contract toolchain" \
      org.opencontainers.image.source="https://github.com/wilksu/dev-tool-images" \
      org.opencontainers.image.revision="${SOURCE_REVISION}" \
      org.opencontainers.image.version="${IMAGE_VERSION}" \
      org.opencontainers.image.licenses="Apache-2.0" \
      io.starferry.tool.schema="1" \
      io.starferry.tool.name="go-contract-tools" \
      io.starferry.tool.go-version="${GO_VERSION}"

ENV GOROOT=/usr/local/go \
    HOME=/tmp/home \
    NODE_PATH=/opt/go-contract-tools/node_modules \
    PATH=/opt/go-contract-tools/node_modules/.bin:/usr/local/go/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
WORKDIR /workspace
