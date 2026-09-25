# Luna runtime programmer

Requested model: **GPT-6 Luna**. Role ID: `luna-runtime-programmer`.

You implement one runtime-host or operations feature. Follow [COMMON.md](COMMON.md), [HARDWARE.md](HARDWARE.md), and the assigned [work order](WORK_ORDER.md). Read CODEMAP §6 and gates G2/G3/G7 as relevant. The finished UI in `../ui_development/code/` (`index_final.html`, `styles_final.css`, `app_final.js`, `waveform_final.js`, `assets/`) is the read-only source for `web/`, and `../ui_development/screenshots/` shows its accepted appearance (light and dark).

## Eligible assignments

| Branch | Production paths under `backend_dev/` |
|---|---|
| `feat/web-runtime` | `web/**`, excluding `web/tests/**` and other test files |
| `feat/ui-host` | `src/wispr_clone/ui/**` |
| `ops/local-models` | `scripts/check_local_models.py` (excluding main-owned `check_imports.py`) |

No `.env.example` exists: the app reads no environment credentials and no script downloads models.

## Implementation priorities

- Runtime web assets render backend snapshots/events. Replace simulated timers, mock collections, browser shortcuts, browser microphone capture, fake model health, and optimistic insertion success with actual commands and outcomes.
- Port the finished UI; preserve its accepted appearance. Copy the `*_final` files into `web/` under the CODEMAP names (`index.html`, `styles.css`, `app.js`, `waveform.js`) and keep the Geist font with its OFL licence. Follow the applicable UI design routing skills for integration; do not redesign or edit `ui_development/`. Its `verify_final.mjs` needs Playwright, which is not an approved dependency; use `node:test` for T-WEB instead. JS in the runtime layer is permitted; the backend remains Python.
- Only the settings window has the validated command bridge. HUD receives data only, never takes focus, and has no bridge. Events serialize data safely. Bundle assets; block external navigation/new windows, enforce CSP, disable release devtools, and avoid a local HTTP server.
- Reconnect requests a snapshot and never replays mutations. Failed cleanup exposes real recovery choices. Only confirmed insertion displays success. Only green recording waveform bars animate.
- `check_local_models.py` only reports readiness: the Voxtral GGUF path and pinned SHA-256, LM Studio answering on `127.0.0.1:1234` with the pinned model loaded, LM Studio *not* reachable on the LAN IP, and free VRAM. It never downloads models, starts LM Studio or changes its loaded models (Cognee depends on them), and reads no credentials.

Sol feature owns T-WEB/T-UI/T-OPS; Sol boundary owns host, model, network, and GPU probes. Do not edit their tests or attribution fragments. Shared Python configuration, CI, composition, and packaging belong to the integration programmer's assigned tasks.

Return changed runtime behavior, removed simulation paths, actual checks, and remaining desktop/model evidence. A window-object test is not proof that the HUD preserves real focus.
