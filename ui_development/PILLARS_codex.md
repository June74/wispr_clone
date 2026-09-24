# Quiet Pillars · five motion samples

All five preserve the exact original Quiet Pillars default: **29 rounded pillars, 3 px stroke, 9 px spacing, 2 px resting height**, centered in the existing waveform area, with the same plum color and opacity taper. Browser pixel comparisons verify the resting image against option 01 in the original ten-option study.

The existing application and HUD are unchanged. These are review alternatives, not a committed replacement.

## Open

```bash
cd /home/injun/projects/wispr_clone/ui_development
WISPR_WAVEFORM_PORT=8767 node waveform_server_codex.mjs
```

Visit **http://127.0.0.1:8767/pillars_codex.html**. Use **Waveform overview** to compare all five, or the full component view for the original card context. Both themes use the existing CSS tokens.

| Sample | Motion | Frequency differentiation |
| --- | --- | --- |
| 01 — Thread envelope | Pillars grow into a changing waveform envelope around a fixed centerline | Audio sample detail supplies most of the contour; frequency bands add per-pillar emphasis |
| 02 — Floating thread | Pillars grow and move slightly above/below center, drawing a Fine Thread-like path | Each pillar’s height also responds to its frequency band |
| 03 — Frequency lanes | Peaks move between low-frequency columns on the left and high-frequency columns on the right | Direct logarithmic frequency mapping, with a small waveform contribution |
| 04 — Mirrored voice | A symmetric waveform expands on either side of the midpoint | Lower frequencies in the middle, higher frequencies toward the outside |
| 05 — Woven contour | Broad peaks move with a softer, more continuous release | Neighbor-averaged spectrum mixed with finer waveform lobes |

**02** is the closest visual match to the rise-and-fall of Fine Thread. **01** retains the most stable pillar alignment. **03** makes the low/high-frequency relationship clearest. These are design judgments.

## Compare the two requested behaviors

The **Sample input** menu offers four deterministic synthetic tests, with no sound playback:

- **Natural phrasing:** syllables, frequency changes, and pauses.
- **Quiet → loud:** the same waveform and frequency distribution at four increasing levels. Compare size without changing tone.
- **Low → high frequencies:** a fixed input level with the fundamental and harmonics shifting upward. Compare which pillars are emphasized without changing loudness.
- **Silence:** every option returns to the identical Quiet Pillars default.

Use **Use microphone** for actual input. One `AnalyserNode` supplies all five variants with the same RMS level, 32 frequency bands, and waveform samples. Live motion has no decorative sine-wave clock: only the explicitly labeled synthetic preview generates a signal. Stop input / Escape releases microphone tracks. Audio is not played back, saved, uploaded, or transcribed.

This is a volume/spectrum/waveform visualizer, not a musical note recognizer or a speech-only detector. Background sound can also produce movement. Mic sensitivity adjusts gain and the quiet threshold.

## Motion specifics

- All variants scale pillar height monotonically with input level for the same sound profile.
- Pillar positions on the horizontal axis, widths, opacity, and colors stay fixed.
- 02 allows up to 10 px vertical displacement; 05 uses up to 3 px. Other samples keep a fixed centerline.
- Microphone input retains the existing overall 45 ms attack / 150 ms release envelope.
- Per-pillar targets add roughly 45 ms attack / 110 ms release. 05 uses a softer 90 ms / 200 ms response.
- On silence, the input envelope settles and all five return to the exact baseline. Nothing cycles independently at rest.
- Reduced motion uses stepped updates and skips per-pillar interpolation.
- The original component's copy, controls, dimensions, spacing, and palette remain unchanged. Review labels and sample controls live outside it.

## Files and review artifacts

- `pillars_codex.html`: five-option review page.
- `pillars_codex.js`: five motion profiles and controlled sample signals.
- `pillars_codex.css`: comparison-page controls/overview formatting only.
- `waveforms_codex.js`: existing shared microphone and comparison engine, now with an optional extension hook. The original ten designs use their original path.
- [Light comparison](review_codex/pillars_light_codex.png), [dark comparison](review_codex/pillars_dark_codex.png), [full component](review_codex/pillars_component_codex.png).
- [Animation video](review_codex/pillars_animation_codex.webm): approximately 37 seconds, covering phrasing, quiet-to-loud, and low-to-high-frequency examples.
- `verify_pillars_codex.mjs` / `review_codex/pillars_results_codex.json`: verification of default pixel identity, volume response, frequency differentiation, fixed spacing, animation, quiet settling, real analyser path using a synthetic Chromium microphone fixture, reduced motion, layout, and export.

Run `node verify_pillars_codex.mjs` with the server and the existing local browser tools available. It creates its own synthetic audio fixture under `.tools_codex/`. Physical microphone behavior is available for review but was not physically tested here. The original ten-option browser suite also checks backward compatibility of the shared engine.
