# 0061 — The Mac app bundle: minimum macOS, Python, FFmpeg, signing, updates

- Status: accepted (M3 step 5)
- Deciders: agent (autonomous). Signing and notarization need the owner's Apple Developer ID (gate G1).

## Context

M3 asks for:
- Python bundled through python-build-standalone or PyInstaller;
- an LGPL FFmpeg with VideoToolbox;
- the first-run model downloads (ADR 0058);
- code signing, notarization and a DMG built from CI, with a signing step that skips when credentials are missing;
- the Tauri updater, off by default until release signing is set up.

Acceptance 1 is a clean Mac that runs analyze → edit → render with no Python, FFmpeg or Homebrew installed, on a minimum macOS version this ADR decides.

The development FFmpeg (`scripts/build-ffmpeg.sh`) links Homebrew libraries (X11/xcb, zimg, xz, OpenH264), so it cannot ship.

## Decision

- **Minimum macOS 14 (Sonoma), Apple silicon only.**
  - ADR 0057's session check needs WebKit's `Sec-Fetch-Site`, which arrived in macOS 13.3.
  - The ONNX Runtime and CTranslate2 wheels MosAic locks target macOS 14 on arm64.
  - Intel Macs and a universal build are out for now. A universal build would double the Python wheels, and the analysis models are too slow on Intel CPUs.
  - `LSMinimumSystemVersion` is 14.0.
- **Python: python-build-standalone**, not PyInstaller.
  - It is a relocatable CPython 3.12.15 (release 20261003, pinned by SHA-256) into which `uv pip install` puts exactly the locked runtime dependencies (`uv export --frozen --no-dev`, hash-checked) and the mosaic package.
  - The backend runs as `python3 -m mosaic.cli.main serve`, the same code as development and the server (invariant 12). No freezing step can drop a dynamically imported module.
  - The build removes:
    - `bin/` except the interpreter (the console scripts' shebangs name the build machine);
    - Tk, IDLE, pip, test suites and headers.
  - Wheels can carry absolute library search paths from their build machines (Homebrew, CI). A Mac with those paths could then load a library from there instead of from the app, so every non-relative `LC_RPATH` is deleted and the file re-signed.
  - Bytecode for the whole library, the standard library included, is compiled at build time.
  - The app runs the Python with `-I -B`:
    - no user site-packages;
    - no `PYTHON*` variables;
    - no bytecode written into the bundle, whose seal must not change once signed.
  - The package's build backend is pinned (`hatchling==1.32.4`).
  - The app is 466 MB; the DMG is 160 MB.
- **FFmpeg: `scripts/build-ffmpeg-bundle.sh`**, FFmpeg 8.1.2, LGPL, static, macOS 14 or later.
  - Its source tarball is pinned by SHA-256, like zimg's and Python's.
  - The bundle script rebuilds it when the build script changes, using a stamp next to the binaries.
  - zimg 3.0.6 (WTFPL, for `zscale` tone mapping) is compiled from a pinned source as a static library, without autotools.
  - pkg-config sees only that zimg, so nothing from Homebrew can slip in.
  - X11/xcb, xz, SDL and OpenH264 are left out: VideoToolbox encodes H.264 and HEVC on every supported Mac.
  - The script fails if the result links anything outside macOS, reports `--enable-gpl`, or lacks `zscale` or `h264_videotoolbox`.
- **Layout.** `MosAic.app/Contents/Resources/` holds:
  - `backend/` (the Python and its site-packages);
  - `ui/` (the web build);
  - `ffmpeg/` (`ffmpeg`, `ffprobe`).

  The shell finds `backend/bin/python3` and passes `MOSAIC_UI_DIR` and `MOSAIC_FFMPEG_DIR` (ADR 0060). Model weights are not bundled: S1 downloads them, verified (ADR 0058).
- **Build.** `scripts/build-desktop-bundle.sh` stages the three folders (`desktop/src-tauri/bundle-resources/`, not committed), then runs `tauri build --bundles app,dmg`.
- **Clean-machine check** (`scripts/check-desktop-bundle.sh`, run in CI after the build):
  - Every Mach-O file in the app (its arm64 slice) links only `/System`, `/usr/lib` or the app's own files.
  - Every `@rpath` and `@loader_path` load resolves inside the app, and no search path points outside it.
  - The bundled Python runs `scripts/desktop_e2e.py` with an empty environment (`PATH=/usr/bin:/bin`: no uv, Homebrew or developer Python). It generates clips with the bundled FFmpeg and starts the bundled backend as the shell does (`-I -B`, token on stdin). Cloud tasks run on the offline fake, and image understanding on the real SigLIP model in ONNX Runtime. The trip goes from folder to a ranged 206 of the rendered preview, and afterwards nothing in the app has changed.

  On the owner's Mac: scan 3 s, Quick analysis 13 s, edit 1 s, preview render 3 s.
- **Signing and notarization.** `.github/workflows/desktop.yml` builds on an Apple silicon runner. When the repository secrets exist (`APPLE_CERTIFICATE`, `APPLE_CERTIFICATE_PASSWORD`, `APPLE_SIGNING_IDENTITY`, `APPLE_ID`, `APPLE_PASSWORD`, `APPLE_TEAM_ID`):
  - CI imports the Developer ID certificate.
  - The bundle script signs every nested Mach-O (the Python, its extension modules, FFmpeg) with the hardened runtime.
  - `tauri build` signs and notarizes the app and the DMG.

  Without the secrets the same steps run unsigned: the signing variables are never set, and binaries are signed ad hoc, as Apple silicon requires. The DMG is uploaded as an artifact.
  - When signed, CI checks the result with `codesign --verify --deep --strict`, `spctl -a` and `stapler validate`, on both the app and the DMG.
  - The certificate file lives in `$RUNNER_TEMP` and is removed even on failure.
  - The certificate password (`security import -P`) and notarization's app-specific password pass through argv on the throwaway runner. That is the tools' only interface for these build credentials. Invariant 11 concerns the product's secrets, which never reach the build. An App Store Connect API key (`APPLE_API_KEY`, `APPLE_API_ISSUER`) can replace the app-specific password at G1.
  - The entitlements take one exception, `com.apple.security.cs.allow-unsigned-executable-memory`, for ctypes/libffi closures and ONNX Runtime. There is no App Sandbox (ADR 0060).
  - Whether notarization accepts the bundle can only be checked with the owner's credentials (G1).
- **Updates.** `tauri-plugin-updater` is an optional Cargo feature, `updater`, off in every build. A signed release build enables it with `--features updater --config tauri.updater.conf.json`, which sets the release public key and the update endpoint. Neither exists until release signing is set up (G1).
- **Licences.**
  - python-build-standalone ships CPython (PSF) with OpenSSL (Apache-2.0), libffi and expat (MIT), SQLite and xz (public domain), zlib, bzip2, mpdecimal, ncurses and libedit (BSD-style), and Tcl (BSD-style; Tk, tkinter and IDLE are removed from the bundle).
  - The updater's root-certificate data, `webpki-root-certs`, is under CDLA-Permissive-2.0, a permissive data licence with no copyleft. It is accepted here and checked by `scripts/check_rust_licenses.py` (all features: 479 crates).

## Consequences

- One `make desktop-bundle` (or the CI job) produces a DMG that runs without developer tools.
- The check runs on a machine that has developer tools installed. `env -i` clears the environment, not the disk, so a second, clean Mac is the final proof (procedure in the M3 report).
  - Until the app is signed and notarized, a downloaded DMG is quarantined: the first open is right-click → Open, or `xattr -dr com.apple.quarantine MosAic.app`.
- Intel Macs are not supported.
- The app carries about 350 MB of Python packages. A slimmer environment (for example, dropping SciPy for the few functions MosAic uses) is a later optimisation.
