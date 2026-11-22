"""Entry point for running the LyraForge PyWebView desktop application."""

from __future__ import annotations

import sys

from lyraforge.cli import main

if __name__ == "__main__":
    raise SystemExit(main(["desktop", *sys.argv[1:]]))
