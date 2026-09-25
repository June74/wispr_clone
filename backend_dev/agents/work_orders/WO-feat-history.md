# WO-feat-history — Temporary run history, retention and insertion attempts

```text
Work-order ID: WO-feat-history
Role file / requested model: RED + verify: sol-feature-test-author.md / gpt-6-sol
                             GREEN: luna-core-programmer.md / gpt-6-luna
Pipeline branch or P0/M stage: Wave 2, branch feat/history (needs storage; migration 004 merges
  after 002 settings and 003 dictionary)
Outcome and observable acceptance:
  Runs and insertion attempts are stored with the CODEMAP §5 invariants: at most 10 runs younger
  than 24 h (expire at equality), eviction/expiry notify the run controller deferred on the loop,
  age never renews, at most one automatic attempt per run, duplicate request ids deduplicated,
  insertion outcome derived from the latest attempt only, restart turns in-flight attempts into
  uncertain and pending cleanup into failed + awaiting_cleanup_choice, the original transcript is
  immutable, and deletion removes audio and both transcript versions (failed file deletion becomes
  a hidden retry task with no transcript). This is the persistence M2's insertion protocol needs.
Base revision / worktree / branch: 41a20f0 / ~/projects/wc-history / feat/history
  (coordinator rebases onto main after feat/dictionary-repo merges, before GREEN)
Relevant sections: CODEMAP.md §4 (insertion protocol steps 1-5, recovery rules), §5 (runs,
  insertion_attempts, WAV files, cleanup_status, derived outcome, retention and consistency);
  feature spec "Temporary history and deletion"; dev_pipeline.md §6 Wave 2 row feat/history;
  WO-feat-storage (Database API), WO-feat-settings-store (Connection/IntegrityError re-exports,
  migration merge order), WO-feat-dictionary-repo (test rule: never assert the latest version).
Exact writable paths (under backend_dev/):
  Sol:  tests/integration/history/**, tests/unit/history/**
  Luna: src/wispr_clone/history/__init__.py (docstring only), history/repo.py,
        history/retention.py, src/wispr_clone/storage/migrations/m004_history.py
Read-only: everything else.
Allowed imports: history -> storage (Database, Connection, IntegrityError), contracts, config,
  util + stdlib (json, asyncio, dataclasses, pathlib, os). Never `import sqlite3`.
Required tiers: S, U, I (real SQLite + real files in tmp_path) on ubuntu and windows.
Check commands (from backend_dev/, UV_LINK_MODE=copy):
  uv sync --locked; uv run ruff check .; uv run ruff format --check .;
  uv run mypy src scripts tests/_attribution tests/fakes; uv run python scripts/check_imports.py;
  uv run pytest -q -W error
Authorization: edit only writable paths; no git writes; no PRs; no new dependencies.
Privacy: transcripts, destination snapshots and config snapshots never appear in exception text,
  events or logs; events carry run ids and reasons only.
Deferred: the scheduled next-expiry timer and periodic sweep are wired in M5 (app composition);
  this order exposes `next_expiry_at()` and `enforce_retention()` for it. The claim → recheck →
  dispatch sequence itself is M2 (insertion_protocol); history only stores claims and outcomes.
Handoff: coordinator. Sol: RED command/output. Luna: GREEN outputs. Sol: verification findings.
```

## Schema: `m004_history.py` (VERSION 4, NAME "history"; `Connection` from storage.migrations)

```sql
CREATE TABLE runs (
    id TEXT PRIMARY KEY,
    start_request_id TEXT NOT NULL UNIQUE,
    created_at REAL NOT NULL,
    version INTEGER NOT NULL,
    status TEXT NOT NULL,              -- RunStatus value
    awaiting_since REAL,
    audio_path TEXT,
    audio_duration REAL,
    original_text TEXT,                -- write-once (trigger below)
    adjusted_text TEXT,
    cleaned_text TEXT,
    output_selection TEXT,             -- 'original' | 'adjusted' | 'cleaned' | NULL
    cleanup_status TEXT NOT NULL,      -- CleanupStatus value
    cleanup_reason TEXT,
    destination TEXT,                  -- JSON, opaque to history
    error_code TEXT,
    config TEXT NOT NULL               -- JSON minimal configuration snapshot
);
CREATE TABLE insertion_attempts (
    attempt_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    request_id TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL CHECK (kind IN ('automatic', 'explicit')),
    target TEXT,
    started_at REAL NOT NULL,
    completed_at REAL,
    outcome TEXT NOT NULL,             -- AttemptOutcome value
    seq INTEGER NOT NULL               -- monotonically increasing per database; "latest" = max seq
);
CREATE UNIQUE INDEX one_automatic_attempt_per_run ON insertion_attempts(run_id) WHERE kind = 'automatic';
CREATE TABLE pending_deletions (path TEXT PRIMARY KEY);   -- hidden retry tasks: a file path only
CREATE TRIGGER runs_original_text_write_once BEFORE UPDATE OF original_text ON runs
  WHEN OLD.original_text IS NOT NULL AND NEW.original_text IS NOT OLD.original_text
  BEGIN SELECT RAISE(ABORT, 'original_text is immutable'); END;
```

## Pinned API (use these exact names)

`wispr_clone.history.repo`:

```python
@dataclass(frozen=True, slots=True)
class RunRecord:
    id: str; start_request_id: str; created_at: float; version: int; status: RunStatus
    awaiting_since: float | None; audio_path: str | None; audio_duration: float | None
    original_text: str | None; adjusted_text: str | None; cleaned_text: str | None
    output_selection: str | None; cleanup_status: CleanupStatus; cleanup_reason: str | None
    destination: dict[str, object] | None; error_code: str | None; config: dict[str, object]

@dataclass(frozen=True, slots=True)
class AttemptRecord:
    attempt_id: str; run_id: str; request_id: str; kind: str   # "automatic" | "explicit"
    target: dict[str, object] | None; started_at: float; completed_at: float | None
    outcome: AttemptOutcome

@dataclass(frozen=True, slots=True)
class ClaimResult:
    attempt: AttemptRecord
    deduplicated: bool          # True: this request_id was already claimed; nothing new written

@dataclass(frozen=True, slots=True)
class DeleteResult:
    run_ids: tuple[str, ...]
    audio_pending: bool         # True when at least one WAV could not be deleted yet

@dataclass(frozen=True, slots=True)
class StartupReport:
    in_flight_to_uncertain: tuple[str, ...]      # attempt ids
    pending_cleanup_failed: tuple[str, ...]      # run ids
    expired: tuple[str, ...]
    deleted_orphan_wavs: int
    pending_deletions_left: int

UPDATABLE_FIELDS = frozenset({"status", "awaiting_since", "audio_path", "audio_duration",
    "original_text", "adjusted_text", "cleaned_text", "output_selection", "cleanup_status",
    "cleanup_reason", "destination", "error_code"})

class HistoryRepo:
    def __init__(self, db: Database, *, clock: Callable[[], float], audio_dir: Path,
                 events: EventSink,
                 on_run_evicted: Callable[[str], None] | None = None,
                 remove_file: Callable[[Path], None] = _unlink) -> None      # no I/O
    async def create_run(self, *, run_id: str, start_request_id: str,
                         config: Mapping[str, object],
                         destination: Mapping[str, object] | None = None,
                         audio_path: str | None = None) -> RunRecord
    async def get(self, run_id: str) -> RunRecord
    async def list_runs(self) -> tuple[RunRecord, ...]                 # newest first
    async def update_run(self, run_id: str, *, expected_version: int,
                         **fields: object) -> RunRecord
    async def claim_attempt(self, run_id: str, *, attempt_id: str, request_id: str,
                            kind: str, target: Mapping[str, object] | None = None) -> ClaimResult
    async def resolve_attempt(self, attempt_id: str, outcome: AttemptOutcome) -> AttemptRecord
    async def attempts(self, run_id: str) -> tuple[AttemptRecord, ...]  # oldest first
    async def insertion_outcome(self, run_id: str) -> InsertionOutcome
    async def delete_run(self, run_id: str) -> DeleteResult
    async def delete_all(self) -> DeleteResult
    async def enforce_retention(self) -> tuple[str, ...]              # expired run ids
    def next_expiry_at(self) -> float | None                           # from the last known state
    async def recover_on_startup(self) -> StartupReport
    async def retry_pending_deletions(self) -> int                     # files still pending
```

`wispr_clone.history.retention` holds the pure rules used by the repo:
`MAX_RUNS = config.MAX_RETAINED_RUNS` (10), `RETENTION_SECONDS = config.RUN_RETENTION_SECONDS`,
`is_expired(created_at, now) -> bool` (`created_at <= now - RETENTION_SECONDS`, equality expires),
`expires_at(created_at) -> float`, `runs_to_evict(created_ats_oldest_first, incoming=1) -> int`.

## Rules

- **Errors:** unknown run → `WisprError(ErrorCode.RUN_NOT_FOUND, "history", "run")`; a run that
  exists but is expired at access time is deleted first and then → `RUN_EXPIRED`; version
  mismatch → `STALE_VERSION`; unknown field or immutable field (`id`, `start_request_id`,
  `created_at`, `version`, `config`) in `update_run` → `VALIDATION`; changing a non-null
  `original_text` → `VALIDATION` (the trigger's `IntegrityError` is mapped; `why` names the field
  only). Unknown attempt → `RUN_NOT_FOUND`.
- **Age never renews (T-HIS-003):** nothing ever writes `created_at` after insert; `get`, `list`,
  `update_run`, attempts and recovery leave it unchanged.
- **Expiry first (T-HIS-004):** `get`, `list_runs`, `update_run`, `claim_attempt`,
  `insertion_outcome` enforce retention before acting.
- **create_run (T-HIS-001):** in ONE write: expire; if `start_request_id` already exists, return
  that run unchanged (no new row, no event); otherwise evict oldest (`created_at`, then `id`) until
  fewer than `MAX_RUNS` remain, insert with `version = 1`, `status = recording`,
  `cleanup_status = off`. After the transaction: publish `history:changed` (`reason` `"expired"`,
  `"evicted"`, then `"created"`; ids only) and schedule `on_run_evicted(run_id)` for every expired or
  evicted run with `asyncio.get_running_loop().call_soon` — NEVER called synchronously inside
  `create_run` (not re-entrant). The same deferral applies to every expiry path.
- **update_run:** version must match; bumps `version` by 1; returns the new record; publishes
  `history:changed` `"updated"`.
- **claim_attempt (T-HIS-007/008):** in ONE write: if `request_id` exists → `ClaimResult(existing,
  deduplicated=True)` (even if it belongs to another run: then `VALIDATION`); a second
  `automatic` claim for the same run → `WisprError(ErrorCode.DUPLICATE_REQUEST, "history",
  "automatic attempt")` (UNIQUE index, mapped); otherwise insert with `outcome = in_flight`,
  `started_at = clock()`, next `seq`.
- **resolve_attempt:** sets `outcome` and `completed_at = clock()`; only from `in_flight`
  (otherwise `VALIDATION`).
- **insertion_outcome (T-HIS-009):** `none` without attempts, else the outcome of the attempt with
  the highest `seq` (never an earlier one).
- **recover_on_startup (T-HIS-010/011/005/006):** in order: every `in_flight` attempt →
  `uncertain` (never re-dispatched); every run with `cleanup_status = pending` → `failed` and
  `status = awaiting_cleanup_choice` (version +1); expire; retry pending deletions; delete every
  `*.wav` in `audio_dir` that no run references and that is not a pending deletion. Returns the
  report; events and deferred callbacks as above.
- **Deletion (T-HIS-012/005):** `delete_run` / `delete_all` / expiry / eviction: in ONE write,
  delete the run rows (attempts cascade) and add each run's `audio_path` to `pending_deletions`;
  after commit, try `remove_file(path)` for each; on success remove the pending row; on `OSError`
  keep it (no transcript is stored there) and report `audio_pending=True`. A missing file counts as
  deleted. Settings and dictionary tables are never touched (T-DIC-013 re-check).
- **JSON columns** (`destination`, `config`, `target`) are stored with `json.dumps` and returned as
  dicts; a corrupted JSON column → `WisprError(STORAGE_ERROR, "history", "stored run <id>")`.

## Tests (Sol; `tests/fakes` FakeClock and FakeEventSink; real SQLite + files in tmp_path;
## explicit migration lists: m001_base, placeholder v2 and v3, m004_history)

| ID | Must assert |
|---|---|
| **T-HIS-001** (invariant) | creating the 11th live run evicts exactly the oldest; `on_run_evicted` is NOT called during `create_run` but is called once after one loop turn (`await asyncio.sleep(0)`), with the evicted id; `history:changed` events in order evicted, created; the evicted run's audio file is gone |
| **T-HIS-002** (invariant) | with FakeClock: a run created at t is available at t+24h−ε and expired at exactly t+24h (and after); expired → `RUN_EXPIRED` then `RUN_NOT_FOUND`; `retention.is_expired` truth table at the boundary |
| **T-HIS-003** (invariant) | `get`, `list_runs`, `update_run`, attempts, `resolve_attempt` and `recover_on_startup` never change `created_at`; a run updated repeatedly still expires 24 h after creation |
| **T-HIS-004** (invariant) | every read/claim path enforces expiry first (advance the clock past 24 h, then `get`/`list_runs`/`claim_attempt`/`insertion_outcome` each see the run gone) |
| T-HIS-005 | a `remove_file` that raises `OSError` → `DeleteResult.audio_pending` True; the run row and transcripts are gone; `pending_deletions` holds only the path; `retry_pending_deletions()` and `recover_on_startup()` delete it once the fault clears |
| T-HIS-006 | `recover_on_startup` deletes unreferenced WAVs in `audio_dir`, keeps referenced ones and non-WAV files |
| **T-HIS-007** (invariant) | a second automatic claim for a run → `DUPLICATE_REQUEST`, still one automatic row; explicit claims for the same run are allowed |
| **T-HIS-008** (invariant) | the same `request_id` claimed twice → second returns `deduplicated=True` with the same attempt, one row total; reused for a different run → `VALIDATION` |
| **T-HIS-009** (invariant) | outcome is `none` without attempts; with attempts [inserted, then a later explicit uncertain] it is `uncertain`; it follows the highest `seq`, not the latest timestamp |
| **T-HIS-010** (invariant) | an `in_flight` attempt becomes `uncertain` on `recover_on_startup` (on a reopened database file) and is never reported as inserted |
| **T-HIS-011** (invariant) | a run with `cleanup_status=pending` becomes `failed` + `awaiting_cleanup_choice` on restart, version +1 |
| **T-HIS-012** (invariant) | `delete_run` removes the WAV, `original_text`, `cleaned_text` and all attempts (cascade); `delete_all` removes every run and leaves rows in stand-in `settings` and `dictionary_entries` tables (created by a test migration) untouched |
| **T-HIS-013** (invariant) | `original_text` can be set once; changing it via `update_run` → `VALIDATION`; a direct SQL UPDATE is refused by the trigger |
| T-HIS-014 | `create_run` with an existing `start_request_id` returns the same run, no new row, no event; `update_run` with an unknown/immutable field → `VALIDATION`; stale version → `STALE_VERSION`; no transcript/destination sentinel ever appears in an event or error |
| T-HIS-015 | `m004_history` is version 4; history/ and the migration never import `sqlite3` (ast scan); T-DIC-013 re-check: with the real `m003_dictionary` in the list (once merged) dictionary rows survive `delete_all` |
