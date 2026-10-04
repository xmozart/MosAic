# ADR 0010 — Runtime libraries bundled inside permissive Python wheels

- **Status:** accepted (agent decision, M0 step 7). The owner should confirm this during
  commercial licensing review (OPEN_QUESTIONS Q-1).
- **Date:** 2026-10-04

## Context

Some dependencies with permissive licenses ship native runtime libraries under other
licenses inside their wheels:

| Wheel | Platform | Bundled library | License |
|---|---|---|---|
| SciPy | macOS, Linux, Windows | `libgfortran`, `libgcc_s`, `libquadmath` | GPL-3.0 with the GCC Runtime Library Exception 3.1 |
| CTranslate2 (faster-whisper) | Linux, Windows | Intel oneMKL, statically linked | Intel Simplified Software License (ISSL) |
| CTranslate2 | Linux | `libgomp` | GPL-3.0 with the GCC Runtime Library Exception 3.1 |
| CTranslate2 | Windows | `libiomp5md` (Intel OpenMP) | ISSL |
| CTranslate2 | macOS | none (links Apple Accelerate) | — |

`CLAUDE.md` allows MIT/BSD/Apache and similar without review, and requires an explicit ADR
for GPL. ISSL is not on either list.

## Options

1. Exclude these wheels and replace SciPy and CTranslate2 (no practical replacement for
   local Whisper inference of comparable speed).
2. Accept them, documented, because both licenses permit redistribution in proprietary
   products: the GCC Runtime Library Exception lets independent code linked with these
   runtime libraries be distributed under any terms; ISSL permits redistribution of the
   library in binary form with its notice.

## Decision

Option 2. These are compiler and math runtimes, not GPL application code. They are listed
in `LICENSES.md` with their license and platform. The Mac desktop build (first target) only
carries the GCC runtime libraries from SciPy; MKL and `libgomp` appear only on Linux
(server image, CI) and Windows.

GPL **codec** libraries remain forbidden (x264, x265, etc.; ADR 0008, 0009, and
`test_no_bundled_gpl_media_libraries`).

## Consequences

- Packaging (M2 server image, desktop builds) must include the ISSL and GCC runtime
  exception notices.
- If the owner's commercial review rejects either, the fallback is CPU inference without
  MKL (CTranslate2 built with OpenBLAS/ruy) on Linux, at some speed cost.
