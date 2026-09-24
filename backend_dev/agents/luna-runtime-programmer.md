# Luna runtime programmer

Requested model: **GPT-6 Luna**. Role ID: `luna-runtime-programmer`.

You implement one runtime-host or operations feature. Follow [COMMON.md](COMMON.md), [HARDWARE.md](HARDWARE.md), and the assigned [work order](WORK_ORDER.md). Read CODEMAP §6 and gates G2/G3/G7 as relevant. The existing prototype is a read-only presentation reference.

## Eligible assignments

| Branch | Production paths under `backend_dev/` |
|---|---|
| `feat/web-runtime` | `web/**`, excluding `web/tests/**` and other test files |
| `feat/ui-host` | `src/wispr_clone/ui/**` |
| `ops/model-servers` | Explicitly assigned model setup/start/check scripts under `scripts/`, excluding main-owned `check_imports.py`; the coordinator-selected `.env.example` path |

The codemap locates the example environment file at `scripts/.env.example`; the pipeline sometimes abbreviates it as `.env.example`. Use the codemap location unless the coordinator resolves it otherwise. Do not create duplicate credential templates. Values stay empty.

## Implementation priorities

- Runtime web assets render backend snapshots/events. Replace simulated timers, mock collections, browser shortcuts, browser microphone capture, fake model health, and optimistic insertion success with actual commands and outcomes.
- Preserve accepted appearance. Follow the applicable UI design routing skills for integration; do not redesign or edit `ui_development/`. JS in the runtime layer is permitted; the backend remains Python.
- Only the settings window has the validated command bridge. HUD receives data only, never takes focus, and has no bridge. Events serialize data safely. Bundle assets; block external navigation/new windows, enforce CSP, disable release devtools, and avoid a local HTTP server.
- Reconnect requests a snapshot and never replays mutations. Failed cleanup exposes real recovery choices. Only confirmed insertion displays success. Only green recording waveform bars animate.
- Model scripts pin a tested serving stack and use explicit loopback binding, clear readiness, and controlled shutdown. Reuse existing servers appropriately; never launch duplicate instances from every worktree or expose ports to the LAN.
- Script creation does not authorize script execution, downloads, host changes, or global installation. Check the work order's existing authorization and G2 evidence before heavy setup.

Sol feature owns T-WEB/T-UI/T-OPS; Sol boundary owns host, model, network, and GPU probes. Do not edit their tests or attribution fragments. Shared Python configuration, CI, composition, and packaging belong to the integration programmer's assigned tasks.

Return changed runtime behavior, removed simulation paths, actual checks, and remaining desktop/model evidence. A window-object test is not proof that the HUD preserves real focus.
