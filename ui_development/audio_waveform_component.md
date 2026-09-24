# Audio waveform component

**Selected by the user: Frequency Lanes animation, with the Quiet Pillars still/default design.**

This is the approved design direction for the audio waveform component. The selected animation is **sample 03, Frequency lanes**, from the five Quiet Pillars motion samples (`frequency-lanes` in `pillars_codex.js`). It is not sample 03, Fine Thread, from the earlier ten-design study.

This file records the selection, visual specification, and animation behavior. The working implementation remains in the linked prototype source; selecting this design does not by itself integrate it into the main application or HUD.

## Design

Keep the existing component’s colors, layout, typography, text, controls, spacing, and shadows. Change only the waveform behavior.

| Property | Selected specification |
| --- | --- |
| Default appearance | Quiet Pillars: a completely still row of small rounded vertical marks |
| Pillar count | 29 |
| Pillar stroke | 3 px, round caps |
| Horizontal spacing | 9 px center-to-center |
| Resting height | 2 px between stroke endpoints; rounded caps extend the visible silhouette |
| Drawing area | 340 × 72 logical pixels; current canvas backing store is 680 × 144 |
| Pillar positions | `x = 44 + 9 × index`, for indices 0–28 |
| Vertical center | Fixed at `y = 36`; pillars expand equally upward and downward |
| Opacity | `0.30 + 0.55 × sin(π × index / 28)`; subtle ends, stronger center |
| Edge treatment | Existing horizontal gradient mask: transparent edges, opaque between 16% and 84% |
| Light-mode pillar color | Existing `--primary`: `#745689` |
| Dark-mode pillar color | Existing `--primary`: `#B796CE` |
| Recording surface | Existing `--hero`: light `#F2EDF5`, dark `#2C2433` |
| Surface glow | Existing `--hero-glow`: light `#E6D9ED`, dark `#463250` |

Horizontal positions, widths, opacity, and colors remain constant as the user speaks. The selected Frequency Lanes animation changes pillar **height**, not position.

## Animation

1. **Loudness controls size.** Louder input makes the pillars taller for the same sound profile.
2. **Frequency content selects pillars.** Lower frequencies emphasize pillars toward the left; higher frequencies emphasize pillars toward the right. Different pillars fluctuate independently rather than expanding as one block.
3. **Waveform detail adds movement.** A small contribution from the actual audio waveform adds the fluctuation inspired by Fine Thread, while preserving the pillar shape.
4. **Silence returns to Quiet Pillars.** The response settles gently, then returns to the exact still/default appearance. There is no idle breathing, perpetual flow, or clock-driven wave in microphone mode.
5. **Keep the response readable.** Use a quick attack and softer release so syllables register without abrupt flicker.

This is a sound-level and frequency visualization, not musical note recognition or speech-only detection. Background sounds can also activate it.

## Input and motion parameters

| Parameter | Current selected implementation |
| --- | --- |
| Audio source | One microphone stream feeding a Web Audio `AnalyserNode` |
| Analysis window | FFT size 2048 |
| Frequency analysis | 32 logarithmic bands across approximately 80 Hz–6 kHz |
| Overall level | RMS input magnitude, normalized to 0–1 after threshold/gain |
| Mic sensitivity | Default 1.5×; adjustable between 0.5× and 3× |
| Quiet threshold | `0.012 / sensitivity` in the current normalized input scale |
| Normalized target level | `clamp((RMS − threshold) × sensitivity × 7, 0, 1)`; zero below threshold |
| Overall level smoothing | 45 ms attack / 150 ms release time constants |
| Spectrum smoothing | Analyser smoothing 0.55, followed by approximately 70 ms band smoothing |
| Per-pillar smoothing | 45 ms attack / 110 ms release time constants |
| Draw cadence | Approximately 30 fps for visible reactive previews |
| Reduced motion | Stepped updates at approximately 4 fps; no per-pillar interpolation; stable trace shape scaled by input |

Time constants describe exponential smoothing, not a guarantee that settling finishes within that exact duration. When the target input is zero and the smoothed level falls below `0.008`, the current implementation snaps to the exact resting state.

The spectrum is mapped onto the 29 pillar positions. Neighbor-weighted interpolation prevents abrupt differences between adjacent bands. Absolute, locally averaged waveform samples supply the smaller fluctuation term.

## Selected geometry and animation formula

The following is the selected branch from the prototype, expressed independently of the other four alternatives. `level` is the smoothed 0–1 audio level; `bands` contains 32 normalized frequency values; `wave` contains 128 normalized signed audio samples.

```js
function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function interpolate(values, position) {
  const at = clamp(position, 0, values.length - 1);
  const low = Math.floor(at);
  const high = Math.min(values.length - 1, low + 1);
  return values[low] + (values[high] - values[low]) * (at - low);
}

function smoothSample(values, position, radius) {
  let sum = 0;
  let weights = 0;
  for (let offset = -radius; offset <= radius; offset++) {
    const weight = radius + 1 - Math.abs(offset);
    sum += interpolate(values, position + offset) * weight;
    weights += weight;
  }
  return sum / weights;
}

function frequencyLanesTargets({ level, bands, wave }) {
  return Array.from({ length: 29 }, (_, index) => {
    const position = index / 28;
    const band = smoothSample(bands, position * 31, 1);
    const waveform = Math.abs(smoothSample(wave, position * 127, 2));

    return {
      x: 44 + index * 9,
      center: 36,
      width: 3,
      opacity: 0.30 + 0.55 * Math.sin(Math.PI * position),
      height: 2 + 57 * clamp(level, 0, 1)
        * (0.025 + 0.84 * band + 0.135 * waveform),
    };
  });
}

function smoothPillarHeight(current, target, deltaSeconds) {
  const timeConstant = target > current ? 0.045 : 0.110;
  const amount = 1 - Math.exp(-deltaSeconds / timeConstant);
  return current + (target - current) * amount;
}
```

Draw each pillar as a vertical round-capped stroke from `center − height / 2` to `center + height / 2`. Apply per-pillar smoothing during active input; apply the exact target immediately at rest or when reduced motion is enabled. The geometry formula is a reference, not a complete microphone lifecycle implementation.

## Working design and animation

- **[Open the selected Frequency Lanes component](http://127.0.0.1:8767/pillars_codex.html#frequency-lanes)**. Sample 03 shows the still default on the left and the animation on the right.
- **[Watch the animation comparison](review_codex/pillars_animation_codex.webm)**. Frequency Lanes is row 03. The video demonstrates natural phrasing, increasing loudness, and a low-to-high frequency sweep using synthetic input.
- [Light design sheet](review_codex/pillars_light_codex.png) and [dark design sheet](review_codex/pillars_dark_codex.png): row 03 is the selected component.
- [Selected geometry and rendering source](pillars_codex.js): `geometry()` → `frequency-lanes`, plus `draw()` for interpolation.
- [Microphone analysis and lifecycle](waveforms_codex.js): `microphoneFrame()`, `tick()`, `startMicrophone()`, and `releaseInput()`.
- [Existing colors and component styling](styles_codex.css).

Start the local preview if needed:

```bash
cd /home/injun/projects/wispr_clone/ui_development
WISPR_WAVEFORM_PORT=8767 node waveform_server_codex.mjs
```

Use **Use microphone** for live analysis. **Quiet → loud** isolates volume response; **Low → high frequencies** isolates frequency response; **Silence** verifies the resting state. The sample input is synthetic and explicitly labeled. Live microphone input is analyzed locally and is not stored, uploaded, or played through speakers. Stop input / Escape releases the microphone; the existing demo also releases it when the page is hidden or left.

## Acceptance criteria and existing evidence

- Resting pixels match the approved Quiet Pillars design.
- Raising loudness with the same sound profile increases pillar heights.
- Changing frequency distribution at the same level changes which pillars are emphasized.
- Pillar positions, widths, colors, opacity, and surrounding component layout remain unchanged.
- Quiet input settles to stillness; the microphone path contains no autonomous looping wave.
- Both themes and reduced motion are supported.

The [existing verification report](review_codex/pillars_results_codex.json) records the geometry, resting-pixel, animation, silence, and synthetic microphone-capture checks. Physical microphone performance has not been tested here. This selection record adds no new runtime behavior or production integration.
