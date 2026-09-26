"""Recording pywebview 6.2.1 surface used by the native UI tests."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


class Event:
    def __init__(self) -> None:
        self.handlers: list[Callable[..., object]] = []

    def __iadd__(self, handler: Callable[..., object]) -> Event:
        self.handlers.append(handler)
        return self

    def emit(self, *args: object, **kwargs: object) -> None:
        for handler in self.handlers:
            handler(*args, **kwargs)


class WindowEvents:
    def __init__(self) -> None:
        self.loaded = Event()
        self.before_load = Event()
        self.closing = Event()
        self.closed = Event()
        self.shown = Event()
        self.request_sent = Event()
        self.response_received = Event()
        self.initialized = Event()


class Window:
    def __init__(self, title: str, url: str | None, options: dict[str, object]) -> None:
        self.title = title
        self.url = url
        self.options = options
        self.events = WindowEvents()
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.on_top = bool(options.get("on_top", False))
        self.raise_on_run_js = False

    def run_js(self, script: str) -> None:
        self.calls.append(("run_js", (script,)))
        if self.raise_on_run_js:
            raise RuntimeError("fake JS delivery failed")

    def evaluate_js(self, script: str) -> None:
        self.calls.append(("evaluate_js", (script,)))

    def get_current_url(self) -> str | None:
        self.calls.append(("get_current_url", ()))
        return self.url

    def load_url(self, url: str) -> None:
        self.calls.append(("load_url", (url,)))
        self.url = url

    def show(self) -> None:
        self.calls.append(("show", ()))
        self.events.shown.emit()

    def hide(self) -> None:
        self.calls.append(("hide", ()))

    def destroy(self) -> None:
        self.calls.append(("destroy", ()))
        self.events.closed.emit()

    def move(self, x: int, y: int) -> None:
        self.calls.append(("move", (x, y)))

    def resize(self, width: int, height: int) -> None:
        self.calls.append(("resize", (width, height)))


class FakeWebview:
    def __init__(self) -> None:
        self.settings: dict[str, object] = {
            "ALLOW_DOWNLOADS": True,
            "ALLOW_FILE_URLS": False,
            "OPEN_EXTERNAL_LINKS_IN_BROWSER": True,
            "OPEN_DEVTOOLS_IN_DEBUG": True,
        }
        self.windows: list[Window] = []
        self.calls: list[tuple[str, dict[str, object]]] = []

    def create_window(
        self,
        title: str,
        url: str | None = None,
        html: str | None = None,
        js_api: object | None = None,
        width: int = 800,
        height: int = 600,
        x: int | None = None,
        y: int | None = None,
        resizable: bool = True,
        hidden: bool = False,
        frameless: bool = False,
        easy_drag: bool = True,
        shadow: bool = True,
        focus: bool = True,
        minimized: bool = False,
        on_top: bool = False,
        background_color: str = "#FFFFFF",
        transparent: bool = False,
        text_select: bool = False,
        zoomable: bool = False,
        draggable: bool = False,
        min_size: tuple[int, int] = (200, 100),
        **kwargs: object,
    ) -> Window:
        options: dict[str, object] = {
            "url": url,
            "html": html,
            "js_api": js_api,
            "width": width,
            "height": height,
            "x": x,
            "y": y,
            "resizable": resizable,
            "hidden": hidden,
            "frameless": frameless,
            "easy_drag": easy_drag,
            "shadow": shadow,
            "focus": focus,
            "minimized": minimized,
            "on_top": on_top,
            "background_color": background_color,
            "transparent": transparent,
            "text_select": text_select,
            "zoomable": zoomable,
            "draggable": draggable,
            "min_size": min_size,
            **kwargs,
        }
        self.calls.append(("create_window", {"title": title, **options}))
        window = Window(title, url, options)
        self.windows.append(window)
        return window

    def start(
        self,
        func: Callable[..., Any] | None = None,
        args: object = None,
        gui: str | None = None,
        debug: bool = False,
        http_server: bool = False,
        private_mode: bool = True,
        storage_path: str | None = None,
        icon: str | None = None,
        **kwargs: object,
    ) -> None:
        self.calls.append(
            (
                "start",
                {
                    "func": func,
                    "args": args,
                    "gui": gui,
                    "debug": debug,
                    "http_server": http_server,
                    "private_mode": private_mode,
                    "storage_path": storage_path,
                    "icon": icon,
                    **kwargs,
                },
            )
        )
