# Ten waveform directions

This is a separate comparison study based on the latest Codex recorder component in `app_codex.js` and `styles_codex.css`, including its current plum palette, typography, copy, spacing, shadows, and controls. The existing application and HUD have not been replaced. Full component view changes only the waveform contents; surrounding comparison labels are outside the component. Card copy stays fixed so its changes do not distract from comparing waveforms.

## Open

```bash
cd /home/injun/projects/wispr_clone/ui_development
node waveform_server_codex.mjs
```

Visit **http://127.0.0.1:8766/waveforms_codex.html**. No runtime package installation is needed. The server is limited to this study's public files and localhost. The HTML can also be opened directly, but localhost is the preferred origin for browser microphone permissions.

Each option shows the **default, always-still state on the left**, and **the input-reactive version on the right**. Start in the original component context or use **Waveform overview** to see all ten together. Light/dark controls reuse the existing palette.

## Designs

| # | Design | Default | While speaking |
| --- | --- | --- | --- |
| 01 | Quiet pillars | Fine rounded ticks | Slender bars expand with input and spectral energy |
| 02 | Soft ribbon | A thin tapered spindle | One filled, symmetric waveform envelope opens and closes |
| 03 | Fine thread | A fine line with a small central notch | A trace derived from microphone time-domain samples |
| 04 | Twin contours | Two almost-flat contours | Mirrored outlines spread around the center |
| 05 | Dot field | A faint dot grid and central row | Dots brighten outward according to spectral energy |
| 06 | Segmented meter | A short row of rectangular ticks | Segmented stacks appear above and below the baseline |
| 07 | Five capsules | Five short rounded pills | Five broad voice-frequency groups change their heights |
| 08 | Voice bloom | A stationary circular tick mark | Radial strokes expand with spectral energy, without rotation |
| 09 | Resonance rings | Three small nested ellipses | Frequency groups reshape the rings, without timed ripples |
| 10 | Phrase trail | A dotted line with an endpoint | A short input-level history forms a phrase, then clears in silence |

01 is the closest evolution of the current bars. 07 makes the most compact mark. 03 puts the most emphasis on an actual audio trace. These are design judgments, not measured preferences.

## Input modes

**Sample preview:** a silent, synthetic input envelope runs on a 12-second cycle, containing several phrases and genuine zero-input gaps. It is explicitly labeled. It is not a recording, generated speech, or a response to the room. All ten designs receive the same input at the same time. Playback starts automatically unless the system requests reduced motion.

**Use microphone:** asks for browser permission and connects one microphone stream to a Web Audio `AnalyserNode`. Its output is not connected to speakers. No `MediaRecorder`, transcription service, upload, or storage is used. Click Stop input or press Escape to stop its tracks. Changing to the sample, leaving the page, or hiding the tab also releases microphone access. If permission is declined, a sample fallback remains available.

The unchanged Start dictation buttons also start microphone analysis in this study; they do not transcribe. `Ctrl + Shift + Space` toggles microphone input while the page is focused.

**Mic sensitivity:** adjusts gain and the quiet-input threshold. This visualizer reacts to sound, not recognized words: background noise can also move it. It is not a speech/non-speech classifier.

## Motion implementation

- One shared input signal drives all alternatives for fair comparison.
- RMS audio level drives the overall size; 32 logarithmic bands between roughly 80 Hz and 6 kHz provide frequency detail.
- About 45 ms attack and 150 ms release smooth syllables without a constant autonomous wave.
- Below-threshold input decays to a true static resting shape. A short release tail is intentional.
- Dot/segment opacity interpolates for quiet signals rather than waiting for a full extra row to switch on.
- Drawings use the existing `--primary` token and its opacity variations; no new color palette is introduced.
- The waveform occupies the existing 72 px-high slot. Canvas coordinates are 340 × 72, with a 2× backing store.
- Reduced motion uses stepped updates at four frames per second and a stable trace shape scaled by input, rather than a flowing trace.
- Only visible reactive canvases redraw; inactive/default views stay still. The phrase history is shared and limited to 40 levels.

API references: [MDN AnalyserNode](https://developer.mozilla.org/en-US/docs/Web/API/AnalyserNode) and [time-domain samples](https://developer.mozilla.org/en-US/docs/Web/API/AnalyserNode/getFloatTimeDomainData). These document the browser primitives used; the visual designs and signal processing choices above are specific to this prototype.

## Deliverables

- `waveforms_codex.html`, `waveforms_codex.css`, `waveforms_codex.js`: interactive comparison.
- `waveform_server_codex.mjs`: optional localhost server on port 8766.
- [Full component comparison](review_codex/waveforms_component_codex.png).
- [Light overview](review_codex/waveforms_overview_light_codex.png) and [dark overview](review_codex/waveforms_overview_dark_codex.png). Each pairs a still default with a frozen active sample frame.
- [Animation video](review_codex/waveforms_animation_codex.webm): silent overview with a complete synthetic phrase/pause cycle. The interactive page is the source for live microphone behavior.
- `verify_waveforms_codex.mjs` and `review_codex/waveforms_results_codex.json`: reproducible browser verification and actual results.

Verification uses the already installed local Playwright setup. It checks distinct resting designs, stationary defaults, input changes, quiet-input settling, matching component geometry, layout, theme captures, the real microphone-analysis code using a synthetic Chromium capture fixture, permission failure, and cancellation of a delayed permission response. This does not substitute for listening on the user's physical microphone or testing every browser.
