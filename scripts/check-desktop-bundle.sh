#!/usr/bin/env bash
# M3 acceptance 1 on this machine (ADR 0061): the app needs no Python, FFmpeg or Homebrew.
#
#   scripts/check-desktop-bundle.sh path/to/MosAic.app
#
# 1. Every Mach-O file in the app (its arm64 slice) links only macOS (/System, /usr/lib)
#    or files inside the app, and every @rpath/@loader_path load resolves inside the app.
#    No library search path points outside the app.
# 2. The bundled backend takes a trip from folder to rendered preview through its API
#    with an empty environment (PATH=/usr/bin:/bin: no uv, Homebrew or developer Python),
#    the bundled FFmpeg and the local SigLIP model (scripts/desktop_e2e.py).
# 3. Nothing was written into the app while it ran.
set -euo pipefail
APP="${1:?usage: $0 MosAic.app}"
RES="$APP/Contents/Resources"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
ABS_APP="$(cd "$APP" && pwd)"

echo "== linkage"
bad=0
while IFS= read -r f; do
  file -b "$f" | grep -q "Mach-O" || continue
  dir="$(cd "$(dirname "$f")" && pwd)"
  rpaths=()
  while IFS= read -r rp; do
    [[ -z "$rp" ]] && continue
    case "$rp" in
      @loader_path*) rpaths+=("${rp/@loader_path/$dir}") ;;
      @executable_path*) rpaths+=("${rp/@executable_path/$ABS_APP/Contents/Resources/backend/bin}") ;;
      *) echo "  $f: search path outside the app: $rp"; bad=1 ;;
    esac
  done < <(otool -arch arm64 -l "$f" 2>/dev/null | awk '/cmd LC_RPATH/{getline; getline; print $2}')
  self_id="$(otool -arch arm64 -D "$f" 2>/dev/null | tail -n +2 | head -1)"  # its own install name
  while IFS= read -r lib; do
    [[ -n "$self_id" && "$lib" == "$self_id" ]] && continue
    case "$lib" in
      /System/Library/*|/usr/lib/*) ;;
      @loader_path/*)
        [[ -e "${lib/@loader_path/$dir}" ]] || { echo "  $f -> $lib (missing)"; bad=1; } ;;
      @rpath/*)
        found=0
        for rp in "${rpaths[@]+"${rpaths[@]}"}"; do
          [[ -e "$rp/${lib#@rpath/}" ]] && { found=1; break; }
        done
        [[ $found == 1 ]] || { echo "  $f -> $lib (not inside the app)"; bad=1; } ;;
      *) echo "  $f -> $lib"; bad=1 ;;
    esac
  done < <(otool -arch arm64 -L "$f" 2>/dev/null | grep -v ':$' | awk '{print $1}')
done < <(find "$APP" -type f \( -perm -u+x -o -name "*.so" -o -name "*.dylib" \))
[[ $bad == 0 ]] || { echo "libraries outside macOS and the app" >&2; exit 1; }
echo "  ok"

echo "== a trip, end to end, with an empty environment"
marker="$(mktemp)"
env -i HOME="$HOME" PATH=/usr/bin:/bin TMPDIR="${TMPDIR:-/tmp}" PYTHONDONTWRITEBYTECODE=1 \
  ${MOSAIC_MODELS_DIR:+MOSAIC_MODELS_DIR="$MOSAIC_MODELS_DIR"} \
  "$RES/backend/bin/python3" -I -B "$REPO/scripts/desktop_e2e.py" "$RES"

echo "== the app is unchanged"
written="$(find "$APP" -newer "$marker" -type f | head -5)"
rm -f "$marker"
[[ -z "$written" ]] || { echo "written into the app at run time:"; echo "$written"; exit 1; }
echo "  ok"
