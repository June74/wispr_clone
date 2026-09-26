# WO-M3f — Run controller: retry STT from the retained WAV

```text
Work-order ID: WO-M3f
Role file / requested model: RED + verify: sol-integration-test-author.md / gpt-6-sol
                             GREEN: luna-integration-programmer.md / gpt-6-luna
Pipeline branch or P0/M stage: M3f, branch integ/m3f-retry-stt
Outcome and observable acceptance:
  - A run in `error` whose STT never produced text and whose WAV is retained offers
    `retry_stt`. It replays the WAV through `stt.transcribe_file`, then continues the normal
    path: dictionary, cleanup (by the run's config), insertion.
  - The run's age is never reset.
  - Without audio, `retry_stt` is neither offered nor accepted.
Base revision / worktree / branch: 37480f1 / ~/projects/wc-m3f / integ/m3f-retry-stt
Relevant sections: CODEMAP.md §4 recovery table ("Microphone/STT failure → retry STT"); WO-M3a..e
  (all decisions); dev_pipeline.md §8 row M3f.
Exact writable paths (under backend_dev/):
  Sol:  tests/unit/pipeline/test_run_controller_retry_stt*.py (new),
        tests/unit/pipeline/test_run_controller_cancel.py (T-RUN-007 only, rule 5),
        tests/fakes/stt.py (transcribe_file behavior only, matching the real class)
  Luna: src/wispr_clone/pipeline/run_controller.py
Read-only: everything else.
Check commands (from backend_dev/, UV_LINK_MODE=copy):
  uv sync --locked; uv run ruff check --no-cache .; uv run ruff format --check .;
  uv run mypy src scripts tests/_attribution tests/fakes; uv run python scripts/check_imports.py;
  uv run pytest -q -W error
Authorization: edit only writable paths; no git writes; no PRs; the coordinator commits.
```

## Rules (binding)

1. **Offered only when useful.** `retry_stt` is in a run's effective actions only when all of
   these hold:
   - the state machine allows it (status `error`);
   - `record.original_text is None` (history makes `original_text` immutable, so a run that
     already has a transcript cannot be re-transcribed);
   - `record.audio_path` is set, the file exists, and it holds at least 1 frame.
   Every run:recovery `actions` list uses these effective actions, not the raw
   `allowed_recovery_actions`.
2. **`recover(RETRY_STT)`:**
   - history.get → version check → effective-action check. A missing WAV or existing text gives
     WisprError(VALIDATION, "run", "no audio").
   - Then transition RETRY_STT → `processing`, persisting it and clearing `error_code` in the
     same write, and start a background recovery task, like M3c `recover`.
3. **Slot:** the retry holds the recording slot while transcribing, because the real engine
   allows one STT session and `transcribe_file` opens one.
   - `start` during a retry transcription → DEVICE_LEASE_CONFLICT "busy".
   - `recover(RETRY_STT)` while recording → DEVICE_LEASE_CONFLICT "busy".
   - The slot is freed as soon as `transcribe_file` returns or raises.
4. **Retry task:**
   1. `text = await stt.transcribe_file(Path(record.audio_path))`.
   2. Then continue exactly like the normal post-`finish` path: no-speech check (rule 5), the
      dictionary with entries **re-read now** (an explicit action, as in M3c decision 1),
      cleanup by the run's stored config, then insertion (`kind="automatic"`; the run never had
      an automatic attempt, because STT failed before it).
   - Cancel and abort flags are checked after every await, as in M3b/M3e.
   - An STT failure → `error` again with the new error code, and the WAV is kept, so the retry
     stays offered.
   - `created_at` is never touched, so expiry still counts from the original start.
5. **No speech (amends M3b rule 8):** an empty or whitespace transcript does NOT persist
   `original_text=""`. It stays None, so a false "no speech" can be retried from the WAV.
   Otherwise unchanged: FAIL with `no_speech_detected`, 0 dispatch.
   - Sol updates T-RUN-007 to expect `original_text is None`.

## Tests (Sol; IDs in function names)

| ID | Assertion |
|---|---|
| T-RUN-040 | STT `finish` raises (after audio was captured) → `error` with the code, and run:recovery actions include "retry_stt". `recover(RETRY_STT)` → `transcribe_file` is called with the run's WAV path → the transcript is stored → inserted once → `done`. `created_at` is unchanged; advancing the clock past `created_at` + 24 h expires the run on schedule |
| T-RUN-040b | Retry where `transcribe_file` fails again → `error` with the new code; retry is still offered; a second retry succeeds |
| T-RUN-040c | A no-speech run (M3b T-RUN-007) → `original_text` None; retry is offered; a retry with real text succeeds |
| T-RUN-040d | `start` during a retry transcription (the fake blocks `transcribe_file`) → DEVICE_LEASE_CONFLICT; after it returns, a start succeeds. `recover(RETRY_STT)` while recording → DEVICE_LEASE_CONFLICT |
| T-RUN-040e | Cancel during a retry transcription → `cancelled`, 0 dispatch; the slot is freed |
| T-RUN-041 | No WAV (the file was deleted, or zero frames) → retry_stt absent from the run:recovery actions; `recover(RETRY_STT)` → VALIDATION "no audio" |
| T-RUN-041b | An `error` from an insertion failure (`original_text` set) → retry_stt not offered, and rejected |
| T-RUN-041c | Stale version → STALE_VERSION; expired run → RUN_EXPIRED |

## Coordinator decisions after RED review

1. The real `transcribe_file` keeps its STT session internal, so it cannot be interrupted.
   - Cancel (or abort) during a retry transcription sets the flag immediately.
   - When `transcribe_file` returns or raises, its result is discarded and the run ends
     `cancelled` (abort: quietly, as in M3e), with 0 dispatch.
   - The recording slot stays held until `transcribe_file` returns, because the engine really
     is busy, and is freed then.
   - T-RUN-040e asserts the slot is free after the transcription returns, not before.
