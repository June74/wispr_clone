# WO-hud-compact-tune: the user's chosen HUD geometry

The user tuned the HUD in design/hud-preview.html and chose:

```json
{"window": [268, 44], "padding": [16, 0], "gap": 12,
 "label": {"size": 12, "weight": 500, "hideWhileListening": false},
 "dot": 8, "wave": [88, 28]}
```

This equals the current look except:
- right padding 6 → 0;
- window width 280 → 268, the natural width with the longest label, "Waiting for destination".

Luna: src/wispr_clone/ui/overlay.py sets `HUD_WIDTH = 268`; web/styles.css adds `padding: 0 0 0 16px`
to `.pill.hud-pill`. Nothing else changes.
Sol: update every test that expects 280 for the HUD width (T-UI-003, 007, 008, 011 and any others)
to 268, and extend T-WEB-013 with the padding.

Deferred (user decision, 2026-09-27):
- The user wants a full pill (22 px radius). Windows 11 DWM caps the corners at about 8 px, and
  WebView2's composition layer ignores window regions, so a larger radius needs a native-drawn
  HUD (a per-pixel-alpha layered window with the waveform ported from waveform.js).
- For now the corners stay at 8 px; the native-drawn HUD is a later work order.
