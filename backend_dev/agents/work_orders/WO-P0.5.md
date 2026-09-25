# WO-P0.5 — Shared fakes and conformance harness

```text
Work-order ID: WO-P0.5
Role file / requested model: RED + verify: sol-integration-test-author.md / gpt-6-sol
                             GREEN: luna-integration-programmer.md / gpt-6-luna
Pipeline branch or P0/M stage: P0.5, branch integ/p0.5-fakes-conformance
Outcome and observable acceptance:
  Deterministic shared fakes exist for time, IDs and events; a conformance harness lets one suite
  run the same cases against a fake and (when available) the real adapter; the attribution plugin
  labels "real fails, fake passes the same case" as OURS · fake-drift (deferred from P0.4).
Relevant sections: dev_pipeline.md §2.2 (replicability rules), §5.2 (fake-drift branch), §6 row
  0.5, §7.5 (keep fakes honest); agents/COMMON.md folder rules; CODEMAP §2 (worker, STT thread).
Exact writable paths (under backend_dev/):
  Sol:  tests/meta/** (T-FAKE meta-tests), tests/conformance/** (harness + suite files)
  Luna: tests/fakes/** (fake implementations), tests/_attribution/** (fake-drift verdict only)
Fakes (Luna), stdlib only, fully typed, no sleeping, no wall clock:
  FakeClock: now() -> float seconds (starts at a given value); call_at(t, cb) / call_later(d, cb)
    return a handle with cancel(); advance(seconds) moves time forward and fires due callbacks in
    time order, FIFO for equal times, including callbacks scheduled by callbacks if they fall
    within the advanced window; never goes backwards (negative advance -> ValueError).
  FakeIdFactory: deterministic, readable IDs per prefix ("run-1", "run-2", "req-1"...).
  FakeEventSink: implements contracts.events.EventSink; records events in order; helper to filter
    by name; rejects non-JSON-data payloads (same data-only rule as T-CON-003).
Conformance harness (Sol):
  tests/conformance/harness.py with a way to declare implementations for a suite: the fake always,
  the real adapter only when its adapter module imports and its marker allows (real impls carry
  @pytest.mark.adapter("<dist>")). Each case runs once per implementation with ids
  "<suite>[fake]" / "<suite>[real]". Suite files exist, EMPTY of cases for now, for: stt, cleanup,
  inserter, audio_source (cases arrive with each adapter branch; Sol boundary adds them).
Fake-drift verdict (Luna, plugin): a failing conformance case on [real] whose same case passed on
  [fake] in this run, and whose dependency probe passed, is OURS · fake-drift, naming the fake
  (tests/fakes/...) and the case. If the probe failed -> NOT OURS as before; if no probe ran ->
  UNDETERMINED as before.
Test IDs:
  T-FAKE-001 FakeClock advances deterministically and fires scheduled callbacks in order (incl.
             equal-time FIFO, cancel, nested scheduling, no backwards time)
  T-FAKE-002 FakeEventSink records events in order and rejects non-data payloads
  T-FAKE-003 FakeIdFactory is deterministic per prefix and independent across instances
  T-FAKE-004 the harness runs a sample suite once per available impl with the documented ids, and
             skips [real] cleanly (not fails) when the real adapter is unavailable
  T-DIAG-008 real-fails/fake-passes conformance case with passing probe -> OURS · fake-drift
Check commands (from backend_dev/, UV_LINK_MODE=copy): uv sync --locked; ruff check .;
  ruff format --check .; uv run mypy src scripts tests/_attribution tests/fakes;
  uv run python scripts/check_imports.py; uv run pytest -q -W error
Authorization: edit only writable paths; no git writes; coordinator commits, pushes, opens PR.
```

## Coordinator decisions after verification

1. FakeEventSink accepts only a real event: a dict whose `name` is a key of
   `contracts.events.EVENT_PAYLOAD_TYPES`, containing every required key of that payload type,
   with data-only values. Anything else raises TypeError or ValueError.
2. Fake-drift requires the [real] case to fail in its CALL phase and its [fake] twin to pass
   completely (setup, call and teardown). Setup and teardown errors keep their own OURS · logic
   attribution with `phase:` and never trigger fake-drift.
