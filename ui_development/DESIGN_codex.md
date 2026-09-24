# Wispr · desktop design notes

## Direction

A quiet voice workspace for someone who wants to capture a thought, check the result, and continue working. The primary task is recording; the next task is reviewing/copying the resulting text. Setup and long-term preferences sit a level deeper.

The workspace has three primary destinations: Workspace, History, and Dictionary. Settings opens a separate left navigation column with Recording, Models, Text cleanup, Appearance, and Privacy & history. This follows the requested Bionic-inspired navigation structure without copying product assets or branding.

The content is purposefully bounded rather than stretched across a wide monitor. Record and review remain the visual anchors. The setup summary is secondary. Recent activity sits last. The navigation bar and footer remain visible while content scrolls independently.

## Typography

**Geist variable** is bundled locally under the SIL Open Font License. The interface uses actual variable weights rather than relying on browser-synthesized bold. Font fallback: Segoe UI, Arial, sans-serif.

| Role | Size / weight | Treatment |
| --- | --- | --- |
| Workspace heading | 32 px / 550 | 1.2 line height, −1.1 px tracking |
| Settings heading | 28 px / 550 | Compact page hierarchy |
| Section headings | 15–17 px / 600 | Clear grouping without heavy visual weight |
| Transcript | 15 px / 400 | 1.85 line height for comfortable review |
| Navigation and actions | 12–13 px / 500–550 | Icon paired with concise wording |
| Supporting content | 11–13 px / 400 | Secondary contrast, not opacity alone |
| Eyebrows and metadata | 9–11 px / 500–600 | Only nonessential contextual information |
| Shortcuts and timer | 10–12 px / monospace | Distinguish literal keys and elapsed time |

## Color system

Warm gray neutrals support a single **plum** primary hue. Lavender and deep plum extend the same family for selection, backgrounds, borders, and emphasis. Dark mode remaps both surfaces and foregrounds; it is not a blanket inversion.

| Token | Light | Dark | Purpose |
| --- | --- | --- | --- |
| Canvas | `#f8f7f5` | `#1b191e` | Low-glare workspace |
| Surface | `#ffffff` | `#232026` | Controls and readable text regions |
| Primary | `#745689` | `#b796ce` | Main action, focus, waveform |
| Primary hover | `#634575` | `#c6a7dc` | Pointer feedback |
| Primary subtle | `#eee6f2` | `#3a2e45` | Active navigation and selection |
| Primary text | `#69437f` | `#ceb0e4` | Accent labels on subtle surfaces |
| Hero surface | `#f2edf5` | `#2c2433` | Recording zone |
| Hero glow | `#e6d9ed` | `#463250` | Gentle radial gradient depth |
| Main text | `#29252d` | `#f0eaf3` | Primary reading |
| Secondary text | `#746d79` | `#aca2b3` | Supporting information |
| Green | `#317356` | `#93cfaa` | Readiness / successful test |
| Blue | `#426c9b` | `#a1c4eb` | Informational guidance / in-progress model test |
| Amber | `#946414` | `#e6c37f` | Quiet microphone warning |
| Red | `#b3464c` | `#f0a0a6` | Unavailable input / destructive action |

Color is always paired with text or an icon. Core text/accent/status combinations measured at least 4.5:1 in both themes; see `review_codex/results_codex.json` for individual values. Disabled controls intentionally use reduced opacity and do not receive keyboard focus. The contrast measurements are selected token checks, not a claim of complete WCAG conformance.

## Spacing and depth

- A 4 px base rhythm, with controlled optical exceptions for icon alignment.
- Content maximum width: 1056 px including side padding; settings: 860 px.
- Settings column: 226 px, narrowing to 195 px on smaller desktop windows.
- Primary card gap: 20 px; typical internal padding: 18–24 px.
- Card radius: 14 px; control radius: 7–9 px; status badge radius: 5 px.
- Cards use a small contact shadow plus a soft ambient shadow. The primary button has a slightly stronger plum shadow.
- Dialogs use a deeper shadow and a dark gradient scrim with 4 px background blur. This preserves separation and contrast behind form text.
- The waveform has a gradient edge mask; its decorative glow stays behind text on a controlled surface.

## Controls and feedback

Filled plum buttons express the main action. Bordered standalone buttons support tests and changes. Ghost buttons handle low-emphasis actions such as Copy text, View history, theme changes, and navigation. Icon-only row actions have explicit accessible names; primary navigation and actions pair text with icons.

| State | Visual behavior |
| --- | --- |
| Default | Neutral surface, fine border, quiet shadow |
| Hover | Surface tint and stronger border or foreground |
| Pressed | 1 px downward movement |
| Selected | Plum-tinted surface, accent text, settings indicator |
| Keyboard focus | 3 px plum outline with 4 px offset |
| Disabled | Reduced opacity, unavailable cursor, disabled semantics |
| Recording | Animated waveform, pulsing indicator, elapsed timer, Finish action |
| Processing | Spinner/waveform motion, disabled repeat action |
| Success | Brief live-region toast; green model status |
| Warning | Amber message, finite nudge, explicit recovery guidance |
| Error | Red message and a visible Try again action |
| Empty | Short explanation and clear route to the main task |

Small surface/focus changes run for 160–200 ms. System reduced-motion preferences and the in-app setting stop animation. Dialogs support Escape, focus containment, and focus restoration. Deleting data uses a scoped confirmation dialog. All simulation claims are marked in the UI.

## Inspiration and assets

References were consulted on September 23, 2026. The resulting layout, CSS, icons, and demo content were authored for this concept.

- [LM Studio Bionic](https://lmstudio.ai/docs/bionic): reference product for the requested workspace/settings separation. The left settings column here is an interpretation of the user's requested structure.
- [Wispr Flow: What is Flow?](https://docs.wisprflow.ai/articles/2772472373-what-is-flow): dictated speech, cleanup, history, and personal vocabulary informed the task hierarchy.
- [OpenWhispr](https://openwhispr.com/): explicit speech/cleanup model choices and local processing informed the settings organization.
- [Speech to Note desktop companion on Dribbble](https://dribbble.com/shots/26687381-Speech-to-Note-Desktop-Companion-App): inspiration for a compact recording companion, transcript entries, and shortcut hints. No illustration or screenshot was copied into this UI.
- [Geist on Google Fonts](https://github.com/google/fonts/tree/main/ofl/geist): the sole third-party visual asset. Bundled variable font and license are under `assets_codex/`. Replacing it with a system font removes the font download but changes text metrics and visual character.

No icon, UI component, or CSS framework was added. Inline SVG icons and CSS waveform bars keep this concept portable and easy to integrate after design review.

## Floating HUD

The recording companion sits at the bottom center, 65 px above the window edge, clear of the demo status bar. The listening state is approximately 510 × 72 px. An 18 px radius, fine plum border, opaque tonal gradient, and layered shadow separate it from underlying content without dimming the workspace.

Its hierarchy is status → voice activity and elapsed time → Finish/Cancel. Labels use Geist at 12 px / 600; secondary context is 10 px; the timer uses 11 px monospace. Status changes use the same semantic colors as the full interface. The waveform animates only in the recording state and respects reduced motion. Processing retains Cancel and disables duplicate completion. Success offers Copy and auto-dismisses after five seconds; error/warning states remain until addressed.

The HUD has its own labeled region and a polite status announcement. Timer updates are kept out of the live region to avoid announcing every second. Toasts move above the HUD, and scrollable content receives extra bottom padding so covered controls can be scrolled into view. It remains available across pages, with no backdrop or modal focus trap. This implementation previews the appearance in the browser; an always-on-top native window and real audio-level input are future application integration work.
