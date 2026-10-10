# MosAic developer targets. `make ci` mirrors .github/workflows/ci.yml exactly.

UV ?= uv
PYTEST = $(UV) run pytest

.PHONY: help sync lint format typecheck unit check frontend integration acceptance ci eval ffmpeg ffmpeg-ci corpus docker docker-e2e desktop-dev desktop-check clean

help:
	@echo "check       lint + types + unit tests (fast)"
	@echo "frontend    web UI: tokens, types, lint, tests, build, Storybook"
	@echo "integration integration tests on synthetic media"
	@echo "acceptance  milestone acceptance tests"
	@echo "ci          everything CI runs"
	@echo "eval        real-corpus evaluation (uses the configured AI provider)"
	@echo "ffmpeg      build the LGPL dev FFmpeg (macOS)"
	@echo "docker      build the server image for this machine and smoke-test it"
	@echo "docker-e2e  docker compose up, then the browser's API calls to a rendered preview"
	@echo "desktop-dev run the Mac app (Tauri) around this repository's backend"
	@echo "desktop-check  Rust fmt, clippy and crate licenses for the Mac app"

sync:
	$(UV) sync --frozen

lint:
	$(UV) run ruff check backend tests scripts
	$(UV) run ruff format --check backend tests scripts
	@if command -v cargo >/dev/null 2>&1; then $(UV) run python scripts/check_rust_licenses.py; fi

format:
	$(UV) run ruff check --fix backend tests
	$(UV) run ruff format backend tests

typecheck:
	$(UV) run mypy

unit:
	$(PYTEST) tests/unit -q

check: lint typecheck unit

NPM ?= npm
frontend:  # needs Docker: the visual check renders in the pinned Playwright image (ADR 0056)
	cd frontend && $(NPM) ci --no-audit --no-fund
	cd frontend && $(NPM) test
	cd frontend && $(NPM) run typecheck
	cd frontend && $(NPM) run lint
	cd frontend && $(NPM) run build
	cd frontend && $(NPM) run build-storybook
	cd frontend && $(NPM) run visual

integration:
	$(PYTEST) tests/integration -q

acceptance:
	$(PYTEST) tests/acceptance -q

ci: sync check frontend integration acceptance

eval:  # real corpus, real AI; exits 3 at a human gate (G1/G2) with the fix
	$(UV) run python -m mosaic.evaluation.run

ffmpeg:
	./scripts/build-ffmpeg.sh

docker:
	./scripts/docker-smoke.sh

docker-e2e:  # M2 acceptance 1 against `docker compose up` (ADR 0056)
	./scripts/docker-e2e.sh

desktop-dev:  # the Mac shell around the repository's backend (ADR 0060)
	cd frontend && $(NPM) run build
	cd desktop && $(NPM) install --no-audit --no-fund && $(NPM) run tauri dev

desktop-check:  # Rust format, clippy and crate licenses (macOS: needs the system webview)
	cd desktop/src-tauri && cargo fmt --check && cargo clippy --locked --all-targets -- -D warnings
	$(UV) run python scripts/check_rust_licenses.py

ffmpeg-ci:
	./scripts/fetch-ffmpeg-ci.sh

corpus:
	$(UV) run mosaic-dev gen-corpus .cache/corpus

clean:
	rm -rf .cache .pytest_cache .mypy_cache .ruff_cache
