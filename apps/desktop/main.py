"""Entry point for running the LyraForge PyWebView desktop application."""

from __future__ import annotations

import sys

from lyraforge.cli import main
from lyraforge.startup_report import report_startup_failure


def _report(error: BaseException) -> None:
    report_startup_failure(error, argv=sys.argv)


if __name__ == "__main__":
    try:
        exit_code = main(["desktop", *sys.argv[1:]], error_reporter=_report)
    except BaseException as exc:  # noqa: BLE001 - a windowed build has no console for tracebacks
        _report(exc)
        exit_code = 1
    raise SystemExit(exit_code)
