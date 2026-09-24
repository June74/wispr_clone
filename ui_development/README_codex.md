# Wispr desktop UI · Codex concept

A self-contained, interactive desktop design demo. All authored demo files are in this folder and use `_codex` names; `.gitignore` is the conventional exception for excluding local test tools. Other demos and existing files are independent.

**Waveform design alternatives:** the separate [10-option study](WAVEFORMS_codex.md) shows still defaults and input-reactive animations in the current recorder component. Start it with `node waveform_server_codex.mjs` and open http://127.0.0.1:8766/waveforms_codex.html. The main demo remains unchanged until a waveform is selected for integration.

**Quiet Pillars animation refinement:** [five motion samples](PILLARS_codex.md) preserve the chosen default pillars and compare volume/frequency-driven animations. Open http://127.0.0.1:8767/pillars_codex.html after starting `WISPR_WAVEFORM_PORT=8767 node waveform_server_codex.mjs`.

## Open the demo

Open `index_codex.html` directly in a desktop browser, or use the local preview server for clipboard support:

```bash
cd /home/injun/projects/wispr_clone/ui_development
node server_codex.mjs
```

Visit **http://127.0.0.1:8765/index_codex.html**. The server binds only to localhost and serves an explicit list of demo assets. Set `WISPR_DEMO_PORT` if port 8765 is already occupied.

No build, account, API key, or runtime package installation is needed. The font is bundled, so the interface also works offline.

## A five-minute review

1. **Workspace:** click Start dictation, then Finish dictation. Review the waveform, loading state, and completed sample. Switch between Original and Polished, then copy text.
2. **Settings:** opens the dedicated left column. Explore Recording, Models, Text cleanup, Appearance, and Privacy & history. Test a simulated microphone/model and try both recording modes.
3. **Dictionary:** add/edit/remove a word, search, and export JSON. Import accepts an array such as `[{"word":"PostgreSQL","sounds":"post gres Q L"}]`; duplicate spellings are skipped.
4. **History:** search a phrase, open a transcript, inspect the original, copy, or delete it.
5. **Preview states** in the bottom bar: inspect ready, recording, processing, warning, unavailable, empty, and disabled feedback. Hover controls and navigate with Tab to see their interaction states.
6. Switch **Light / Dark** in the top bar. Try Reduce motion under Appearance. Privacy & history → Restore samples resets the example history and dictionary after testing.

Default shortcut: `Ctrl + Shift + Space`. Escape cancels a recording or closes a dialog. `Ctrl + ,` opens settings. Shortcuts apply only while this browser tab is focused; a desktop environment may reserve the same combination. Click controls remain available.

## Floating dictation HUD

Click **Preview HUD** in the footer, **Start dictation**, or use the recording shortcut. A small companion appears at the bottom center, above the status bar. It remains visible while you navigate within the demo.

- Listening: plum waveform, synchronized timer, **Finish** and **Cancel**.
- Processing: spinner, disabled Working button, and cancellation.
- Complete: green check, **Copy**, and **Close**. It dismisses after five seconds.
- Warning/error: amber or red icon, readable explanation, and **Try again**. Use Preview states to inspect these examples.

The HUD follows the selected theme and reduced-motion preference. Its waveform is simulated; it does not measure real audio. It is a browser overlay, not an operating-system always-on-top window. Native integration is needed to display it above other desktop applications.

HUD screenshots: [light](review_codex/hud_light_codex.png), [dark](review_codex/hud_dark_codex.png), and [inside the workspace](review_codex/hud_workspace_codex.png). Run `node verify_hud_codex.mjs` with the preview server running for the focused HUD checks.

`review_codex/hud_results_codex.json` records eight passing HUD check groups: theme/timer synchronization, navigation and completion controls, cancellation, shortcuts, warning/error recovery, reduced motion/positioning, automatic dismissal with focus restoration, and browser errors.

## What is real and what is simulated

Navigation, theme changes, preferences, dictionary CRUD/import/export, filtering, copying, confirmation dialogs, and browser storage work. Data uses the `wispr_codex_` localStorage prefix and stays local to this browser origin.

Recording, microphone levels, model tests, and transcription/cleanup are **simulated**. Every completed recording uses a fixed sample transcript. No microphone access, model downloads, backend calls, system-wide hotkeys, or insertion into other applications is implemented. Cleanup instructions are stored but do not affect the fixed sample output. Local/cloud model mode is a preference preview, not an implemented connection.

Desktop only. Reviewed at 1024–1920 px widths; the UI keeps desktop navigation rather than introducing a mobile layout. Pages scroll inside the app frame so navigation and the status bar stay visible. Browser storage or clipboard restrictions may limit persistence/copying; the app shows a session-only notice or manual-copy dialog in those cases.

## Files

| File | Responsibility |
| --- | --- |
| `index_codex.html` | Document, asset links, dialog and notification roots |
| `styles_codex.css` | Themes, typography, layout, components, motion, and interaction states |
| `app_codex.js` | Screens, sample data, local preferences, and interactive demo behavior |
| `server_codex.mjs` | Optional Node.js localhost preview server |
| `assets_codex/geist_codex.ttf` | Bundled Geist variable font |
| `assets_codex/OFL_codex.txt` | Font license |
| `DESIGN_codex.md` | Design rationale, tokens, hierarchy, and references |
| `verify_codex.mjs` | Browser interaction checks and screenshot capture |
| `review_codex/` | Review screenshots and actual verification results |

## Review images

- [Light workspace](review_codex/workspace_light_codex.png)
- [Dark workspace](review_codex/workspace_dark_codex.png)
- [Recording settings](review_codex/settings_light_codex.png)
- [Dark appearance settings](review_codex/settings_dark_codex.png)
- [Dictionary](review_codex/dictionary_codex.png)
- [Recording](review_codex/recording_codex.png), [processing](review_codex/processing_codex.png), [warning](review_codex/warning_codex.png), and [error](review_codex/error_codex.png)
- [Compact desktop](review_codex/compact_desktop_codex.png)

## Verification

`review_codex/results_codex.json` records 19 passing check groups in Chromium 145.0.7632.6, including actual interaction flows, local persistence, focus containment/restoration in dialogs, clipboard, import validation, retention controls, reduced motion, layout widths, and sampled token contrast. No JavaScript console/page errors or failed HTTP assets were observed. Screenshots were inspected visually. This is not a full accessibility audit or cross-browser certification.

The optional test runner uses **Playwright 1.58.2**, pinned locally under `.tools_codex/`; it is not shipped by the preview server or required by the UI. It supplies an automated browser rather than adding a framework to the application. There is no hosted service or API charge. Removing `.tools_codex/` removes the ability to rerun tests until reinstalled, but does not affect the demo. No application package manifest or lockfile was added.

With the already prepared local test tools and preview server running:

```bash
node verify_codex.mjs
```

To prepare test tools on another machine:

```bash
npm install --prefix .tools_codex --cache .tools_codex/npm-cache --no-save --package-lock=false playwright@1.58.2
PLAYWRIGHT_BROWSERS_PATH="$PWD/.tools_codex/browsers" node .tools_codex/node_modules/playwright/cli.js install chromium
```

This environment reports Ubuntu 26.04, which the pinned runner does not list. Verification used its Ubuntu 24.04 browser build (`PLAYWRIGHT_HOST_PLATFORM_OVERRIDE=ubuntu24.04-x64`) with `libnspr4`, `libnss3`, and `libasound2t64` downloaded and extracted into `.tools_codex/libs/`. No system packages were installed. The test runner sets the local browser/library paths; a normal supported desktop may not need those extracted libraries. Restricted environments may require permission to launch a browser or bind localhost.
