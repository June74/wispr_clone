# WO-packaging: a PyInstaller onedir Windows build (M6, P-PYI-001)

```text
User approval (2026-09-27): "I approve pyinstaller". PyInstaller 6.22.3 is already in the dev
  group (win32) and uv.lock, so there is no manifest or lockfile change.
Format: onedir (dist/WisprClone/WisprClone.exe), windowed (no console), no UPX, unsigned.
  Chosen for faster start and fewer AV false positives than onefile.
Build location: %LOCALAPPDATA%\wispr_clone\{build,dist}. Never build onto the \\wsl.localhost path.
Branch / worktree: feat/packaging / ~/projects/wc-pkg
Coordinator (main-agent-only files): src/wispr_clone/config.py (resource_root),
  src/wispr_clone/app.py (hud_url), packaging/** (spec, launcher, build script)
Luna: src/wispr_clone/ui/windows.py, src/wispr_clone/ui/native_hud.py (use config.resource_root)
Sol:  tests/unit/test_resources.py, tests/unit/packaging/test_spec.py,
      tests/probes/pyinstaller/test_p_pyi_001.py
```

## Rules

1. `config.resource_root() -> Path`: `Path(sys._MEIPASS)` when `sys.frozen` is set, otherwise the
   backend_dev directory (`Path(__file__).resolve().parents[2]`). Web assets are always at
   `resource_root() / "web"`. No I/O at import.
2. Every `Path(__file__)...parents[n] / "web"` in src uses `config.resource_root()`: app.py
   hud_url, ui/windows.py _settings_url, and ui/native_hud.py (the font source).
3. `packaging/wispr_clone.spec`:
   - entry `packaging/launcher.py`, which calls `wispr_clone.__main__.main()`;
   - `hiddenimports = collect_submodules("wispr_clone")`, because selftest imports by name;
   - datas: `web/` excluding `web/tests`, installed as `web`; plus uiautomation's `bin/*.dll`;
   - excludes tkinter, pytest and the tests package;
   - onedir, console=False, name "WisprClone", upx=False.
4. `packaging/build_windows.py` (run with the Windows venv via uv.exe):
   - runs PyInstaller with the spec and distpath/workpath under %LOCALAPPDATA%\wispr_clone;
   - then runs `WisprClone.exe --self-test` and requires exit 0;
   - prints the exe path and a SHA-256 of WisprClone.exe.
5. Privacy: nothing from user data goes into the bundle, and the build logs contain no
   secrets.

## Tests (Sol)

| ID | Assertion |
|---|---|
| T-PKG-001 | resource_root(): not frozen → the backend_dev dir, and web/index.html exists under it. Monkeypatched sys.frozen plus sys._MEIPASS → that dir |
| T-PKG-002 | No src module computes a web path from `__file__` except config.resource_root (static scan) |
| T-PKG-003 | Static parse of packaging/wispr_clone.spec: collect_submodules("wispr_clone"), web datas without web/tests, the uiautomation dlls, console=False, upx=False, name WisprClone |
| P-PYI-001 (WISPR_REAL_PACKAGE=1, win32) | Run packaging/build_windows.py; WisprClone.exe exists; `--self-test` exits 0 within 60 s |
