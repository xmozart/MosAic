# MosAic developer targets. `make ci` mirrors .github/workflows/ci.yml exactly.

UV ?= uv
PYTEST = $(UV) run pytest

.PHONY: help sync lint format typecheck unit check integration acceptance ci eval ffmpeg ffmpeg-ci corpus clean

help:
	@echo "check       lint + types + unit tests (fast)"
	@echo "integration integration tests on synthetic media"
	@echo "acceptance  milestone acceptance tests"
	@echo "ci          everything CI runs"
	@echo "eval        real-corpus evaluation (uses the configured AI provider)"
	@echo "ffmpeg      build the LGPL dev FFmpeg (macOS)"

sync:
	$(UV) sync --frozen

lint:
	$(UV) run ruff check backend tests
	$(UV) run ruff format --check backend tests

format:
	$(UV) run ruff check --fix backend tests
	$(UV) run ruff format backend tests

typecheck:
	$(UV) run mypy

unit:
	$(PYTEST) tests/unit -q

check: lint typecheck unit

integration:
	$(PYTEST) tests/integration -q

acceptance:
	$(PYTEST) tests/acceptance -q

ci: sync check integration acceptance

eval:  # implemented in M0 step 12
	$(UV) run python -m mosaic.evaluation.run

ffmpeg:
	./scripts/build-ffmpeg.sh

ffmpeg-ci:
	./scripts/fetch-ffmpeg-ci.sh

corpus:
	$(UV) run mosaic-dev gen-corpus .cache/corpus

clean:
	rm -rf .cache .pytest_cache .mypy_cache .ruff_cache
