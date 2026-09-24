# Wispr Clone — UI demo

A static, dependency-free prototype for design review. All data is mock data; nothing is
recorded, sent or stored (except your theme choice in `localStorage`).

**Open:** double-click `index.html` (or `file:///…/ui_development/demo/index.html`).
Designed for desktop windows ≥ 1100 × 700.

Deep links for review: `?page=home|general|recording|models|cleanup|dictionary|privacy|history`, `&theme=light|dark`.
The design-system sheet is review-only and has no nav entry: `?page=styleguide`.

## What changed in v2
- **Colour:** muted plum primary on warm neutral surfaces, adopted from Astra's concept (`../DESIGN_codex.md`).
- **Font:** Geist variable, copied from `../assets_codex/` into `assets/`, with its OFL licence.
- **Dictation card:** the gradient hero became a quiet plum "stage": waveform, caption, a primary *Start dictation* button and a shortcut hint.
- **Recording, Models and Text cleanup** were rebuilt to match the reference screenshots. The rail + settings-column layout is unchanged.

## Things to try

| Where | Interaction | What it shows |
|---|---|---|
| Dictate | **Start dictation**, or **Ctrl + Shift + Space** | idle → listening (red ping, live waveform, timer, floating pill) → *Polishing your words* (spinner, disabled button) → success toast + new item |
| Dictate | **Esc** or *Discard* while listening | Cancel path |
| Dictate | Start dictation and speak | **Frequency Lanes waveform** (spec: `../audio_waveform_component.md`): louder → taller pillars; low sounds lift the left, high sounds the right; silence settles to the still Quiet Pillars. Your browser asks for the microphone; if declined/unavailable it plays a labelled synthetic phrase ("simulated input") |
| Sidebar | Panel button / **Ctrl + B**; click empty strip space or logo | Collapses to icon strip with hover labels; reopens; persists |
| Sidebar | Quick search / **Ctrl + K** | Page switcher with keyboard navigation |
| Recording | Test microphone | Segmented level meter → "Sounds clear" (green); AirPods → "A little quiet" (yellow + shake) |
| Recording | Microphone → *No input detected*, then Start dictation | Card warning state (yellow) with a *Choose microphone* recovery button |
| Recording | Shortcut → *Alt + Space* | Yellow conflict warning + shake |
| Recording | *Hold to talk* | Card hint becomes "or hold …"; release the key to finish |
| Models | Cleanup → *Llama · 3.2 3B (Ollama)* → Test model | Blue *Loading/Testing* → red *Not reachable*, red dot on the Models nav item, error toast with Retry → green |
| Models | Keep processing local off | Cloud options become selectable; picking one shows yellow *Leaves this device* |
| Text cleanup | Edit instructions | *Save instructions* goes from disabled → enabled → loading → *Saved* |
| Text cleanup | Preview example / Polish switch | Cross-fade to the next example / whole section dims when off |
| Recent / History | Hover a row, *Retry cleanup* | Ghost actions, undo toast, loading → success |
| Dictionary / Privacy | Add term / Delete all… | Modal over a blurred plum scrim |
| `?page=styleguide` | — | Ramp, type scale, every button state, micro-animations |

**Automated check:** `node demo/verify.mjs` (from `ui_development/`) drives the flows above in headless Chromium, asserts the results and writes `screenshots/`. It reuses the Playwright install already in `../.tools_codex`.

## Design decisions

### Layout: floating sidebar (v4)
```
 open (264px)                          collapsed (60px)
┌──────────────────────────┐           ┌──────┐
│ ◉ Wispr Clone        [▯] │           │  ◉   │  ← logo click = toggle
├──────────────────────────┤           ├──────┤
│ ⌕ Quick search    Ctrl K │           │  ⌕   │
│ App                      │           │  ──  │  ← group labels become dividers
│ ⌂ General   (raised chip)│           │ [⌂]  │  ← active = raised white chip
│ ▭ System                 │           │  ▭   │
│ Voice                    │           │  ──  │
│ 🎙 Recording · Models …   │           │  🎙 ●│  ← status dots stay on icons
│ Data                     │           │  ──  │
│ ⛨ Privacy & data         │           │  ⛨   │
│ ↺ History           ● 5  │           │  ↺ ● │
│                          │           │      │  ← click empty space = expand
└──────────────────────────┘           └──────┘
```
- Toggle (open **and** close): click the logo or press **Ctrl + B**. The panel button in the header collapses.
- Clicking empty space in the **collapsed strip's page list** expands it (cursor shows ▸). The header, the search row and
  the divider lines are not triggers. Empty space in the open sidebar
  does nothing, so a missed click never closes it. The choice persists across launches.
- While collapsed, icons still navigate. Hover or keyboard focus shows a label tooltip ("Recording").
- Rows are identical in both states, so icons never move vertically: each group row (25px) shows its label when open
  and a short line in the same spot when collapsed. Every icon is 12px from the line above/below it; neighbouring icons are 2px apart.
- Icons keep the same x-position in both states (8px card padding + 9px item padding + 1px border → centre at 26px of a
  52px strip), so nothing jumps while the sidebar animates.
- **Quick search** (**Ctrl + K**) opens a page switcher: type, use ↑/↓, press Enter.

### Colour
- **One primary hue: muted plum** (`#745689` = ramp 600; hover 700 `#634575`; subtle fill 100 `#eee6f2`; accent text `#69437f`).
  The ramp 50 → 950 only changes lightness/saturation.
- **Warm neutral surfaces**: canvas `#f8f7f5`, surface `#fff`, surface-2 `#f3f1ef`, text `#29252d`.
  Dark: canvas `#1b191e`, surface `#232026`, primary `#b796ce` with dark text on it. Surfaces and text are remapped, not inverted.
- **Status colours carry meaning only, muted to sit with plum:** blue `#426c9b` in progress,
  green `#317356` ready, yellow `#946414` warning, red `#b3464c` error / destructive / live mic.

### Typography (Geist → Segoe UI Variable → system-ui; Cascadia/JetBrains Mono for keys)
| Token | Size / line | Weight | Use |
|---|---|---|---|
| H1 | 28 / 34 | 550, −2.5 % | Page titles ("Recording", "Good afternoon") |
| H2 | 20 / 28 | 600, −1.5 % | In-page feature heading ("See the difference") |
| H3 | 15 / 22 | 600 | Card titles ("Speech to text") |
| Group | 13 / 18 | 600 | Sentence-case section labels ("Audio input") |
| Body / Body M | 13 / 20 | 400 / 500 | Text / row titles and buttons |
| Small | 12 / 18 | 400 | Descriptions, metadata |
| Label | 11 / 14 | 500 | Rail labels, badges |
| Eyebrow | 10 / 14 | 600, +12 %, UPPERCASE | "TRY IT OUT", "ORIGINAL", nav groups |
| Mono | 12 / 16 | 500 | Shortcuts |

13 px body is deliberate: desktop apps sit closer to the eye than web pages (macOS/Windows
system UI uses 13/14 px).

### Spacing
4 px grid. Inside a component ≤ 12 px; between sibling components 16–24 px; between sections
32 px; page padding 32 × 40 px. Settings rows are ≥ 64 px tall with 20 px side padding.

### Buttons
| Type | When | Example |
|---|---|---|
| Primary (solid, accent shadow) | One forward action per view | Start dictation, Add term |
| Secondary (surface + border) | Standalone supporting action | Test microphone, Test model, Save instructions |
| Ghost (no chrome until hover) | Inline/row/toolbar actions that shouldn't compete | Preview example, Discard, Copy, View all |
| Danger | Only inside a confirmation | Delete history |
| Ghost-danger | Entry point to a destructive flow | Delete all… |

Every control has default / hover / active (pressed, 1 px drop + 0.98 scale) / disabled
(45 % opacity or muted fill, `not-allowed` cursor) / focus-visible (3 px accent ring).

### Depth & overlays
- Light: soft hue-tinted shadows (3 levels). Dark: black shadows plus a 1 px inner top highlight,
  because shadows alone vanish on dark surfaces.
- Dictation card: a soft radial glow sits behind the waveform only, and the waveform is edge-masked with a
  linear gradient. Text always sits on the flat part of the surface, so it stays legible without a scrim.
- Modals: plum-tinted gradient scrim + 4 px backdrop blur; spring scale-in.
- Floating pill is always dark (like Wispr Flow's overlay) so it reads over any app.

### Motion
120 / 180 / 320 ms with an ease-out curve; a spring curve only for things that "arrive"
(toasts, modals, switch knob, radio dot). Listening = red ping + animated waveform + timer + level bars;
loading = spinner / indeterminate bar / skeleton shimmer; warning = pulse ring + horizontal shake;
success = check-mark stroke draw-in. `prefers-reduced-motion` collapses all of it.

## Inspiration
Wispr Flow (floating pill, "hold to talk" hero), OpenWhispr (model/cleanup split, local-first
badges), LM Studio (rail + contextual column), Linear & Raycast settings (row anatomy, ghost
actions), and common Mobbin/Dribbble settings patterns (grouped cards, caption headers).

## Waveform (`waveform.js`)
- Implements the selected spec exactly: 29 pillars, 3 px round strokes, 9 px pitch, 2 px rest height, 340×72 canvas
  (680×144 backing), opacity `0.30 + 0.55·sin(πi/28)`, FFT 2048, 32 log bands 80 Hz–6 kHz, 45/150 ms level and
  45/110 ms pillar attack/release, ~30 fps, and ~4 fps stepped updates under reduced motion.
- **Mic sensitivity: 3×** (doubled from the spec's 1.5× default, at the top of its 0.5–3× range): quieter sounds register
  (threshold 0.004 instead of 0.008) and the same sound drives the pillars twice as tall. The synthetic fallback phrase is unaffected.
- No idle animation: the draw loop stops once the pillars are exactly at rest.
- Audio is analysed locally only: never stored, uploaded or played. The mic is released on finish/discard/tab hide.
- The floating pill's level bars follow the same analysis (14 of the 29 pillars).

## Known limits
- Prototype: microphone audio drives only the waveform; no transcription happens. The shortcut works only while the demo tab has focus.
- The waveform was verified with Chromium's fake microphone (a test tone), not a physical microphone.
- Geist is bundled locally; the mono font falls back to Consolas if Cascadia Code isn't installed.
- Not yet audited with a screen reader; contrast was checked visually, not measured.
