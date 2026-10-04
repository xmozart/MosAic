#!/usr/bin/env bash
# Fetch BtbN's LGPL static FFmpeg for Linux CI (ADR 0002 item B).
# Installs into <repo>/.tools/ffmpeg/bin, the default lookup location.
set -euo pipefail

SERIES="${FFMPEG_SERIES:-8.1}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$REPO_ROOT/.tools/ffmpeg/bin"
NAME="ffmpeg-n${SERIES}-latest-linux64-lgpl-${SERIES}"
URL="https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/${NAME}.tar.xz"

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "This script is for Linux CI. On macOS run scripts/build-ffmpeg.sh." >&2
  exit 1
fi

mkdir -p "$DEST"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
curl -L --fail -o "$tmp/ffmpeg.tar.xz" "$URL"
tar -xf "$tmp/ffmpeg.tar.xz" -C "$tmp"
cp "$tmp/$NAME/bin/ffmpeg" "$tmp/$NAME/bin/ffprobe" "$DEST/"
"$DEST/ffmpeg" -hide_banner -buildconf | grep -q -- "--enable-gpl" && {
  echo "ERROR: fetched build is GPL" >&2; exit 1; }
"$DEST/ffmpeg" -hide_banner -version | head -1
