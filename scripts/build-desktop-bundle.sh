#!/usr/bin/env bash
# Builds the Mac app (M3 step 5; ADR 0061): stages the backend (a standalone Python with
# the locked runtime dependencies and the mosaic package), the web UI and the bundle
# FFmpeg, then `tauri build` makes MosAic.app and the DMG. Signed and notarized only when
# APPLE_SIGNING_IDENTITY (and the notarization credentials) are set; else unsigned.
#
#   scripts/build-desktop-bundle.sh            # → desktop/src-tauri/target/release/bundle/
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
# python-build-standalone (PSF and the libraries' own permissive licences; LICENSES.md).
PBS_TAG="20261003"
PBS_PY="3.12.15"
PBS_ASSET="cpython-$PBS_PY+$PBS_TAG-aarch64-apple-darwin-install_only.tar.gz"
PBS_SHA256="316a463172740e71d8dca1f2730784e325f3f720941137b5d674d5801a632213"
STAGE="$REPO/desktop/src-tauri/bundle-resources"
CACHE="$REPO/.tools/build"
ENTITLEMENTS="$REPO/desktop/src-tauri/entitlements.plist"

[[ "$(uname -s)" == "Darwin" && "$(uname -m)" == "arm64" ]] || { echo "Apple silicon Macs only (ADR 0061)" >&2; exit 1; }
# Unset secrets arrive as empty strings in CI: empty means unsigned, never `codesign -s ""`.
if [[ -z "${APPLE_SIGNING_IDENTITY:-}" ]]; then
  unset APPLE_SIGNING_IDENTITY APPLE_ID APPLE_PASSWORD APPLE_TEAM_ID
  echo "== unsigned build (no APPLE_SIGNING_IDENTITY; signing is gate G1)"
fi
sign() {  # the hardened runtime and our one entitlement (ADR 0061)
  codesign --force --timestamp --options runtime --entitlements "$ENTITLEMENTS" \
    -s "$APPLE_SIGNING_IDENTITY" "$@"
}
mkdir -p "$CACHE"
rm -rf "$STAGE" && mkdir -p "$STAGE"

echo "== web UI"
(cd "$REPO/frontend" && npm ci --no-audit --no-fund >/dev/null && npm run build >/dev/null)
cp -R "$REPO/frontend/dist" "$STAGE/ui"

echo "== FFmpeg (LGPL, self-contained)"
FF="$REPO/.tools/ffmpeg-bundle"
want="$(shasum -a 256 "$REPO/scripts/build-ffmpeg-bundle.sh" | cut -d' ' -f1)"
if [[ ! -x "$FF/bin/ffmpeg" || "$(cat "$FF/.built-by" 2>/dev/null)" != "$want" ]]; then
  "$REPO/scripts/build-ffmpeg-bundle.sh"  # missing, or built by another version of the script
fi
mkdir -p "$STAGE/ffmpeg"
cp "$FF/bin/ffmpeg" "$FF/bin/ffprobe" "$STAGE/ffmpeg/"

echo "== Python $PBS_PY (standalone)"
[[ -f "$CACHE/$PBS_ASSET" ]] || curl -L --fail -o "$CACHE/$PBS_ASSET" \
  "https://github.com/astral-sh/python-build-standalone/releases/download/$PBS_TAG/${PBS_ASSET//+/%2B}"
echo "$PBS_SHA256  $CACHE/$PBS_ASSET" | shasum -a 256 -c -
tar xzf "$CACHE/$PBS_ASSET" -C "$STAGE"
mv "$STAGE/python" "$STAGE/backend"
PY="$STAGE/backend/bin/python3"
LIB="$STAGE/backend/lib/python3.12"

echo "== backend (locked runtime dependencies, no dev tools)"
REQ="$CACHE/desktop-requirements.txt"
(cd "$REPO" && uv export --frozen --no-dev --no-emit-project --format requirements.txt -o "$REQ" >/dev/null)
uv pip install --python "$PY" --break-system-packages --no-deps --require-hashes -r "$REQ"
uv pip install --python "$PY" --break-system-packages --no-deps "$REPO"

echo "== trim"
# Only the interpreter stays in bin/: the console scripts' shebangs name this build
# machine. No Tk, IDLE, pip, test suites or headers.
find "$STAGE/backend/bin" -mindepth 1 ! -name python3 ! -name python3.12 -exec rm -rf {} +
rm -rf "$STAGE/backend/include" "$STAGE/backend/share" "$STAGE/backend/lib/tk"* "$STAGE/backend/lib/libtcl9tk"* \
  "$LIB/tkinter" "$LIB/idlelib" "$LIB/turtledemo" "$LIB/lib-dynload/_tkinter"* \
  "$LIB/site-packages/pip" "$LIB/site-packages/pip-"* "$LIB/ensurepip"
find "$LIB" -depth -type d \( -name tests -o -name test \) -prune -exec rm -rf {} +
"$PY" -I -c "import mosaic, onnxruntime, ctranslate2, numpy, scipy; print('backend imports ok')"

echo "== library search paths"
# Wheels can carry absolute rpaths from their build machines (Homebrew, CI runners). On a
# Mac that has those paths, a library could load from there instead of the app: keep only
# paths relative to the app (@loader_path, @executable_path), then re-sign what changed.
find "$STAGE" -type f \( -name "*.so" -o -name "*.dylib" -o -perm -u+x \) -print0 | while IFS= read -r -d '' f; do
  file -b "$f" | grep -q "Mach-O" || continue
  changed=0
  while IFS= read -r rp; do
    [[ "$rp" == @* ]] && continue
    install_name_tool -delete_rpath "$rp" "$f" 2>/dev/null && changed=1
  done < <(otool -l "$f" | awk '/cmd LC_RPATH/{getline; getline; print $2}' | sort -u)
  # Apple silicon kills code whose signature no longer matches: re-sign ad hoc (the
  # signed build signs everything again below). A failure here stops the build.
  if [[ $changed == 1 ]]; then codesign --force -s - "$f"; fi
done

echo "== bytecode"
# Everything compiled now, and the app runs Python with -B: nothing is written into the
# bundle at run time (a signed bundle's seal must not change).
"$PY" -I -m compileall -q -j 0 "$LIB"

if [[ -n "${APPLE_SIGNING_IDENTITY:-}" ]]; then
  # Notarization needs every Mach-O signed with the hardened runtime; Tauri signs only its
  # own binary, so the Python, its extension modules and FFmpeg are signed here first.
  echo "== signing nested code as $APPLE_SIGNING_IDENTITY"
  find "$STAGE" -type f \( -perm -u+x -o -name "*.so" -o -name "*.dylib" \) -print0 \
    | while IFS= read -r -d '' f; do
        file -b "$f" | grep -q "Mach-O" || continue
        sign "$f"
      done
fi

echo "== app"
(cd "$REPO/desktop" && npm ci --no-audit --no-fund >/dev/null && npx tauri build --bundles app,dmg)
du -sh "$REPO/desktop/src-tauri/target/release/bundle/macos/MosAic.app" "$REPO/desktop/src-tauri/target/release/bundle/dmg/"*.dmg
