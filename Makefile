IMAGE ?=
TAG ?= dev-tool-images/$(IMAGE):local

.PHONY: check build verify

check:
	@python3 scripts/validate.py
	@python3 -m unittest discover -s tests -v

build: check
	@python3 scripts/local_image.py build --image "$(IMAGE)" --tag "$(TAG)"

verify:
	@python3 scripts/local_image.py verify --image "$(IMAGE)" --tag "$(TAG)"
