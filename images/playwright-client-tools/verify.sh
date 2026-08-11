#!/usr/bin/env sh
set -eu

fixture=${1:?usage: verify-tool-image FIXTURE_DIRECTORY}
test -d "$fixture"
test ! -e /root/.cache/ms-playwright
test ! -e /opt/playwright-client-tools/node_modules/.cache/ms-playwright

expected_playwright=$(node -p "require('/opt/playwright-client-tools/package.json').devDependencies['@playwright/test']")
expected_typescript=$(node -p "require('/opt/playwright-client-tools/package.json').devDependencies.typescript")
expected_node=$(node -p "require('/opt/playwright-client-tools/image.json').inventory.components.find(c => c.id === 'node').version")
test "$(node --version)" = "v$expected_node"
test "$(playwright --version)" = "Version $expected_playwright"
test "$(tsc --version)" = "Version $expected_typescript"
node -e "require('@playwright/test'); require('typescript')"

work=$(mktemp -d /tmp/playwright-client-tools.XXXXXX)
trap 'rm -rf "$work"' EXIT
cp -R "$fixture"/. "$work"/
cd "$work"

tsc --noEmit --project tsconfig.json \
  --baseUrl /opt/playwright-client-tools/node_modules \
  --typeRoots /opt/playwright-client-tools/node_modules/@types
playwright test --list --config=playwright.config.ts
