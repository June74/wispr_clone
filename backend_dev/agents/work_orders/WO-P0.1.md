# WO-P0.1 — Project scaffold

```text
Work-order ID: WO-P0.1
Role file / requested model: RED + verify: sol-integration-test-author.md / gpt-6-sol
                             GREEN: luna-integration-programmer.md / gpt-6-luna
Pipeline branch or P0/M stage: P0.1 Scaffold, branch integ/p0.1-scaffold
Outcome and observable acceptance:
  A Python 3.12 project exists at backend_dev/ that uv can lock and sync; pytest runs with
  every pipeline marker registered and unknown markers rejected; CI runs static checks and
  unit tests on ubuntu-latest and windows-latest.
Base revision / worktree / branch: fcae1ec + f984d86 / ~/projects/wc-p0-1 / integ/p0.1-scaffold
Relevant spec, codemap, and pipeline sections:
  dev_pipeline.md §2.1–2.2, §4.1–4.2, §4.5, §6 Phase 0 row 0.1, §7.2 main-agent-only files;
  DEPENDENCIES.md (approved baseline); CODEMAP.md §3 planned layout; agents/HARDWARE.md tools row.
Prerequisites and evidence: Phase −1 complete (G1–G4, CODEMAP §7). G1 layout: one WSL checkout,
  Windows venv on the Windows disk via UV_PROJECT_ENVIRONMENT.
Exact writable paths:
  Sol:  backend_dev/tests/conftest.py, backend_dev/tests/test_ci_scaffold.py
  Luna: backend_dev/pyproject.toml, backend_dev/uv.lock, backend_dev/.python-version,
        backend_dev/src/wispr_clone/__init__.py, .github/workflows/ci.yml (repository root)
Read-only interfaces/callers to inspect: everything else.
Frozen contract version and allowed imports: none yet (contracts arrive in P0.2).
Test IDs and expected assertions:
  T-CI-001  a trivial test is collected and passes (CI proves it on ubuntu and windows).
  T-CI-002  every pipeline marker is registered: unit, integration, conformance, probe, adapter,
            windows, gpu, e2e, manual, feature, invariant, quarantine; a test using an
            unregistered marker is a collection error (--strict-markers), checked with pytester.
Probe IDs / conformance cases / sole impact-fragment owner: none.
RED owner (GPT-6 Sol) and test revision: gpt-6-sol, first pass.
GREEN owner (GPT-6 Luna): gpt-6-luna.
Verification owner and PR opener (GPT-6 Sol): gpt-6-sol verifies; in B1 mode the coordinator
  performs all git commits, the push and the PR on the agents' behalf.
Shared branch worktree (Sol and Luna take turns): ~/projects/wc-p0-1
Required tiers / OS / devices / servers: S and U. No GPU, no desktop, no LM Studio.
Exact check commands (run from backend_dev/ once pyproject exists):
  uv lock && uv sync --locked
  uv run ruff check . && uv run ruff format --check .
  uv run mypy src
  uv run pytest -q
Existing authorization: agents edit only their writable paths and may use the network for
  package resolution. Agents do NOT run git commands that write (commit, push, branch) and do
  NOT open PRs; the coordinator does that. No model downloads, no LM Studio changes.
Resource lease: none heavy. Serial pytest.
Shared-file reservations: tests/conftest.py → Sol integration (this order); pyproject/uv.lock/ci.yml
  → Luna integration (this order).
CCRs / unresolved decisions:
  - UI Automation client (uiautomation vs comtypes) is NOT in this baseline; it is added later by
    the coordinator when feat/insertion-win decides.
  - keyring (optional, cloud only) is NOT in this baseline.
Handoff destination and expected evidence: the coordinator. Sol: RED command + output and why it is
  the right failure. Luna: GREEN command outputs for every check above. Sol: verification result.
```

## Dependency baseline for pyproject.toml (from DEPENDENCIES.md)

- `requires-python = ">=3.12,<3.13"`; `.python-version` = `3.12`.
- src layout: package `wispr_clone` under `backend_dev/src/`.
- Runtime, all platforms: `numpy`, `soxr`, `httpx`, `pydantic`, `sounddevice`.
- Runtime, Windows only (`sys_platform == 'win32'`): `pywin32`, `pynput`, `pywebview`,
  `transcribe-cpp` and `transcribe-cpp-native-cu12` 0.2.3 as direct URLs from
  https://github.com/handy-computer/transcribe.cpp/releases/download/v0.2.3/ (files
  `transcribe_cpp-0.2.3-py3-none-any.whl`, `transcribe_cpp_native_cu12-0.2.3-py3-none-win_amd64.whl`).
- Dev group: `pytest`, `pytest-asyncio`, `ruff`, `mypy`; `pyinstaller` Windows only.
- Pin nothing tighter than needed; `uv.lock` records exact versions and hashes. If a Windows-only
  package makes the universal lock fail, report it instead of dropping the package.

## CI (ci.yml) for this step

- Triggers: push and pull_request.
- `defaults.run.working-directory: backend_dev`.
- Jobs: `static` (ubuntu: ruff check, ruff format --check, mypy src) and `unit` with an OS matrix
  of ubuntu-latest and windows-latest (pytest). Install uv with the official astral-sh/setup-uv
  action pinned to a released version; `uv sync --locked`. Python 3.12.
- Job names must be exactly `static` and `unit` (branch protection will require them in P0.6).
