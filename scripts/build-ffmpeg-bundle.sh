#!/usr/bin/env bash
# The FFmpeg the Mac app ships (M3 step 5; ADR 0061): LGPL, self-contained.
#
# Unlike the development build (scripts/build-ffmpeg.sh) it links nothing outside macOS:
# zimg (WTFPL, for zscale tone mapping) is built here from a pinned source as a static
# library, pkg-config sees only that, and X11/xcb, xz, SDL and OpenH264 are left out
# (VideoToolbox encodes H.264 and HEVC on every supported Mac). Built for macOS 14+.
#
# Never enabled: --enable-gpl, --enable-nonfree, libx264, libx265.
# Output: <repo>/.tools/ffmpeg-bundle/bin/{ffmpeg,ffprobe}.
set -euo pipefail

# Pinned with its hash: a different version needs its own FFMPEG_SHA256.
FFMPEG_VERSION="${FFMPEG_VERSION:-8.1.2}"
FFMPEG_SHA256="${FFMPEG_SHA256:-464beb5e7bf0c311e68b45ae2f04e9cc2af88851abb4082231742a74d97b524c}"
ZIMG_VERSION="3.0.6"
ZIMG_SHA256="be89390f13a5c9b2388ce0f44a5e89364a20c1c57ce46d382b1fcc3967057577"
MACOS_MIN="14.0"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PREFIX="${PREFIX:-$REPO_ROOT/.tools/ffmpeg-bundle}"
WORK="${WORK:-$REPO_ROOT/.tools/build}"
DEPS="$WORK/bundle-deps"
JOBS="$(sysctl -n hw.ncpu)"

[[ "$(uname -s)" == "Darwin" ]] || { echo "macOS only" >&2; exit 1; }
command -v nasm >/dev/null || { echo "missing nasm" >&2; exit 1; }
command -v pkg-config >/dev/null || { echo "missing pkg-config" >&2; exit 1; }
ARCH="$(uname -m)"
FLAGS="-mmacosx-version-min=$MACOS_MIN -O2"

mkdir -p "$WORK" "$DEPS/lib/pkgconfig" "$DEPS/include"
cd "$WORK"

# ---- zimg, static, compiled directly (no autotools needed)
ZTAR="zimg-$ZIMG_VERSION.tar.gz"
[[ -f "$ZTAR" ]] || curl -L --fail -o "$ZTAR" \
  "https://github.com/sekrit-twc/zimg/archive/refs/tags/release-$ZIMG_VERSION.tar.gz"
echo "$ZIMG_SHA256  $ZTAR" | shasum -a 256 -c -
rm -rf "zimg-release-$ZIMG_VERSION" zimg-objs && tar xzf "$ZTAR" && mkdir zimg-objs
SRC="zimg-release-$ZIMG_VERSION/src/zimg"
SIMD=()
[[ "$ARCH" == "arm64" ]] && SIMD=(-DZIMG_ARM)
find "$SRC" -name "*.cpp" ! -path "*/x86/*" | if [[ "$ARCH" == "arm64" ]]; then cat; else grep -v "/arm/"; fi \
  | while read -r f; do
      o="zimg-objs/$(echo "${f#"$SRC"/}" | tr / _).o"
      echo "clang++ -std=c++14 $FLAGS -DNDEBUG ${SIMD[*]} -I$SRC -c $f -o $o"
    done | xargs -P "$JOBS" -I{} sh -c '{}'
ar rcs "$DEPS/lib/libzimg.a" zimg-objs/*.o
cp "$SRC/api/zimg.h" "$SRC/api/zimg++.hpp" "$DEPS/include/"
cat > "$DEPS/lib/pkgconfig/zimg.pc" <<EOF
prefix=$DEPS
libdir=\${prefix}/lib
includedir=\${prefix}/include
Name: zimg
Description: Scaling, colorspace conversion and dithering library
Version: $ZIMG_VERSION
Libs: -L\${libdir} -lzimg -lc++
Cflags: -I\${includedir}
EOF

# ---- FFmpeg, static, LGPL
TARBALL="ffmpeg-$FFMPEG_VERSION.tar.xz"
[[ -f "$TARBALL" ]] || curl -L --fail -o "$TARBALL" "https://ffmpeg.org/releases/$TARBALL"
echo "$FFMPEG_SHA256  $TARBALL" | shasum -a 256 -c -
rm -rf "ffmpeg-$FFMPEG_VERSION" && tar xf "$TARBALL"
cd "ffmpeg-$FFMPEG_VERSION"
# Only our zimg is visible to pkg-config: nothing from Homebrew can slip in.
PKG_CONFIG_LIBDIR="$DEPS/lib/pkgconfig" ./configure \
  --prefix="$PREFIX" \
  --disable-gpl --disable-nonfree \
  --disable-shared --enable-static --pkg-config-flags=--static \
  --disable-doc --disable-ffplay --disable-debug \
  --disable-xlib --disable-libxcb --disable-sdl2 --disable-lzma --disable-libopenh264 \
  --enable-videotoolbox --enable-audiotoolbox \
  --enable-libzimg \
  --extra-cflags="$FLAGS" --extra-ldflags="-mmacosx-version-min=$MACOS_MIN"
make -j"$JOBS"
rm -rf "$PREFIX" && make install

# ---- checks
for bin in ffmpeg ffprobe; do
  if otool -L "$PREFIX/bin/$bin" | tail -n +2 | grep -vE "^\s+(/System/Library/|/usr/lib/)"; then
    echo "ERROR: $bin links a library outside macOS" >&2; exit 1
  fi
done
# Each listing is captured first: `cmd | grep -q` under pipefail can fail on SIGPIPE.
conf="$("$PREFIX/bin/ffmpeg" -hide_banner -buildconf)"
[[ "$conf" != *"--enable-gpl"* && "$conf" != *"--enable-nonfree"* ]] || { echo "ERROR: GPL or nonfree build" >&2; exit 1; }
[[ "$("$PREFIX/bin/ffmpeg" -hide_banner -filters)" == *" zscale "* ]] || { echo "ERROR: no zscale" >&2; exit 1; }
[[ "$("$PREFIX/bin/ffmpeg" -hide_banner -encoders)" == *"h264_videotoolbox"* ]] || { echo "ERROR: no VideoToolbox" >&2; exit 1; }
shasum -a 256 "$0" | cut -d' ' -f1 > "$PREFIX/.built-by"  # rebuild when this script changes
echo "bundle FFmpeg $FFMPEG_VERSION (LGPL, macOS $MACOS_MIN+, $ARCH) installed to $PREFIX/bin"
