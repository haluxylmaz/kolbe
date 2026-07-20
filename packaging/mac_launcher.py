"""PyInstaller entry point — launches the Kolbe GUI without a console."""

from __future__ import annotations

import multiprocessing
import sys


def main() -> int:
    from kolbe.gui.app import run_app

    return run_app()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
