"""Settings window creation, bundled navigation lock, and GUI loop startup."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urldefrag, urlsplit


def _settings_url() -> str:
    return (Path(__file__).resolve().parents[3] / "web" / "index.html").as_uri()


def _normalized_url(url: str | None) -> tuple[str, str, str, str, str] | None:
    if url is None:
        return None
    parts = urlsplit(urldefrag(url)[0])
    path = parts.path.casefold() if parts.scheme.casefold() == "file" else parts.path
    return (parts.scheme.casefold(), parts.netloc.casefold(), path, "", "")


def _lock_navigation(window: object, allowed: str) -> None:
    """Keep a native window on its single bundled page."""

    def check_navigation(*_args: object, **_kwargs: object) -> None:
        current = window.get_current_url()  # type: ignore[attr-defined]
        if _normalized_url(current) != _normalized_url(allowed):
            window.load_url(allowed)  # type: ignore[attr-defined]

    window.events.before_load += check_navigation  # type: ignore[attr-defined]
    window.events.loaded += check_navigation  # type: ignore[attr-defined]


def open_settings(webview: object, api_bridge: object, *, debug: bool) -> object:
    """Create the sole bridged window and constrain it to the bundled page."""
    allowed = _settings_url()
    window = webview.create_window(  # type: ignore[attr-defined]
        "Wispr Clone",
        url=allowed,
        js_api=api_bridge,
        width=1180,
        height=760,
        min_size=(1100, 700),
    )

    _lock_navigation(window, allowed)
    return window


def start(webview: object, *, debug: bool) -> None:
    """Configure the local-file security boundary and own the main GUI loop."""
    webview.settings["ALLOW_DOWNLOADS"] = False  # type: ignore[attr-defined]
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = False  # type: ignore[attr-defined]
    webview.settings["OPEN_DEVTOOLS_IN_DEBUG"] = False  # type: ignore[attr-defined]
    webview.settings["ALLOW_FILE_URLS"] = True  # type: ignore[attr-defined]
    webview.start(debug=debug, http_server=False, private_mode=True)  # type: ignore[attr-defined]
