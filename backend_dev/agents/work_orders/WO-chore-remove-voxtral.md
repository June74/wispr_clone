# WO-chore-remove-voxtral — Remove the local Voxtral / transcribe.cpp STT path

```text
Work-order ID: WO-chore-remove-voxtral
Roles: RED: sol / gpt-6-sol (the guard test) ; GREEN: luna / gpt-6-luna (the removal)
Branch: chore/remove-voxtral (after #35, cloud STT)
User decision (2026-09-27): "Remove it". The Voxtral/transcribe.cpp local STT is removed;
  cloud Whisper via OpenRouter/DeepInfra is the only STT. The removal is recoverable through git
  history, so no backup copy is kept.
Base revision / worktree / branch: fadda31 / ~/projects/wc-rmvox / chore/remove-voxtral
```

## Inventory (coordinator; binding)

| Path | Disposition | Reason |
|---|---|---|
| `src/wispr_clone/stt/voxtral_transcribe_cpp.py` | remove | the local adapter |
| `tests/unit/stt/test_stt.py`, `tests/unit/stt/fake_transcribe_cpp.py` | remove | test only the Voxtral adapter and its fake |
| `tests/adapter/stt/test_t_stt_a01_transcribe_cpp.py` | remove | real-adapter test |
| `tests/probes/transcribe_cpp/` (P-TCPP-001..003) | remove | library probes |
| `tests/probes/gpu/test_p_gpu_001.py` | remove | the GPU was needed only for Voxtral; LM Studio manages its own GPU |
| `tests/_attribution/impact/transcribe_cpp.toml` | remove | the dependency is gone |
| `pyproject.toml` `transcribe-cpp`, `transcribe-cpp-native-cu12` | remove, then `uv lock` | only these two packages leave `uv.lock` (verify the lock diff removes nothing else) |
| `src/wispr_clone/config.py` `stt_model_path()` | remove | no GGUF |
| `scripts/check_local_models.py` | edit: remove `check_gguf`, `check_gpu`, `DEFAULT_GGUF`, `EXPECTED_GGUF_SHA256` and their CLI output; keep the LM Studio / network / port checks | readiness without Voxtral |
| `tests/unit/ops/test_t_ops_001_005.py` | edit: drop the GGUF/GPU cases, keep the others | follows the script |
| `settings/schema.py` v1→v2 upgrade (`voxtral-...` id), `tests/unit/settings/test_upgrade_v2.py`, `test_registry.py`, `test_model_service.py` | **keep** | needed to migrate old settings, and negative assertions |
| `experiments/g1_smoke`, `experiments/g2_*` | **keep** | gate evidence referenced by the CODEMAP §7 G2 history; excluded from lint and CI |
| `agents/*.md`, old work orders, `research/` | **keep** | historical records |
| `CODEMAP.md` (project tree, check_local_models description, current-state statements), `DEPENDENCIES.md` (the transcribe-cpp row → removed 2026-09-27, with the reason), `agents/HARDWARE.md` (the GPU is no longer needed by the app), `docs/verification/ops-local-models.md` (a note that the Voxtral tier-G probes were retired, and why), `dev_pipeline.md` E2E-001 wording (real OpenRouter Whisper instead of transcribe.cpp) | edit | current docs |

Do not delete anything not listed as "remove". Check for other importers before deleting
(`git grep`).

## Tests

- **T-DIAG-020 (Sol, new, Python static):**
  - `transcribe_cpp` / `transcribe-cpp` appears nowhere in `src/`, `pyproject.toml`, `uv.lock`,
    `tests/_attribution/impact/`, or `.github/workflows/`;
  - `wispr_clone.stt` has no `voxtral` module;
  - `config` has no `stt_model_path`.
  - Allowed exceptions, by exact path: `settings/schema.py`, which carries the voxtral id for
    the upgrade, and `experiments/`.
- All remaining tests pass, and the self-test passes.

## Check commands

- The usual Python set (UV_LINK_MODE=copy, ruff --no-cache) + node tests + the self-test.
- `uv sync --locked` after `uv lock`.
- The coordinator reruns the full suite on the Windows venv (`uv.exe sync --locked` with the new
  lock).

## Coordinator decisions after GREEN review

1. The `uv lock` delta is 6 packages, not 2: `transcribe-cpp`, `transcribe-cpp-native`,
   `transcribe-cpp-native-cu12`, and their now-unreachable transitives `nvidia-cublas-cu12`,
   `nvidia-cuda-nvrtc-cu12` and `nvidia-cuda-runtime-cu12`. Nothing else depends on them, so
   this is correct. The WO's "only these two" was too strict.
2. `test_model_service.py`: Luna removed the whole T-APP-017 real-adapter test. The coordinator
   restored its LM Studio half, which proves cleanup readiness is a read-only
   `GET /api/v0/models` and never loads a model (the LM Studio is shared with Cognee). Only the
   Voxtral lines are gone.
