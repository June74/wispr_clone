# WO-feat-stt — In-process Voxtral STT adapter (transcribe.cpp)

```text
Work-order ID: WO-feat-stt
Role file / requested model: RED + verify: sol-feature-test-author.md (T-STT, fake transcribe_cpp)
                             and sol-boundary-test-author.md (P-TCPP-001, impact fragment) / gpt-6-sol
                             GREEN: luna-adapter-programmer.md / gpt-6-luna
Pipeline branch or P0/M stage: Wave 1, branch feat/stt
Outcome and observable acceptance:
  An STT engine that loads and warms Voxtral once, runs every blocking transcribe.cpp call on ONE
  dedicated STT thread (never the asyncio loop), streams 16 kHz mono float32 chunks in order,
  returns committed text only, cancels via session.cancel() and ignores late updates, replays a
  retained WAV exactly like live input, allows one session at a time, and wraps every native
  failure as ThirdPartyError("transcribe-cpp", ...). Proven with a fake transcribe_cpp module; the
  real GPU run is tier G (T-STT-A01, Sol boundary, later on ops/local-models evidence).
Base revision / worktree / branch: 54ac9cb / ~/projects/wc-stt / feat/stt
Relevant sections: CODEMAP.md §2 (STT inference thread), §3 (stt row), §7 G2 evidence record
  (80 ms chunks, warm-up, cancel -> Aborted); DEPENDENCIES.md transcribe-cpp rows;
  dev_pipeline.md §6 Wave 1 row feat/stt, §7.2 real-model probe ownership.
Prerequisites: P0 merged. transcribe-cpp 0.2.3 is in the locked baseline (Windows only).
Exact writable paths (under backend_dev/):
  Sol:  tests/unit/stt/** (tests + the fake module, e.g. tests/unit/stt/fake_transcribe_cpp.py),
        tests/fixtures/audio/generated/stt_* (tiny generated WAVs, or generate them in tmp_path),
        tests/probes/transcribe_cpp/test_p_tcpp_001.py, tests/_attribution/impact/transcribe_cpp.toml
  Luna: src/wispr_clone/stt/__init__.py (docstring only), src/wispr_clone/stt/base.py,
        src/wispr_clone/stt/voxtral_transcribe_cpp.py
Read-only: everything else.
Allowed imports: stt -> contracts, config, util + stdlib (array, asyncio, concurrent.futures,
  threading, wave, pathlib, importlib). `transcribe_cpp` is imported LAZILY inside the adapter
  (it is a Windows-only dependency; Linux CI must import stt modules without it).
Required tiers: S, U (fake module) on ubuntu and windows; W for P-TCPP-001 (windows only, skipped
  elsewhere). No GPU, no model file, no LM Studio in this order.
Check commands (from backend_dev/, UV_LINK_MODE=copy):
  uv sync --locked; uv run ruff check .; uv run ruff format --check .;
  uv run mypy src scripts tests/_attribution tests/fakes; uv run python scripts/check_imports.py;
  uv run pytest -q -W error
Authorization: edit only writable paths; no git writes; no PRs; no model downloads; no GPU runs.
Deferrals: conformance cases for STT and a shared FakeSttEngine in tests/fakes arrive with M3a
  (the run controller is their first consumer). STT deadlines (STT_TIMEOUT) are owned by the run
  controller (M3), not this adapter.
Handoff: coordinator. Sol: RED command/output. Luna: GREEN outputs. Sol: verification findings.
```

## Real transcribe.cpp 0.2.3 API (read from the installed wheel on 2026-09-25; the fake must match)

- `transcribe_cpp.backends() -> list[BackendDevice]`; `BackendDevice` has `name` (e.g. `"CUDA0"`,
  `"Vulkan1"`, `"CPU"`), `device_type`, `description`, `memory_free`, ...
- `transcribe_cpp.Model(path, *, backend="auto", device: BackendDevice | None = None)`; context
  manager; `.close()`; `.session()` returns a `Session` (context manager).
- `Session.run(pcm) -> Result` (`Result.text`), `Session.stream(**options) -> Stream` (context
  manager), `Session.cancel()` (callable from another thread; the blocked call raises `Aborted`),
  `Session.close()`, `Session.was_aborted`.
- `Stream.feed(pcm) -> StreamUpdate`, `Stream.text() -> StreamText(full, committed, tentative)`,
  `Stream.finalize()`, `Stream.reset()`.
- `pcm` is float samples (a `Sequence[float]`, `array.array("f")`, bytes/memoryview), 16 kHz mono.
- Errors (in `transcribe_cpp` and `transcribe_cpp.errors`): base `TranscribeError(RuntimeError)`;
  `Aborted`, `ModelFileNotFound`, `ModelLoadError`, `OutOfMemory`, `BackendError`,
  `InvalidArgument`, `InputTooLong`, ...

## Pinned API (use these exact names)

`wispr_clone.stt.base` (interfaces only; pipeline M3 depends on these, not on the adapter):

```python
SAMPLE_RATE = 16_000
CHUNK_SAMPLES = 1_280                     # 80 ms, from the G2 record

TextCallback = Callable[[str, str], None] # (committed, tentative), delivered on the event loop

class SttSession(Protocol):
    def push_audio(self, samples: array.array) -> None   # typecode "f"; non-blocking
    async def finish(self) -> str                         # committed text after finalize()
    def cancel(self) -> None                              # idempotent

class SttEngine(Protocol):
    @property
    def ready(self) -> bool
    async def start(self) -> None                         # load + warm up once
    def start_session(self, on_text: TextCallback | None = None) -> SttSession
    async def transcribe_file(self, path: Path) -> str
    async def close(self) -> None
```

`wispr_clone.stt.voxtral_transcribe_cpp`:

```python
class VoxtralTranscribeCpp:               # implements SttEngine
    def __init__(self, model_path: Path, *, device_name: str = "CUDA0",
                 module: ModuleType | None = None) -> None
        # No I/O. `module` injects a transcribe_cpp-compatible module (tests pass the fake);
        # None means `importlib.import_module("transcribe_cpp")` inside start().
```

Behavior:

1. **One STT thread.** A single-worker executor owns the model, the session and the stream. Every
   `Model(...)`, `run`, `feed`, `finalize`, `text` call runs there. `push_audio` only submits (it
   never waits); chunks are fed in submission order. `cancel()` calls `session.cancel()` directly
   from the caller's thread (that is how transcribe.cpp interrupts a blocked call), then marks the
   session cancelled.
2. **start()** (T-STT-001): imports the module (if not injected), picks the device from
   `backends()` whose `name == device_name`, loads `Model(model_path, device=that)`, then warms up
   with one `session.run` on 1 s of silence, then `ready = True`. Called twice → no second load.
   Device not found → `ThirdPartyError("transcribe-cpp", "load", "device not found",
   ErrorCode.MODEL_LOAD_FAILED)`; `ImportError` → same dependency, operation `"import"`,
   `STT_UNAVAILABLE`; `ModelFileNotFound`/`ModelLoadError`/`OutOfMemory`/any `TranscribeError` or
   other exception during load/warm-up → operation `"load"`, `MODEL_LOAD_FAILED`. `detail` is the
   exception TYPE NAME only (never message text, which may contain paths).
3. **start_session** before `ready` → `WisprError(ErrorCode.STT_UNAVAILABLE, "stt", "not ready")`.
   While another session is active (not finished/cancelled) → `WisprError(STT_UNAVAILABLE, "stt",
   "session active")` (T-STT-007). It opens `model.session()` and `session.stream()` on the STT
   thread.
4. **Updates:** after each `feed`, the adapter reads `stream.text()` on the STT thread and, if
   `on_text` is given, delivers `(committed, tentative)` on the event loop with
   `loop.call_soon_threadsafe`. After `cancel()` or `finish()` no further callback is delivered,
   even for work already queued (T-STT-005).
5. **finish()** (T-STT-003): waits for queued feeds, calls `stream.finalize()`, returns
   `stream.text().committed` (never `tentative`, never `full`), closes stream and session, frees the
   slot. After `cancel()` → `WisprError(ErrorCode.STT_STREAM_CLOSED, "stt", "cancelled")`.
6. **Errors during a session:** a native exception from `feed`/`finalize` →
   `ThirdPartyError("transcribe-cpp", "feed" | "finalize", <type name>, ErrorCode.STT_UNAVAILABLE)`,
   surfaced from the next `push_audio` call or from `finish()` (whichever comes first; never
   swallowed), and the session slot is freed. `Aborted` after our own `cancel()` is not an error.
7. **push_audio** with anything other than `array.array` typecode `"f"` → `TypeError`; after
   finish/cancel → `WisprError(STT_STREAM_CLOSED, "stt", "closed")`.
8. **transcribe_file(path)** (T-STT-006): reads a 16 kHz, mono, 16-bit PCM WAV with stdlib `wave`
   (anything else → `WisprError(ErrorCode.VALIDATION, "stt", "wav format")`), converts to float
   (`s / 32768.0`), and feeds it through a normal session in `CHUNK_SAMPLES` chunks, then finish —
   the exact live path (no `session.run` shortcut). Same one-session rule.
9. **close()**: cancels an active session, closes the model on the STT thread, stops the thread;
   idempotent.
10. No logging of text or audio.

## Tests (Sol; IDs in function names; the fake module lives in tests/unit/stt/)

The fake `transcribe_cpp` module mirrors the real API above (same names, `Aborted` subclassing
`TranscribeError(RuntimeError)`), records which thread every call runs on and the order of fed
chunks, lets a test script committed/tentative text per feed, can raise on load/feed/finalize, and
can block a `run`/`feed` on a `threading.Event` so cancel can be tested without sleeps.

| ID | Must assert |
|---|---|
| T-STT-001 | `start()` loads exactly once on the named device and runs exactly one warm-up before `ready`; `start_session` before `start()` → `STT_UNAVAILABLE`; second `start()` loads nothing; device missing / import error / load error → the pinned `ThirdPartyError` fields, detail = type name |
| T-STT-002 | chunks are fed in exact order and every native call ran on one thread that is not the event-loop thread; `push_audio` returns without waiting for a blocked `feed` |
| T-STT-003 | `finish()` returns `committed` even when `tentative`/`full` differ; tentative text is only ever passed to `on_text`, never returned |
| T-STT-004 | a native error in feed/finalize surfaces as `ThirdPartyError("transcribe-cpp", op, <type>, STT_UNAVAILABLE)`; message text from the native error (a sentinel) never appears in the raised error |
| **T-STT-005** (invariant) | `cancel()` calls `session.cancel()` (unblocking a blocked feed via `Aborted`); no `on_text` call is delivered after `cancel()`, including for feeds already queued; `finish()` after cancel → `STT_STREAM_CLOSED`; `cancel()` twice is fine |
| T-STT-006 | `transcribe_file` on a generated WAV feeds the same chunks (count, order, values) as pushing that audio live in 1,280-sample chunks, and returns the same committed text; non-16 kHz / stereo / 8-bit WAV → `VALIDATION` |
| T-STT-007 | a second `start_session` (or `transcribe_file`) while one is active → `STT_UNAVAILABLE`; allowed again after finish or cancel |
| T-STT-008 | `import wispr_clone.stt.voxtral_transcribe_cpp` works without `transcribe_cpp` installed (no top-level import); `close()` is idempotent and cancels an active session |

Probe (Sol boundary), tests/probes/transcribe_cpp/test_p_tcpp_001.py, `@pytest.mark.probe("transcribe-cpp")`
and `@pytest.mark.windows`; skipped with a reason when `transcribe_cpp` is not importable:

- P-TCPP-001 `import transcribe_cpp` works; `__version__ == "0.2.3"`; `backends()` lists a device
  with `name == "CPU"`; the names the adapter relies on exist (`Model`, `Session`, `Stream`,
  `StreamText`, `Aborted`, `TranscribeError`, `ModelLoadError`, `ModelFileNotFound`,
  `OutOfMemory`) and `Aborted` subclasses `TranscribeError`. No model file needed.

Impact fragment `tests/_attribution/impact/transcribe_cpp.toml`: as in dev_pipeline.md §5.3 (dependency
`transcribe-cpp`, kind library, modules `["stt.voxtral_transcribe_cpp"]`, features live dictation /
retry_stt / model readiness, error_codes `stt_unavailable`, `model_load_failed`, `stt_stream_closed`,
action pointing at the uv.lock pin, the GGUF SHA-256 and free VRAM).

## Coordinator findings from reviewing GREEN against the real wheel (binding)

Real public attributes of transcribe-cpp 0.2.3 (read from the installed wheel, 2026-09-25):
- `Model`:   accepts, arch, backend, capabilities, close, device, session, supports, tokenize, variant (+ context manager)
- `Session`: cancel, close, limits, run, run_batch, stream, was_aborted (+ context manager)
- `Stream`:  feed, finalize, last_status, reset, revision, snapshot, state, text (+ context manager; **no `close`**)

1. **Fake drift (critical):** the adapter calls `stream.close()`; the real `Stream` has no `close`,
   so with the real library every `finish()` would raise `AttributeError` and be reported as an STT
   failure. The fake hid it because it defines `Stream.close`. Rule: the adapter manages session
   and stream lifetimes ONLY through the context-manager protocol (e.g. a `contextlib.ExitStack`
   entered on the STT thread and closed there); it never calls `stream.close()`.
2. The fake exposes no public attribute that the real class lacks. Sol adds a unit test asserting
   each fake class's public attributes are a subset of the lists above, and P-TCPP-001 asserts the
   real classes have every attribute the adapter uses (Stream: feed, finalize, text, `__enter__`,
   `__exit__`; Session: run, stream, cancel, close, `__enter__`, `__exit__`; Model: session, close).
3. `cancel()` never blocks the caller: if the native session is not open yet, it only marks the
   session cancelled (the queued open/feeds then do nothing); it waits on nothing from the loop.
