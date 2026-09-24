# Wispr Clone — Dependency and Setup Decisions

Status: **planning only**. Companion to [CODEMAP.md](CODEMAP.md). No packages, models, environments, or manifests are created by these documents. All package/host choices below are **proposed**; compatibility and current distribution details are **unverified**. Model targets are **selected** in [the project notes](../research/notes_1.md).

## Environment and installation boundary

The Windows application and WSL model servers have separate environments. The proposed Windows project uses Python 3.12 and `uv`, with metadata in `backend_dev/pyproject.toml`, a committed `uv.lock`, and `.python-version`. Keep project packages local. Decide whether Windows runs a Windows-side clone or uses a WSL checkout with its venv on a Windows-local path (codemap G1).

WSL has its own isolated vLLM environment and an Ollama installation. Do not use the Windows lockfile to install the WSL server stack. The planned model scripts must record the tested server/model versions and support a reproducible install; choose a compatible stable release when possible, or an exact prerelease only when measured compatibility requires it. No floating nightly is an accepted reproducibility strategy.

**Manifest impact now:** none. At implementation, add approved Windows runtime/dev dependencies and commit their lockfile; separately pin the tested WSL serving stack. Optional cloud, encryption, and launcher dependencies wait for their corresponding decisions.

## Proposed Windows packages

| Package/location | Purpose and cost/tradeoff | Alternative | Consequence of removal |
|---|---|---|---|
| `pywebview` — runtime | Native web UI host and JS bridge; introduces a webview runtime/packaging requirement | PySide6/QtWebEngine; browser-hosted UI would add local HTTP hosting | Replace window and bridge integration |
| `pynput` — runtime | Global down/up events for hold/toggle controls; native hook lifecycle must be tested | Own Win32 hook adapter | Buttons remain; global hotkeys need replacement |
| `sounddevice` — runtime | PortAudio capture/device enumeration; test actual Windows audio backend and distribution | PyAudio or soundcard | Replace capture/device layer |
| `numpy` — runtime | Audio array operations, RMS and frequency bands; compiled dependency | Small stdlib implementation with measured performance | Rewrite audio analysis/conversion |
| `soxr` — runtime | Resample when the chosen mic cannot open at the STT sample rate | Another measured resampler such as `scipy.signal` | Device sample-rate compatibility narrows |
| `websockets` — runtime | Async streaming STT transport | `aiohttp` | Replace streaming transport |
| `httpx` — runtime | Async cleanup requests and HTTP health checks | `aiohttp`, which could consolidate both transports | Replace cleanup/health transport |
| `pydantic` — runtime | Settings, command and import validation | Dataclasses plus explicit validation, or another schema validator | Validation responsibility remains and needs replacement |
| `pywin32` — runtime | Desktop/process/clipboard APIs | `ctypes` wrappers | Rewrite native wrappers; keep insertion contract unchanged |
| `keyring` — optional runtime | Cloud credential storage; backend availability must be verified | Windows credential APIs via pywin32 | Local mode unaffected; replace cloud secret store |
| `pytest`, `pytest-asyncio` — dev | Deterministic unit/integration checks for asynchronous behavior | stdlib `unittest` | Replace test harness |
| `ruff` — dev | Shared formatting/lint rules | Separate formatter/linter | Replace checks or maintain manually |
| `pyright` or `mypy` — optional dev | Check shared command/event and adapter types; choose one | Runtime validation/tests alone | Less static checking |
| `pyinstaller` — dev | Proposed Windows executable packaging | Nuitka or Briefcase | Run from source or replace packager |

Baseline proposal: nine direct Windows runtime packages, plus optional keyring. The local system has the app process and two model-serving processes; do not add another orchestration service without a concrete requirement. Runtime libraries add packaging and compatibility maintenance, while model operation adds local memory, disk and power costs. No paid inference service is required by the local workflow; any cloud pricing must be evaluated if that scope is selected.

Use stdlib `sqlite3`, `wave`, `asyncio`, `threading`, `queue`, `ctypes`, `logging`, `uuid`, `json`, and `re` where appropriate. Do not add an ORM, task queue, or model orchestration framework for this scope.

The simple host proposal is pywebview because the UI already exists as web assets. PySide6 is an alternative if native window/focus requirements cannot be demonstrated with pywebview. Do not assume that mixing GUI toolkits is trivial; prove lifecycle/thread compatibility before adopting a separate HUD host. These are proposals, not newly verified library comparisons.

## Selected models and proposed serving

| Role | Selected target | Proposed host/interface | Verification needed |
|---|---|---|---|
| Local STT | `mistralai/Voxtral-Mini-4B-Realtime-2602` | vLLM, loopback port 8000, `/v1/realtime` WebSocket | Supported vLLM/tokenizer versions, protocol/finalization, sample rate, encoding, chunks, latency, dictionary biasing, GPU support and VRAM |
| Local cleanup | Llama 3.1 8B Instruct | Ollama, loopback port 11434, native chat API | Available tag/quantization, context and memory needs, output behavior and cancellation; low temperature is not a meaning-preservation guarantee |
| Optional cloud STT | MAI-Transcribe or a Mistral adapter, not yet selected for implementation | Provider API determined later | Exact product/endpoint, authentication, cost and local-only enforcement before any adapter work |

The earlier draft proposed 16 kHz PCM16 and approximately 80 ms chunks for STT, a quantized Llama model, and a vLLM prerelease. Treat these as experiment inputs, not established protocol or version requirements. Verify current primary documentation and the actual endpoint before encoding them as constants.

The target-machine plan refers to an RTX 5080. Record actual GPU capacity/available memory, Windows driver, WSL configuration, CUDA/PyTorch/vLLM compatibility, and both models' observed memory use in G2. Test concurrent operation first; consider smaller contexts, quantization, CPU offload or sequential loading only after measuring latency and resource tradeoffs. Download size alone does not establish runtime memory fit.

## Planned setup scripts and packaging

| Planned file | Responsibility and exit evidence |
|---|---|
| `scripts/check-gpu.sh` | Report detected GPU/driver/memory for the experiment record; do not infer serving compatibility solely from detection |
| `scripts/setup-models.sh` | Install pinned, tested WSL serving dependencies and acquire selected models; document source, version, access/license requirements and cache locations |
| `scripts/start-stt.sh` | Start the verified vLLM configuration on loopback; make readiness and shutdown observable |
| `scripts/start-cleanup.sh` | Start the verified Ollama configuration on loopback; handle an already-running instance clearly |
| `packaging/wispr_clone.spec` | Package Windows source/web assets; verify required webview/audio/native dependencies and a clean target launch |

Test Windows access to the WSL loopback endpoints under the user's actual networking configuration. Loopback binding and local-only policy must be checked rather than inferred from a model label. Do not expose the model services to the LAN to work around an uninvestigated connection issue.

Optional `models/wsl_launcher.py` would own subprocess startup/readiness/shutdown only if app-managed startup is selected. Until then, document manual server startup. Choosing a launcher must not change the STT or cleanup interfaces.

## API keys, secrets, and data

| Credential | When needed | Proposed storage |
|---|---|---|
| None for local inference | Default workflow after models are acquired | No runtime API key |
| `HF_TOKEN` | Only if the chosen download route requires authentication or access approval; verify current model access terms | WSL environment or the download tool's user credential store; never source control |
| Provider-specific cloud key, such as `MISTRAL_API_KEY` | Only after a cloud adapter/provider is selected | Windows Credential Manager through the chosen secret-store adapter |

The earlier plan expected Ollama acquisition of Llama to avoid a Hugging Face token and identified model-specific license terms. Verify those access and license details against the selected distributions at setup time; do not treat this document as current licensing research.

Future `scripts/.env.example` lists WSL download credential names (such as `HF_TOKEN`) without values; the Windows app reads no environment credentials, so it has no `.env` file. Ignore `.env`, `*.key`, and local environments in source control. Never expose provider credentials to JS or log them. Validate configured endpoints and block cloud adapters when local-only is enabled; never silently fail over from a local server to cloud inference.

Transcript/audio retention belongs to the codemap's history contract. Per-user storage does not mean encrypted storage. Optional encryption requires a separate decision covering key storage, recovery and deletion; do not quietly add an encryption package or permanent backup of temporary data.
