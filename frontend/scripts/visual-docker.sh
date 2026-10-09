#!/usr/bin/env sh
# Runs the visual regression in the pinned Playwright image (ADR 0056): the same Chromium,
# fonts and rasterizer on every host, so macOS and Linux CI share one set of baselines.
# The image's version is the `playwright` dev dependency's (pinned exactly).
set -eu
cd "$(dirname "$0")/.."
VERSION="$(node -p "require('./package.json').devDependencies.playwright")"
IMAGE="mcr.microsoft.com/playwright:v${VERSION}-noble"
exec docker run --rm --ipc=host --user "$(id -u):$(id -g)" -e HOME=/tmp \
  -v "$PWD:/work" -w /work "$IMAGE" node scripts/visual.mjs "$@"
