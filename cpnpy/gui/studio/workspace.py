"""Workspace folders: a folder such as "Week 2" as the unit you work in.

Opening a folder as a workspace (File ▸ Open Workspace Folder…) makes the
sidebar list every event log and Petri net in it, opened or not, and makes
save dialogs start in it.  This module is the part that does not need Qt:

* :meth:`Workspace.files` -- which files in the folder the app can open;
* :meth:`Workspace.load_state` / :meth:`Workspace.save_state` -- which of
  them were open, so the workspace comes back as you left it.

The state lives in a small hidden JSON file, ``.cpnpy``, inside the folder.
Paths in it are relative to the folder, so the workspace still works after
the folder is moved, renamed or synced to another computer (iCloud, a USB
stick, a Git repository).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: What the app can open, by extension, and the sidebar section it goes in.
KINDS = {
    ".xes": "log",
    ".xes.gz": "log",
    ".csv": "log",
    ".pnml": "petri",
    ".cpn": "cpn",
}

#: The hidden file holding the workspace's state.
STATE_FILE = ".cpnpy"

#: How deep into subfolders to look ("Week 2/logs/boarding.xes" is depth 1).
MAX_DEPTH = 3

#: Stop listing after this many files, so opening a huge folder by mistake
#: (your home folder, say) does not freeze the window.
MAX_FILES = 500

#: Folders never looked into: tools' caches and the like.
SKIPPED_FOLDERS = {"__pycache__", "node_modules", "build", "dist", "venv", ".venv"}


def file_kind(path: Path) -> str | None:
    """``"log"``, ``"petri"``, ``"cpn"`` or ``None`` for a file the app cannot open."""
    name = path.name.lower()
    if name.endswith(".xes.gz"):
        return KINDS[".xes.gz"]
    return KINDS.get(path.suffix.lower())


def display_name(relative: str) -> str:
    """The name shown in the sidebar: the path inside the folder, without extension.

    ``"order handling.pnml"`` → ``"order handling"``;
    ``"logs/boarding.xes.gz"`` → ``"logs/boarding"``.
    """
    lower = relative.lower()
    for extension in sorted(KINDS, key=len, reverse=True):     # ".xes.gz" before ".gz"
        if lower.endswith(extension):
            return relative[: len(relative) - len(extension)]
    return relative


@dataclass(frozen=True)
class WorkspaceFile:
    """One file in the workspace that the app can open."""

    path: Path          # absolute
    relative: str       # inside the folder, with "/" separators
    kind: str           # "log", "petri" or "cpn"

    @property
    def name(self) -> str:
        return display_name(self.relative)


class Workspace:
    """A folder opened as a workspace."""

    def __init__(self, folder: str | Path) -> None:
        self.folder = Path(folder).expanduser().resolve()

    @property
    def name(self) -> str:
        return self.folder.name or str(self.folder)

    def exists(self) -> bool:
        return self.folder.is_dir()

    # -- the files ---------------------------------------------------------------
    def files(self) -> list[WorkspaceFile]:
        """Every file the app can open, sorted by path (subfolders after files).

        Hidden files and folders (starting with ".") are skipped, as Finder
        does, and so are the folders in :data:`SKIPPED_FOLDERS`.
        """
        found: list[WorkspaceFile] = []
        for directory, folders, names in os.walk(self.folder):
            here = Path(directory)
            depth = len(here.relative_to(self.folder).parts)
            # Prune in place: os.walk then does not descend into these.
            folders[:] = sorted(f for f in folders if not f.startswith(".")
                                and f not in SKIPPED_FOLDERS and depth < MAX_DEPTH)
            for name in sorted(names, key=str.lower):
                if name.startswith("."):
                    continue
                path = here / name
                kind = file_kind(path)
                if kind is None:
                    continue
                relative = path.relative_to(self.folder).as_posix()
                found.append(WorkspaceFile(path, relative, kind))
                if len(found) >= MAX_FILES:
                    return found
        return found

    def directories(self) -> list[Path]:
        """The folders whose changes matter (for a file system watcher)."""
        result = [self.folder]
        for directory, folders, _names in os.walk(self.folder):
            here = Path(directory)
            depth = len(here.relative_to(self.folder).parts)
            folders[:] = [f for f in folders if not f.startswith(".")
                          and f not in SKIPPED_FOLDERS and depth < MAX_DEPTH]
            result += [here / f for f in folders]
            if len(result) > 200:
                break
        return result

    def contains(self, path: str | Path) -> bool:
        try:
            Path(path).resolve().relative_to(self.folder)
        except (ValueError, OSError):
            return False
        return True

    def relative(self, path: str | Path) -> str:
        """``path`` relative to the folder if it is inside it, else absolute."""
        resolved = Path(path).resolve()
        try:
            return resolved.relative_to(self.folder).as_posix()
        except ValueError:
            return str(resolved)

    def absolute(self, stored: str) -> Path:
        """The inverse of :meth:`relative`."""
        path = Path(stored)
        return path if path.is_absolute() else self.folder / path

    # -- what was open -----------------------------------------------------------
    @property
    def state_path(self) -> Path:
        return self.folder / STATE_FILE

    def load_state(self) -> dict[str, Any]:
        """``{"open": [{"path": …, …options}], "selected": path | None}``; empty if none."""
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"open": [], "selected": None}
        entries = [e for e in data.get("open", []) if isinstance(e, dict) and e.get("path")]
        for entry in entries:
            entry["path"] = str(self.absolute(entry["path"]))
        selected = data.get("selected")
        return {"open": entries,
                "selected": str(self.absolute(selected)) if selected else None}

    def save_state(self, entries: list[dict[str, Any]], selected: str | None) -> None:
        """Remember the open files.  Never fails: a read-only folder just is not written."""
        data = {
            "about": "CPNpy workspace: the files that were open. Safe to delete.",
            "version": 1,
            "open": [dict(entry, path=self.relative(entry["path"])) for entry in entries],
            "selected": self.relative(selected) if selected else None,
        }
        text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
        try:
            if self.state_path.exists() and self.state_path.read_text(encoding="utf-8") == text:
                return                      # unchanged: do not touch the file (or its sync)
            if not entries and not self.state_path.exists():
                return                      # nothing worth a file yet
            self.state_path.write_text(text, encoding="utf-8")
        except OSError:
            pass
