# Wispr Clone — Dependency and Setup Decisions

Status: **planning only**. Companion to [CODEMAP.md](CODEMAP.md). No packages, models, environments, or manifests are created by these documents. All package/host choices below are **proposed**; compatibility and current distribution details are **unverified**. Model targets are **selected** in [the project notes](../research/notes_1.md).

## Environment and installation boundary

The Windows project uses Python 3.12 and `uv`, with metadata in `backend_dev/pyproject.toml`, a committed `uv.lock`, and `.python-version`. Keep project packages local. G1 is decided: one WSL checkout, with the Windows venv on the Windows disk (`UV_PROJECT_ENVIRONMENT`). The WSL venv serves development and Linux CI only.

**No model server runs in WSL (G2, decided 2026-09-24).** Speech recognition runs in-process through transcribe.cpp. Cleanup uses the user's existing LM Studio on Windows, which is an external application: it is not installed, pinned or started by this project. Record the LM Studio version and loaded model with each G2/tier G result.

**Manifest impact now:** none. At implementation, add approved Windows runtime/dev dependencies and commit their lockfile. The transcribe.cpp wheels come from GitHub release URLs (not PyPI), so pin them by URL with hashes in `uv.lock`. Optional cloud, encryption, and launcher dependencies wait for their corresponding decisions.

## Proposed Windows packages

| Package/location | Purpose and cost/tradeoff | Alternative | Consequence of removal |
|---|---|---|---|
| `pywebview` — runtime | Native web UI host and JS bridge; introduces a webview runtime/packaging requirement | PySide6/QtWebEngine; browser-hosted UI would add local HTTP hosting | Replace window and bridge integration |
| `pynput` — runtime | Global down/up events for hold/toggle controls; native hook lifecycle must be tested | Own Win32 hook adapter | Buttons remain; global hotkeys need replacement |
| `sounddevice` — runtime | PortAudio capture/device enumeration; test actual Windows audio backend and distribution | PyAudio or soundcard | Replace capture/device layer |
| `numpy` — runtime | Audio array operations, RMS and frequency bands; compiled dependency | Small stdlib implementation with measured performance | Rewrite audio analysis/conversion |
| `soxr` — runtime | Resample when the chosen mic cannot open at the STT sample rate | Another measured resampler such as `scipy.signal` | Device sample-rate compatibility narrows |
| `transcribe-cpp` 0.2.3 — runtime | In-process Voxtral Realtime streaming: `feed()` chunks, committed/tentative text, `finalize()`, `session.cancel()`. MIT. 0.x and "in development" per its README, so the API may change; `stt/base.py` confines that to one adapter. One run at a time per loaded model | vLLM server in WSL (≈8 GB bf16 weights, no longer fits beside LM Studio) | Return to the vLLM plan and its WebSocket adapter |
| `transcribe-cpp-native-cu12` 0.2.3 — runtime | CUDA 12 native provider for the above; bundles the CUDA 12.9 runtime, about 200 MB, which also grows the packaged app. Also carries Vulkan and CPU backends (measured too slow for live use) | Vulkan-only native wheel (smaller; measured on the Intel iGPU: falls behind live speech) | STT falls back to a slower backend |
| `httpx` — runtime | Async requests to LM Studio's OpenAI-compatible `/v1/chat/completions` and `/v1/models` (cleanup and health) | `openai` client package; `aiohttp` | Replace cleanup/health transport |
| `pydantic` — runtime | Settings, command and import validation | Dataclasses plus explicit validation, or another schema validator | Validation responsibility remains and needs replacement |
| `pywin32` — runtime | Desktop/process/clipboard APIs | `ctypes` wrappers | Rewrite native wrappers; keep insertion contract unchanged |
| `keyring` — optional runtime | Cloud credential storage; backend availability must be verified | Windows credential APIs via pywin32 | Local mode unaffected; replace cloud secret store |
| `pytest`, `pytest-asyncio` — dev | Deterministic unit/integration checks for asynchronous behavior | stdlib `unittest` | Replace test harness |
| `ruff` — dev | Shared formatting/lint rules | Separate formatter/linter | Replace checks or maintain manually |
| `pyright` or `mypy` — optional dev | Check shared command/event and adapter types; choose one | Runtime validation/tests alone | Less static checking |
| `pyinstaller` — dev | Proposed Windows executable packaging | Nuitka or Briefcase | Run from source or replace packager |

Baseline: ten direct Windows runtime packages (`websockets` removed; `transcribe-cpp` and its CUDA provider added), plus optional keyring. The local system has the app process and the user's LM Studio process; do not add another orchestration service without a concrete requirement. Runtime libraries add packaging and compatibility maintenance, while model operation adds local memory, disk and power costs. No paid inference service is required by the local workflow; any cloud pricing must be evaluated if that scope is selected.

Use stdlib `sqlite3`, `wave`, `asyncio`, `threading`, `queue`, `ctypes`, `logging`, `uuid`, `json`, and `re` where appropriate. Do not add an ORM, task queue, or model orchestration framework for this scope.

The simple host proposal is pywebview because the UI already exists as web assets. PySide6 is an alternative if native window/focus requirements cannot be demonstrated with pywebview. Do not assume that mixing GUI toolkits is trivial; prove lifecycle/thread compatibility before adopting a separate HUD host. These are proposals, not newly verified library comparisons.

## Selected models and serving (G2 decided 2026-09-24)

| Role | Selected target | Host/interface | Status |
|---|---|---|---|
| Local STT | Voxtral Mini 4B Realtime 2602, GGUF Q4_K_M from `handy-computer/Voxtral-Mini-4B-Realtime-2602-gguf` (2.8 GB, already in LM Studio's model folder; the app reads the file, LM Studio does not serve it) | transcribe.cpp in-process, CUDA, 16 kHz mono float32 chunks | Measured on synthetic speech (CODEMAP §7 G2 record): ~15× faster than real time warm, final text 0.04–0.24 s after audio ends, cancel 0.004 s, +2.1 GB VRAM. Real microphone still to test. Dictionary biasing support unverified |
| Local cleanup | Llama 3.1 8B Instruct, Q4_K_S GGUF, loaded in LM Studio (model id `meta-llama-3.1-8b-instruct`, 8,192-token context) | LM Studio, `127.0.0.1:1234`, OpenAI-compatible chat API | Shared with Cognee, so cleanup can wait behind Cognee requests; deadlines apply. Temperature-0 behavior, cancel on disconnect, loopback-only serving and LM Studio's own request logging are still to be checked. Low temperature is not a meaning-preservation guarantee |
| STT fallback | `mistralai/Voxtral-Mini-4B-Realtime-2602` original weights | vLLM in WSL, loopback WebSocket `/v1/realtime` | Documented only. Revisit if transcribe.cpp fails a later check; needs its own download and VRAM that does not fit beside LM Studio today |
| Optional cloud STT | MAI-Transcribe or a Mistral adapter, not yet selected for implementation | Provider API determined later | Exact product/endpoint, authentication, cost and local-only enforcement before any adapter work |

GPU budget on the RTX 5080 (16.3 GB): LM Studio (Llama + Cognee's embedding model) about 7.5 GB, Voxtral about 2.1 GB, plus other Windows processes. The G2 run peaked at 15.1 GB, leaving about 1 GB of headroom. Record free VRAM with every tier G result. If headroom disappears, options in order: smaller LM Studio context, a different quantization, then sequential loading. The Intel iGPU (Vulkan) is fast enough for re-transcribing a saved WAV (`retry_stt`) but not for live dictation.

## Planned setup scripts and packaging

| Planned file | Responsibility and exit evidence |
|---|---|
| `scripts/check_local_models.py` | Readiness report: Voxtral GGUF present at the configured path with the pinned SHA-256; LM Studio answers on `127.0.0.1:1234` with the pinned model loaded; LM Studio not reachable on the LAN IP; free VRAM. Reads no credentials and downloads nothing |
| `packaging/wispr_clone.spec` | Package Windows source/web assets; verify webview/audio/native dependencies, the transcribe.cpp CUDA provider, and a clean target launch |

Model acquisition is a documented manual step (download in LM Studio). No project script downloads models or starts LM Studio. LM Studio's "serve on local network" setting must stay off; check it rather than assume it. Do not expose it to the LAN to work around a connection problem.

Optional `models/lmstudio_launcher.py` (using LM Studio's `lms` CLI) would own startup/readiness only if app-managed startup is selected (G7). Until then, the user starts LM Studio. Choosing a launcher must not change the STT or cleanup interfaces.

## API keys, secrets, and data

| Credential | When needed | Proposed storage |
|---|---|---|
| None for local inference | Default workflow after models are acquired | No runtime API key |
| Provider-specific cloud key, such as `MISTRAL_API_KEY` | Only after a cloud adapter/provider is selected | Windows Credential Manager through the chosen secret-store adapter |

Both local models were acquired through LM Studio, so no Hugging Face token is needed. Model-specific license terms (Llama 3.1's license; Voxtral's base-model license and the GGUF conversion's terms) still need checking against the exact distributions before any release; this document is not licensing research.

No `.env.example` is needed: the app reads no environment credentials, and no project script downloads models. Ignore `.env`, `*.key`, and local environments in source control. Never expose provider credentials to JS or log them. Validate configured endpoints and block cloud adapters when local-only is enabled; never silently fail over from a local server to cloud inference.

Transcript/audio retention belongs to the codemap's history contract. Per-user storage does not mean encrypted storage. Optional encryption requires a separate decision covering key storage, recovery and deletion; do not quietly add an encryption package or permanent backup of temporary data.
