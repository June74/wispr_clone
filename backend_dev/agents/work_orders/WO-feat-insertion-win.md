# WO-feat-insertion-win — Windows destination capture, verification and insertion

```text
Work-order ID: WO-feat-insertion-win
Role file / requested model: RED + verify: sol-feature-test-author.md (T-INS, fake Win32/UIA) and
                             sol-boundary-test-author.md (P-WIN32, P-UIA, fragments) / gpt-6-sol
                             GREEN: luna-adapter-programmer.md; the ONE manifest change below as
                             luna-integration-programmer.md / gpt-6-luna
Pipeline branch or P0/M stage: Wave 1, branch feat/insertion-win (unblocks M2 with history merged)
Outcome and observable acceptance:
  The insertion package captures a destination (window, tab, focused field) without storing titles,
  verifies it later, chooses ONE strategy before dispatch (Korean layout → exclusion-flagged paste),
  brings the destination forward and restores the user's window, dispatches once, and confirms by
  UI Automation read-back (mismatch/unreadable → uncertain). No claims, no retries, no orchestration
  (that is M2). All Windows calls sit behind two small interfaces so tests run with fakes anywhere.
Base revision / worktree / branch: 744a95b / ~/projects/wc-insertion / feat/insertion-win
Relevant sections: CODEMAP.md §4 (hybrid delivery, insertion protocol, clipboard privacy, strategy
  rules incl. the G4b Korean-layout rule), §5 (destination snapshot: title hash only), §7 G4 and G4b
  records; DEPENDENCIES.md (UI Automation client = uiautomation, user decision 2026-09-25);
  dev_pipeline.md §6 Wave 1 row feat/insertion-win.
Exact writable paths (under backend_dev/):
  Sol:  tests/unit/insertion/**, tests/probes/win32/**, tests/probes/uia/**,
        tests/diag/test_import_names.py (T-DIAG-010),
        tests/_attribution/impact/pywin32.toml, tests/_attribution/impact/uiautomation.toml
  Luna: src/wispr_clone/insertion/__init__.py (docstring only), insertion/destination.py,
        verifier.py, inserter.py, app_strategies.py, win32.py, uia.py;
        RESERVED for this order: tests/_attribution/plugin.py (only `check_impact_map_sync`: an
        optional fragment key `import_names = [..]` lists the top-level module names that belong to
        the dependency, used when the package is not installed on this OS — e.g. pywin32 on Linux:
        `["win32clipboard", "win32con", "win32gui", "win32process", "pywintypes"]`); T-DIAG-010 below;
        pyproject.toml (add exactly `"uiautomation==2.0.29; sys_platform ==
        'win32'"` to the runtime dependencies) and uv.lock (regenerate with `uv lock`; no other change)
Read-only: everything else.
Allowed imports: insertion -> contracts, config, util + stdlib (hashlib, json, dataclasses, ctypes,
  time, typing). pywin32 modules and `uiautomation` are imported LAZILY, only in win32.py and uia.py
  (Windows-only; Linux CI imports the package fine).
Required tiers: S, U (fakes) on ubuntu and windows; W for P-WIN32/P-UIA (windows-latest; skip with a
  reason when there is no interactive desktop/clipboard → UNDETERMINED, never a pass).
Check commands (from backend_dev/, UV_LINK_MODE=copy):
  uv lock --check (after Luna's lock) ; uv sync --locked; uv run ruff check .; uv run ruff format --check .;
  uv run mypy src scripts tests/_attribution tests/fakes; uv run python scripts/check_imports.py;
  uv run pytest -q -W error
Authorization: the user approved `uiautomation` (2026-09-25); network for uv only. Tests never send
  real keystrokes, never touch the real clipboard, never move real windows.
Privacy: never store or log window titles (hash only), field contents, or inserted text; errors
  and results carry no text.
Handoff: coordinator. Sol: RED command/output. Luna: GREEN outputs. Sol: verification findings.
```

## Pinned API (use these exact names)

`insertion.win32` — the Win32 boundary:

```python
class Win32Api(Protocol):
    def foreground_window(self) -> int
    def is_window(self, hwnd: int) -> bool
    def window_process(self, hwnd: int) -> tuple[int, str]        # (pid, exe basename, lowercase)
    def window_title(self, hwnd: int) -> str                        # used ONLY to hash
    def keyboard_layout(self, hwnd: int) -> int                     # LANGID of the window's thread
    def set_foreground(self, hwnd: int) -> bool
    def idle_ms(self) -> int                                        # GetLastInputInfo
    def send_inputs(self, inputs: Sequence[KeyEvent]) -> int        # number accepted
    def clipboard_text(self) -> str | None
    def set_clipboard(self, text: str, *, exclusion_formats: bool) -> None
    def clear_clipboard(self) -> None

@dataclass(frozen=True, slots=True)
class KeyEvent:
    vk: int = 0; scan: int = 0; flags: int = 0                     # KEYEVENTF_* flags

EXCLUSION_FORMATS = ("ExcludeClipboardContentFromMonitorProcessing",
                     "CanIncludeInClipboardHistory", "CanUploadToCloudClipboard")
KOREAN_LANGID = 0x0412

class RealWin32:  # implements Win32Api with pywin32 + ctypes (lazy imports); exclusion formats are
                  # set with 4 zero bytes (DWORD 0), as in the G4 experiment
```

`insertion.uia` — the UI Automation boundary:

```python
RuntimeId = tuple[int, ...]

class UiaApi(Protocol):
    def focused_element(self) -> RuntimeId | None
    def element_control_type(self, rid: RuntimeId) -> str | None
    def selected_tab(self, hwnd: int) -> RuntimeId | None
    def select_tab(self, hwnd: int, tab: RuntimeId) -> bool
    def focus_element(self, rid: RuntimeId) -> bool
    def element_text(self, rid: RuntimeId) -> str | None           # ValuePattern, else TextPattern; None if unreadable
    def is_on_screen(self, rid: RuntimeId) -> bool

class RealUia:  # implements UiaApi with `uiautomation` (lazy import); must be used from ONE thread
                # (COM apartment) — M2 owns that thread
```

`insertion.destination`:

```python
@dataclass(frozen=True, slots=True)
class DestinationSnapshot:
    hwnd: int; pid: int; exe: str; title_hash: str       # sha256 hex of the title; NEVER the title
    tab: RuntimeId | None; field: RuntimeId | None; field_type: str | None; langid: int
    def to_json(self) -> dict[str, object]                 # for history.destination
    @classmethod
    def from_json(cls, data: Mapping[str, object]) -> DestinationSnapshot   # strict; bad data -> VALIDATION

def capture(win32: Win32Api, uia: UiaApi) -> DestinationSnapshot   # the foreground window now
```

`insertion.verifier`:

```python
VerifyStatus = Literal["same", "changed", "closed", "unverifiable"]
@dataclass(frozen=True, slots=True)
class Verification:
    status: VerifyStatus; reason: str                       # reason: "window" | "process" | "field" | "tab" | "no field" | "off screen"

def verify(snapshot: DestinationSnapshot, win32: Win32Api, uia: UiaApi) -> Verification
    # closed: not is_window(hwnd). changed: foreground != hwnd, pid/exe differ, selected tab differs,
    # focused field differs. A matching title hash alone is NEVER enough (T-INS-003): identity is
    # hwnd + pid + exe (+ tab + field). unverifiable: snapshot has no field, or field not on screen.
    # "same" only when every recorded part matches.
```

`insertion.app_strategies`:

```python
Strategy = Literal["paste", "unicode"]
def choose_strategy(snapshot: DestinationSnapshot) -> Strategy
    # Korean layout (langid 0x0412) -> "paste" (G4b: typing corrupts in both IME modes);
    # exe in PASTE_APPS (e.g. "devin.exe", "notepad.exe") -> "paste"; otherwise "unicode".
PASTE_APPS: frozenset[str]
```

`insertion.inserter`:

```python
def build_unicode_inputs(text: str) -> list[KeyEvent]
    # KEYEVENTF_UNICODE (0x0004) down + up (0x0004|0x0002) per UTF-16 code unit (surrogate pairs as
    # two units); pure

@dataclass(frozen=True, slots=True)
class PreviousFocus:
    hwnd: int; tab: RuntimeId | None

def bring_forward(snapshot, win32, uia, *, settle_s: float = 0.1, timeout_s: float = 1.0,
                  sleep: Callable[[float], None] = time.sleep,
                  clock: Callable[[], float] = time.monotonic) -> PreviousFocus | None
    # remembers the current foreground window/tab, set_foreground(snapshot.hwnd), reselects the
    # snapshot tab, focuses the snapshot field; then waits until foreground == hwnd and focused ==
    # field for settle_s (polling with `sleep`, bounded by timeout_s). Returns None if it could not
    # settle (caller must not dispatch).
def restore(previous: PreviousFocus, win32, uia) -> None      # back to the user's window/tab

@dataclass(frozen=True, slots=True)
class DispatchResult:
    strategy: Strategy; events_accepted: int; before_text: str | None

def dispatch(text: str, snapshot, win32, uia) -> DispatchResult
    # strategy = choose_strategy(snapshot) BEFORE any input; reads before_text of the field; paste:
    # save clipboard text, set_clipboard(text, exclusion_formats=True), Ctrl+V, restore the saved
    # text (or clear) — paste NEVER falls back to typing, even if 0 events were accepted; unicode:
    # send_inputs(build_unicode_inputs(text)). Never sends Enter.
def confirm(text: str, result: DispatchResult, snapshot, uia) -> Literal["inserted", "uncertain"]
    # read the field again: "inserted" only if before_text and after_text are both readable and the
    # text occurs exactly once more than before; otherwise "uncertain"
```

## Tests (Sol; IDs in function names; fake Win32 and fake UIA in the test folder; no real input)

| ID | Must assert |
|---|---|
| **T-INS-001** (invariant) | `capture` stores `sha256(title)`; `to_json` and `repr` of the snapshot never contain the title (sentinel) |
| T-INS-002 | `verify` → `changed` when pid or exe differ for the same hwnd, and when foreground is another window; `closed` when the window is gone |
| **T-INS-003** (invariant) | same title hash but different hwnd (or pid) → `changed`, never `same` |
| **T-INS-004** (invariant) | every transcript clipboard write passes `exclusion_formats=True`; `RealWin32.set_clipboard` (with a fake win32clipboard module) sets all three formats with 4 zero bytes |
| **T-INS-005** (invariant) | the strategy is fixed before any input event; a paste that is rejected (0 events) returns without calling `send_inputs` with Unicode events (no fallback) |
| T-INS-006 | `build_unicode_inputs` for ASCII, Korean and an emoji (surrogate pair) gives exact scan codes/flags, down+up per unit, no VK_RETURN |
| T-INS-007 | `capture` records hwnd, pid, exe, title hash, selected tab and focused field from a fake UIA tree; `from_json(to_json(s)) == s`; malformed JSON → `VALIDATION` |
| T-INS-008 | `bring_forward` calls `set_foreground(target)`, `select_tab(target tab)`, `focus_element(field)`; `restore` returns to the recorded previous window and tab |
| **T-INS-009** (invariant) | `confirm` → `uncertain` when the field is unreadable (before or after), when the text appears 0 or 2+ times more, or when text changed elsewhere; `inserted` only on exactly one new occurrence |
| **T-INS-010** (invariant) | Korean langid (0x0412) → `paste` for any exe (both IME modes are the same layout); a non-Korean layout in an unknown exe → `unicode`; PASTE_APPS → `paste` |
| T-INS-011 | `bring_forward` returns None (no settle) when foreground never becomes the target within `timeout_s` (fake clock/sleep), and waits at least `settle_s` before returning success |
| T-INS-012 | importing `wispr_clone.insertion.*` works without pywin32/uiautomation (lazy imports); no module logs or stores inserted text (caplog + inspection) |

Probes (Sol boundary), Windows only (`@pytest.mark.windows`), skip with a reason off Windows or
without an interactive desktop:

- P-WIN32-001 `win32clipboard.RegisterClipboardFormat` returns non-zero ids for the three exclusion
  format names; P-WIN32-002 clipboard set/get round trip of a synthetic string (skip if the runner
  has no clipboard); P-WIN32-003 `ctypes.windll.user32.SendInput` and `GetLastInputInfo` exist.
- P-UIA-001 `import uiautomation`; `uiautomation.GetRootControl()` returns a control whose
  `ControlTypeName` is a string (skip without a desktop); version 2.0.29 via `importlib.metadata`.

Impact fragments: `pywin32.toml` (modules `insertion.win32`; features insertion, clipboard privacy;
error codes `insertion_failed`, `insertion_uncertain`, `destination_unverifiable`), `uiautomation.toml`
(modules `insertion.uia`; features tab/field capture, read-back, hybrid delivery; same codes plus
`destination_closed`). `pywin32.toml` declares `import_names` for every pywin32 module the code imports (T-DIAG-006 must
pass on Linux, where pywin32 is not installed).

T-DIAG-010 (Sol, tests/diag/test_import_names.py): a fragment with `import_names` makes a src
module's import of one of those names count as that dependency (sync passes without the package
installed); a listed module that is not imported, or an import not covered by any fragment, still
fails; fragments without the key behave exactly as before.

## Coordinator decisions after RED review

1. P-WIN32-002 (clipboard round trip) runs only when `CI == "true"` (GitHub-hosted runners, whose
   clipboard belongs to nobody) and restores the previous clipboard text; on any other machine it
   skips with the reason "clipboard round trip runs on hosted CI only". Sol adjusts it in VERIFY.
2. The G4b record is on main (PR #20); this branch is rebased onto it.

## Coordinator review of GREEN (binding)

3. **Paste must land before the clipboard is restored.** `SendInput` only queues keystrokes; the
   target processes Ctrl+V later. Restoring the previous clipboard immediately can make the app
   paste the USER'S old clipboard text instead of the dictation. `dispatch` takes
   `paste_settle_s: float = 0.5` and an injected `sleep`; after Ctrl+V it waits until the field's
   read-back shows one new occurrence of the text, polling up to `paste_settle_s`, and only then
   restores the clipboard. If the text never appears, it still restores after `paste_settle_s`
   (and `confirm` will say `uncertain`).
4. **Always return the user to their window.** If `bring_forward` fails after changing the
   foreground (tab select fails, field focus fails, or no settle), it calls `restore(previous)`
   before returning None.
5. **The user's own clipboard is restored as it was:** `set_clipboard(old_text,
   exclusion_formats=False)`. Only transcript text carries the exclusion formats (T-INS-004).
6. Sol fixes the ruff import-order finding in its own test file.
