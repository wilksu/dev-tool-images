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
	@test "$(IMAGE)" = go-contract-tools -o "$(IMAGE)" = playwright-client-tools
	@set -eu; \
	args="$$(python3 -c 'import json; c=json.load(open("images/$(IMAGE)/image.json")); print(" ".join("--build-arg %s=%s" % (k.upper(),v) for s in ("base_images","tools","packages") for k,v in c.get(s,{}).items()))')"; \
	docker buildx build --load --tag "$(TAG)" $$args "images/$(IMAGE)"

verify:
	@test "$(IMAGE)" = go-contract-tools -o "$(IMAGE)" = playwright-client-tools
	@set -eu; \
	case "$(IMAGE)" in go-contract-tools) fixture=contract ;; playwright-client-tools) fixture=playwright ;; esac; \
	docker run --rm --network none --read-only --cap-drop ALL \
		--security-opt no-new-privileges \
		--tmpfs /tmp:rw,nosuid,nodev,size=256m \
		--mount "type=bind,src=$(CURDIR),dst=/src,readonly" \
		"$(TAG)" verify-tool-image "/src/fixtures/$$fixture"
