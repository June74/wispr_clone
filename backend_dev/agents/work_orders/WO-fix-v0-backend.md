# WO-fix-v0-backend: v0 runthrough bugs 1, 3, 5, 6 and 10 (backend)

```text
Source: coordinator runthrough 2026-09-28 (dead-code/outdated-comment pass + independent reviews).
User decision (2026-09-28): fix bugs 1–4 and 6–10, remove local-only (item 5); tests first.
Base revision: HEAD 5aee0f6 plus the coordinator's UNCOMMITTED cleanup in the same checkout.
  Preserve those changes. No git commands that change state (no add/commit/stash/checkout/reset).
Checkout / worktree: /home/injun/projects/wispr_clone (one writer at a time; the coordinator
  hands over the turn). Paths below are relative to backend_dev/.
Paired order: WO-fix-v0-web.md (web half of items 3 and 5). T-WEB-008 (messages.js mirrors
  util/error_messages.py) stays red between Luna's backend turn and Luna's web turn; expected.
Authorization: no commits, pushes, PRs, installs or downloads. Report back to the coordinator.

Roles / writable paths
  Sol (sol-integration-test-author + sol-feature-test-author; one boundary fragment):
    tests/unit/app/** (incl. _support.py), tests/unit/application/**, tests/unit/settings/**,
    tests/integration/settings/**, tests/unit/models/**, tests/unit/contracts/**, tests/diag/**,
    tests/_attribution/impact/pydantic.toml
  Luna (luna-integration-programmer + luna-core-programmer):
    src/wispr_clone/app.py, src/wispr_clone/settings/schema.py, src/wispr_clone/models/registry.py,
    src/wispr_clone/application/model_service.py, src/wispr_clone/contracts/common.py,
    src/wispr_clone/util/error_messages.py, tests/_attribution/plugin.py
Checks (from backend_dev, UV_LINK_MODE=copy):
  uv run pytest -q -p no:cacheprovider -m "not probe and not gpu and not e2e and not manual"
  uv run ruff check . && uv run ruff format --check .
  uv run mypy src scripts tests/_attribution tests/fakes
  uv run python scripts/check_imports.py
```

## Item 1 — the insertion protocol runs on the wrong clock

Evidence: `app.py` builds `InsertionProtocol(..., clock=self.factories.monotonic)`, but the
protocol compares that clock with wall-clock values: `run.created_at` (history clock) at
`insertion_protocol.py:170` (`is_expired` right before dispatch) and `w.awaiting_since`
(RunServices clock) at `:282` (the destination wait limit). With `time.monotonic` against
`time.time` both checks are always false, so a waiting run is never held after
`destination_wait_limit_seconds` and the dispatch-time expiry guard never fires.
Tests hide it: `tests/unit/app/_support.py` gives `clock` and `monotonic` the same lambda.

Rule: the protocol receives the same wall clock as history and the run controller
(`factories.clock`). No other timing changes.

| ID | Assertion (app composition, distinct clock bases, e.g. wall 1_000_000+t, monotonic 50+t) |
|---|---|
| T-APP-053a | A run left in `awaiting_destination` for longer than `destination_wait_limit_seconds` (wall time) is held on the next delivery tick with no dispatch (zero `send_inputs`/paste calls) |
| T-APP-053b | A run waiting for its destination that is at least 24 h old (wall time) at delivery time is not dispatched |

If T-APP-053b cannot fail on the current code because an earlier retention check already stops
the dispatch, say so in the RED report instead of forcing a failure; T-APP-053a is the required
RED for this item.

## Item 3 (backend half) — a saved microphone must drive the next dictation

`settings_update` already accepts `microphone_id` (string) and `new_run_capture` reads it.
Prove the wiring end to end; fix only if a test shows a gap.

| ID | Assertion |
|---|---|
| T-APP-054 | After `settings_update {"microphone_id": "2"}` the next `run_start` opens capture on device 2; `"0"` opens device 0 (not the default); clearing it (`null`) opens the default (`None`) |

(`_support.new_capture` currently discards the device argument; Sol may record it.)

## Item 5 — remove local-only mode

Every speech model is a cloud model, so `local_only=True` can never be saved (it raises
CLOUD_MODEL_FORBIDDEN) and the Privacy switch always fails. The user chose removal.

Rules:
1. `Settings` drops `local_only`. `SETTINGS_SCHEMA_VERSION` becomes 3. A new upgrade step 2→3
   removes the `local_only` key (whatever its value) and sets `schema_version` 3; the existing
   1→2 step is unchanged. `extra="forbid"` stays, so a patch containing `local_only` is rejected
   with `ErrorCode.VALIDATION`.
2. Model-selection validation keeps its role checks (registered ids must match their role;
   discovered ids must be well formed for the role) and loses the locality/local-only check.
   `ModelCatalog` no longer needs `is_local`; remove `ModelRegistry.is_local` if nothing else uses
   it. Keep `ModelInfo.local` and `is_local_role` (they choose endpoints and loopback checks).
3. `ModelService` loses `_enforce_local_only`.
4. `ErrorCode.CLOUD_MODEL_FORBIDDEN` is no longer produced: remove it from `contracts/common.py`
   and `util/error_messages.py` (the web mirror is updated in WO-fix-v0-web).
5. A stored v2 settings row (with `local_only` true or false) loads as v3 without losing any other
   preference; no settings reset, no backup.

| ID | Assertion |
|---|---|
| T-SET-023 | `parse_settings` upgrades a v2 dict with `local_only` false or true to v3 without the key, other fields unchanged; `default_settings()` has no `local_only` and schema_version 3 |
| T-SET-024 | `SettingsStore.update({"local_only": ...})` raises VALIDATION; a real stored v2 row with `local_only` loads through the store as v3 and keeps its other values |
| T-SET-025 | Cloud STT and cleanup ids that were refused under local-only now validate by role only (registered id with wrong role still VALIDATION; malformed discovered id still VALIDATION) |
| T-APP-017 (rewrite) | `models_select` / `models_test` never raise CLOUD_MODEL_FORBIDDEN; a `settings_update` carrying `local_only` returns VALIDATION |
| T-CON-002 (update) | The required-codes list no longer contains `cloud_model_forbidden`, and `ErrorCode` has no such member |

Also update or remove the existing local-only tests (T-SET-003, T-SET-021/022, T-MOD cases,
`tests/integration/settings/test_store.py` rows, `tests/unit/models/test_registry.py` `is_local`
asserts) so none still expects local-only behaviour, and drop `cloud_model_forbidden` and the
"local-only enforcement" feature from `tests/_attribution/impact/pydantic.toml`.

## Item 6 — toggle-mode hotkey gets out of step with the real run

Evidence: `HotkeyService._toggled` flips only on dictation presses. After an Esc cancel, a stop
from the settings window or HUD, or a run that ended on its own, the next press posts `on_stop`;
`app.py` drops it because nothing is recording, so the press is ignored. A run started from the
settings window cannot be stopped with the shortcut (the press posts `on_start`, which is refused).

Rule: in toggle mode each dictation-shortcut press starts a run when no run is recording and
stops the recording run otherwise, decided on the worker loop from the controller's real state
(`active_run_id` is set exactly while a run records). Fix it in `app.py`'s hotkey wiring; do not
change `HotkeyService`'s public callbacks or existing T-KEY behaviour. Hold mode is unchanged.

| ID | Assertion (app composition, `recording_mode="toggle"`, presses through the listener's service) |
|---|---|
| T-APP-055a | press → recording; Esc → cancelled; press → a new run starts recording |
| T-APP-055b | `run_start` from the settings API → recording; press → that run stops (leaves `recording`) |
| T-APP-055c | press → recording; `run_stop` from the settings API; press → a new run starts |
| T-APP-055d | hold mode keeps today's down-starts/up-stops behaviour (regression guard) |

## Item 10 — architecture failures are misfiled by the attribution plugin

Evidence: `tests/_attribution/plugin.py` checks `"/tests/arch/" in item.nodeid`, but node ids are
rootdir-relative (`tests/arch/test_x.py::...`), so the WO-P0.4 rule "tests under tests/arch/ →
OURS · architecture" never fires and such failures are reported as `logic`.

| ID | Assertion (pytester suite with the production plugin) |
|---|---|
| T-DIAG-021 | A failing test in `tests/arch/test_*.py` is reported with verdict OURS and category `architecture`; a failing test elsewhere keeps its previous category |

## Handoff

Sol: write the tests above, run them, and report RED with the exact command and the failing
assertion for each ID (collection/import errors are not RED). Then stop; Luna takes the turn.
Luna: make them pass without editing tests; run all checks listed at the top; report GREEN.
Sol (verification turn): re-run everything, review the diff, add regressions only if required.

## Coordinator review addendum (2026-09-28)

- **T-APP-055b synchronization (Sol).** `RunController.stop()` clears `active_run_id` as soon as
  capture stops; the status leaves `recording` a moment later in the capture task. Verified by the
  coordinator: with `await app._controller.settled(run_id)` before reading the record, the status
  is past `recording`. Add that wait (as T-APP-055d does); the RED reason on the old code is the
  earlier `wait_for_stopped` assertion, which stays.
- **Dead test code (Sol).** `TestCatalog.is_local` in `tests/unit/settings/test_schema.py` is no
  longer called now that `ModelCatalog` has no `is_local`; remove it.
