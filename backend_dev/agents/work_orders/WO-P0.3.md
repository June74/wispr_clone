# WO-P0.3 — Import-boundary checker

```text
Work-order ID: WO-P0.3
Role file / requested model: RED + verify: sol-integration-test-author.md / gpt-6-sol
                             GREEN: luna-integration-programmer.md / gpt-6-luna
Pipeline branch or P0/M stage: P0.3, branch integ/p0.3-import-checker
Outcome and observable acceptance:
  scripts/check_imports.py enforces CODEMAP §3 dependency directions on src/wispr_clone and runs
  in CI's static job. Violations and cycles are reported as path:line with the rule broken.
Base revision / worktree / branch: 67c7b58 / ~/projects/wc-p0-3 / integ/p0.3-import-checker
Relevant sections: CODEMAP.md §3 ("Contracts and dependency direction" table, contracts rule);
  dev_pipeline.md §6 row 0.3, §5.2 (import-boundary failures are OURS · architecture).
Exact writable paths (under backend_dev/ unless noted):
  Sol:  tests/arch/**
  Luna: scripts/check_imports.py, and .github/workflows/ci.yml (repo root; add one step to the
        `static` job: `uv run python scripts/check_imports.py`)
Allowed imports for the checker itself: standard library only (ast, graphlib, pathlib, argparse).
Test IDs:
  T-ARCH-001 (core) the application import graph is acyclic (graphlib); a seeded cycle in a
             temporary package tree is reported and exits non-zero.
  T-ARCH-002 (core) each package imports only what the rule table below allows; a seeded bad
             import in a temporary tree is reported with the offending file and line number.
  T-ARCH-003 contracts/, config and util import nothing above them (a seeded upward import is
             reported); the real src/wispr_clone passes cleanly.
CLI contract (tests use it as a black box via subprocess):
  python scripts/check_imports.py [--root PATH]   (PATH = the wispr_clone package directory;
                                                   default: src/wispr_clone next to the script)
  exit 0 when clean; exit 1 on any violation or cycle; each violation on its own stdout line:
  `<path relative to root>:<line>: <importer> -> <imported>: <reason>`
  Relative imports (from . / from ..) are resolved to absolute wispr_clone modules.
  Only imports of wispr_clone.* are judged; stdlib and third-party imports are ignored here.
Rule table (package = first component under wispr_clone; a package may always import itself):
  base = {contracts, config, util}
  contracts   -> {contracts}
  config      -> {contracts}
  util        -> {contracts, config}
  storage, hotkeys, audio, stt, cleanup, models, insertion -> base
  dictionary, history, settings -> base + {storage}
  pipeline    -> base + {audio, stt, cleanup, dictionary, history, insertion}
  application -> base + {pipeline, audio, settings, dictionary, history, models, stt, cleanup}
  ui          -> base + {application}
  app, __main__ -> any wispr_clone package (composition root)
  Any package not in the table is a violation ("unknown package") until the table is updated.
  Finer rules inside application/ (api -> commands only) are out of scope for this order.
Check commands (from backend_dev/, UV_LINK_MODE=copy): uv sync --locked; uv run ruff check .;
  uv run ruff format --check .; uv run mypy src; uv run python scripts/check_imports.py;
  uv run pytest -q -W error
RED rule: the script does not exist yet; a failing subprocess (missing file) is accepted RED only
  if the tests would also fail against a checker that ignores relative imports or line numbers.
Authorization: edit only writable paths; no git writes; coordinator commits, pushes, opens PR.
Handoff: coordinator.
```
