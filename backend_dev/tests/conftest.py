from pathlib import Path

pytest_plugins = ("pytester",)
if (Path(__file__).parent / "_attribution" / "plugin.py").is_file():
    pytest_plugins += ("_attribution.plugin",)
