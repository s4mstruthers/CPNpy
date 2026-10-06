"""Print a version's section of CHANGELOG.md: the release's description.

    python packaging/release_notes.py 0.3.2 > notes.md

The release workflow uses this as the text of the GitHub release, which is
what the app shows when it offers the update.  Exits with an error when the
changelog has no section for that version, so a release is never published
without saying what is new.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

CHANGELOG = Path(__file__).resolve().parents[1] / "CHANGELOG.md"


def section(version: str, text: str | None = None) -> str | None:
    """The text under ``## <version>`` (without the heading), or None."""
    text = CHANGELOG.read_text(encoding="utf-8") if text is None else text
    version = version.lstrip("vV")
    match = re.search(rf"^##\s+v?{re.escape(version)}\s*$(.*?)(?=^##\s|\Z)", text,
                      re.M | re.S)
    if match is None or not match.group(1).strip():
        return None
    return match.group(1).strip() + "\n"


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    notes = section(argv[1])
    if notes is None:
        print(f"CHANGELOG.md has no section '## {argv[1].lstrip('vV')}': say what is new "
              "in this version before releasing it.", file=sys.stderr)
        return 1
    sys.stdout.write(notes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
