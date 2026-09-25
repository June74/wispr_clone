# WO-P0.6 — Full CI skeleton, attribution report, nightly triage

```text
Work-order ID: WO-P0.6
Role file / requested model: RED + verify: sol-integration-test-author.md / gpt-6-sol
                             GREEN: luna-integration-programmer.md / gpt-6-luna
Pipeline branch or P0/M stage: P0.6, branch integ/p0.6-ci
Outcome and observable acceptance:
  CI runs every hosted tier on the current (small) suite; each test job uploads its attribution
  JSON; an always-running `attribution-report` job merges them and writes a Markdown summary to
  the run page ("0 failures" when clean). A nightly workflow checks dependency drift and opens or
  updates one `triage` issue on failure. Branch protection is applied by the coordinator after merge.
Relevant sections: dev_pipeline.md §4.1–§4.3 (tiers, workflows, required checks, triage
  automation), §5.3 (cross-job merge), §5.5 (report format); DEPENDENCIES.md (no new packages).
Exact writable paths:
  Sol:  backend_dev/tests/ci/** (tests for the report script)
  Luna: backend_dev/scripts/attribution_report.py, .github/workflows/ci.yml,
        .github/workflows/nightly.yml (repository root)
Scope decision: release.yml is DEFERRED to M6 (it needs the packaged app and `--self-test`, which
  arrive in M5/M6). Web (`node --test`) job is added when web/ exists (feat/web-runtime).
attribution_report.py (stdlib only, typed, testable as a module and via CLI):
  python scripts/attribution_report.py OUT.md INPUT.json [INPUT.json ...]
  - Reads the plugin's JSON lists (missing/empty files allowed and reported as "no report").
  - Merges them; a probe result from any job can resolve an UNDETERMINED for the same dist in the
    same commit (e.g. nightly GPU probe): an UNDETERMINED whose dist has a passing probe in another
    input stays UNDETERMINED but notes "probe passed in <job>"; a failing probe elsewhere turns it
    into NOT OURS. (Inputs carry a job name derived from the file name `attribution-<job>.json`.)
  - Writes Markdown: a totals line ("0 failures" when none), then a table per verdict with nodeid,
    category/dist, where, and the reproduce command. Never includes captured output.
  - Exit code 0 always (the report job must not hide test failures; the test jobs already fail).
ci.yml changes:
  - Jobs: `static` (unchanged + import checker), `unit` matrix ubuntu/windows running
    `pytest -m "not probe and not gpu and not e2e and not manual" --attribution-json
    attribution-unit-<os>.json`, `probes` matrix ubuntu/windows running `pytest -m "probe and not
    gpu"` (passes when no probes are collected: treat exit code 5 "no tests" as success), and
    `attribution-report` (needs all, `if: always()`, downloads the JSON artifacts, runs the script,
    appends to $GITHUB_STEP_SUMMARY).
  - Keep workflow-level PYTHONUTF8=1, pinned action versions, `uv sync --locked`.
nightly.yml: schedule (daily) + workflow_dispatch. Job `drift`: copy the project to a scratch dir,
  `uv lock --upgrade`, `uv sync`, run unit + hosted probes; on failure open or update ONE issue
  labelled `triage` titled "Nightly dependency drift" with the run URL and the attribution summary
  (use `gh` with `permissions: issues: write`). No secrets beyond the default GITHUB_TOKEN.
Test IDs (Sol, via the script's Python API and CLI with temporary JSON files):
  T-CI-003 no failures → Markdown contains "0 failures"; missing/empty inputs are reported, not fatal
  T-CI-004 merged verdict tables list every failure once with its reproduce command
  T-CI-005 an UNDETERMINED is upgraded to NOT OURS when another job's probe for that dist failed,
           and annotated (not upgraded) when it passed
  T-CI-006 the report never contains captured output / private sentinel text from inputs beyond
           the fields the plugin writes
Check commands (from backend_dev/, UV_LINK_MODE=copy): uv sync --locked; uv run ruff check .;
  uv run ruff format --check .; uv run mypy src scripts tests/_attribution tests/fakes;
  uv run python scripts/check_imports.py; uv run pytest -q -W error
  Workflows are validated by the real CI run of this PR (both OS) — the coordinator checks the run
  page summary shows "0 failures".
Authorization: edit only writable paths; no git writes; coordinator commits, pushes, opens PR,
  and applies branch protection after merge.
```

## Coordinator decisions after verification (first hosted run: all 6 jobs green)

1. Unreadable input (malformed JSON, invalid UTF-8, wrong shape) is reported as
   "unreadable report from <job>" and never crashes the script; exit code stays 0.
2. Everything user-controlled in the Markdown (nodeid, dist, where, reproduce) is escaped: shown as
   inline code with backticks neutralised, HTML special characters escaped, newlines replaced, and
   `|` escaped, so test names cannot inject links, HTML or table cells.
3. The CI report step passes the EXPECTED artifact paths explicitly (one per unit/probes job and
   OS), not a glob; a missing one is shown as "missing report from <job>" and the totals line says
   "INCOMPLETE" instead of "0 failures".
4. nightly.yml: `concurrency: {group: nightly-drift, cancel-in-progress: false}` and the issue step
   finds an existing open issue by exact title before creating one.
5. Every checkout in ci.yml and nightly.yml sets `persist-credentials: false`; the issue step gets
   GH_TOKEN explicitly.
