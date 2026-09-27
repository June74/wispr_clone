# Machine constraints and execution budget

Inventory observed on **2026-09-24**. Utilization changes; this is not a benchmark or a promise that both inference models fit. Recheck before heavy work.

| Item | Observed evidence | Constraint for agents |
|---|---|---|
| Development OS | `/etc/os-release`: Ubuntu 26.04.1 LTS; `uname -sr`: Linux 6.18.33.2-microsoft-standard-WSL2 | Develop under WSL; the desktop application still targets Windows |
| CPU visible to WSL | `lscpu`: Intel Core Ultra 7 270K Plus, 24 logical CPUs | Do not automatically set test/build worker count to all CPUs |
| RAM visible to WSL | `free -h`: about 15 GiB total, 11 GiB available at inspection | This is WSL-visible RAM, not a measurement of total Windows physical RAM |
| Swap | 4 GiB, unused at inspection | Swap is not a substitute for a viable inference memory budget |
| GPU | `nvidia-smi` outside the sandbox: NVIDIA GeForce RTX 5080, driver 610.88 | GPU is accessible outside this sandbox; the app no longer requires it |
| GPU memory | 16,303 MiB total. Used before any Wispr model: 7.7–13.2 GB across checks on 2026-09-24. LM Studio (Llama 3.1 8B + Cognee's embedding model) holds about 7.5 GB | These observations are historical; the app no longer loads Voxtral or requires GPU memory |
| WSL filesystem | `df -h /home/injun`: 1,007 GiB capacity, 946 GiB available in the mounted filesystem | Virtual filesystem space does not establish free space on the Windows backing volume; check both before large downloads |
| Node | `node --version`: v22.22.1 | Existing `node:test` supports the pipeline's web tests without adding npm test packages |
| Tools (rechecked 2026-09-24) | `gh` 2.101.0 at `~/.local/bin/gh`; `uv` at `~/.local/bin/uv` (WSL). Windows: standalone `%USERPROFILE%\.local\bin\uv.exe` 0.12.19 (checked 2026-09-24). Another app's `hermes\bin\uv.exe` (0.12.17) comes first on the user PATH, so call the standalone `uv.exe` by full path. Windows Python 3.12 present | Pin both sides to uv 0.12.19 |

The sandboxed GPU query failed with `GPU access blocked by the operating system`; the approved read-only query outside the sandbox succeeded. Treat such a failure as an execution-context limitation, not evidence that the machine lacks a GPU. Use the client's normal permission flow when required; never bypass it.

## Resource scheduling rules

These are conservative starting policies for this agent pack, not measured maximum capacity or changes to global settings.

- Run at most two feature work orders actively at first, plus the M-track (M1 runs alongside them and does not count toward the two). RED → GREEN → verification is sequential within a feature. The app uses cloud STT and does not require GPU capacity; local GPU budgeting applies only to unrelated model evaluation jobs.
- Allow one resource-heavy local job at a time: model acquisition/loading, inference evaluation, large native build, or packaged runtime exercise. Do not load models for this app; never start a second LM Studio or LLM server.
- Default to serial pytest execution and bounded fixtures; do not add `pytest-xdist` or another scheduler solely to use the CPU count. Where an existing tool supports a worker limit, start at no more than two workers.
- Before heavy work, record available RAM, swap usage, free VRAM, disk/cache location, and existing server processes. Defer new heavy jobs if available WSL RAM is below 4 GiB or sustained swap pressure appears. This 4 GiB reserve is a proposed operating guard, not an inference fit calculation.
- **Sol boundary is the single GPU owner for GPU evaluation jobs.** It runs those jobs; other roles request runs through the coordinator. It never loads, unloads or reconfigures LM Studio models without approval (Cognee depends on them). Account for weights, runtime overhead, context/KV caches and other GPU users. Do not assume a download size equals runtime VRAM use.
- Stop the job you launched on OOM, repeated allocation failure, or unacceptable desktop disruption; retain sanitized evidence. Do not terminate other users' processes or change drivers, WSL memory limits, swap, power settings, or global tools to force success.
- If unrelated concurrent model serving fails, return measured quantization/context/offload/sequential-loading options to the coordinator. No performance target is considered satisfied until measured.
- Keep Windows and WSL Python environments separate. G1 is decided: one WSL checkout, with the Windows venv on the Windows disk (`UV_PROJECT_ENVIRONMENT=%LOCALAPPDATA%\wispr_clone\venv`) and the WSL venv inside the checkout. Python 3.12 remains the proposal; the installed interpreter and native dependency compatibility are checked in Phase −1.1. Never share a Linux venv with Windows.

## What each environment can prove

| Environment | Suitable evidence | Still not proven |
|---|---|---|
| WSL, no models | Pure logic, fake adapters, SQLite recovery, JS tests, static checks | Windows focus/hotkeys/clipboard/mic and real inference |
| Hosted Windows CI | Supported native imports, input builders, packaging smoke, noninteractive platform checks | Real user's desktop focus, insertion, mic unplug, Win+V/cloud-sync behavior |
| WSL Python environment | Cloud STT client behavior with fakes, cleanup integration, loopback checks, static checks | Real provider behavior and interactive behavior unless separately exercised with the remote service and on the real desktop |
| User's Windows desktop | G3/G4 and H-tier focus, destination, clipboard privacy, microphone checks | Untested applications or privilege contexts |

Required evidence still missing: total host RAM/backing-volume space, desktop runtime configuration, STT latency while LM Studio is generating, and real-microphone accuracy. Do not turn these unknowns into invented hardware guarantees.
