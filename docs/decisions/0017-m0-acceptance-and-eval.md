# ADR 0017 — M0 acceptance suite and `make eval`

- **Status:** accepted (agent decision, M0 step 12)
- **Date:** 2026-10-05

## Context

M0 acceptance requires:
- every synthetic case end to end (analyze → edit → render), checked frame-accurate by
  barcode;
- no float times;
- zero repeat AI calls;
- a `make eval` on the owner's real corpus that produces the Airshow (3 min) and Dubai
  (75 s) edits, within the real-AI budget ($5 per run, $25 per milestone), with draft
  expectations.

The spec leaves open:
- how the offline fake AI makes an edit cover every synthetic case;
- where expectations and results live, given that trip folders may only receive
  `.mosaic-project.json` and `MosAic/`;
- how the budgets are enforced;
- how `make eval` reports a gate.

## Decision

1. **Fake AI coverage.** The fake selector goes round-robin over recordings. It gets each
   candidate's asset from the request's structured context; the rendered prompt is
   unchanged. The first clip of each recording is priority 5, extras lower. A long
   (150 s, energetic, strict-chronology) synthetic edit therefore includes every case,
   and the acceptance test asserts that.
2. **Acceptance tests** (`tests/acceptance/test_m0_e2e.py`, run by `make ci`):
   - the corrupt file is listed as unsupported, with a reason;
   - every required case is in the edit, with all blocking metrics at zero;
   - the lossless final render has exactly the expected frames and samples, and every
     event's barcodes are within ±1 frame (nearest PTS for VFR);
   - no float time values in any project-DB JSON column or in the edit export;
   - an identical re-edit makes zero AI calls.

   Acceptance 2 (kill -9 resume), 6 (licenses) and 7 (configuration) are covered by
   existing tests (`test_worker.py`, `test_m0_licenses.py`, `test_config.py`/`test_ai.py`).
3. **Where eval data lives.**
   - Trip folders get only the project descriptor and `MosAic/` (analysis, edits,
     renders). The renders are written there, never next to the originals.
   - Expectations live in the repo: `tests/evaluation/corpus/<trip>/expectations.yaml`.
     When missing they are drafted from the analysis, marked `draft: true`:
     - must-exclude: REJECTs for accidental, pocket, obstructed or black material;
     - must-include: high-interest, well-composed moments.
   - Results go to `tests/evaluation/results/M0/<trip>.json` (metrics, expectation score,
     render path and loudness, versions) and `<trip>.md` (the rubric, never overwritten).
   - The spend ledger is `tests/evaluation/results/M0/ledger.json`.
4. **Budgets.**
   - Each eval job is submitted with `cost_limit_usd` = the smaller of the run budget left
     and the milestone budget left, using the ledger.
   - A job that hits its limit pauses (`paused_cost_limit`), and the run stops at gate G2.
   - Providers billed by subscription (`claude-cli`, `codex-cli`, ADR 0014) report $0 and
     are bounded by the owner's plan instead.
5. **Gates.** `make eval` exits with code 3 at a human gate.
   - G1 lists exactly what is missing (corpus folder, provider key or app) and the
     `mosaic config` commands that fix it. With no key, it offers
     `mosaic config ai use claude-cli` / `codex-cli`.
   - The offline fake provider is refused for the eval.
6. **Paused jobs in the CLI.** `mosaic analyze` and `mosaic edit` stop following a job
   that paused at its cost limit and say how to raise the limit. Before this change,
   waiting would never end.

7. **Scoring expectations.** A moment's `file` is authoritative: it is resolved to the
   project's current asset, so re-initialising a project cannot mis-score. Ranges are
   compared in exact time even when their time base differs from the event's.
8. **Test isolation.** `pytest_configure` points `MOSAIC_HOME` at a temp folder and
   sets the fail keyring before any fixture of any scope. Tests can never reach the
   owner's app data, keychain or AI providers. An earlier module-scoped fixture had
   written test rows into the real control DB; they were removed.

## Consequences

- `make ci` covers acceptance 1, 2, 4, 5, 6, 7 and 8 offline. Acceptance 3 needs the owner's
  corpus and provider, so it is gate G1, then G6.
- Draft expectations are reported but never block until the owner confirms them
  (`draft: false`) at G6.
