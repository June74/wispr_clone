# WO-feat-settings-models — Settings schema and model registry

```text
Work-order ID: WO-feat-settings-models
Role file / requested model: RED + verify: sol-feature-test-author.md (T-SET, T-REG) and
                             sol-boundary-test-author.md (P-PYD, impact fragment) / gpt-6-sol
                             GREEN: luna-core-programmer.md / gpt-6-luna
Pipeline branch or P0/M stage: Wave 1, branch feat/settings-models
Outcome and observable acceptance:
  A validated, versioned Settings value (pydantic, strict) with defaults matching the finished UI,
  upgrade steps for older stored versions, and local-only enforcement; a metadata-only model
  registry listing the two selected local models, rejecting non-loopback endpoints for local
  models. No storage, no health checks, no adapters.
Base revision / worktree / branch: 984ab46 / ~/projects/wc-settings-models / feat/settings-models
Relevant sections: feature spec "Recording controls", "Speech-to-text and model control",
  "Meaning-preserving cleanup", "Text insertion" (1 s idle / 10 min limits configurable);
  CODEMAP.md §3 (settings and models.registry rows; contracts rule), §5 (settings row), §7 G7;
  dev_pipeline.md §6 Wave 1 row feat/settings-models; UI reference
  ../ui_development/code/index_final.html ("How you record", "Models" pages).
Prerequisites: P0 merged.
Exact writable paths (under backend_dev/):
  Sol:  tests/unit/settings/**, tests/unit/models/**, tests/probes/pydantic/**,
        tests/_attribution/impact/pydantic.toml
  Luna: src/wispr_clone/settings/__init__.py (docstring only; feat/settings-store adds store.py
        later), src/wispr_clone/settings/schema.py, src/wispr_clone/models/__init__.py (docstring
        only), src/wispr_clone/models/registry.py
Read-only: everything else.
Allowed imports: settings -> contracts, config, util, pydantic (NOT models: settings receives a
  ModelCatalog by injection). models -> contracts, config, util + stdlib (ipaddress,
  urllib.parse, dataclasses). pydantic only in settings/schema.py.
Probe IDs / impact fragment: P-PYD-001; tests/_attribution/impact/pydantic.toml (Sol).
Required tiers: S, U, P on ubuntu and windows. No devices, no LM Studio.
Check commands (from backend_dev/, UV_LINK_MODE=copy):
  uv sync --locked; uv run ruff check .; uv run ruff format --check .;
  uv run mypy src scripts tests/_attribution tests/fakes; uv run python scripts/check_imports.py;
  uv run pytest -q -W error
Authorization: edit only writable paths; no git writes; no PRs; the coordinator commits, pushes,
  opens the PR. No new dependencies (pydantic 2.13.5 is already locked).
CCRs / deferrals:
  T-SET-002 (invalid shortcut rejected via the shortcuts contract) is DEFERRED: the shortcut parser
  in contracts/shortcuts.py is written by feat/hotkeys, which has not started. Until then the
  shortcut fields are non-empty strings (max 64 chars) and their meaning is not checked here.
  The coordinator adds T-SET-002 to feat/settings-store or a follow-up once feat/hotkeys merges.
Handoff: coordinator. Sol: RED command/output. Luna: GREEN outputs. Sol: verification findings.
```

## Pinned API (use these exact names)

`wispr_clone.models.registry` (stdlib + contracts/config only):

```python
ModelRole = Literal["stt", "cleanup"]

@dataclass(frozen=True, slots=True)
class ModelInfo:
    model_id: str
    role: ModelRole
    display_name: str
    local: bool
    runtime: str            # "transcribe-cpp", "lmstudio", or a cloud provider name
    endpoint: str | None    # None for in-process models

class ModelRegistry:
    def __init__(self, models: Iterable[ModelInfo]) -> None
    def list_models(self, role: ModelRole | None = None) -> tuple[ModelInfo, ...]  # registration order
    def get(self, model_id: str) -> ModelInfo | None
    def role_of(self, model_id: str) -> str | None       # None when unknown
    def is_local(self, model_id: str) -> bool             # False when unknown

def is_loopback_endpoint(url: str) -> bool
def default_registry() -> ModelRegistry
```

- `ModelRegistry.__init__` raises `WisprError(ErrorCode.VALIDATION, where="models.registry", ...)`
  for a duplicate `model_id` or empty id, and `WisprError(ErrorCode.NON_LOOPBACK_ENDPOINT,
  where="models.registry", ...)` for a `local=True` model whose endpoint is not loopback.
- `is_loopback_endpoint`: True only for `http`/`https` URLs whose host is an IP literal with
  `ipaddress.ip_address(host).is_loopback` (e.g. `127.0.0.1`, `127.0.0.5`, `[::1]`). False for
  `localhost` (a name, which a hosts file can redirect), `0.0.0.0`, LAN or public IPs, hostnames,
  missing host, other schemes, and malformed URLs. Never raises.
- `default_registry()` lists exactly, in this order:
  1. `voxtral-mini-4b-realtime-2602`, role `stt`, display "Voxtral Mini 4B Realtime", local True,
     runtime `transcribe-cpp`, endpoint None.
  2. `config.LM_STUDIO_MODEL_ID` (`meta-llama-3.1-8b-instruct`), role `cleanup`, display
     "Llama 3.1 8B Instruct", local True, runtime `lmstudio`, endpoint `config.LM_STUDIO_ENDPOINT`.
  No cloud models (G7: no cloud provider selected).

`wispr_clone.settings.schema` (pydantic v2):

```python
SETTINGS_SCHEMA_VERSION: int = 1

class ModelCatalog(Protocol):          # ModelRegistry satisfies this structurally
    def role_of(self, model_id: str) -> str | None: ...
    def is_local(self, model_id: str) -> bool: ...

class Settings(BaseModel):             # model_config = ConfigDict(strict=True, extra="forbid", frozen=True)
    schema_version: int = SETTINGS_SCHEMA_VERSION
    recording_mode: Literal["toggle", "hold"] = "toggle"
    dictation_shortcut: str = "ctrl+shift+space"     # 1..64 chars
    cancel_shortcut: str = "escape"                  # 1..64 chars
    microphone_id: str | None = None                 # None = system default input
    stt_model_id: str = "voxtral-mini-4b-realtime-2602"
    cleanup_model_id: str = "meta-llama-3.1-8b-instruct"
    cleanup_enabled: bool = True
    cleanup_instructions: str = ""                   # 0..2000 chars
    local_only: bool = True
    theme: Literal["system", "light", "dark"] = "light"
    idle_jump_seconds: float = 1.0                   # 0.5 ..= 10.0   (default = config.IDLE_JUMP_SECONDS)
    return_settle_seconds: float = 0.3               # 0.1 ..= 2.0    (config.RETURN_SETTLE_SECONDS)
    destination_wait_limit_seconds: int = 600        # 60 ..= 3600    (config.DESTINATION_WAIT_LIMIT_SECONDS)

UpgradeStep = Callable[[dict[str, object]], dict[str, object]]   # version n data -> version n+1 data
UPGRADE_STEPS: Mapping[int, UpgradeStep] = {}        # empty until schema version 2 exists

def default_settings() -> Settings
def parse_settings(data: Mapping[str, object], catalog: ModelCatalog, *,
                   upgrade_steps: Mapping[int, UpgradeStep] = UPGRADE_STEPS) -> Settings
def settings_to_data(settings: Settings) -> dict[str, object]     # JSON-ready; round-trips via parse_settings
```

`parse_settings` order and errors (all `WisprError`, `where="settings.schema"`):

1. `schema_version` missing or not an int → `VALIDATION`. Greater than `SETTINGS_SCHEMA_VERSION`
   → `VALIDATION` ("newer settings schema"). Lower → apply `upgrade_steps[v]` for v, v+1, ... up to
   the current version; a missing step → `VALIDATION`. The input mapping is never mutated.
2. Pydantic validation. A `ValidationError` becomes `VALIDATION` whose `why` lists only the failing
   field names (from `errors(include_input=False)`), never the input values. The pydantic exception
   is not chained into the raised error's text (`raise ... from None`), because inputs such as
   cleanup instructions are user text.
3. Catalog checks: `catalog.role_of(stt_model_id) != "stt"` or `role_of(cleanup_model_id) !=
   "cleanup"` (unknown or wrong role) → `VALIDATION`. `local_only` and a selected model where
   `catalog.is_local(...)` is False → `CLOUD_MODEL_FORBIDDEN`.

## Tests (Sol; IDs in function names)

| ID | Location | Must assert |
|---|---|---|
| T-SET-001 | tests/unit/settings/ | `default_settings()` has exactly the pinned defaults; `parse_settings(settings_to_data(default_settings()), default_registry())` round-trips equal; the data is `json.dumps`-able; defaults for the three delivery timings equal the `config` constants |
| **T-SET-003** (invariant) | tests/unit/settings/ | with a test catalog containing a cloud STT model: `local_only=True` + cloud model → `CLOUD_MODEL_FORBIDDEN`; `local_only=False` + same model → accepted; same for the cleanup model; unknown model id or wrong role → `VALIDATION` |
| T-SET-004 | tests/unit/settings/ | a version-0 payload plus an injected step `{0: fn}` upgrades to version 1 and validates; the input dict is unchanged; a missing step, a newer version (2) and a missing `schema_version` → `VALIDATION` |
| T-SET-005 | tests/unit/settings/ | strictness and privacy: extra field, wrong type (`"true"` for a bool, `"1"` for an int), out-of-range timings, too-long instructions, empty shortcut → `VALIDATION`; a sentinel string placed in `cleanup_instructions` (too long) never appears in `str(error)`, `error.why` or the exception chain text; `Settings` is frozen |
| T-REG-001 | tests/unit/models/ | `default_registry().list_models()` returns the two pinned models in order with `local=True`; `list_models("stt")`/`("cleanup")` filter; `get`, `role_of`, `is_local` for known and unknown ids; duplicate id → `VALIDATION` |
| **T-REG-002** (invariant) | tests/unit/models/ | `is_loopback_endpoint` truth table from the pinned rules (at least: `http://127.0.0.1:1234/v1`, `http://[::1]:1234` True; `http://localhost:1234`, `http://0.0.0.0:1234`, `http://192.168.1.20:1234`, `https://api.example.com`, `ftp://127.0.0.1`, `""`, `"not a url"` False); a local model with a non-loopback endpoint → `NON_LOOPBACK_ENDPOINT`; a non-local model with a remote endpoint is accepted |

Probe (Sol boundary; `@pytest.mark.probe("pydantic")`; pydantic only, no wispr_clone code), in
tests/probes/pydantic/:

- P-PYD-001 a strict model with `extra="forbid"` rejects an extra field and `"1"` for an `int`;
  `ValidationError.errors(include_input=False)` entries carry `loc` and have no `input` key; a
  `frozen=True` model rejects attribute assignment.

Impact fragment `tests/_attribution/impact/pydantic.toml`: `dependency = "pydantic"`, `kind =
"library"`, `modules = ["settings.schema"]`, features = settings validation and upgrade, local-only
enforcement; `error_codes = ["validation", "cloud_model_forbidden"]`; action = check the pydantic pin
in uv.lock, not a wispr_clone fix.
</content>

## Coordinator findings from a demo of the GREEN code (binding)

1. `is_loopback_endpoint` must also return False when the port is invalid (e.g. `:99999`,
   `:0`, non-numeric) — reading `urlsplit(...).port` raises for these today but is never read.
2. It must return False when the URL carries user info (`http://user:pw@127.0.0.1:1234`):
   credentials never belong in settings or the registry.
3. `microphone_id`, when not None, is 1..256 characters (device IDs are short; an unbounded
   string is a needless storage/validation risk).
   IPv4-mapped loopback (`[::ffff:127.0.0.1]`) and an upper-case scheme stay accepted.

## Coordinator decisions after verification

4. Upgrade steps receive a deep copy of the data (`copy.deepcopy`), so a step can never mutate the
   caller's mapping, nested values included. A step that returns anything other than a `dict`, or
   raises, → `VALIDATION`.
5. `is_loopback_endpoint` returns False for any URL containing whitespace or ASCII control
   characters (checked on the raw string before parsing; `urlsplit` silently strips `\t\n\r`).
6. Findings 1-3 from the demo are confirmed by Sol's tests (ports, user info, microphone_id 1..256).
