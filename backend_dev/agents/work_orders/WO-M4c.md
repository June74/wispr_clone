# WO-M4c — Application layer: dictionary, history and microphone commands

```text
Work-order ID: WO-M4c
Role file / requested model: RED + verify: sol-integration-test-author.md / gpt-6-sol
                             GREEN: luna-integration-programmer.md / gpt-6-luna
Pipeline branch or P0/M stage: M4 part c (last), branch integ/m4c-commands
Outcome and observable acceptance:
  The remaining command groups from CODEMAP §6 are routed through `Api`:
  - `dict_list/add/update/delete/import/export`;
  - `history_list/get/delete/delete_all/copy`;
  - `mic_list`, `mic_test_start`, `mic_test_stop`.
  Manual history deletes stop an in-progress run and invalidate its start request (WO-M3e
  decision 1, binding).
Base revision / worktree / branch: e04ca62 / ~/projects/wc-m4c / integ/m4c-commands
Relevant sections: CODEMAP.md §3, §6 (command table, clipboard privacy); WO-M4a (Api,
  CommandSpec, RunCommands.invalidate); WO-M3e decision 1; WO-M3d (copy_text).
Exact writable paths (under backend_dev/):
  Sol:  tests/unit/application/test_dict_history_mic*.py (new)
  Luna: src/wispr_clone/application/commands/dictionary_commands.py,
        history_commands.py, audio_commands.py (all new)
Read-only: everything else.
Check commands (from backend_dev/, UV_LINK_MODE=copy):
  uv sync --locked; uv run ruff check --no-cache .; uv run ruff format --check .;
  uv run mypy src scripts tests/_attribution tests/fakes; uv run python scripts/check_imports.py;
  uv run pytest -q -W error
Authorization: edit only writable paths; no git writes; no PRs; the coordinator commits.
Privacy: dictation text may appear ONLY in history_get / history_list results (the app's own UI
  shows history). Never in logs, events, or any other result. history_copy returns no text.
```

## Pinned API

```text
# commands/dictionary_commands.py
class DictionaryCommands:
    def __init__(self, repo: DictionaryRepo) -> None: ...
    def specs(self) -> dict[str, CommandSpec]: ...
        # dict_list (mutating=False), dict_export (False), dict_add/update/delete/import (True)

# commands/history_commands.py
class HistoryCommands:
    def __init__(self, history: HistoryRepo, controller: RunController, runs: RunCommands, *,
                 copy_to_clipboard: Callable[[str], Awaitable[None]]) -> None: ...
    def specs(self) -> dict[str, CommandSpec]: ...
        # history_list (False), history_get (False), history_delete/delete_all/copy (True)

# commands/audio_commands.py
class AudioCommands:
    def __init__(self, *, list_devices: Callable[[], tuple[InputDevice, ...]],
                 new_test_capture: Callable[[int | None], CaptureLike],   # owner "mic_test"
                 events: EventSink,
                 max_test_s: float = 30.0) -> None: ...
    def specs(self) -> dict[str, CommandSpec]: ...
        # mic_list (False), mic_test_start/stop (True)
```

## Rules (binding)

1. **Dictionary.** Entries are JSON dicts `{"id", "spelling", "aliases": [...], "note"}`.
   - `dict_add` takes `entry: {spelling, aliases?, note?}`. `dict_update` takes
     `id: int, entry`. `dict_delete` takes `id: int`.
   - `dict_import` takes `text: str` and returns `{"added": n, "skipped_duplicates": [indexes]}`.
   - `dict_export` returns `{"text": ...}`.
   - Malformed input → VALIDATION: wrong types, a bool used as an int, or unknown keys in
     `entry`. Repo errors keep their codes.
2. **history_list** returns `{"runs": [item...]}`, newest first. Each item is
   `controller.run_snapshot(r)` plus `"text"`: the selected output
   (cleaned/adjusted/original per `output_selection`, else `original_text`, else None).
   - `history_get` takes `run_id` and returns one such item, plus `"original_text"`,
     `"adjusted_text"` and `"cleaned_text"`. Expiry is enforced through `history.get`
     (RUN_EXPIRED/RUN_NOT_FOUND).
3. **history_delete** takes `run_id`. In this order:
   1. `controller.abort(run_id)`: stop the pipeline first, so no task writes after deletion.
   2. `runs.invalidate(run_id)`.
   3. `history.delete_run(run_id)`.
   It returns `{"run_ids": [...], "audio_pending": bool}` from the DeleteResult.
   - **history_delete_all** snapshots the ids with `list_runs()`, then does abort + invalidate
     for each, then `delete_all()`, and returns the same shape.
4. **history_copy** takes `run_id`: `text = await controller.copy_text(run_id)`, then
   `await copy_to_clipboard(text)`, then `{"run_id": run_id}`. No text is returned.
5. **mic_list** returns `{"devices": [{"device_id", "name", "is_default"}...]}`.
6. **mic_test_start** takes `device_id: int | None`. Only one mic test at a time; a second
   start → DEVICE_LEASE_CONFLICT.
   - `capture = new_test_capture(device_id)`, then `capture.start()`. A held lease raises
     DEVICE_LEASE_CONFLICT from the lease, for example while recording.
   - A background task pumps chunks and publishes `{"name": "audio:level", "run_id": None,
     "bands": ...}`. Audio is never written to disk, sent to STT, or kept.
   - It stops automatically after `max_test_s`.
   - `mic_test_stop` stops the capture and waits for the pump. With no test running, it is a
     no-op. It returns `{"stopped": bool}`.
   - Pump errors end the test quietly, release the lease, and publish nothing further.
7. Handlers log codes only.

## Tests (Sol; IDs in function names)

- Use a real Database with migrations, DictionaryRepo, HistoryRepo, and RunController with the
  M3 fakes.
- Use a FakeCapture for mic tests, driven with the real DeviceLease so conflicts are real
  (extend the fake only inside the test file if needed).

| ID | Assertion |
|---|---|
| T-APP-020 | dict add/list/update/delete round trip through Api; a duplicate spelling → the repo's code; malformed entry (extra key, bool id) → validation |
| T-APP-021 | dict_import returns added and skipped indexes; dict_export text re-imports to the same entries |
| T-APP-022 | history_list returns newest-first items with text; history_get includes the three text fields; expired run → run_expired |
| T-APP-023 | history_delete during an active recording: capture cancelled, lease free, run gone; its start request replay → run_deleted; no later events for that run |
| T-APP-024 | history_delete_all aborts and invalidates every run, then deletes; returns the ids |
| T-APP-025 | history_copy puts the text on the fake clipboard; the result has no text; no send_inputs |
| T-APP-026 | mic_test_start publishes audio:level with run_id None; mic_test_start while recording → device_lease_conflict; a second mic_test_start → device_lease_conflict; stop → lease released; auto-stop after max_test_s (fake time) |
| T-APP-027 | Privacy: no text in caplog output or in any published event across these commands |

## Coordinator decisions after RED review

1. The mic-test auto-stop uses `asyncio.sleep(max_test_s)` / `wait_for` with no clock
   injection. Tests pass a tiny `max_test_s` and bound their waits. Accepted as is.
