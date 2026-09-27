# WO-feat-cloud-stt — Cloud speech-to-text: Whisper Large v3 Turbo via OpenRouter (DeepInfra)

```text
Work-order ID: WO-feat-cloud-stt
Role file / requested model: RED + verify: sol / gpt-6-sol ; GREEN: luna / gpt-6-luna
Branch: feat/cloud-stt (branch 2, chore/remove-voxtral, follows after this merges)
User decisions (2026-09-27, binding):
  - STT = `openai/whisper-large-v3-turbo` through OpenRouter, provider pinned to DeepInfra only
    (no fallback).
  - The OpenRouter API key is pasted in the app and stored encrypted with Windows DPAPI.
  - Voxtral/transcribe.cpp will be removed (branch 2). This branch only stops using it by
    default.
Outcome and observable acceptance:
  - A dictation's audio is transcribed by OpenRouter → DeepInfra Whisper after stop. The
    recording is kept, so retry_stt works on network failure.
  - The key can be set and cleared from the Models page. It is never stored in plaintext, never
    returned to the UI, never logged, and never in events, the DB, results or the repo.
  - Settings upgrade existing installs to the new model.
  - Privacy text and docs state that audio leaves the device.
Base revision / worktree / branch: f9d3177 / ~/projects/wc-cstt / feat/cloud-stt
Verified current API facts (coordinator, 2026-09-27; openrouter.ai model page, llms.txt and the
  audio-API announcement):
  - `POST https://openrouter.ai/api/v1/audio/transcriptions`
  - headers: `Authorization: Bearer <key>`, `Content-Type: application/json`
  - body: `{"model": "openai/whisper-large-v3-turbo", "input_audio": {"data": <base64>,
    "format": "wav"}, "language"?: <hint>}`
  - response: `{"text": str, "usage": {"seconds", "total_tokens", "cost"}}`
  - Served by DeepInfra and Groq. Pinning on this endpoint is NOT documented, so the adapter
    sends `"provider": {"only": ["deepinfra"], "allow_fallbacks": false}` and a probe must verify
    it (rule 8).
  - About $0.000003 per second of audio.
Exact writable paths (under backend_dev/):
  Sol:  tests/unit/stt/test_openrouter_whisper*.py, tests/unit/settings/test_secret_store*.py,
        tests/unit/application/test_secret_commands*.py, tests/unit/settings/test_upgrade_v2*.py,
        tests/probes/openrouter/** (new; manual/network probe, skipped unless opted in),
        web/tests/**, tests/unit/web/**
  Luna: src/wispr_clone/stt/openrouter_whisper.py (new),
        src/wispr_clone/settings/secret_store.py (new),
        src/wispr_clone/settings/schema.py (the v2 upgrade + defaults only),
        src/wispr_clone/models/registry.py (the default registry only),
        src/wispr_clone/contracts/common.py (+2 ErrorCodes only),
        src/wispr_clone/util/error_messages.py (+2 messages only),
        src/wispr_clone/application/commands/settings_commands.py (secret commands, state_get flag),
        src/wispr_clone/application/model_service.py (stt readiness for the cloud engine only),
        src/wispr_clone/app.py (factory wiring only), src/wispr_clone/config.py (+constants only),
        web/index.html, web/app.js, web/lib/messages.js (key field + privacy copy only),
        tests/_attribution/impact/openrouter.toml (new),
        CODEMAP.md, DEPENDENCIES.md (privacy/architecture statements)
Dependencies: NONE new (httpx is already locked; DPAPI through ctypes).
Check commands: the usual Python set (UV_LINK_MODE=copy, ruff --no-cache), plus the node tests,
  plus `python -m wispr_clone --self-test`.
Privacy/secrets:
  - The key never appears in logs, exception text, events, results, the DB, test output or
    fixtures. Tests use obviously fake keys (`sk-or-v1-test…`).
  - No network call happens in the default test suite (httpx MockTransport).
```

## Pinned API

```text
# stt/openrouter_whisper.py
class OpenRouterWhisper:                       # satisfies stt.base.SttEngine
    def __init__(self, *, api_key: Callable[[], str | None],   # read at call time (key may be set later)
                 base_url: str = "https://openrouter.ai/api/v1",
                 model: str = "openai/whisper-large-v3-turbo",
                 provider_only: tuple[str, ...] = ("deepinfra",),
                 timeout_s: float = 30.0,
                 transport: httpx.AsyncBaseTransport | None = None,
                 language: str | None = None) -> None: ...
    ready: bool          # True when an api key is configured (no network)
    async def start(self) -> None          # no-op (no model to load)
    def start_session(self, on_text=None) -> SttSession   # a buffering session; one active at a time (STT_UNAVAILABLE otherwise)
    async def transcribe_file(self, path: Path) -> str     # reads the 16 kHz mono 16-bit WAV (the same checks as before), uploads
    async def close(self) -> None          # closes the httpx client
# The session: push_audio(array('f')) appends (non-blocking, float32 16 kHz);
#   finish() → encode WAV (16-bit PCM, 16 kHz mono) in memory → POST → returns text.strip() ("" allowed);
#   cancel() → drops the buffer, and finish() then raises STT_STREAM_CLOSED.

# settings/secret_store.py
class SecretStore(Protocol):
    def get(self, name: str) -> str | None: ...
    def set(self, name: str, value: str) -> None: ...
    def clear(self, name: str) -> None: ...
class DpapiSecretStore:          # Windows: CryptProtectData/CryptUnprotectData via ctypes (user scope),
    def __init__(self, directory: Path, *, entropy: bytes = b"WisprClone.v1") -> None: ...
    # a file per secret: <directory>/<name>.dpapi (encrypted bytes only); atomic write (tmp + replace)
class MemorySecretStore:         # tests and self-test; non-Windows fallback for development only
```

## Rules (binding)

1. **HTTP:**
   - The body is exactly the verified shape plus
     `"provider": {"only": list(provider_only), "allow_fallbacks": false}`, and `"language"` only
     if set.
   - Status mapping:
     - 200 with a string `text` → text;
     - 401/403 → `ThirdPartyError(..., ErrorCode.API_KEY_INVALID)`;
     - 402 (credits) and 429 → STT_UNAVAILABLE;
     - 5xx, or a non-JSON / missing `text` → STT_UNAVAILABLE;
     - an httpx timeout → STT_TIMEOUT;
     - a connect error → STT_UNAVAILABLE.
   - No key → `ThirdPartyError(..., ErrorCode.API_KEY_MISSING)`, with no request sent.
   - No automatic retries: a failed run keeps its WAV and offers retry_stt.
   - **The error `detail` never contains the key, the audio, or the response body.**
   - HTTPS only, and `base_url` must start with `https://`: validated in `__init__` (VALIDATION).
     Redirects are not followed.
   - An empty buffer (0 samples) → return "" without a request, so no-speech is handled upstream.
2. **New ErrorCodes:**
   - `API_KEY_MISSING = "api_key_missing"`, message "Add your OpenRouter API key in Models to
     enable dictation.";
   - `API_KEY_INVALID = "api_key_invalid"`, message "The OpenRouter API key was rejected. Check
     it in Models.".
   - Mirror both in web/lib/messages.js (T-WEB-008 keeps them in sync).
3. **Secret store:**
   - DPAPI user scope, with the given entropy. The file holds only ciphertext.
   - `get` of a missing or undecryptable file → None; it is never raised to the UI and never
     logged with content.
   - `set` validates `1 <= len <= 512` and the absence of whitespace/control characters
     (VALIDATION). It does not validate the format further, so providers may change it.
   - `clear` deletes the file.
   - Non-Windows `DpapiSecretStore` → OSError. The app uses `MemorySecretStore` only in the
     self-test.
4. **Commands** (settings_commands; all mutating except status):
   - `secret_set {name: "openrouter_api_key", value}` → `{"configured": true}`.
   - `secret_clear {name}` → `{"configured": false}`.
   - Only the name `openrouter_api_key` is allowed (VALIDATION otherwise).
   - `state_get` adds `secrets: {"openrouter_api_key": {"configured": bool}}`.
   - The value is never echoed in any result. After a change, `model_service.poll()` publishes
     readiness.
   - The Bridge and Api already never log payloads; keep it that way.
5. **Registry and settings (schema v2):**
   - The default registry becomes
     `ModelInfo("openai/whisper-large-v3-turbo", "stt", "Whisper Large v3 Turbo (DeepInfra)",
     local=False, runtime="openrouter", endpoint="https://openrouter.ai/api/v1")` plus the
     unchanged LM Studio cleanup model. Voxtral leaves the registry.
   - The `Settings` defaults become `stt_model_id="openai/whisper-large-v3-turbo"` and
     `local_only=False`.
   - `SETTINGS_SCHEMA_VERSION = 2`. `UPGRADE_STEPS[1]`: `stt_model_id` "voxtral-..." → the
     whisper id, and `local_only` → False (it would otherwise forbid the only STT model).
     Everything else is kept.
   - With `local_only=True` set later by the user, validation → CLOUD_MODEL_FORBIDDEN on
     `stt_model_id`, so the UI explains that dictation needs cloud STT.
6. **Model readiness:**
   - stt ready = engine present, and `engine.ready` (a key is configured).
   - No key → `error_code "api_key_missing"`. No network call in readiness; model_service stays
     read-only.
7. **App wiring:**
   - `stt_engine` factory → `OpenRouterWhisper(api_key=lambda: store.get("openrouter_api_key"))`.
   - The store is `DpapiSecretStore(app_data_dir()/"secrets")` on Windows.
   - The self-test keeps its fake STT, using `MemorySecretStore`.
   - The `config.stt_model_path()` use is removed from the app (the function is deleted in
     branch 2).
8. **Probe (manual, opt-in):** `tests/probes/openrouter/test_p_openrouter_001.py`, marked
   `probe("httpx")` and `manual`.
   - It runs only if `WISPR_NETWORK_PROBES=1` and a key is available from `DpapiSecretStore`
     (Windows) or the env var `OPENROUTER_API_KEY`.
   - It sends ~2 s of the committed public-domain fixture, or a generated 440 Hz tone if no
     fixture exists, with provider pinned.
   - It asserts a 200 with a string `text`, and records `usage.cost`.
   - If the response carries provider information (a header or body field), it asserts
     deepinfra.
   - It never prints the key.
   - The coordinator runs it with the user's key after the user saves it in the app.
9. **UI (Models page; reuse the existing `field-label` / `field` / `btn` patterns, no new
   styles):**
   - Under the Speech to text model select: a password input "OpenRouter API key" with
     `autocomplete="off"`, a Save button, and Clear.
   - A status line reads "Key saved" or "No key saved". The value is cleared from the input right
     after sending and never displayed.
   - The Speech model select shows Whisper Large v3 Turbo (DeepInfra), and the existing "Leaves
     this device" yellow note is shown for it.
   - The Privacy & data page copy: "Your audio is sent to OpenRouter and transcribed by DeepInfra
     (Whisper Large v3 Turbo). Transcripts stay on this PC." Remove any "nothing leaves this
     device" claims.
10. **Docs:**
    - CODEMAP §1/§2 baseline, the §5 privacy notes, and §7 G2 are updated to cloud STT via
      OpenRouter/DeepInfra.
    - DEPENDENCIES.md adds OpenRouter/DeepInfra as an external service (no package).
    - The impact fragment `openrouter.toml`: dependency "openrouter-service", kind "service",
      modules ["stt.openrouter_whisper"], features ["live dictation", "retry_stt"],
      error_codes ["stt_unavailable", "stt_timeout", "api_key_missing", "api_key_invalid"],
      action "Check the OpenRouter key in Models, credits, and status.openrouter.ai".

## Tests (Sol)

| ID | Assertion |
|---|---|
| T-STT-020 | Request shape: URL, method, bearer header present, JSON body with model, base64 WAV `input_audio` (decodes to a valid 16 kHz mono 16-bit WAV of the pushed samples), `format` wav, provider `{"only":["deepinfra"],"allow_fallbacks":false}`, language only if set |
| T-STT-021 | Status mapping per rule 1 (401/403/402/429/500/timeout/connect/bad JSON/missing text) → codes; no retries (exactly 1 request) |
| T-STT-022 | No key → api_key_missing and 0 requests; empty buffer → "" and 0 requests; cancel → finish raises stt_stream_closed; a second concurrent session → stt_unavailable |
| T-STT-023 | Privacy: the fake key string and the audio base64 never appear in exception str/detail, caplog, or `repr` of the engine |
| T-STT-024 | transcribe_file validates the WAV format and uploads that audio; http base_url → validation; redirects are not followed |
| T-SET-020 | Secret store: MemorySecretStore round trip; DpapiSecretStore on Windows (skipped elsewhere) writes a file without the plaintext bytes and round-trips; get of a corrupt file → None; value validation |
| T-SET-021 | Settings v1 → v2 upgrade: voxtral id → whisper id, local_only → False, other fields kept; local_only=True with whisper → cloud_model_forbidden |
| T-APP-030 | secret_set/secret_clear through Api: the result never contains the value; state_get shows configured true/false; an unknown name → validation; models:status goes api_key_missing → ready after set |
| T-WEB-010 | The key input is type=password; the value is never rendered into the DOM or state; messages.js has the 2 new codes; the privacy copy has no "nothing leaves" claim (static check) |
| P-OPENROUTER-001 | (manual, opt-in) the live request per rule 8 |

## Coordinator decisions after RED review

1. Resolved conflicts:
   - a. `web/lib/bridge.js` is writable for Luna: add `secret_set` and `secret_clear` to the
     mutating set.
   - b. **The defaults changed by user decision.** Existing tests that assert the old defaults
     (schema v1, Voxtral in the default registry, Voxtral as the selected stt model,
     `local_only=True`, "current version is 1") are updated by Sol to the new defaults:
     whisper id, `local_only=False`, schema v2 with the v1→v2 step.
     - They must keep their original intent. For example, a test proving the local-only
       rejection of a cloud model still proves it, now with whisper as the cloud model.
     - This is test maintenance forced by the product change, not bending the code.
   - c. `SettingsCommands(..., secret_store: SecretStore, model_service: ModelService | None =
     None)`: the keyword names Sol's tests use. `model_service.poll()` is awaited after
     secret_set/secret_clear when present.
2. **After Sol's security verification (binding):**
   - a. **No retained exception context:** in the HTTP send, catch the httpx exception, record
     only its code, leave the `except` block, then raise the ThirdPartyError. The raised error
     then has `__context__ is None` and `__cause__ is None`, so no httpx Request object (which
     carries the Authorization header) is reachable. Apply the same pattern to every raise in
     openrouter_whisper.py and secret_store.py that happens inside an `except`.
   - b. **Non-Windows real factory:** use an `UnavailableSecretStore` (`get` → None; `set` /
     `clear` → WisprError(STORAGE_ERROR, "secrets", "unsupported platform")), never the volatile
     MemorySecretStore. MemorySecretStore is for tests and the self-test only.
   - c. **Privacy switch:** the Privacy & data local-only switch reflects `settings.local_only`
     from state_get and settings events. Toggling it sends settings_update. Turning it on shows
     the existing yellow warning text, "Dictation needs cloud speech-to-text; it is disabled
     while local-only is on." Source file: web/index.html and web/app.js.
   - d. **CODEMAP §2** (and any other "in-process Voxtral / no cloud needed" statement) is
     rewritten for cloud STT via OpenRouter → DeepInfra.
