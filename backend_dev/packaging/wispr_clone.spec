# PyInstaller spec for the Windows onedir build (WO-packaging). Run via packaging/build_windows.py.
# ruff: noqa
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).resolve().parent  # backend_dev
WEB = ROOT / "web"

# Bundle web/ as "web", without its node tests.
web_datas = [
    (str(path), str(Path("web") / path.relative_to(WEB).parent))
    for path in WEB.rglob("*")
    if path.is_file() and "tests" not in path.relative_to(WEB).parts
]

# uiautomation loads UIAutomationClient_VC140_*.dll from its own bin folder.
uia_binaries = [
    (source, dest)
    for source, dest in collect_data_files("uiautomation", includes=["bin/*.dll"])
]

a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT / "src")],
    binaries=uia_binaries,
    datas=web_datas,
    # selftest imports its modules by name, so collect every wispr_clone module.
    hiddenimports=collect_submodules("wispr_clone"),
    excludes=["tkinter", "pytest", "tests"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="WisprClone",
    console=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="WisprClone", upx=False)
