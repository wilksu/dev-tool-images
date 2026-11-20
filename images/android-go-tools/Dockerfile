ARG JDK_BASE_IMAGE=scratch

FROM ${JDK_BASE_IMAGE} AS archive-tools
RUN apt-get update && \
    apt-get install -y --no-install-recommends unzip && \
    rm -rf /var/lib/apt/lists/*
COPY unpack-sdk.sh /usr/local/bin/unpack-sdk
COPY sdk-metadata/ /opt/sdk-metadata/

FROM ${JDK_BASE_IMAGE} AS go
ARG GO_URL
ARG GO_SHA256
RUN set -eu; \
    curl --fail --location --silent --show-error --retry 3 "$GO_URL" -o /tmp/go.tar.gz; \
    echo "$GO_SHA256  /tmp/go.tar.gz" | sha256sum -c -; \
    tar -xzf /tmp/go.tar.gz -C /opt; \
    rm /tmp/go.tar.gz

FROM archive-tools AS platform
ARG ANDROID_PLATFORM_URL
ARG ANDROID_PLATFORM_SHA1
ARG ANDROID_PLATFORM_SHA256
ARG ANDROID_PLATFORM_PACKAGE
ARG ANDROID_PLATFORM_REVISION
RUN sh /usr/local/bin/unpack-sdk "$ANDROID_PLATFORM_URL" "$ANDROID_PLATFORM_SHA1" \
    "$ANDROID_PLATFORM_SHA256" "$ANDROID_PLATFORM_PACKAGE" "$ANDROID_PLATFORM_REVISION"

FROM archive-tools AS build-tools
ARG BUILD_TOOLS_URL
ARG BUILD_TOOLS_SHA1
ARG BUILD_TOOLS_SHA256
ARG BUILD_TOOLS_PACKAGE
ARG BUILD_TOOLS_REVISION
RUN sh /usr/local/bin/unpack-sdk "$BUILD_TOOLS_URL" "$BUILD_TOOLS_SHA1" \
    "$BUILD_TOOLS_SHA256" "$BUILD_TOOLS_PACKAGE" "$BUILD_TOOLS_REVISION"

FROM archive-tools AS ndk
ARG NDK_URL
ARG NDK_SHA1
ARG NDK_SHA256
ARG NDK_PACKAGE
ARG NDK_REVISION
RUN sh /usr/local/bin/unpack-sdk "$NDK_URL" "$NDK_SHA1" \
    "$NDK_SHA256" "$NDK_PACKAGE" "$NDK_REVISION"

FROM ${JDK_BASE_IMAGE}
ARG NDK_REVISION
COPY --link --from=ndk /out/ /opt/android-sdk/
COPY --link --from=build-tools /out/ /opt/android-sdk/
COPY --link --from=platform /out/ /opt/android-sdk/
COPY --link --from=go /opt/go/ /opt/go/
COPY --link --from=inventory /image.json /opt/android-go-tools/image.json

ENV ANDROID_HOME=/opt/android-sdk \
    GOTOOLCHAIN=local \
    PATH=/opt/go/bin:${PATH}
ENV ANDROID_NDK_HOME=${ANDROID_HOME}/ndk/${NDK_REVISION}
LABEL org.opencontainers.image.title="android-go-tools" \
      org.opencontainers.image.description="Pinned Android and Go development tools for Linux amd64"
WORKDIR /workspace
