"""Command-line entry point."""

from __future__ import annotations

import argparse
import importlib

from wispr_clone import config
from wispr_clone.app import App, acquire_single_instance, real_factories


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="wispr_clone")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        selftest = importlib.import_module("wispr_clone.selftest")
        return int(selftest.run_self_test())
    instance = acquire_single_instance()
    if instance is None:
        return 3
    app = App(real_factories(), data_dir=config.app_data_dir(), debug=args.debug)
    app._instance = instance
    try:
        return app.run()
    finally:
        instance.release()


if __name__ == "__main__":
    raise SystemExit(main())
