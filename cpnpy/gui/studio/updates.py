"""Checking for a newer CPNpy, and installing it from within the app.

The latest release is asked of GitHub (no account needed for a public
repository), its version compared with the running one, and, if it is newer,
the download for this system is chosen by the names the build gives them
(``packaging/build.py``)::

    CPNpy-<version>-macOS-<arch>.dmg
    CPNpy-<version>-Windows-<arch>.zip
    CPNpy-<version>-Linux-<arch>.tar.gz

Installing replaces the app the user is running.  The app cannot overwrite
itself while it runs, so it downloads and unpacks the new version, writes a
small script that waits for the app to quit, swaps the old app for the new
one (keeping the old one until the new one is in place) and starts it, and
then quits.  CPNpy run from source (``git clone`` + ``pip install -e``) is
never touched: it only gets told what to run.

Everything but :class:`UpdateDialog` (at the end) works without a window.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from urllib.request import Request, urlopen

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QTextBrowser, QVBoxLayout

from ... import __version__

REPOSITORY = "s4mstruthers/CPNpy"
LATEST_URL = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPOSITORY}/releases/latest"


# ---------------------------------------------------------------------------
# Versions
# ---------------------------------------------------------------------------
def parse_version(text: str) -> tuple:
    """``"v0.10.2"`` → ``(0, 10, 2, 1)``; a pre-release (``0.3.0rc1``, ``0.3.0-beta``)
    sorts before its release: ``(0, 3, 0, 0)``."""
    match = re.match(r"^\s*v?(\d+(?:\.\d+)*)(.*)$", text or "")
    if match is None:
        return (0,)
    numbers = [int(part) for part in match.group(1).split(".")]
    while len(numbers) < 3:
        numbers.append(0)
    final = 0 if match.group(2).strip(" .-+") and not match.group(2).startswith("+") else 1
    return (*numbers, final)


def is_newer(latest: str, current: str = __version__) -> bool:
    return parse_version(latest) > parse_version(current)


# ---------------------------------------------------------------------------
# This system and this installation
# ---------------------------------------------------------------------------
def system_name() -> str:
    """As in the download names (see ``packaging/build.py``)."""
    return {"darwin": "macOS", "win32": "Windows"}.get(sys.platform, "Linux")


def architecture() -> str:
    machine = platform.machine().lower()
    return {"amd64": "x64", "x86_64": "x64", "arm64": "arm64",
            "aarch64": "arm64"}.get(machine, machine)


def installed_app() -> Path | None:
    """The app being run (``CPNpy.app`` or the ``CPNpy`` folder), or None from source."""
    if not getattr(sys, "frozen", False):
        return None
    executable = Path(sys.executable).resolve()
    if sys.platform == "darwin":
        bundle = executable.parents[2]          # CPNpy.app/Contents/MacOS/CPNpy
        return bundle if bundle.suffix == ".app" else None
    return executable.parent                    # CPNpy/CPNpy(.exe)


# ---------------------------------------------------------------------------
# The latest release
# ---------------------------------------------------------------------------
@dataclass
class Release:
    version: str                     # "0.3.0"
    tag: str                         # "v0.3.0"
    notes: str                       # Markdown
    page: str                        # the release's web page
    assets: dict[str, str] = field(default_factory=dict)     # file name → download URL
    #: file name → SHA-256 (hex), as GitHub computes it for every upload
    digests: dict[str, str] = field(default_factory=dict)
    prerelease: bool = False

    @classmethod
    def from_github(cls, data: dict) -> "Release":
        tag = data.get("tag_name") or ""
        return cls(version=tag.lstrip("vV"), tag=tag, notes=data.get("body") or "",
                   page=data.get("html_url") or RELEASES_PAGE,
                   assets={a["name"]: a["browser_download_url"]
                           for a in data.get("assets", [])
                           if a.get("name") and a.get("browser_download_url")},
                   digests={a["name"]: a["digest"].split(":", 1)[1].lower()
                            for a in data.get("assets", [])
                            if a.get("name") and str(a.get("digest", "")).startswith("sha256:")},
                   prerelease=bool(data.get("prerelease") or data.get("draft")))

    def download_for(self, system: str | None = None,
                     arch: str | None = None) -> tuple[str, str] | None:
        """(file name, URL) of the app for this system, or None if there is none."""
        system, arch = system or system_name(), arch or architecture()
        extension = {"macOS": ".dmg", "Windows": ".zip"}.get(system, ".tar.gz")
        wanted = f"-{system}-{arch}{extension}".lower()
        for name, url in self.assets.items():
            if name.lower().startswith("cpnpy-") and name.lower().endswith(wanted):
                return name, url
        return None

    def checksum_for(self, name: str) -> str | None:
        """The SHA-256 GitHub reports for ``name`` (None for an old upload without one)."""
        return self.digests.get(name)


def _get(url: str, timeout: float) -> bytes:
    request = Request(url, headers={"Accept": "application/vnd.github+json",
                                    "User-Agent": f"CPNpy/{__version__}"})
    with urlopen(request, timeout=timeout) as response:      # noqa: S310 - https only
        return response.read()


def fetch_latest(timeout: float = 10.0) -> Release:
    """The latest published release (raises on a network or GitHub problem)."""
    return Release.from_github(json.loads(_get(LATEST_URL, timeout)))


# ---------------------------------------------------------------------------
# Downloading and installing
# ---------------------------------------------------------------------------
def download(url: str, target: Path, progress: Callable[[int, int], None] | None = None,
             cancelled: Callable[[], bool] | None = None, timeout: float = 30.0) -> Path:
    """Download ``url`` to ``target``, reporting (bytes so far, total) as it goes."""
    request = Request(url, headers={"User-Agent": f"CPNpy/{__version__}"})
    with urlopen(request, timeout=timeout) as response, open(target, "wb") as out:  # noqa: S310
        total = int(response.headers.get("Content-Length") or 0)
        done = 0
        while chunk := response.read(1 << 16):
            if cancelled is not None and cancelled():
                raise InterruptedError("cancelled")
            out.write(chunk)
            done += len(chunk)
            if progress is not None:
                progress(done, total)
    return target


def verify(path: Path, expected: str) -> bool:
    """Does the file's SHA-256 match ``expected`` (hex)?"""
    expected = expected.strip().lower()
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest() == expected


def unpack(archive: Path, folder: Path) -> Path:
    """The new app out of the download: ``CPNpy.app`` (macOS) or the ``CPNpy`` folder."""
    name = archive.name.lower()
    if name.endswith(".dmg"):
        mount = folder / "mounted"
        mount.mkdir()
        subprocess.run(["hdiutil", "attach", "-nobrowse", "-readonly", "-noautoopen",
                        "-mountpoint", str(mount), str(archive)], check=True,
                       capture_output=True, timeout=120)
        try:
            app = next(mount.glob("*.app"))
            target = folder / app.name
            # ditto keeps the bundle exactly (symlinks, permissions, signature).
            subprocess.run(["ditto", str(app), str(target)], check=True,
                           capture_output=True, timeout=300)
        finally:
            subprocess.run(["hdiutil", "detach", str(mount), "-quiet"], check=False,
                           capture_output=True, timeout=60)
        return target
    out = folder / "unpacked"
    if name.endswith(".zip"):
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(out)
    else:
        with tarfile.open(archive) as bundle:
            bundle.extractall(out, filter="data") if hasattr(tarfile, "data_filter") \
                else bundle.extractall(out)  # noqa: S202 - our own release
    found = [p for p in out.iterdir() if p.is_dir()]
    return found[0] if len(found) == 1 else out


def looks_like_cpnpy(app: Path) -> bool:
    """A safety check before the old app is replaced: is this really CPNpy?"""
    if sys.platform == "darwin":
        return app.suffix == ".app" and (app / "Contents" / "MacOS" / "CPNpy").exists()
    if sys.platform == "win32":
        return (app / "CPNpy.exe").exists()
    return (app / "CPNpy").exists()


def installer_script(new: Path, old: Path, pid: int, work: Path,
                     system: str | None = None) -> tuple[Path, list[str]]:
    """Write the script that swaps the apps once this one has quit; (script, command).

    The old app is renamed out of the way first and only removed once the
    new one is in its place; if that fails, the old one is put back.
    """
    system = system or system_name()
    if system == "Windows":
        script = work / "install-update.bat"
        executable = old / "CPNpy.exe"
        script.write_text(
            "@echo off\r\n"
            ":wait\r\n"
            f'tasklist /FI "PID eq {pid}" 2>NUL | find "{pid}" >NUL\r\n'
            "if not errorlevel 1 (timeout /t 1 /nobreak >NUL & goto wait)\r\n"
            f'move "{old}" "{old}.previous" >NUL || exit /b 1\r\n'
            f'move "{new}" "{old}" >NUL || (move "{old}.previous" "{old}" >NUL & exit /b 1)\r\n'
            f'rmdir /s /q "{old}.previous"\r\n'
            f'start "" "{executable}"\r\n'
            f'rmdir /s /q "{work}"\r\n', encoding="utf-8")
        return script, ["cmd", "/c", str(script)]
    script = work / "install-update.sh"
    start = f'open "{old}"' if system == "macOS" else f'"{old}/CPNpy" >/dev/null 2>&1 &'
    quarantine = (f'xattr -dr com.apple.quarantine "{old}" 2>/dev/null\n'
                  if system == "macOS" else "")
    script.write_text(
        "#!/bin/sh\n"
        f"while kill -0 {pid} 2>/dev/null; do sleep 0.5; done\n"
        f'rm -rf "{old}.previous"\n'
        f'mv "{old}" "{old}.previous" || exit 1\n'
        f'if mv "{new}" "{old}"; then rm -rf "{old}.previous"; '
        f'else mv "{old}.previous" "{old}"; exit 1; fi\n'
        + quarantine +
        f"{start}\n"
        f'rm -rf "{work}"\n', encoding="utf-8")
    script.chmod(0o755)
    return script, ["/bin/sh", str(script)]


def prepare(release: Release, progress: Callable[[int, int], None] | None = None,
            cancelled: Callable[[], bool] | None = None) -> list[str]:
    """Download, check and unpack the update; the command that installs it.

    Run the command (detached) and quit the app: the command waits for that.
    """
    app = installed_app()
    if app is None or not looks_like_cpnpy(app):
        raise RuntimeError("This copy of CPNpy was not installed from a download, so it "
                           "cannot update itself.")
    if not os.access(app.parent, os.W_OK):
        raise PermissionError(f"CPNpy cannot replace itself in {app.parent} (no permission "
                              "to write there).")
    chosen = release.download_for()
    if chosen is None:
        raise RuntimeError(f"Release {release.tag} has no download for {system_name()} "
                           f"({architecture()}).")
    name, url = chosen
    # Unpack next to the app, so the final move is a rename on one disk.
    work = Path(tempfile.mkdtemp(prefix=".cpnpy-update-", dir=app.parent))
    try:
        archive = download(url, work / name, progress, cancelled)
        checksum = release.checksum_for(name)
        if checksum is not None and not verify(archive, checksum):
            raise RuntimeError(f"{name} did not download correctly (its checksum does not "
                               "match). Try again later.")
        new = unpack(archive, work)
        if not looks_like_cpnpy(new):
            raise RuntimeError(f"{name} does not contain the CPNpy app.")
        archive.unlink()
        _, command = installer_script(new, app, os.getpid(), work)
    except BaseException:
        shutil.rmtree(work, ignore_errors=True)
        raise
    return command


def run_detached(command: list[str]) -> None:
    """Start the installer so that it outlives the app."""
    if sys.platform == "win32":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        subprocess.Popen(command, creationflags=flags, close_fds=True)  # noqa: S603
    else:
        subprocess.Popen(command, start_new_session=True, close_fds=True,  # noqa: S603
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ---------------------------------------------------------------------------
# The dialog
# ---------------------------------------------------------------------------
class UpdateDialog(QDialog):
    """"CPNpy 0.3.0 is available": its release notes, and what to do about it."""

    INSTALL, LATER, SKIP, PAGE = range(4)

    def __init__(self, release: Release, can_install: bool, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Software Update")
        self.setMinimumSize(520, 420)
        self.outcome = self.LATER
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        heading = QLabel(f"<b>CPNpy {release.version} is available</b> — you have "
                         f"{__version__}.")
        heading.setWordWrap(True)
        layout.addWidget(heading)
        notes = QTextBrowser()
        notes.setOpenExternalLinks(True)
        notes.setMarkdown(release.notes or "_No release notes._")
        layout.addWidget(notes, 1)
        if not can_install:
            hint = QLabel("You are running CPNpy from its source code, which it does not "
                          "change by itself. To update, run <code>git pull</code> in your "
                          "CPNpy folder, then <code>conda env update -f environment.yml "
                          "--prune</code> (or <code>pip install -e \".[gui]\"</code>).")
            hint.setWordWrap(True)
            layout.addWidget(hint)
        buttons = QDialogButtonBox()
        if can_install:
            install = buttons.addButton("Download && Install", QDialogButtonBox.AcceptRole)
            install.clicked.connect(lambda: self._finish(self.INSTALL))
            install.setDefault(True)
        else:
            page = buttons.addButton("Open Release Page", QDialogButtonBox.AcceptRole)
            page.clicked.connect(lambda: self._finish(self.PAGE))
        buttons.addButton("Later", QDialogButtonBox.RejectRole).clicked.connect(
            lambda: self._finish(self.LATER))
        buttons.addButton("Skip This Version", QDialogButtonBox.DestructiveRole) \
            .clicked.connect(lambda: self._finish(self.SKIP))
        layout.addWidget(buttons)

    def _finish(self, outcome: int) -> None:
        self.outcome = outcome
        if outcome in (self.INSTALL, self.PAGE):
            self.accept()
        else:
            self.reject()
