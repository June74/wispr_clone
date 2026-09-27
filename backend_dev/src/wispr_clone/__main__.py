"""Command-line entry point."""

from __future__ import annotations

import argparse
import importlib
import sys

from wispr_clone import config
from wispr_clone.app import App, acquire_single_instance, real_factories
from wispr_clone.ui import win_frame


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="wispr_clone")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--debug", action="store_true")
    # Launch at login: start in the tray without showing the window.
    parser.add_argument("--background", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        selftest = importlib.import_module("wispr_clone.selftest")
        return int(selftest.run_self_test())
    instance = acquire_single_instance()
    if instance is None:
        # Already running (often hidden in the tray): bring its window forward.
        if not args.background:
            win_frame.activate_existing("Wispr Clone")
        return 3
    app = App(
        real_factories(),
        data_dir=config.app_data_dir(),
        debug=args.debug,
        start_hidden=args.background,
    )
    app._instance = instance
    try:
        exit_code = app.run()
        if exit_code != 0 and app.failure is not None:
            step, exception_type = app.failure
            print(
                f"wispr_clone: startup failed at {step} ({exception_type})",
                file=sys.stderr,
            )
        return exit_code
    finally:
        instance.release()


if __name__ == "__main__":
    raise SystemExit(main())
