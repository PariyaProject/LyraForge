"""Regenerate self-authored MIDI fixtures into tests/fixtures/midi/.

Usage:  uv run python scripts/make_fixtures.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests" / "fixtures"))

from midi_builders import FIXTURES  # noqa: E402

OUT = ROOT / "tests" / "fixtures" / "midi"


def main() -> int:
    for name, build in FIXTURES.items():
        path = OUT / name
        path.parent.mkdir(parents=True, exist_ok=True)
        data = build()
        path.write_bytes(data)
        print(f"wrote {path.relative_to(ROOT)} ({len(data)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
