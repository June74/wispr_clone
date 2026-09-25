# WO-ops-local-models — Model readiness check and real-model probes (tier G)

```text
Work-order ID: WO-ops-local-models
Role file / requested model: RED + tier G runs + verify: sol-feature-test-author.md (T-OPS) and
                             sol-boundary-test-author.md (P-TCPP-002/003, P-LMS, P-NET, P-GPU,
                             T-STT-A01, lmstudio fragment; single GPU owner) / gpt-6-sol
                             GREEN: luna-runtime-programmer.md / gpt-6-luna
Pipeline branch or P0/M stage: Wave 1, branch ops/local-models
Outcome and observable acceptance:
  scripts/check_local_models.py reports, without downloading, loading or reconfiguring anything,
  whether the local stack is ready: Voxtral GGUF present with the pinned SHA-256, LM Studio
  answering on 127.0.0.1:1234 with the pinned model loaded, LM Studio NOT reachable on the LAN IP,
  free VRAM. Real-model probes and the real STT adapter test run on this machine's GPU through the
  Windows venv and their evidence (attribution JSON + free VRAM) is attached to the PR.
Base revision / worktree / branch: 74a10b8 / ~/projects/wc-local-models / ops/local-models
Relevant sections: CODEMAP.md §7 G2 record (LM Studio config, Voxtral timings, VRAM budget);
  DEPENDENCIES.md (models, GPU budget, "no script downloads models or starts LM Studio");
  dev_pipeline.md §5.4 (P-TCPP-002..004, P-LMS, P-NET, P-GPU), §6 row ops/local-models, §9
  decisions 5-6; agents/HARDWARE.md (single GPU owner, one heavy job, record free VRAM);
  WO-feat-stt (adapter API), WO-feat-cleanup (/api/v0/models shape, never trigger JIT loading).
Exact writable paths (under backend_dev/):
  Sol:  tests/unit/ops/**, tests/probes/lmstudio/**, tests/probes/net/**, tests/probes/gpu/**,
        tests/probes/transcribe_cpp/test_p_tcpp_002_003.py, tests/adapter/stt/** (T-STT-A01),
        tests/_attribution/impact/lmstudio.toml, docs/verification/ops-local-models.md (tier G record)
  Luna: scripts/check_local_models.py
Read-only: everything else.
Allowed imports: the script is stdlib only (argparse, hashlib, json, socket, subprocess,
  urllib.request, pathlib, dataclasses); it is not imported by src/.
Required tiers: S, U (fake HTTP / fake files / fake subprocess) on ubuntu and windows; G (real GPU,
  real LM Studio, real network interfaces) on this machine only, marked `gpu` so hosted CI skips it.
Check commands (from backend_dev/, UV_LINK_MODE=copy):
  uv sync --locked; uv run ruff check .; uv run ruff format --check .;
  uv run mypy src scripts tests/_attribution tests/fakes; uv run python scripts/check_imports.py;
  uv run pytest -q -W error
Tier G command (Sol boundary only, from WSL, Windows venv on the Windows disk):
  export UV_PROJECT_ENVIRONMENT='C:\Users\2006i\AppData\Local\wispr_clone\venv'
  /mnt/c/Users/2006i/.local/bin/uv.exe sync --locked            # first run creates the venv
  /mnt/c/Users/2006i/.local/bin/uv.exe run pytest -m "gpu or adapter" -p no:cacheprovider \
      --attribution-json ../../wc-logs/tier-g-ops.json            (run from the backend_dev dir
      via its \\wsl.localhost\Ubuntu\... path, as in G1)
Authorization (already given by the user): tier G runs locally through the Windows venv; the
  locked baseline may be installed into that venv (G1 layout); network access for uv only.
  FORBIDDEN without the user: downloading any model, loading/unloading/reconfiguring LM Studio
  models or settings, starting or stopping LM Studio, changing "serve on local network".
  One heavy job at a time; record free VRAM before and after every GPU run.
Deferred (coordinator decision): P-TCPP-004 (word error rate on a public-domain LibriVox clip) and
  tests/fixtures/audio/speech/** — LibriVox publishes MP3 and no approved package decodes MP3;
  a follow-up picks a decoding path (user decision if it needs a new dependency).
Privacy: no transcript text of real speech in logs or artifacts; probes use synthetic silence/tones
  or a generated WAV and record timings, not text; LM Studio prompts are synthetic.
Handoff: coordinator. Sol: RED output, then tier G evidence. Luna: GREEN outputs.
```

## Pinned facts (observed by the coordinator on 2026-09-25, read-only)

- GGUF: `C:\Users\2006i\.lmstudio\models\handy-computer\Voxtral-Mini-4B-Realtime-2602-gguf\Voxtral-Mini-4B-Realtime-2602-Q4_K_M.gguf`,
  2,830,493,984 bytes, SHA-256 `39dc1f65539373a406edea7490505822d77c12edff521744678717eef4da4723`
  (hash of the local file; not compared against a published hash).
- LM Studio `GET /api/v0/models`: `meta-llama-3.1-8b-instruct` `state: "loaded"`, Q4_K_S, context
  8,192; `voxtral-mini-4b-realtime-2602` is listed but `not-loaded` (LM Studio cannot serve it; the
  app runs it in-process).

## Pinned API: `scripts/check_local_models.py`

```python
EXPECTED_GGUF_SHA256 = "39dc1f65539373a406edea7490505822d77c12edff521744678717eef4da4723"
DEFAULT_GGUF = Path(r"C:\Users\2006i\.lmstudio\models\handy-computer\Voxtral-Mini-4B-Realtime-2602-gguf\Voxtral-Mini-4B-Realtime-2602-Q4_K_M.gguf")
LMSTUDIO_BASE = "http://127.0.0.1:1234"; LMSTUDIO_PORT = 1234; PINNED_MODEL = "meta-llama-3.1-8b-instruct"

@dataclass(frozen=True)
class Check:
    name: str                 # "gguf", "lmstudio", "lan_exposure", "gpu"
    status: str               # see below
    ok: bool
    detail: str               # short, no secrets, no file contents

def check_gguf(path: Path, expected_sha256: str = EXPECTED_GGUF_SHA256) -> Check
    # status "missing" (detail names the expected path) | "sha256_mismatch" (detail names the path
    # and both hashes) | "ok"; streams the file in 1 MiB blocks
def check_lmstudio(base: str = LMSTUDIO_BASE, model: str = PINNED_MODEL, *,
                   opener=urllib.request.urlopen, timeout: float = 3.0) -> Check
    # GET {base}/api/v0/models ONLY; status "not_running" (connection refused/timeout) |
    # "model_not_loaded" (missing or state != "loaded") | "ready"; never POSTs
def check_lan_exposure(port: int = LMSTUDIO_PORT, *, lan_ip: str | None = None,
                       connect=socket.create_connection, timeout: float = 1.0) -> Check
    # lan_ip: this machine's primary IPv4 via a UDP socket connect to 192.0.2.1:9 (TEST-NET,
    # no packet is sent) unless given; status "not_exposed" (ok) | "exposed" (NOT ok — a failure,
    # never a warning) | "no_lan_ip" (ok, detail says why)
def check_gpu(*, run=subprocess.run) -> Check
    # nvidia-smi --query-gpu=name,memory.total,memory.used,memory.free --format=csv,noheader,nounits;
    # status "ok" with free MiB in detail | "unavailable"
def run_checks(**overrides) -> list[Check]
def main(argv: list[str] | None = None) -> int
    # prints one JSON object {"checks": [...], "ready": bool}; exit 0 when all ok, 1 otherwise;
    # --gguf PATH overrides the model path; --skip-gpu; --json-only
```

The script reads NO environment credentials, downloads nothing, starts nothing, and never sends a
request other than `GET /api/v0/models` to loopback and one TCP connect attempt to the LAN IP.

## Tests

T-OPS (Sol feature, tests/unit/ops/, fakes only; load the script with `importlib` from its path):

| ID | Must assert |
|---|---|
| T-OPS-001 | missing GGUF → `missing` naming the expected path; a temp file with other content → `sha256_mismatch` with both hashes; a temp file whose hash is passed as expected → `ok` |
| **T-OPS-002** (invariant) | a fake `connect` that succeeds on the LAN IP → `exposed`, `ok=False`, and `main` exits 1; refused → `not_exposed`; the check never connects to anything but the given LAN IP and port |
| T-OPS-003 | fake opener: connection refused → `not_running`; model missing or `not-loaded` → `model_not_loaded`; loaded → `ready`; the opener only ever receives a GET for `/api/v0/models` |
| T-OPS-004 | static (ast): the script imports no third-party packages, never reads `os.environ`/`getenv` for anything but `LOCALAPPDATA`/`USERPROFILE`, contains no `http(s)://` literal other than loopback, no POST/PUT/DELETE, no `urlretrieve`, no `lms` CLI call |
| T-OPS-005 | `main` prints valid JSON with every check and `ready`; exit codes 0/1; `--skip-gpu` omits the GPU check; fake `nvidia-smi` output parsed to free MiB |

Tier G (Sol boundary; `@pytest.mark.gpu` plus the probe/adapter marker; skip with a reason when
not on Windows, when `transcribe_cpp` is not importable, when the GGUF is missing, or when LM Studio
is not running — so hosted CI reports them skipped, never passed):

- P-GPU-001 `probe("nvidia-smi")`-style platform probe: `nvidia-smi` lists the RTX 5080; free VRAM
  recorded (`record_property`).
- P-NET-001 LM Studio reachable on `127.0.0.1:1234`; P-NET-002 NOT reachable on the LAN IP.
- P-LMS-001 `/api/v0/models` lists `meta-llama-3.1-8b-instruct` with `state == "loaded"` (if not
  loaded: SKIP with "model not loaded; not loading it", never load it).
- P-LMS-002 two chat requests at temperature 0 with a short synthetic prompt return identical
  non-empty content (only when P-LMS-001's condition holds).
- P-LMS-003 closing a streaming chat request mid-way does not raise and a follow-up request still
  succeeds (disconnect accepted; GPU-level evidence stays the G2 record).
- P-TCPP-002 `transcribe_cpp.Model(GGUF, device=CUDA0)` loads, warms up on 1 s of silence, reports
  streaming capability; load and warm-up seconds + VRAM delta recorded.
- P-TCPP-003 feeding 5 s of silence/tone in 80 ms chunks at live pace never falls behind (max feed
  call < 0.5 s), `finalize()` returns; `session.cancel()` during a long `run` raises `Aborted`
  within 2 s.
- T-STT-A01 (`adapter("transcribe-cpp")`): `VoxtralTranscribeCpp(GGUF).start()`, then
  `transcribe_file` on a generated 16 kHz WAV (tone/silence) completes and returns a string;
  `close()` frees the model. Records timings, not text.

`tests/_attribution/impact/lmstudio.toml`: dependency `lmstudio`, kind `service`, modules `[]`
(no src module imports it; it is reached over HTTP by `cleanup.lmstudio_cleanup`), features cleanup
after dictation / retry cleanup / model readiness, error_codes `cleanup_unavailable`,
`cleanup_timeout`, action = load the model in LM Studio yourself or check its idle-unload setting;
not a wispr_clone code fix.

`docs/verification/ops-local-models.md` (Sol boundary): date, revision, OS, GPU driver, LM Studio
model list (ids + state), free VRAM before/after, every tier G result with timings, and every skip
with its reason. No transcript text.
