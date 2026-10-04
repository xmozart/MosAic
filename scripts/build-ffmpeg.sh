#!/usr/bin/env bash
# Build an LGPL FFmpeg for development (ADR 0002 item B).
#
# Enabled: libzimg (WTFPL, for zscale tone mapping), VideoToolbox and
# AudioToolbox (macOS system frameworks), libopenh264 (BSD-2).
# Never enabled: --enable-gpl, --enable-nonfree, libx264, libx265.
#
# Output: <repo>/.tools/ffmpeg/bin/{ffmpeg,ffprobe}. Point MosAic at it with
#   mosaic config set ffmpeg.dir <repo>/.tools/ffmpeg/bin
# (the default lookup already prefers this path when it exists).
set -euo pipefail

FFMPEG_VERSION="${FFMPEG_VERSION:-8.1.2}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PREFIX="${PREFIX:-$REPO_ROOT/.tools/ffmpeg}"
WORK="${WORK:-$REPO_ROOT/.tools/build}"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This script targets macOS. Linux CI uses BtbN LGPL builds (scripts/fetch-ffmpeg-ci.sh)." >&2
  exit 1
fi

for dep in nasm pkg-config; do
  command -v "$dep" >/dev/null || { echo "missing $dep: brew install nasm pkg-config zimg openh264" >&2; exit 1; }
done
for lib in zimg openh264; do
  pkg-config --exists "$lib" || { echo "missing $lib: brew install $lib" >&2; exit 1; }
done

mkdir -p "$WORK" "$PREFIX"
cd "$WORK"
TARBALL="ffmpeg-$FFMPEG_VERSION.tar.xz"
if [[ ! -f "$TARBALL" ]]; then
  curl -L --fail -o "$TARBALL" "https://ffmpeg.org/releases/$TARBALL"
fi
rm -rf "ffmpeg-$FFMPEG_VERSION"
tar xf "$TARBALL"
cd "ffmpeg-$FFMPEG_VERSION"

./configure \
  --prefix="$PREFIX" \
  --disable-gpl --disable-nonfree \
  --disable-shared --enable-static \
  --disable-doc --disable-ffplay --disable-debug \
  --enable-videotoolbox --enable-audiotoolbox \
  --enable-libzimg --enable-libopenh264 \
  --extra-cflags="-I$(brew --prefix)/include" \
  --extra-ldflags="-L$(brew --prefix)/lib"

make -j"$(sysctl -n hw.ncpu)"
make install

"$PREFIX/bin/ffmpeg" -hide_banner -buildconf | grep -q -- "--enable-gpl" && {
  echo "ERROR: resulting build is GPL" >&2; exit 1; }
echo "LGPL FFmpeg $FFMPEG_VERSION installed to $PREFIX/bin"
