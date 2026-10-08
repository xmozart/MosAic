#!/usr/bin/env bash
# Build the image for this machine and check it starts healthy, serves the UI, and runs an
# LGPL FFmpeg (ADR 0055). Leaves nothing running.
set -euo pipefail
cd "$(dirname "$0")/.."
TAG="${MOSAIC_IMAGE:-mosaic:dev}"
NAME="mosaic-smoke-$$"
docker build -t "$TAG" .
media="$(mktemp -d)"
secrets="$(mktemp -d)"
trap 'docker rm -f "$NAME" >/dev/null 2>&1 || true; rm -rf "$media" "$secrets"' EXIT
# The master key as compose passes it: a file secret, never on a command line or in Env.
(umask 077 && openssl rand -base64 48 > "$secrets/master_key")
docker run -d --name "$NAME" -p 127.0.0.1::8765 \
  -v "$secrets/master_key:/run/secrets/mosaic_master_key:ro" \
  -e MOSAIC_MASTER_KEY_FILE=/run/secrets/mosaic_master_key \
  -v "$media:/media" "$TAG" >/dev/null
for _ in $(seq 1 60); do
  [ "$(docker inspect -f '{{.State.Health.Status}}' "$NAME")" = healthy ] && break
  sleep 2
done
[ "$(docker inspect -f '{{.State.Health.Status}}' "$NAME")" = healthy ] || { docker logs "$NAME"; echo "not healthy" >&2; exit 1; }
port="$(docker port "$NAME" 8765 | head -1 | cut -d: -f2)"
curl -fsS "http://127.0.0.1:$port/" -o /dev/null
curl -fsS "http://127.0.0.1:$port/api/auth/status" | grep -q '"mode":"server"'
if docker exec "$NAME" ffmpeg -hide_banner -buildconf | grep -q -- "--enable-gpl"; then echo "GPL FFmpeg in the image" >&2; exit 1; fi
[ "$(docker exec "$NAME" id -u)" != 0 ] || { echo "runs as root" >&2; exit 1; }
if docker inspect -f '{{json .Config.Env}}' "$NAME" | grep -q "MOSAIC_MASTER_KEY="; then echo "master key in Env" >&2; exit 1; fi
docker exec "$NAME" sh -c 'test "$MOSAIC_FOLDER_DB" = never' || { echo "live DBs could land in footage folders" >&2; exit 1; }
echo "docker smoke: ok ($TAG)"
