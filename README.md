# Wispr Clone

A personal, Wispr Flow–style voice dictation app for Windows. Press a shortcut, speak, and the
transcribed (and optionally cleaned-up) text is typed into the window you were in when you started
talking — even if you switched elsewhere while it was processing.

**Status: v0 complete.** Windows only; developed in WSL.

## What v0 does

- **Global shortcut dictation**: toggle (press to start, press to stop) or hold-to-talk. Default
  `Ctrl+Shift+Space`; `Esc` cancels, including during processing. Both can be rebound in the app.
- **Speech-to-text** with Whisper Large v3 Turbo through OpenRouter, pinned to the DeepInfra
  provider. Only speech segments are sent (silence is trimmed so Whisper doesn't invent phrases).
- **Optional cleanup** through a local model in [LM Studio](https://lmstudio.ai) on
  `127.0.0.1:1234`, or the NVIDIA hosted API using your own key. NVIDIA cleanup tries an editable
  ordered list, defaulting to DeepSeek V4.1 Flash → GLM 5.3 → Kimi K3. Rate limits and unavailable
  models advance to the next choice; account-wide credits cannot be replenished by switching models.
  Cleanup shares a 25-second total timeout across the remaining available models, with at most 10 seconds
  per attempt, so later fallbacks still get a chance.
  Nemotron 3.5 Lightning uses NVIDIA's [documented thinking-off setting](https://github.com/NVIDIA-AI-Blueprints/nemotron-voice-agent/blob/main/docs/how-to/configure-llm.md)
  for faster cleanup.
  If cleanup is unavailable or every NVIDIA model times out, the original transcript is
  inserted instead and the failure remains in History. Other cleanup failures offer
  Retry cleanup or Use original before insertion continues.
- **Destination-safe insertion**: the target window and text field are captured when recording
  starts. If you've moved away, the text is delivered when you return or after 1 s of keyboard/mouse
  idle (the app jumps back, inserts once, and returns you). It never presses Enter or runs commands.
  If Windows refuses the focus change, the app waits for you to return to the original text field.
  Copy and Cancel remain available while waiting.
- **Floating HUD** pill that never takes focus, shown while a dictation is active: a status dot
  (pulsing green while listening, yellow while working, red when something needs attention), a
  Listening/Working label, an m:ss timer and a ✕ that cancels like `Esc`.
- **Settings window**: microphone selection and test, model selection and health checks, cleanup
  instructions, personal dictionary (add/edit/import/export), temporary history, theme, sound cues,
  launch at login. Closing the window keeps the app running in the tray (Open/Quit).
- **Temporary history**: at most the 10 most recent runs, each deleted after 24 hours, with
  copy/retry/delete.

Audio leaves the device for transcription. When NVIDIA cleanup is selected, the transcript,
cleanup instructions and dictionary spellings are also sent to NVIDIA. Both API keys are stored
encrypted with Windows DPAPI; settings, dictionary and history live in `%LOCALAPPDATA%\WisprClone`.

## Repository layout

| Path | Contents |
|---|---|
| `backend_dev/src/wispr_clone/` | The Python application (audio, STT, cleanup, pipeline, insertion, hotkeys, storage, UI host) |
| `backend_dev/web/` | Settings window and HUD pages loaded by pywebview ([web/README.md](backend_dev/web/README.md)) |
| `backend_dev/tests/` | pytest suite (unit, integration, conformance, probe markers) |
| `backend_dev/packaging/` | Windows per-user installer |
| `backend_dev/scripts/` | Import-boundary check, local-model check, CI attribution report |
| `backend_dev/design/` | HUD geometry preview tool |
| `backend_dev/CODEMAP.md`, `CODEMAP_GRAPH.md`, `DEPENDENCIES.md` | Architecture and dependency plans written before implementation, with dated decision records (not a description of the current code) |
| `backend_dev/agents/`, `dev_pipeline.md` | Role specs and workflow used to build the backend |
| `research/` | Feature specification ([voice-dictation-features.md](research/voice-dictation-features.md)) and model notes |
| `ui_development/` | Original HTML/CSS/JS UI prototype and screenshots |

## Requirements

- Windows 10/11 for running the app
- Python 3.12 (the python.org build for installing) and [uv](https://docs.astral.sh/uv/)
- An OpenRouter API key
- Optional: LM Studio with a downloaded chat model (default `meta-llama-3.1-8b-instruct`; the app loads it), or an NVIDIA API key for hosted cleanup
- Node.js, only to run the web tests

## Install (Windows)

From `backend_dev` in a Windows checkout:

```powershell
py -3.12 packaging\install_windows.py
```

This creates a venv in `%LOCALAPPDATA%\wispr_clone\app` with the versions pinned in `uv.lock`, adds a
Start Menu shortcut, and leaves your existing settings and history untouched. Re-run it to update.
Then open **Wispr Clone**, paste your OpenRouter key under Models, and start dictating.

To run from source instead:

```powershell
uv sync --locked
uv run python -m wispr_clone            # --debug for verbose logs, --self-test for a quick check
```

## Development

Run from `backend_dev` (WSL or Windows). These mirror CI (`.github/workflows/ci.yml`):

```bash
uv sync --locked
uv run pytest -q -m "not probe and not gpu and not e2e and not manual"
uv run ruff check . && uv run ruff format --check .
uv run mypy src scripts tests/_attribution tests/fakes
uv run python scripts/check_imports.py      # enforces module dependency direction
node --test "web/tests/*.test.mjs"
```

Windows-only behavior (hotkeys, insertion, HUD, tray) is covered by fakes in the unit suite; real
desktop checks are marked `windows` (interactive ones also `manual`).

## Known limitations in v0

- Windows only; transcription requires the network (the local STT path was removed, so there is no
  fully offline mode).
- Local cleanup depends on LM Studio already running; the app doesn't start it (it only loads the
  selected cleanup model). NVIDIA cleanup depends on your key, the network and provider availability.
  Choose NVIDIA under Models, save its key, then save the fallback order. No additional packages are needed.
- A few settings from the prototype are shown but disabled: floating-indicator preference, history
  on/off and retention choice, and usage statistics.
- Not included: voice commands, spoken formatting, snippets, per-app styles, accounts or sync.
