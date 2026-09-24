# Backend agent profiles

Status: instruction files only, created 2026-09-24. These do not register agents, configure a client, start workers, install dependencies, or implement the backend. Set the requested model in the client when creating each agent; a Markdown model label does not enforce routing.

Programming uses **GPT-6 Luna**. Test creation uses **GPT-6 Sol**, including tests of integration code and the test infrastructure itself. These are the user's requested model names, not assertions about API model identifiers or account availability.

## Create the agents

For each agent, supply [COMMON.md](COMMON.md), [HARDWARE.md](HARDWARE.md), its role file, and a filled [WORK_ORDER.md](WORK_ORDER.md). Give it repository read access and write access only to the work order's paths. If the client cannot follow local links, include those files' contents in its instructions. The seven profiles are reusable: assign one pipeline feature at a time, rather than creating a permanent agent for every module.

| Profile | Requested model | Responsibility |
|---|---|---|
| [Luna core programmer](luna-core-programmer.md) | GPT-6 Luna | Storage, settings, dictionary, history |
| [Luna adapter programmer](luna-adapter-programmer.md) | GPT-6 Luna | Hotkeys, audio, STT, cleanup, Windows insertion adapters |
| [Luna runtime programmer](luna-runtime-programmer.md) | GPT-6 Luna | Runtime web UI, native host, WSL server scripts |
| [Luna integration programmer](luna-integration-programmer.md) | GPT-6 Luna | Foundation and main-agent production-code stages P0/M1–M6 |
| [Sol feature test author](sol-feature-test-author.md) | GPT-6 Sol | Feature unit tests and deterministic component tests |
| [Sol boundary test author](sol-boundary-test-author.md) | GPT-6 Sol | Dependency probes, adapter conformance, real-model evaluations, desktop checklists |
| [Sol integration test author](sol-integration-test-author.md) | GPT-6 Sol | Cross-module tests, crash/restart, shared fakes, attribution framework and its tests |

The existing main/coordinating agent retains scheduling, architecture decisions, work-order allocation, review, and the authorized merge policy. It delegates production coding to Luna and test creation to Sol. The integration programmer is the programming role for the pipeline's main-agent track; it does not independently acquire merge or release authority. No additional coordinator model is selected here.

## Alignment with Claude's pipeline

These profiles implement the role split for [dev_pipeline.md](../dev_pipeline.md), read from the shared filesystem after it appeared during this task. The other conversation's unsaved messages were not directly accessible. Current repository documents take precedence over recalled older plans.

All paths below are relative to `backend_dev/`, except repository-root `.github/`. The pipeline's branch path allocation is divided further: Luna owns production files; Sol owns tests and test support. The coordinator gives each file one writer at a time.

| Pipeline branch/stage | Programmer | Primary test author | Additional boundary coverage |
|---|---|---|---|
| P0.1–P0.6 foundation | Luna integration | Sol integration | Sol boundary for baseline probes |
| `feat/storage` | Luna core | Sol feature: T-STO-* | Sol boundary: P-SQLITE-* |
| `feat/hotkeys` | Luna adapter | Sol feature: T-KEY-* | Sol boundary: P-PYNPUT-* |
| `feat/audio` | Luna adapter | Sol feature: T-AUD-* | Sol boundary: P-NUMPY/P-SOXR/P-SD |
| `feat/dictionary-core` | Luna core | Sol feature: T-DIC-001..007 | — |
| `feat/cleanup` | Luna adapter | Sol feature: T-CLN-* | Sol boundary: HTTPX/Ollama, conformance, EVAL-G6 |
| `feat/stt` | Luna adapter | Sol feature: T-STT-001..006 | Sol boundary: WebSocket/vLLM, T-STT-A01 |
| `feat/insertion-win` | Luna adapter | Sol feature: T-INS-* | Sol boundary: P-WIN32-*, desktop evidence |
| `feat/settings-models` | Luna core | Sol feature: T-SET-001..004, T-REG-* | Sol boundary: P-PYD-* |
| `ops/model-servers` | Luna runtime | Sol feature: T-OPS-* | Sol boundary: GPU/network/vLLM/Ollama |
| `feat/settings-store` | Luna core | Sol feature: T-SET-010..012 | — |
| `feat/dictionary-repo` | Luna core | Sol feature: T-DIC-010..013 | — |
| `feat/history` | Luna core | Sol feature: T-HIS-* | Sol integration for shared restart harness |
| `feat/web-runtime` | Luna runtime | Sol feature: T-WEB-* | Sol boundary for desktop observations |
| `feat/ui-host` | Luna runtime | Sol feature: T-UI-* | Sol boundary: P-WEBVIEW-*, desktop observations |
| M1 state machine | Luna integration | Sol integration: T-SM-* | — |
| M2 insertion protocol | Luna integration | Sol integration: T-PRO-* | Sol boundary for real desktop limits |
| M3a–M3f controller | Luna integration | Sol integration: T-RUN-* | — |
| M4 application commands | Luna integration | Sol integration: T-APP-001..007 | — |
| M5 composition | Luna integration | Sol integration: T-APP-010..013 | Sol boundary for Windows launch |
| M6 packaging/end-to-end | Luna integration | Sol integration: E2E-* | Sol boundary: P-PYI-*, GPU/EVAL-G6/H-01..06 |

This table references planned IDs; it does not assert that tests exist. Read their full assertions in pipeline §§6 and 8 rather than inferring requirements from the prefixes.

## Dispatch and handoff

1. The coordinator resolves the stage's prerequisites and gives Sol a bounded work order with behavior, interfaces, test IDs, and paths.
2. Sol creates meaningful tests and records the expected failing run (RED). Missing tools, broken collection, or unavailable hardware are setup blockers, not behavioral RED evidence.
3. Hand the same reviewed test revision to Luna. Luna implements production code and runs those tests without weakening them (GREEN), then refactors within scope.
4. Sol checks the resulting behavior and adds any necessary regression cases. The coordinator reviews the combined diff and merges only under the user's existing authorization.

Use separate worktrees for simultaneous agents. Transfer the Sol test commit to the Luna branch and the implementation back for validation when commits are authorized. Otherwise the coordinator applies a reviewed patch with a content hash. Never use two simultaneous writers in one checkout, and never mark a feature ready to merge while its contract-request xfails remain unresolved.

The pipeline's 4–5-agent advice describes logical parallelism. This pack starts conservatively with at most **two active feature work orders**, at most **one resource-heavy local job**, and serial GPU experiments; see [HARDWARE.md](HARDWARE.md). Increase parallelism only after measuring headroom. Profiles can be reused sequentially and do not imply seven simultaneous sessions.

Before implementation, resolve the prerequisites already listed in pipeline §9, respecting any authorization already given. In particular, ensure the untracked planning files are available in each worktree. These role documents alone authorize no commits, installs, model downloads, pushes, runner registration, or releases.
