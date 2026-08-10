ARG NODE_BASE_IMAGE=scratch
FROM ${NODE_BASE_IMAGE}

ENV PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1
WORKDIR /opt/playwright-client-tools
COPY package.json package-lock.json image.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund && npm cache clean --force

COPY verify.sh /usr/local/bin/verify-tool-image

ARG NODE_VERSION
ARG SOURCE_REVISION=unknown
LABEL org.opencontainers.image.title="playwright-client-tools" \
      org.opencontainers.image.description="Pinned Playwright client and TypeScript execution toolchain without browser binaries" \
      org.opencontainers.image.source="https://github.com/wilksu/dev-tool-images" \
      org.opencontainers.image.revision="${SOURCE_REVISION}" \
      org.opencontainers.image.licenses="Apache-2.0" \
      io.starferry.tool.schema="2" \
      io.starferry.tool.name="playwright-client-tools" \
      io.starferry.tool.inventory-path="images/playwright-client-tools/image.json#inventory" \
      io.starferry.tool.node-version="${NODE_VERSION}" \
      io.starferry.tool.browser-binaries="false"

ENV HOME=/tmp/home \
    NODE_PATH=/opt/playwright-client-tools/node_modules \
    PATH=/opt/playwright-client-tools/node_modules/.bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
WORKDIR /workspace
