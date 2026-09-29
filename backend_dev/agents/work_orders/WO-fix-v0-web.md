# WO-fix-v0-web: v0 runthrough bugs 2, 3, 4, 5, 7, 8 and 9 (web runtime)

```text
Source: coordinator runthrough 2026-09-28. User decision (2026-09-28): fix all, remove local-only.
Base revision: HEAD 5aee0f6 plus the coordinator's UNCOMMITTED cleanup in the same checkout.
  Preserve those changes. No git commands that change state (no add/commit/stash/checkout/reset).
Checkout: /home/injun/projects/wispr_clone (one writer at a time). Paths relative to backend_dev/.
Paired order: WO-fix-v0-backend.md (backend halves of items 3 and 5).
Authorization: no commits, pushes, PRs, installs, npm packages or downloads.

Roles / writable paths
  Sol (sol-feature-test-author): web/tests/**, tests/unit/web/test_web_static.py
  Luna (luna-runtime-programmer): web/app.js, web/index.html, web/styles.css, web/lib/*.js
    (a new web/lib/forms.js is allowed; pyproject already bundles web/lib/). Not web/tests/**.
Checks: from the repo root  node --test "backend_dev/web/tests/*.test.mjs"
        from backend_dev    uv run pytest -q -p no:cacheprovider tests/unit/web
                            (plus the full suite listed in WO-fix-v0-backend.md)
Test seam: node:test only. app.js runs against the real DOM, so put decisions in pure lib
  functions (API below) and keep app.js as thin wiring; check wiring statically in
  test_web_static.py or a web test, as existing T-WEB tests do.
```

## Helper API Luna must provide (Sol tests against it)

`web/lib/forms.js` (new):
- `termSaveEnabled(spelling)` → true only for a string with non-whitespace text.
- `instructionsDirty(text, saved)` → true when the textarea text differs from the saved
  `cleanup_instructions` (`null`/`undefined` saved counts as `''`).
- `micDeviceId(value)` → `null` for `''`/`null`/`undefined`, otherwise `Number(value)`
  (`'0'` → `0`, never `null`).
- `micSelection(settings, devices)` → the `device_id` (as a string) to select: the saved
  `settings.microphone_id` when a listed device has that id, else the `is_default` device, else `''`.
- `micTestRunningAfter(command, result, running)` → for an ok result: `'mic_test_start'` →
  `result.data.started === true`; `'mic_test_stop'` → `false` whether `stopped` is true or false.
  For a failed result → `running` unchanged.
- `MIC_TEST_IDLE_MS = 1500` and `micTestEnded(lastLevelAt, now)` → true when
  `now - lastLevelAt >= MIC_TEST_IDLE_MS`.

`web/lib/view.js`: add `canDiscard(status)` → true exactly for `recording`, `processing`,
`awaiting_cleanup_choice`, `awaiting_destination` (the statuses the state machine can cancel;
`held` cannot be cancelled). Keep `hudState`, `shouldToastInserted`, `recoveryButtons`.

`web/lib/store.js`: `acceptsEvent` / `applyEvent` accept a `run:recovery` whose version is **equal
to or newer than** the stored run (the backend publishes `run:state` then `run:recovery` with the
same version) and merge its `status`/`actions` into the run; an older recovery is ignored.
`run:state` keeps the strict newer-only rule.

## Item 2 — "Save term" and "Save instructions" can never be clicked

Nothing ever removes their `disabled` attribute; `renderSettings` also rewrites `#instructions`
on every render (including ~30 `audio:level` events a second), discarding typed text.
Rules: `#save-term` follows `termSaveEnabled(#term-input value)` on input; opening the Add modal
starts disabled, opening Edit (prefilled) starts enabled. `#save-instructions` follows
`instructionsDirty(textarea, saved)` on input; renders do not overwrite unsaved edits; after a
successful save the button is disabled and `#save-note` says "Saved".

## Item 3 (web half) — the chosen microphone is never saved

Rules: changing `#mic-select` sends `settings_update {patch: {microphone_id: <id string or null>}}`
and shows an error toast on failure; the option list selects `micSelection(settings, devices)`
when it is rendered and when settings change; the mic test sends `device_id: micDeviceId(value)`
(today `Number(value) || null` turns device 0 into "default").

## Item 4 — the cleanup-recovery buttons never appear

The store rejects the same-version `run:recovery`, so `state.lastRecovery` is never set; the
caption also reads an `error_code` the event never carries.
Rules: when the active run is `awaiting_cleanup_choice`, the dictation card shows one button per
`recoveryButtons(run)` entry in a dedicated container (e.g. `#dictate-recovery`) that is replaced
on every render and emptied in any other status (no duplicates, no stale buttons); the existing
`[data-recover]` handler and its `run_recover` call shape stay; the caption for that status is
"Text cleanup couldn't finish. Choose how to continue."; the `state.lastRecovery` path goes.

## Item 5 (web half) — remove local-only mode

Remove the Privacy page "Local-only mode" row (`#privacy-local-switch`), `#local-only-warning`,
the `#local-switch`/`#privacy-local-switch` handlers (`#local-switch` is the Models page "Keep
processing local" row; the coordinator first misread it as missing), the
local-only code in `renderSettings`, the speech-picker lock, and `cloud_model_forbidden` from
`lib/messages.js` (T-WEB-008 must still mirror `util/error_messages.py` after the backend turn).

## Item 7 — Discard stays invisible outside recording

`app.js` un-hides `#dictate-cancel` for several statuses, but `.dictate-cancel` is `opacity: 0;
pointer-events: none` except under `data-state="recording"`.
Rules: `#dictate-cancel` is hidden exactly when `!canDiscard(status)`; when not hidden it is
visible and clickable in every state (keep its position and look).

## Item 8 — the mic-test button gets stuck on "Stop test"

After the backend's 30 s auto-stop, "Stop test" returns `{stopped: false}`, which the page reads
as still running. Rules: use `micTestRunningAfter` for both commands; while a test runs, a
presentation timer (period ≤ 500 ms) returns the button to "Test microphone" once
`micTestEnded(lastMicLevelAt, now)`, where mic-test levels are `audio:level` events with
`run_id === null` (start counting from the start result).

## Item 9 — a web test that can never fail (Sol only)

`web/tests/html-escaping.test.mjs` "a stale done event cannot trigger the inserted toast": the
sandbox lacks `acceptsEvent`, the handler's `catch {}` swallows the ReferenceError, and
`lastEvent` is `undefined` for stale and fresh events alike. Provide the real store functions,
assert the stale event leaves no toast (`lastEvent === null`) and add a fresh-event control that
does set it. Show (outside the repo, e.g. a /tmp copy) that the fixed test fails when the gating
is broken.

## Tests (Sol)

| ID | Assertion |
|---|---|
| T-WEB-023 | `termSaveEnabled` cases; app.js wires `#term-input` input → `#save-term` disabled state, Add opens disabled, Edit opens enabled |
| T-WEB-024 | `instructionsDirty` cases; `#instructions` input toggles `#save-instructions`; `renderSettings` never overwrites unsaved text; save success disables and notes "Saved" |
| T-WEB-025 | `micDeviceId` (`''`→null, `'0'`→0, `'3'`→3), `micSelection` (saved present / saved missing → default / no default); `#mic-select` change sends `settings_update` with `microphone_id`; mic test sends `micDeviceId(...)` |
| T-WEB-026 | store: after `run:state` v4, a `run:recovery` v4 is accepted and merges `actions`; v3 recovery ignored; `run:state` v4 again ignored. app.js renders recovery buttons from the active run's actions into the dedicated container, empties it otherwise, uses the new caption, and no longer uses `lastRecovery` |
| T-WEB-027 | no "Local-only mode", `privacy-local-switch`, `local-switch`, `local-only-warning` or `local_only` in index.html/app.js; `cloud_model_forbidden` absent from messages.js (replaces T-WEB-011) |
| T-WEB-028 | `canDiscard` for every run status (incl. `held` → false); `.dictate-cancel` is not transparent/unclickable by default in styles.css; app.js sets `hidden = !canDiscard(status)` |
| T-WEB-029 | `micTestRunningAfter` cases (start ok, stop ok stopped true/false, failure unchanged); `micTestEnded` at threshold −1 / threshold / +1; app.js runs the timer and resets the button |
| T-WEB-030 | the fixed stale-event toast test (item 9) with its fresh-event control |

## Handoff

Sol: write the tests, run them, and report RED per ID with the exact command and the failing
assertion (a missing helper export is acceptable RED only if the assertion that follows is real;
item 9 has no RED, report its mutation evidence). Then stop; Luna takes the turn.
Luna: implement without editing tests; run the checks; report GREEN.
Sol (verification turn): re-run, review the diff, add regressions only if required.

## Coordinator review addendum (2026-09-28)

**Item 7b — the `hidden` attribute does not hide styled elements.** `styles.css` has no `[hidden]`
rule, and author `display` values beat the browser's `[hidden] { display: none }`. `.btn` is
`display: inline-flex`, so after the item-7 change `#dictate-cancel` shows in every state even
when `hidden`; `.item` is `display: flex`, so the History search's `item.hidden = ...` never hides
non-matching rows (a pre-existing bug). Rule (Luna): add one global
`[hidden] { display: none !important; }` near the base styles. Test (Sol):

| ID | Assertion |
|---|---|
| T-WEB-031 | styles.css hides every `[hidden]` element regardless of author `display` (a `[hidden]` rule with `display: none !important`); `.dictate-cancel` and `.item` rely on it (app.js toggles `hidden` on both) |
