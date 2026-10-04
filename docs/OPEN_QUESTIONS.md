# Open Questions

Non-blocking questions the agent has parked with a default. The owner answers them in batches at gates.

Format: `Q-<n> · <question> · default used · impact if the default is wrong`

- Q-1 · Commercial licensing review of runtime libraries bundled in permissive wheels: GCC runtime (SciPy, CTranslate2 on Linux) and Intel oneMKL/OpenMP (CTranslate2 on Linux/Windows) · default used: accepted and documented (ADR 0010); the Mac build carries only the GCC runtime · impact if wrong: the server image would need CTranslate2 built without MKL (OpenBLAS), somewhat slower transcription
