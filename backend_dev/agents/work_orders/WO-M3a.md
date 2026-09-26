# WO-M3a — Run controller: happy path

```text
Work-order ID: WO-M3a
Role file / requested model: RED + verify: sol-integration-test-author.md / gpt-6-sol
                             GREEN: luna-integration-programmer.md / gpt-6-luna
Pipeline branch or P0/M stage: M3a, branch integ/m3a-run-controller
Outcome and observable acceptance:
  pipeline/run_controller.py coordinates one run with injected services:
    hotkey -> destination capture -> audio capture + STT + WAV -> stop -> final transcript ->
    dictionary -> insertion protocol -> done.
  - original_text and adjusted_text are stored separately.
  - run:state events go in order: recording -> processing -> done.
  - The controller owns every run-status change through the M1 state machine. The M2 protocol
    never changes status.
  M3b-f extend this same file (cancellation, cleanup, awaiting/held/recovery, eviction,
  retry_stt), so the skeleton below is pinned for them too.
Base revision / worktree / branch: 94f879c / ~/projects/wc-m3 / integ/m3a-run-controller
Relevant sections: CODEMAP.md §3 (callbacks never re-entrant), §4 steps 1-3, 6-7, §5;
  dev_pipeline.md §8 row M3a.
Exact writable paths (under backend_dev/):
  Sol:  tests/unit/pipeline/test_run_controller*.py (new),
        tests/integration/pipeline/test_run_happy_path.py (new),
        tests/fakes/audio.py (new: FakeCapture), tests/fakes/stt.py (new: FakeSttEngine/Session;
          must follow the stt/base.py Protocols exactly, including array typecode "f")
  Luna: src/wispr_clone/pipeline/run_controller.py (new)
Read-only: everything else.
Allowed imports: pipeline -> contracts, config, util, audio, stt, dictionary, history, insertion
  (+ stdlib, numpy). pipeline.run_controller may import pipeline.state_machine and
  pipeline.insertion_protocol.
Required tiers: S, U, I on ubuntu and windows.
Check commands (from backend_dev/, UV_LINK_MODE=copy):
  uv sync --locked; uv run ruff check --no-cache .; uv run ruff format --check .;
  uv run mypy src scripts tests/_attribution tests/fakes; uv run python scripts/check_imports.py;
  uv run pytest -q -W error
Authorization: edit only writable paths; no git writes; no PRs; the coordinator commits.
Privacy: never log transcript text, titles or field contents.
```

## Pinned API

```text
class CaptureLike(Protocol):          # satisfied by audio.capture.AudioCapture
    def start(self) -> None: ...
    def chunks(self) -> AsyncIterator[CaptureChunk]: ...
    def stop(self) -> None: ...
    def cancel(self) -> None: ...

class WavLike(Protocol):              # satisfied by audio.wav_writer.WavWriter
    def write(self, samples: Any) -> None: ...
    def close(self) -> None: ...
    @property
    def frames_written(self) -> int: ...

@dataclass(frozen=True, slots=True)
class RunServices:
    history: HistoryRepo
    dictionary: DictionaryRepo
    stt: SttEngine
    insertion: InsertionProtocol
    events: EventSink
    capture_destination: Callable[[], Awaitable[DestinationSnapshot]]
        # the app offloads insertion.destination.capture(...) with its own pid excluded;
        # it raises WisprError(DESTINATION_UNVERIFIABLE) when there is no usable window
    new_capture: Callable[[], CaptureLike]       # a fresh capture per run
    new_wav: Callable[[Path], WavLike]
    new_id: Callable[[], str]                    # run ids and insertion request ids
    audio_dir: Path
    config_snapshot: Callable[[], Mapping[str, object]]   # stored on the run at start (M3d/M3e)

class RunController:
    def __init__(self, services: RunServices) -> None: ...
    @property
    def active_run_id(self) -> str | None: ...        # the run holding the recording slot
    async def start(self, *, start_request_id: str) -> str: ...   # returns run_id once recording
    async def stop(self, run_id: str) -> None: ...     # requests stop; returns without waiting
                                                       # for processing
    async def settled(self, run_id: str) -> RunRecord: ...   # awaits that run's background task
                                                              # and returns the final record

def events_for(result: ProtocolResult) -> tuple[RunEvent, ...]: ...   # pure mapping, below
```

## Sequence (binding)

1. **`start`:**
   1. `snapshot = await capture_destination()`. If it raises `WisprError(DESTINATION_UNVERIFIABLE)`,
      keep `snapshot = None` and continue; step 6 then holds the run.
   2. `run_id = new_id()`.
   3. `history.create_run(run_id=..., start_request_id=..., config=config_snapshot(),
      destination=snapshot.to_json() or None, audio_path=str(audio_dir / f"{run_id}.wav"))`.
      The run starts `recording`, version 1.
   4. Publish `{"name": "run:state", "run_id", "version": 1, "status": "recording"}`.
   5. `capture = new_capture(); capture.start()`, then `session = stt.start_session()`, then
      `wav = new_wav(path)`.
   6. Spawn one background task per run, which pumps the chunks. For each chunk it calls
      `session.push_audio(array("f", chunk.samples))` and `wav.write(chunk.samples)`, and
      publishes `{"name": "audio:level", "run_id", "bands": chunk.bands}`.
   7. Return `run_id`.
2. **`stop`:** `capture.stop()` (queued blocks drain). The background task continues:
   1. After the pump ends, `wav.close()`.
   2. Transition STOP → processing, persist, publish.
   3. `text = await session.finish()`.
   4. `adjusted = apply_dictionary(text, await dictionary.entries())`.
   5. Persist in one `update_run`: `original_text=text`, `adjusted_text=adjusted`,
      `output_selection="adjusted"`, `cleanup_status=OFF`,
      `audio_duration=wav.frames_written / 16000`.
   6. The recording slot is released as soon as capture has stopped. Processing continues
      without holding it.
3. **Every status change** goes through `state_machine.transition` on
   `RunState(record.status, record.version)`. Persist it with
   `history.update_run(run_id, expected_version=record.version, status=new.status)`, then
   publish `run:state` with the **record's** new version. The DB version is authoritative.
4. **Insertion** (M3a happy path):
   - `snapshot is None` → HOLD.
   - Otherwise `result = await insertion.attempt(run_id, adjusted, snapshot, request_id=new_id(),
     kind="automatic", is_cancelled=<controller flag for this run; always False in M3a>)`.
   - Apply `events_for(result)` in order.
5. **`events_for` mapping (pinned; M3b-d rely on it):**

   | ProtocolOutcome | Events |
   |---|---|
   | INSERTED | DISPATCH_BEGIN_AUTO, INSERTED |
   | UNCERTAIN | DISPATCH_BEGIN_AUTO, INSERT_UNCERTAIN |
   | FAILED | DISPATCH_BEGIN_AUTO, INSERT_FAILED |
   | AWAITING | DESTINATION_AWAY |
   | HELD | HOLD |
   | CANCELLED | CANCEL |
   | ABANDONED | () (the run is gone; publish nothing more) |
   | DUPLICATE | () (another path owns that attempt) |

   - FAILED is always "nothing was sent", so it becomes run `error` with retry allowed
     (CODEMAP §4 step 7).
   - DISPATCH_BEGIN_AUTO + INSERT_FAILED from `processing` reaches `error`, which is legal in M1.
6. **Settling:** exceptions from STT or storage in M3a propagate out of `settled`. M3b adds the
   failure branches. `active_run_id` is None after stop.
7. **Only one recording at a time:** a second `start` while `active_run_id` is set raises
   `WisprError(DEVICE_LEASE_CONFLICT, "run", "busy")`. M3b tests this further.

## Tests (Sol; IDs in function names)

- Real `HistoryRepo` and `DictionaryRepo` on a temporary SQLite file with migrations.
- Real `InsertionProtocol` with the `tests/fakes/insertion.py` fakes and an inline offload.
- `FakeCapture` yields scripted `CaptureChunk`s and records start/stop/cancel.
  `chunks()` ends after `stop()` once the queued chunks are drained.
- `FakeSttEngine`/`FakeSttSession` record pushed arrays (typecode "f") and return scripted
  final text.
- `FakeEventSink` from tests/fakes.

| ID | Assertion |
|---|---|
| T-RUN-001 (int) | Wiring: `HotkeyService` (hold mode) with `post` = loop.call_soon_threadsafe, and on_start/on_stop scheduling `controller.start`/`stop`. DOWN → recording, chunks pumped to STT and WAV, UP → processing → done. The adjusted text is inserted exactly once. `original_text` holds the raw STT text and `adjusted_text` the dictionary-applied text, and they differ (a dictionary alias is used). run:state statuses go exactly recording, processing, done, with strictly increasing versions. audio:level events are published only while recording. |
| T-RUN-001b | The final record has `output_selection == "adjusted"`, `cleanup_status == "off"`, and `audio_duration == frames / 16000`. The WAV writer is closed before processing starts. |
| T-RUN-001c | `events_for` gives the exact table for every ProtocolOutcome (built from this WO, not imported from the implementation). |
| T-RUN-001d | Destination capture raises DESTINATION_UNVERIFIABLE → the run ends `held`, with 0 dispatches. |
| T-RUN-001e | `start` while another run is recording → DEVICE_LEASE_CONFLICT; the first run is unaffected. |
| T-RUN-001f | Privacy: transcript text never appears in caplog output. |

## Coordinator decisions after RED review

1. `dispatching` is never persisted. The protocol result arrives after dispatch has already
   happened, so the controller applies each `events_for(result)` sequence **in memory**:
   - start from `RunState(record.status, record.version)`;
   - apply every event with `transition` (e.g. DISPATCH_BEGIN_AUTO then INSERTED);
   - persist only the final status with ONE `update_run(expected_version=record.version)`;
   - publish ONE run:state with the final status and the record's new version.
   The durable record of "an insertion is in progress" is the `in_flight` attempt row (M2), not
   the run.
