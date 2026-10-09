#!/usr/bin/env bash
# M2 acceptance 1 (ADR 0056): `docker compose up` with one media root, then the web UI's
# API calls up to a first rendered preview. Uses a few synthetic corpus clips and the
# offline fake AI. Removes the compose project and its volume when done.
set -euo pipefail
cd "$(dirname "$0")/.."
work="$(mktemp -d)"
project="mosaic-e2e-$$"
export MOSAIC_MEDIA="$work/media" MOSAIC_MASTER_KEY_PATH="$work/master_key" MOSAIC_PORT="${MOSAIC_PORT:-18765}"
cleanup() { docker compose -p "$project" down -v >/dev/null 2>&1 || true; rm -rf "$work"; }
trap cleanup EXIT
(umask 077 && openssl rand -base64 48 > "$MOSAIC_MASTER_KEY_PATH")
mkdir -p "$MOSAIC_MEDIA/Trip"
uv run python - "$work/corpus" "$MOSAIC_MEDIA/Trip" <<'PY'
import shutil, sys
from pathlib import Path
from mosaic.devtools.corpus import CorpusGenerator
from mosaic.media.ffmpeg.capabilities import locate
out, trip = Path(sys.argv[1]), Path(sys.argv[2])
CorpusGenerator(out, locate()).generate()
for name in ("A001_basic.mp4", "A002_basic.mp4", "speech.mp4", "GX010042.MP4", "GX020042.MP4"):
    shutil.copy2(out / name, trip / name)
PY
docker compose -p "$project" up -d --build
for _ in $(seq 1 90); do
  id="$(docker compose -p "$project" ps -q mosaic)"
  [ "$(docker inspect -f '{{.State.Health.Status}}' "$id")" = healthy ] && break
  sleep 2
done
uv run python scripts/docker_e2e.py "http://127.0.0.1:$MOSAIC_PORT" || { docker compose -p "$project" logs --tail 200; exit 1; }
