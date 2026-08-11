IMAGE ?=
TAG ?= dev-tool-images/$(IMAGE):local

.PHONY: check build verify

check:
	@python3 scripts/validate.py
	@python3 -m json.tool images/go-contract-tools/package-lock.json >/dev/null
	@python3 -m json.tool images/playwright-client-tools/package-lock.json >/dev/null
	@for file in images/*/verify.sh; do test -x "$$file"; done
	@! grep -R -n -E '(^|[^[:alnum:]_-])latest([^[:alnum:]_-]|$$)' catalog images .github/workflows

build: check
	@set -eu; \
	args="$$(python3 scripts/image_config.py build-args "$(IMAGE)" | sed 's/^/--build-arg /')"; \
	docker buildx build --load --tag "$(TAG)" $$args "images/$(IMAGE)"

verify:
	@scripts/verify_image.sh "$(TAG)" \
		"$$(python3 scripts/image_config.py fixture "$(IMAGE)")"
