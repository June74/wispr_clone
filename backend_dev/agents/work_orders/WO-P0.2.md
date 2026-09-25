# WO-P0.2 — Contracts v1 (frozen)

```text
Work-order ID: WO-P0.2
Role file / requested model: RED + verify: sol-integration-test-author.md / gpt-6-sol
                             GREEN: luna-integration-programmer.md / gpt-6-luna
Pipeline branch or P0/M stage: P0.2 Contracts v1, branch integ/p0.2-contracts
Outcome and observable acceptance:
  The shared cross-package types exist, are data-only, stdlib-only, JSON-serializable, strictly
  typed, and match CODEMAP §4–§6 exactly. After merge they are FROZEN: later changes need a CCR.
Base revision / worktree / branch: b903fe7 / ~/projects/wc-p0-2 / integ/p0.2-contracts
Relevant spec, codemap, and pipeline sections:
  CODEMAP.md §3 (layout; "Contracts rule"; dependency table), §4 (run lifecycle, hybrid delivery,
  recovery, insertion protocol), §5 (runs, insertion_attempts, cleanup_status, derived outcome),
  §6 (command/event contract); dev_pipeline.md §5.3 (ThirdPartyError/WisprError), §6 row 0.2.
Prerequisites: P0.1 merged (scaffold, markers, CI).
Exact writable paths (all under backend_dev/):
  Sol:  tests/unit/contracts/** (new)
  Luna: src/wispr_clone/contracts/__init__.py, contracts/common.py, contracts/events.py,
        contracts/run.py, contracts/shortcuts.py (named, EMPTY module with a docstring only;
        feat/hotkeys fills it later), src/wispr_clone/config.py,
        src/wispr_clone/util/__init__.py, src/wispr_clone/util/error_messages.py
Read-only: everything else.
Allowed imports: contracts/, config and util import only the Python standard library (and each
  other in the direction util/config -> contracts is NOT allowed: contracts import nothing from
  config or util; config and util may import contracts). No pydantic or third-party packages here.
Test IDs and expected assertions:
  T-CON-001 (core)  Result is exactly one of ok/error: ok carries data and no error; failure
                    carries an ErrorCode-based error and no data; invalid combinations are rejected.
  T-CON-002 (core)  every ErrorCode member has a user message and at least one recovery action in
                    util/error_messages.py (exhaustive; adding a code without a message fails).
  T-CON-003         every event payload type serializes with json.dumps using data-only types
                    (no callables, no enums leaking as objects, no datetime objects unless
                    converted), and carries run_id, version and status where the event is run-specific.
  T-CON-004         ThirdPartyError carries dependency, operation, detail and error_code;
                    WisprError carries error_code, where and why; both are Exceptions.
  T-CON-005         RunStatus, AttemptOutcome (plus the derived "none") and CleanupStatus values
                    equal exactly the sets in CODEMAP §4/§5 (listed below).
Values that must match exactly (from CODEMAP):
  RunStatus: recording, processing, awaiting_cleanup_choice, awaiting_destination, held, done,
             error, uncertain, cancelled
  AttemptOutcome: in_flight, inserted, failed, uncertain, cancelled; derived insertion outcome
             adds none
  CleanupStatus: off, pending, ok, failed, rejected
  Recovery actions accepted by run_recover: retry_stt, retry_cleanup, use_original, copy, insert
  Event names: run:state, run:recovery, models:status, history:changed, audio:level
ErrorCode set (Luna defines; each must trace to a behavior in CODEMAP/spec/pipeline):
  at least: validation, unknown command, stale version, expired command, previous session token,
  run not found / expired / deleted, duplicate request, device lease conflict, microphone
  unavailable/disconnected, audio queue overflow, no speech detected, STT unavailable / model load
  failed / timeout / stream closed, cleanup unavailable / timeout / rejected by guard, cloud model
  forbidden in local-only mode, non-loopback endpoint, destination unverifiable / closed / wait
  limit exceeded, insertion failed, insertion uncertain, storage error, deletion failed.
  Recovery-action vocabulary for messages may include UI actions (e.g. open_settings, choose_mic,
  dismiss) in addition to the run_recover actions.
Also include: CONTRACT_VERSION = 1 in contracts/__init__.py.
config.py: paths (%LOCALAPPDATA%\WisprClone, history dir) resolved lazily (no I/O at import) and
  validated operational limits from the spec/CODEMAP: 10 runs, 24 h retention, 1 s idle jump,
  0.3 s return settle, 10 min destination wait limit, LM Studio endpoint http://127.0.0.1:1234/v1
  and model id meta-llama-3.1-8b-instruct. Limits are constants with types; no environment secrets.
Required tiers: S and U on ubuntu and windows (pure stdlib; must import on Linux).
Check commands (from backend_dev/, UV_LINK_MODE=copy):
  uv sync --locked; uv run ruff check .; uv run ruff format --check .; uv run mypy src;
  uv run pytest -q -W error
RED rule for this order: the contract modules do not exist yet, so an ImportError on the new
  names is accepted as RED here (coordinator decision); also include at least one assertion that
  would fail against a plausible wrong implementation (e.g. a missing RunStatus member).
Authorization: agents edit only their writable paths; no git writes; no PRs; the coordinator
  commits, pushes and opens the PR.
Handoff: coordinator. Sol: RED command/output. Luna: GREEN outputs for every check.
  Sol: verification result and review findings.
```

## Coordinator decisions after RED review (binding for Sol's revision and Luna's GREEN)

Public names (Sol's choices accepted): `contracts.common`: `Result`, `ErrorCode`, `ThirdPartyError`,
`WisprError`; `contracts.run`: `RunStatus`, `AttemptOutcome`, `InsertionOutcome` (adds `none`),
`CleanupStatus`, `RecoveryAction` (the five run_recover actions); `contracts.events`: `EventSink`
(Protocol with `publish(event) -> None`) and `EVENT_PAYLOAD_TYPES: dict[str, type]`;
`util.error_messages`: `get_error_message(code) -> str`, `get_recovery_actions(code) -> tuple[str, ...]`.

Event payloads are TypedDicts (plain dicts at runtime) whose REQUIRED keys are exactly:

| Event | Required keys and JSON types |
|---|---|
| `run:state` | `name` str, `run_id` str, `version` int, `status` str (a RunStatus value) |
| `run:recovery` | `name`, `run_id`, `version`, `status`, `actions` list[str] (RecoveryAction values) |
| `models:status` | `name`, `models` list of {`model_id` str, `role` str ("stt" or "cleanup"), `ready` bool, `error_code` str or null} |
| `history:changed` | `name`, `run_ids` list[str], `reason` str ("created", "updated", "deleted", "expired", "evicted") |
| `audio:level` | `name`, `run_id` str or null (null during a microphone test, which has no run), `bands` list[float] |

`audio:level` is NOT run-specific: it must not require `version` or `status`.
T-CON-003 must build a full valid sample of each payload, check `__required_keys__` equals the set
above, and check json round-trip with data-only values.
