# Tier G record — ops/local-models (2026-09-25)

Run by the coordinator (the agent sandbox has no GPU access; agents/HARDWARE.md), from WSL through
the Windows venv `C:\Users\2006i\AppData\Local\wispr_clone\venv` created with
`uv.exe sync --locked` (uv 0.12.19, Python 3.12, locked baseline incl. transcribe-cpp 0.2.3 + cu12).
Nothing was downloaded except the locked packages; no LM Studio model or setting was changed.

## Machine state

| Item | Value |
|---|---|
| GPU / driver | NVIDIA GeForce RTX 5080 / 610.88, 16,303 MiB total |
| Free VRAM before / after | 2,430 MiB / 2,432 MiB (desktop apps + LM Studio in use) |
| LM Studio models (read-only `GET /api/v0/models`) | meta-llama-3.1-8b-instruct **loaded** (Q4_K_S, ctx 8,192); text-embedding-qwen3-embedding-0.6b loaded; voxtral-mini-4b-realtime-2602 not-loaded; text-embedding-nomic-embed-text-v1.5 not-loaded |
| WSL RAM available | 10 GiB |

## `scripts/check_local_models.py` (Windows Python)

| Check | Status |
|---|---|
| gguf | ok — SHA-256 `39dc1f65…4723` verified for the pinned path |
| lmstudio | ready — pinned model loaded |
| lan_exposure | not_exposed — port 1234 not reachable at 192.168.1.89 |
| gpu | ok — 2,368 MiB free |

Exit code 0, `"ready": true`.

## Tier G probes: `pytest -m gpu -k "not TCPP and not A01"` → 6 passed

| Test | Result | Recorded |
|---|---|---|
| P-GPU-001 | passed | RTX 5080, driver 610.88, 2,432 MiB free |
| P-NET-001 | passed | LM Studio reachable on 127.0.0.1:1234 |
| P-NET-002 | passed | not reachable on LAN IP 192.168.1.89 |
| P-LMS-001 | passed | pinned model loaded, Q4_K_S, context 8,192 |
| P-LMS-002 | passed | temperature 0 repeatable; 0.33 s then 0.031 s |
| P-LMS-003 | passed | first stream event 0.036 s; follow-up after disconnect 0.05 s |

## Not run (deliberately deferred)

| Test | Why |
|---|---|
| P-TCPP-002, P-TCPP-003, T-STT-A01 | They load Voxtral on the GPU (+≈2.1 GB per the G2 record). Only ≈2.4 GB was free with the user's desktop apps and LM Studio (shared with Cognee) running; loading would leave ≈0.3 GB and risk slowing LM Studio/Cognee or the desktop. User decision 2026-09-25: skipped for now; run before a release (dev_pipeline §4.3). |
| P-TCPP-004 | Needs a public-domain speech fixture; LibriVox is MP3 and no approved package decodes MP3 (WO deferral). |
