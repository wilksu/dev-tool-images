ARG ANDROID_BASE_IMAGE=scratch
FROM ${ANDROID_BASE_IMAGE} AS go-toolchain

RUN cd /tmp && \
    curl -fsSL --retry 2 --max-time 120 \
      https://go.dev/dl/go1.27.4.linux-amd64.tar.gz -o go.tar.gz && \
    echo '7226736c2339719cda28fbf3a54d71aa63bcefe376e98cef00034268dab24840  go.tar.gz' | sha256sum -c - && \
    tar -xzf go.tar.gz && rm go.tar.gz

FROM ${ANDROID_BASE_IMAGE}
COPY --link --from=go-toolchain /tmp/go/ /opt/go/

ENV ANDROID_NDK_HOME=${ANDROID_HOME}/ndk/30.0.16248370 \
    ANDROID_NDK_ROOT=${ANDROID_HOME}/ndk/30.0.16248370 \
    GOTOOLCHAIN=local
ENV PATH=/opt/go/bin:${ANDROID_NDK_HOME}:${PATH}
