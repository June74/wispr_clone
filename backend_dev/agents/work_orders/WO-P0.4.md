# WO-P0.4 — Failure-attribution plugin

```text
Work-order ID: WO-P0.4
Role file / requested model: RED + verify: sol-integration-test-author.md / gpt-6-sol
                             GREEN: luna-integration-programmer.md / gpt-6-luna
Pipeline branch or P0/M stage: P0.4, branch integ/p0.4-attribution
Outcome and observable acceptance:
  Every failing test is labelled OURS / NOT OURS / UNDETERMINED with the evidence pipeline §5.1
  requires, printed in the §5.5 format with a reproduce command, and optionally written to a JSON
  file for the later cross-job report. Probes run first. Quarantines older than 7 days fail.
Relevant sections: dev_pipeline.md §2.1 (quarantine rule), §5.1–§5.5, §6 row 0.4, §4.2 triage
  automation; agents/COMMON.md "Verification and triage".
Exact writable paths (under backend_dev/):
  Sol:  tests/diag/** (the T-DIAG meta-tests, using pytester) and tests/conftest.py (register the
        plugin, keep pytester)
  Luna: tests/_attribution/__init__.py, tests/_attribution/plugin.py (and any helper modules in
        tests/_attribution/*.py), tests/_attribution/impact/.gitkeep
Allowed imports for the plugin: stdlib (ast, json, tomllib, importlib.metadata, datetime,
  pathlib, sys, traceback) and pytest. No wispr_clone runtime code except contracts.common.ErrorCode
  (to validate impact fragments).
Marker usage the plugin understands (already registered in pyproject):
  @pytest.mark.probe("<dist>")        exercises only the third party <dist>
  @pytest.mark.adapter("<dist>")      our adapter over <dist>
  @pytest.mark.invariant("<text>")    names the invariant (reported for OURS)
  @pytest.mark.quarantine(issue="<id>", since="YYYY-MM-DD")
Verdict rules (implement exactly; fake-drift is deferred to P0.5 with the conformance harness):
  - Tests under tests/arch/ → OURS · architecture.
  - A failing probe("<dist>") test → NOT OURS for <dist> (with installed version).
  - A failing adapter("<dist>") test → look up probes for the same <dist> in this run:
      any probe failed → NOT OURS (<dist>); none ran or all skipped → UNDETERMINED (name the
      missing probe and that a runner with <dist> available must decide); all passed → OURS ·
      adapter-misuse, listing the probe IDs that passed ("probe coverage: ...").
  - Any other failing test: if the deepest traceback frame is inside site-packages, map that
      module to its distribution (importlib.metadata.packages_distributions) and apply the
      adapter rule for that distribution; otherwise OURS · logic with the deepest src/wispr_clone
      frame (file:line, function) and the invariant marker text if present.
  - Skips are never failures and never OURS/NOT OURS.
Report format (stdout, terminal summary), one block per failure, as in pipeline §5.5:
  [ATTRIBUTION] OURS · <category> | NOT OURS · <kind> | UNDETERMINED
  test:/reproduce:/where:/invariant:/source:/probe:/missing:/decide by: lines as applicable.
  reproduce is always `uv run pytest <nodeid-path> -k <test function name>`.
  With --attribution-json PATH, also write a JSON list with verdict, category, nodeid, dist,
  version, where, probes. Never include captured stdout/stderr or assertion text beyond the
  exception type and first line (privacy: no transcripts in artifacts).
Impact map: fragments tests/_attribution/impact/<dist>.toml with keys dependency, kind
  (library|service|platform), modules, features, error_codes, action. NOT OURS output includes
  modules/features/error_codes/action from the fragment when present. error_codes must be real
  ErrorCode VALUES (snake_case, e.g. "stt_unavailable").
Test IDs (Sol, pytester-driven):
  T-DIAG-001  fake-only failure → OURS · logic with the src frame file:line
  T-DIAG-002  failing probe → NOT OURS with dist name and installed version
  T-DIAG-003  adapter failure + probe passed → OURS · adapter-misuse with probe coverage
  T-DIAG-004  adapter failure + probe skipped/absent → UNDETERMINED naming the missing probe
  T-DIAG-005  every failure block prints a reproduce command that re-selects exactly that test
  T-DIAG-006  impact-map sync: parse src/ imports with ast; every third-party top-level import
              must appear in a fragment listing that module, every fragment module must really
              import it, and every fragment error_code must be a real ErrorCode value; exposed as
              a function the real suite calls against the real src and impact dir (passes now:
              src has no third-party imports yet)
  T-DIAG-007  a quarantine older than 7 days is a collection error; within 7 days it runs as
              xfail(strict=False) and is reported; missing since= is an error; core invariant
              tests (marked invariant) can never be quarantined
  Also: probes are collected/run before other tests (pytest_collection_modifyitems).
Check commands (from backend_dev/, UV_LINK_MODE=copy): uv sync --locked; uv run ruff check .;
  uv run ruff format --check .; uv run mypy src scripts; uv run python scripts/check_imports.py;
  uv run pytest -q -W error
Authorization: edit only writable paths; no git writes; coordinator commits, pushes, opens PR.
```

## Coordinator decisions after RED review

1. Accepted API: `check_impact_map_sync(src_root: Path, impact_dir: Path) -> None` in
   `tests/_attribution/plugin.py`; it raises `ValueError` (or `AssertionError`) naming the first
   mismatch. `src_root` is the directory that contains the `wispr_clone` package.
2. The conditional plugin registration in tests/conftest.py is allowed for RED only. In the verify
   step Sol makes it unconditional (`pytest_plugins = ("pytester", "_attribution.plugin")`), so a
   missing or broken plugin fails loudly.
