# Desktop checklist (tier H), run with the user on 2026-09-27; main at e7d010a

| # | Check | Result |
|---|---|---|
| H-01 | Hold / toggle on F3 (G3); Esc and HUD ✕ cancel paste nothing; ✕ keeps focus | PASS (user, 5/5; run codes cross-checked) |
| H-02 | HUD colours (green, yellow, red) and timer; no focus steal; click-through when hidden; no taskbar/Alt+Tab entry | PASS (user, 6/6) |
| H-03 | Switch away mid-dictation: return path and idle jump deliver once to the original field; nothing typed into the other window; nothing while typing | PASS (user, A+B) |
| H-04 | Devin, VS Code, Chrome, Terminal (Office: not installed) | PASS with finding F-2: all delivered once on retry, but the FIRST dictation in VS Code and in Terminal was held (no attempt) |
| H-05 | Win+V history excludes transcripts; previous clipboard restored | PASS (user) |
| H-06a | LM Studio port not reachable from the LAN | PASS (verified: 127.0.0.1:1234 only; the listener is Bionic.exe, an LM Studio-compatible server) |
| H-06b | Mic unplug mid-recording, and start with no mic | SKIPPED (user decision 2026-09-27: not relevant, the mic stays plugged in). Automated coverage only |

## Findings
- F-1: pastes into Win11 Notepad land, but are recorded `uncertain`. confirm() can't read Notepad's
  text via UIA element_text, so it returns None. No duplicate risk (uncertain is never retried), but
  history and state are wrong. Fix after the checklist: read through TextPattern/ValuePattern,
  including the RichEdit "Document" control of Win11 Notepad.
- F-2: the first dictation in VS Code (07:24:19) and in Windows Terminal (07:25:40) went to `held`,
  with no error code and no attempt. The retries worked. verify() compares the focused UIA element's
  RuntimeId with the captured field (not titles). Hypothesis: Chromium/Electron apps build their
  UIA tree lazily on the first client query, so the field id changes between capture and insert.
  Terminal doesn't fit that hypothesis. Needs a live diagnostic with the user (capture, wait,
  verify, print the reason; no titles).
- Note: cleanup_unavailable is because the cleanup model `meta-llama-3.1-8b-instruct` is listed by
  the port-1234 server (Bionic.exe) but not loaded. Loading it is the user's decision; we never
  load models.

## Summary
H-01 to H-05 PASS; H-06a PASS; H-06b SKIPPED (user). Office not installed (H-04). Open findings
before release: F-1 (Notepad and others recorded `uncertain`), F-2 (first dictation per
Electron/Terminal app held).
