# Wispr Clone — Dependency and Setup Decisions

Status: **planning only**. Companion to [CODEMAP.md](CODEMAP.md). No packages, models, environments, or manifests are created by these documents. All package/host choices below are **proposed**; compatibility and current distribution details are **unverified**. Model targets are **selected** in [the project notes](../research/notes_1.md).

## Environment and installation boundary

The Windows project uses Python 3.12 and `uv`, with metadata in `backend_dev/pyproject.toml`, a committed `uv.lock`, and `.python-version`. Keep project packages local. G1 is decided: one WSL checkout, with the Windows venv on the Windows disk (`UV_PROJECT_ENVIRONMENT`). The WSL venv serves development and Linux CI only.

**No model server runs in WSL.** STT uses cloud Whisper through OpenRouter/DeepInfra; audio leaves the device and usage pricing applies. Cleanup uses the user's existing LM Studio on Windows, which is an external application: it is not installed, pinned or started by this project.

**Manifest impact (2026-09-27):** removed `transcribe-cpp` and `transcribe-cpp-native-cu12`; cloud Whisper uses the existing `httpx` dependency. The local Voxtral path was removed because cloud Whisper is the selected STT. Optional encryption and launcher dependencies wait for their corresponding decisions.

## Proposed Windows packages

| Package/location | Purpose and cost/tradeoff | Alternative | Consequence of removal |
|---|---|---|---|
| `pywebview` — runtime | Native web UI host and JS bridge; introduces a webview runtime/packaging requirement | PySide6/QtWebEngine; browser-hosted UI would add local HTTP hosting | Replace window and bridge integration |
| `pynput` — runtime | Global down/up events for hold/toggle controls; native hook lifecycle must be tested | Own Win32 hook adapter | Buttons remain; global hotkeys need replacement |
| `sounddevice` — runtime | PortAudio capture/device enumeration; test actual Windows audio backend and distribution | PyAudio or soundcard | Replace capture/device layer |
| `numpy` — runtime | Audio array operations, RMS and frequency bands; compiled dependency | Small stdlib implementation with measured performance | Rewrite audio analysis/conversion |
| `soxr` — runtime | Resample when the chosen mic cannot open at the STT sample rate | Another measured resampler such as `scipy.signal` | Device sample-rate compatibility narrows |
| `httpx` — runtime | Async requests to LM Studio's OpenAI-compatible `/v1/chat/completions` and `/v1/models` (cleanup and health) | `openai` client package; `aiohttp` | Replace cleanup/health transport |
| UI Automation client — runtime, **`uiautomation` 2.0.29 (Apache-2.0; pulls in `comtypes`), chosen by the user 2026-09-25**; Windows only; added to the lock by `feat/insertion-win`. It cannot share a process thread with pywebview's COM setup, so it runs on the insertion worker thread | Hybrid delivery needs the browser tab and focused text field identity, tab reselection and focus restore. Win32 alone sees only windows | pywinauto (heavier); or window-level delivery only, losing tab/field precision | Hybrid delivery drops to the return trigger only |
| `pydantic` — runtime | Settings, command and import validation | Dataclasses plus explicit validation, or another schema validator | Validation responsibility remains and needs replacement |
| `pystray` 0.19.5 — runtime, **chosen by the user 2026-09-27**; Windows only (LGPL-3.0; pulls in `Pillow` 12.3.0 and `six`) | Tray icon so the app keeps running with its window hidden: closing the window hides it, launch at login starts in the tray, and the global hotkey keeps working. The icon image is drawn with Pillow at startup, so no image asset is bundled | Own `Shell_NotifyIcon` ctypes adapter (more Win32 code, no dependency) | Closing the window quits the app again; launch at login would open a visible window |
| `pywin32` — runtime | Desktop/process/clipboard APIs | `ctypes` wrappers | Rewrite native wrappers; keep insertion contract unchanged |
| `keyring` — optional runtime | Cloud credential storage; backend availability must be verified | Windows credential APIs via pywin32 | Local mode unaffected; replace cloud secret store |
| `pytest`, `pytest-asyncio` — dev | Deterministic unit/integration checks for asynchronous behavior | stdlib `unittest` | Replace test harness |
| `ruff` — dev | Shared formatting/lint rules | Separate formatter/linter | Replace checks or maintain manually |
| `pyright` or `mypy` — optional dev | Check shared command/event and adapter types; choose one | Runtime validation/tests alone | Less static checking |
| ~~`pyinstaller` — dev~~ **removed 2026-09-27** | Built `WisprClone.exe`. Windows Smart App Control blocked each new unsigned build, so the app is now installed as a wheel into a venv made by the signed python.org Python (`packaging/install_windows.py`) | Code signing (paid certificate) | — |

Removed 2026-09-27: `transcribe-cpp` and `transcribe-cpp-native-cu12`. The local Voxtral path was retired because cloud Whisper is the selected STT.

Baseline: no runtime dependency changes for cloud STT; httpx is already locked. OpenRouter / DeepInfra is an external service with usage pricing, and audio leaves the device. The local system also uses the user's LM Studio process for cleanup.

Use stdlib `sqlite3`, `wave`, `asyncio`, `threading`, `queue`, `ctypes`, `logging`, `uuid`, `json`, and `re` where appropriate. Do not add an ORM, task queue, or model orchestration framework for this scope.

The simple host proposal is pywebview because the UI already exists as web assets. PySide6 is an alternative if native window/focus requirements cannot be demonstrated with pywebview. Do not assume that mixing GUI toolkits is trivial; prove lifecycle/thread compatibility before adopting a separate HUD host. These are proposals, not newly verified library comparisons.

## Selected models and serving (G2 updated 2026-09-27)

| Role | Selected target | Host/interface | Status |
|---|---|---|---|
| Cloud STT | User-selectable OpenRouter transcription model (listed from `/models?output_modalities=transcription`); default Whisper Large v3 Turbo pinned to DeepInfra with fallback disabled, other models routed with `data_collection: "deny"` | OpenRouter audio transcription endpoint; no new package (`httpx` is already present) | Audio leaves the device; usage pricing applies; the real provider pin requires the manual probe |
| Local cleanup | Llama 3.1 8B Instruct, Q4_K_S GGUF, loaded in LM Studio (model id `meta-llama-3.1-8b-instruct`, 8,192-token context) | LM Studio, `127.0.0.1:1234`, OpenAI-compatible chat API | Shared with Cognee, so cleanup can wait behind Cognee requests; deadlines apply. Checked 2026-09-24: temperature 0 deterministic, disconnect stops generation, loopback only, and request text no longer logged ("Redact Content" on). Low temperature is not a meaning-preservation guarantee |


## Planned setup scripts and packaging

| Planned file | Responsibility and exit evidence |
|---|---|
| Cloud STT readiness | The app checks key presence locally; `tests/probes/openrouter` verifies the remote transcription and provider pin only when explicitly enabled |
| `packaging/install_windows.py` | Install/update the app for the current user: wheel (with `web/`) into `%LOCALAPPDATA%\wispr_clone\app`, a venv from the signed python.org Python, locked dependencies, `--self-test`, Start menu shortcut, launch-at-login migration |

Model acquisition is a documented manual step (download in LM Studio). No project script downloads models or starts LM Studio. LM Studio's "serve on local network" setting must stay off; check it rather than assume it. Do not expose it to the LAN to work around a connection problem.

Optional `models/lmstudio_launcher.py` (using LM Studio's `lms` CLI) would own startup/readiness only if app-managed startup is selected (G7). Until then, the user starts LM Studio. Choosing a launcher must not change the STT or cleanup interfaces.

## API keys, secrets, and data

OpenRouter credentials are encrypted with Windows DPAPI user scope. The UI receives only whether a key is configured. Audio is sent to OpenRouter for DeepInfra transcription; retry audio and transcripts stay local.

| Credential | When needed | Proposed storage |
|---|---|---|
| OpenRouter key | Cloud STT | Windows DPAPI user-scope encrypted file; UI only receives configured status |


The cleanup model is served by LM Studio. No cloud package was added; OpenRouter is an external service and usage charges apply.

The app stores the OpenRouter key with Windows DPAPI and never returns or logs it. Audio is sent to OpenRouter / DeepInfra. Local-only settings reject cloud model selection; there is no fallback provider.

Transcript/audio retention belongs to the codemap's history contract. Per-user storage does not mean encrypted storage. Optional encryption requires a separate decision covering key storage, recovery and deletion; do not quietly add an encryption package or permanent backup of temporary data.
