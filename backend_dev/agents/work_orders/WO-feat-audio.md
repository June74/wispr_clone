# WO-feat-audio — Microphone lease, capture, resampling, WAV writer, levels

```text
Work-order ID: WO-feat-audio
Role file / requested model: RED + verify: sol-feature-test-author.md (T-AUD, generated fixtures)
                             and sol-boundary-test-author.md (P-NUMPY, P-SOXR, P-SD, fragments) / gpt-6-sol
                             GREEN: luna-adapter-programmer.md / gpt-6-luna
Pipeline branch or P0/M stage: Wave 1, branch feat/audio
Outcome and observable acceptance:
  One exclusive microphone lease shared by capture and the mic test; a capture whose audio callback
  only copies frames into a bounded queue (overflow ends the run with an explicit error, never a
  silent drop); consumer-side resampling to 16 kHz mono float32, a WAV writer whose file is valid
  after finish, error or cancel, and FFT band levels for the waveform. Proven with a fake
  sounddevice module; real microphone behavior is tier H.
Base revision / worktree / branch: 46ec08c / ~/projects/wc-audio / feat/audio
Relevant sections: feature spec "Recording controls" (device select/test, explain unavailable/
  permission/disconnected mics); CODEMAP.md §2 (audio callback row, lease, bounded queue), §3
  (audio row), §6 (waveform takes backend band levels); DEPENDENCIES.md numpy/soxr/sounddevice;
  WO-feat-stt (SAMPLE_RATE 16000, CHUNK_SAMPLES 1280 float32 chunks); dev_pipeline.md §6 Wave 1
  row feat/audio.
Exact writable paths (under backend_dev/):
  Sol:  tests/unit/audio/**, tests/integration/audio/**, tests/fixtures/audio/generated/audio_*,
        tests/probes/numpy/**, tests/probes/soxr/**, tests/probes/sounddevice/**,
        tests/_attribution/impact/numpy.toml, soxr.toml, sounddevice.toml
  Luna: src/wispr_clone/audio/__init__.py (docstring only), audio/device_lease.py, devices.py,
        capture.py, resample.py, wav_writer.py, level_meter.py
Read-only: everything else.
Allowed imports: audio -> contracts, config, util + numpy, soxr + stdlib (queue, threading,
  asyncio, wave, dataclasses, importlib). `sounddevice` is imported LAZILY (inside functions) in
  devices.py and capture.py only: importing it needs the PortAudio system library, which hosted
  Linux CI may lack.
Required tiers: S, U, I on ubuntu and windows; P for numpy/soxr; P-SD-001 may be UNDETERMINED in
  hosted CI (no audio device) — that is expected and must be reported, never rounded to a pass.
Check commands (from backend_dev/, UV_LINK_MODE=copy):
  uv sync --locked; uv run ruff check .; uv run ruff format --check .;
  uv run mypy src scripts tests/_attribution tests/fakes; uv run python scripts/check_imports.py;
  uv run pytest -q -W error
Authorization: edit only writable paths; no git writes; no PRs; no new dependencies; tests never
  open a real microphone (the probe only queries devices).
Privacy: audio samples are never logged; device names may appear in the UI but not in logs.
Handoff: coordinator. Sol: RED command/output. Luna: GREEN outputs. Sol: verification findings.
```

## Pinned API (use these exact names)

`audio.device_lease`:

```python
LeaseOwner = Literal["capture", "mic_test"]

@dataclass(frozen=True, slots=True)
class LeaseToken:
    owner: LeaseOwner
    serial: int

class DeviceLease:                     # thread-safe (threading.Lock); one holder at a time
    def acquire(self, owner: LeaseOwner) -> LeaseToken
        # held by anyone (same or other owner) -> WisprError(ErrorCode.DEVICE_LEASE_CONFLICT,
        # "audio", "lease held")
    def release(self, token: LeaseToken) -> None   # idempotent; a stale/foreign token is ignored
    @property
    def holder(self) -> LeaseOwner | None
```

`audio.devices`:

```python
@dataclass(frozen=True, slots=True)
class InputDevice:
    device_id: int; name: str; channels: int; default_samplerate: float; is_default: bool
def list_input_devices(module: ModuleType | None = None) -> tuple[InputDevice, ...]
    # sd.query_devices() entries with max_input_channels > 0; is_default from sd.default.device[0].
    # Import/PortAudio failure -> ThirdPartyError("sounddevice", "query", <type name>,
    # ErrorCode.MICROPHONE_UNAVAILABLE).
```

`audio.resample`:

```python
TARGET_RATE = 16_000
def to_mono_16k(samples: np.ndarray, source_rate: int) -> np.ndarray
    # input float32 shape (n,) or (n, channels); channels averaged to mono; soxr.resample(...,
    # quality="HQ") when source_rate != 16000; returns contiguous float32 (n',).
```

`audio.level_meter`:

```python
BAND_COUNT = 12
def band_levels(samples: np.ndarray, sample_rate: int = 16_000) -> list[float]
    # BAND_COUNT log-spaced bands between 80 Hz and 7,600 Hz from an rfft of the (Hann-windowed)
    # chunk; each band's RMS magnitude in dBFS mapped linearly from -60 dB -> 0.0 to 0 dB -> 1.0,
    # clipped to [0, 1]. Silence -> all 0.0. Returns plain Python floats (JSON-ready).
```

`audio.wav_writer`:

```python
class WavWriter:                          # 16 kHz, mono, 16-bit PCM via stdlib wave
    def __init__(self, path: Path) -> None     # no I/O until the first write or open()
    def write(self, samples: np.ndarray) -> None   # float32 in [-1, 1], clipped, little-endian int16
    def close(self) -> None                   # idempotent; header always valid afterwards
    @property
    def frames_written(self) -> int
```

`audio.capture`:

```python
@dataclass(frozen=True, slots=True)
class CaptureChunk:
    samples: np.ndarray        # float32 mono 16 kHz, one CHUNK_SAMPLES (1,280) block except the last
    bands: list[float]         # band_levels of this chunk

class AudioCapture:
    def __init__(self, lease: DeviceLease, *, device_id: int | None = None,
                 queue_max_blocks: int = 500, block_ms: int = 80,
                 module: ModuleType | None = None,      # fake sounddevice in tests
                 owner: LeaseOwner = "capture") -> None  # "mic_test" for the settings mic test
    def start(self) -> None
    async def chunks(self) -> AsyncIterator[CaptureChunk]
    def stop(self) -> None                 # stop capture normally; remaining queued audio drains
    def cancel(self) -> None               # stop immediately; queued audio is discarded
```

Behavior:

1. `start()` acquires the lease FIRST (conflict → `DEVICE_LEASE_CONFLICT`, nothing opened), then
   opens `sd.InputStream(device=device_id, channels=1, dtype="float32", samplerate=<device default
   or 16000>, blocksize=<block_ms at that rate>, callback=...)` and starts it. Open/start failure
   → the lease is released and `ThirdPartyError("sounddevice", "open", <type name>,
   ErrorCode.MICROPHONE_UNAVAILABLE)`.
2. **The callback only enqueues** (T-AUD-007): copy `indata` (`indata.copy()`) and
   `queue.put_nowait`; no resampling, no WAV writes, no logging, no locks held while doing I/O.
   A non-empty `status` with input overflow or `queue.Full` → set the overflow flag and stop
   accepting frames (T-AUD-006).
3. `chunks()` runs on the event loop, takes blocks from the queue without blocking the loop
   (`loop.run_in_executor` or `asyncio.to_thread` around `queue.get` with a timeout), resamples
   with `to_mono_16k`, re-blocks to 1,280-sample chunks, computes `bands`, and yields
   `CaptureChunk`s. After an overflow it yields what it already has, then raises
   `WisprError(ErrorCode.AUDIO_QUEUE_OVERFLOW, "audio", "queue overflow")`. A stream callback
   `status` reporting a device error (or the stream finishing unexpectedly) raises
   `ThirdPartyError("sounddevice", "stream", <short detail>, ErrorCode.MICROPHONE_DISCONNECTED)`.
4. `stop()`: stops and closes the stream, lets `chunks()` finish after draining, releases the
   lease. `cancel()`: stops and closes the stream, discards the queue, ends `chunks()` without
   error, releases the lease. Both idempotent; the lease is released on EVERY exit path,
   including errors (T-AUD-002).
5. The WAV writer is not inside capture: the run controller (M3) writes `CaptureChunk.samples` to a
   `WavWriter`, so a cancel still leaves a valid WAV (T-AUD-005).

## Tests (Sol; IDs in function names; fake sounddevice module with a controllable InputStream whose
## test hook calls the callback from a separate thread; generated tones in tmp_path or
## tests/fixtures/audio/generated/audio_*)

| ID | Must assert |
|---|---|
| **T-AUD-001** (invariant) | capture holding the lease → `mic_test` acquire raises `DEVICE_LEASE_CONFLICT` and vice versa; a second `start()` of another capture opens no stream; release by a stale token does nothing; thread-safe under concurrent acquire attempts (exactly one wins) |
| T-AUD-002 | the lease is released after `stop()`, `cancel()`, a stream-open failure, an overflow and a device error |
| T-AUD-003 | `to_mono_16k` on 1 s of a 1 kHz sine at 48 kHz (and 44.1 kHz, stereo) → 16,000 ± 16 samples, dominant FFT bin at 1 kHz ± 20 Hz, float32 contiguous; 16 kHz mono passes through unchanged |
| T-AUD-004 | `band_levels` of a 1 kHz full-scale sine peaks in the band containing 1 kHz; silence → all zeros; a −30 dBFS tone ≈ 0.5 in its band (± 0.1); 12 plain floats in [0, 1] |
| T-AUD-005 | `WavWriter` after writes then close is a valid 16 kHz mono 16-bit WAV with `frames_written` frames and values within 1 LSB of the input; closing after only some writes (cancel mid-run), closing twice and closing without writes all leave a readable file header (or no file when never written) |
| **T-AUD-006** (invariant) | with a tiny queue and a consumer that does not read, extra callback blocks set overflow; `chunks()` then raises `AUDIO_QUEUE_OVERFLOW` after yielding the blocks it had; the number of yielded samples never exceeds the samples accepted (no silent drop in the middle) |
| **T-AUD-007** (invariant) | the callback performs no resampling, WAV writing or logging (spy on `to_mono_16k`, `WavWriter` and `caplog`) and returns within the fake's bound; it runs on the fake's audio thread, never the loop thread |
| T-AUD-008 | chunks are 1,280 samples (last may be shorter), in order, carry `bands`; `stop()` drains then ends; `cancel()` ends immediately; a device error → `MICROPHONE_DISCONNECTED`; `list_input_devices` filters inputs and marks the default; an import failure → `MICROPHONE_UNAVAILABLE` |

Probes (Sol boundary), call the libraries directly:

- P-NUMPY-001 (`probe("numpy")`): rfft of a known sine puts the peak in the expected bin; version 2.5.3.
- P-SOXR-001 (`probe("soxr")`): 48 kHz → 16 kHz keeps the length ratio (±1) and tone frequency; version 1.1.0.
- P-SD-001 (`probe("sounddevice")`): `import sounddevice` works and `query_devices()` returns a
  list; when PortAudio or any input device is missing the test is SKIPPED with the reason (so
  attribution reports UNDETERMINED); it never opens a stream.

Impact fragments: `numpy.toml` (modules `audio.resample`, `audio.level_meter`, `audio.capture` as
they actually import numpy), `soxr.toml` (`audio.resample`), `sounddevice.toml` (`audio.devices`,
`audio.capture`); error codes from the pinned ones; actions point at the uv.lock pins and, for
sounddevice, the Windows microphone privacy setting and device connection.

## Coordinator decisions after RED review

1. `band_levels` exact formula: window = Hann of the chunk length; amplitude spectrum
   `A = |rfft(x * w)| * 2 / sum(w)` (so a full-scale sine at a bin centre reads amplitude ≈ 1.0);
   band edges = `numpy.geomspace(80, 7600, BAND_COUNT + 1)`; a band's value is the PEAK `A` among
   its bins (a band with no bins takes the nearest bin); `dB = 20*log10(max(peak, 1e-12))`;
   level = `clip((dB + 60) / 60, 0, 1)`. So a full-scale tone → ≈ 1.0 in its band, a −30 dBFS tone
   → ≈ 0.5, silence → 0.0. Tests use tones on exact FFT bin centres for 1,280-sample chunks at
   16 kHz (12.5 Hz spacing), e.g. 1,000 Hz.
