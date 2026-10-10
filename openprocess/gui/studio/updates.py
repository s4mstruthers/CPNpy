"""Checking for a newer OpenProcess, and installing it from within the app.

The latest release is asked of GitHub (no account needed for a public
repository), its version compared with the running one, and, if it is newer,
the download for this system is chosen by the names the build gives them
(``packaging/build.py``)::

    OpenProcess-<version>-macOS-<arch>.dmg
    OpenProcess-<version>-Windows-<arch>.zip
    OpenProcess-<version>-Linux-<arch>.tar.gz

Installing depends on how this copy was installed (:func:`how_installed`):

* **a downloaded app** cannot overwrite itself while it runs, so it
  downloads and unpacks the new version, writes a small script that waits
  for the app to quit, swaps the old app for the new one (keeping the old
  one until the new one is in place) and starts it, and then quits;
* **a pip install** runs ``pip install --upgrade "openprocess[app]"`` in
  the same Python and restarts;
* **a checkout** (``git clone`` + ``pip install -e``) runs ``git pull`` and
  the editable install again and restarts, but only when the checkout has
  no uncommitted changes; a copy without ``.git`` is only told what to run.

A release without a download for this system (as 0.7.0 was for CPNpy, whose
files have another name) can only be opened on the release page.

Everything but :class:`UpdateDialog` (at the end) works without a window.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import ssl
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from urllib.request import Request, urlopen

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QLabel, QPushButton, QTextBrowser, QToolButton,
    QVBoxLayout,
)

from ... import __version__

REPOSITORY = "s4mstruthers/openprocess"
RELEASES_URL = f"https://api.github.com/repos/{REPOSITORY}/releases?per_page=30"
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
    """The app being run (``OpenProcess.app`` or the ``OpenProcess`` folder), or None from source."""
    if not getattr(sys, "frozen", False):
        return None
    executable = Path(sys.executable).resolve()
    if sys.platform == "darwin":
        bundle = executable.parents[2]          # OpenProcess.app/Contents/MacOS/OpenProcess
        return bundle if bundle.suffix == ".app" else None
    return executable.parent                    # OpenProcess/OpenProcess(.exe)


@dataclass(frozen=True)
class Install:
    """How this copy of OpenProcess was installed, which decides how it updates."""

    #: ``"app"``: a downloaded bundle; ``"source"``: a checkout; ``"pip"``: a package.
    kind: str
    #: The bundle, the checkout's folder, or the package's folder.
    path: Path
    #: A checkout with a ``.git`` folder, so ``git pull`` works.
    git: bool = False


def _package_dir() -> Path:
    from ... import __file__ as package_init
    return Path(package_init).resolve().parent


def how_installed() -> Install:
    app = installed_app()
    if app is not None:
        return Install("app", app)
    package = _package_dir()
    root = package.parent
    if (root / "pyproject.toml").is_file():
        return Install("source", root, git=(root / ".git").exists())
    return Install("pip", package)


def update_way(install: Install, release: "Release") -> str | None:
    """How ``release`` can be installed over ``install``: ``"app"`` (download and
    swap), ``"pip"`` (pip in the same environment), ``"source"`` (``git pull``
    and the editable install again), or None (only the release page helps)."""
    if install.kind == "app":
        return "app" if release.download_for() is not None else None
    if install.kind == "pip":
        return "pip"
    if install.kind == "source" and install.git:
        return "source"
    return None


def update_commands(install: Install, release: "Release", way: str) -> list[list[str]]:
    """The commands that update a pip install or a checkout, in order."""
    python = sys.executable
    if way == "pip":
        return [[python, "-m", "pip", "install", "--upgrade", f"openprocess[app]=={release.version}"]]
    if way == "source":
        return [["git", "-C", str(install.path), "pull", "--ff-only"],
                [python, "-m", "pip", "install", "-e", f"{install.path}[app]"]]
    raise ValueError(f"no commands for {way!r}")


def run_update(install: Install, release: "Release", way: str, run=subprocess.run) -> str:
    """Run the update commands; their output, or :class:`RuntimeError` with it."""
    if way == "source":
        status = run(["git", "-C", str(install.path), "status", "--porcelain"],
                     capture_output=True, text=True)
        if status.returncode == 0 and status.stdout.strip():
            raise RuntimeError("The checkout has uncommitted changes, which git pull would have "
                               "to merge. Commit or stash them, then update again.")
    output: list[str] = []
    for command in update_commands(install, release, way):
        output.append("$ " + " ".join(command))
        result = run(command, capture_output=True, text=True)
        output.append(((result.stdout or "") + (result.stderr or "")).strip())
        if result.returncode != 0:
            raise RuntimeError("\n".join(output).strip())
    return "\n".join(output).strip()


def restart_command() -> list[str]:
    """The command that starts this OpenProcess again (after a pip or source update)."""
    if getattr(sys, "frozen", False):
        return [sys.executable] + sys.argv[1:]
    return [sys.executable] + sys.argv


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
            if name.lower().startswith("openprocess-") and name.lower().endswith(wanted):
                return name, url
        return None

    def checksum_for(self, name: str) -> str | None:
        """The SHA-256 GitHub reports for ``name`` (None for an old upload without one)."""
        return self.digests.get(name)


def ssl_context() -> ssl.SSLContext:
    """Certificates to trust when talking to GitHub.

    The standalone app carries its own Python, which cannot find the
    system's certificates (on macOS it then fails with "CERTIFICATE_VERIFY_
    FAILED: unable to get local issuer certificate"), so it uses certifi's
    bundle; PyInstaller packs that file into the app.  Without certifi (run
    from source), the system's own certificates are used.
    """
    try:
        import certifi
    except ImportError:
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=certifi.where())


def _get(url: str, timeout: float) -> bytes:
    request = Request(url, headers={"Accept": "application/vnd.github+json",
                                    "User-Agent": f"OpenProcess/{__version__}"})
    with urlopen(request, timeout=timeout, context=ssl_context()) as response:  # noqa: S310
        return response.read()


def fetch_latest(timeout: float = 10.0, current: str = __version__) -> Release:
    """The newest published release (raises on a network or GitHub problem).

    Its :attr:`~Release.notes` say what is new in every version newer than
    ``current``, newest first, so someone several versions behind sees all of
    it, not just the last step.
    """
    releases = [Release.from_github(data) for data in json.loads(_get(RELEASES_URL, timeout))
                if isinstance(data, dict) and not data.get("draft")]
    releases = sorted((r for r in releases if not r.prerelease),
                      key=lambda r: parse_version(r.version), reverse=True)
    if not releases:
        raise RuntimeError("OpenProcess has no published releases yet.")
    latest = releases[0]
    newer = [r for r in releases if is_newer(r.version, current)]
    if len(newer) > 1:
        latest.notes = "\n\n".join(f"### What's new in {r.version}\n\n"
                                    f"{r.notes.strip() or '_No notes._'}" for r in newer)
    return latest


# ---------------------------------------------------------------------------
# Downloading and installing
# ---------------------------------------------------------------------------
def download(url: str, target: Path, progress: Callable[[int, int], None] | None = None,
             cancelled: Callable[[], bool] | None = None, timeout: float = 30.0) -> Path:
    """Download ``url`` to ``target``, reporting (bytes so far, total) as it goes."""
    request = Request(url, headers={"User-Agent": f"OpenProcess/{__version__}"})
    with urlopen(request, timeout=timeout, context=ssl_context()) as response, \
            open(target, "wb") as out:  # noqa: S310
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
    """The new app out of the download: ``OpenProcess.app`` (macOS) or the ``OpenProcess`` folder."""
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


def looks_like_openprocess(app: Path) -> bool:
    """A safety check before the old app is replaced: is this really OpenProcess?"""
    if sys.platform == "darwin":
        return app.suffix == ".app" and (app / "Contents" / "MacOS" / "OpenProcess").exists()
    if sys.platform == "win32":
        return (app / "OpenProcess.exe").exists()
    return (app / "OpenProcess").exists()


def installer_script(new: Path, old: Path, pid: int, work: Path,
                     system: str | None = None) -> tuple[Path, list[str]]:
    """Write the script that swaps the apps once this one has quit; (script, command).

    The old app is renamed out of the way first and only removed once the
    new one is in its place; if that fails, the old one is put back.
    """
    system = system or system_name()
    if system == "Windows":
        script = work / "install-update.bat"
        executable = old / "OpenProcess.exe"
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
    start = f'open "{old}"' if system == "macOS" else f'"{old}/OpenProcess" >/dev/null 2>&1 &'
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
    if app is None or not looks_like_openprocess(app):
        raise RuntimeError("This copy of OpenProcess was not installed from a download, so it "
                           "cannot update itself.")
    if not os.access(app.parent, os.W_OK):
        raise PermissionError(f"OpenProcess cannot replace itself in {app.parent} (no permission "
                              "to write there).")
    chosen = release.download_for()
    if chosen is None:
        raise RuntimeError(f"Release {release.tag} has no download for {system_name()} "
                           f"({architecture()}).")
    name, url = chosen
    # Unpack next to the app, so the final move is a rename on one disk.
    work = Path(tempfile.mkdtemp(prefix=".openprocess-update-", dir=app.parent))
    try:
        archive = download(url, work / name, progress, cancelled)
        checksum = release.checksum_for(name)
        if checksum is not None and not verify(archive, checksum):
            raise RuntimeError(f"{name} did not download correctly (its checksum does not "
                               "match). Try again later.")
        new = unpack(archive, work)
        if not looks_like_openprocess(new):
            raise RuntimeError(f"{name} does not contain the OpenProcess app.")
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
    """"OpenProcess 0.3.0 is available": its release notes, and what to do about it."""

    INSTALL, LATER, SKIP, PAGE = range(4)

    def __init__(self, release: Release, can_install: bool, parent=None,
                 install: Install | None = None, way: str | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Software Update")
        self.setMinimumSize(520, 420)
        self.outcome = self.LATER
        install = install or how_installed()
        if way is None and can_install:
            way = update_way(install, release) or "app"
        if not can_install:
            way = None
        self.way = way
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        heading = QLabel(f"<b>OpenProcess {release.version} is available</b> — you have "
                         f"{__version__}. Here is what's new:")
        heading.setWordWrap(True)
        layout.addWidget(heading)
        notes = QTextBrowser()
        notes.setOpenExternalLinks(True)
        notes.setMarkdown(release.notes or "_No release notes._")
        layout.addWidget(notes, 1)
        text = update_hint(install, release, way)
        if text:
            hint = QLabel(text)
            hint.setWordWrap(True)
            hint.setOpenExternalLinks(True)
            layout.addWidget(hint)
        buttons = QDialogButtonBox()
        if way == "app":
            action = buttons.addButton("Download && Install", QDialogButtonBox.AcceptRole)
            action.clicked.connect(lambda: self._finish(self.INSTALL))
            action.setDefault(True)
        elif way in ("pip", "source"):
            action = buttons.addButton("Update && Restart", QDialogButtonBox.AcceptRole)
            action.clicked.connect(lambda: self._finish(self.INSTALL))
            action.setDefault(True)
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


def update_hint(install: Install, release: Release, way: str | None) -> str:
    """What the dialog says under the notes: how this copy updates, or why it cannot."""
    if way == "app":
        return ""
    if way == "pip":
        return ("You installed OpenProcess with pip. <i>Update &amp; Restart</i> runs "
                "<code>pip install --upgrade \"openprocess[app]\"</code> in this same Python, then "
                "starts OpenProcess again.")
    if way == "source":
        return (f"You are running OpenProcess from a checkout ({install.path}). <i>Update &amp; "
                "Restart</i> runs <code>git pull</code> there and <code>pip install -e "
                "\".[app]\"</code> in this Python (a conda environment keeps working), then starts "
                "OpenProcess again. It refuses while the checkout has uncommitted changes.")
    if install.kind == "app":
        return (f"This release has no download for {system_name()} ({architecture()}), so it "
                "cannot be installed from here. The release page shows what it has.")
    if install.kind == "source":
        return (f"You are running OpenProcess from a copy of its source ({install.path}) that is "
                "not a git checkout, so it cannot update itself. Get the new version from the "
                "release page, or clone the repository and run <code>pip install -e "
                "\".[app]\"</code>.")
    return ""


class UpdateBar(QFrame):
    """A slim bar at the top of the window: a new version is out.

    Shown by the check at launch instead of a dialog, so it never gets in
    the way: carry on working, or choose What's New, Install Now (or, run
    from source, How to Update), Skip This Version, or close it (✕).
    """

    whats_new = Signal()
    install = Signal()
    skip = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("updateBar")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 7, 8, 7)
        layout.setSpacing(8)
        self.text = QLabel()
        self.text.setWordWrap(True)
        layout.addWidget(self.text, 1)
        self.notes_button = QPushButton("What's New")
        self.notes_button.clicked.connect(self.whats_new.emit)
        self.install_button = QPushButton("Install Now")
        self.install_button.setObjectName("primary")
        self.install_button.clicked.connect(self.install.emit)
        self.skip_button = QPushButton("Skip This Version")
        self.skip_button.clicked.connect(self.skip.emit)
        close = QToolButton()
        close.setObjectName("updateBarClose")
        close.setText("✕")
        close.setToolTip("Close (you are reminded next time OpenProcess opens)")
        close.clicked.connect(self.hide)
        for widget in (self.notes_button, self.install_button, self.skip_button, close):
            layout.addWidget(widget)
        self.release: Release | None = None
        self.setVisible(False)

    def offer(self, release: Release, can_install: bool, way: str | None = None) -> None:
        self.release = release
        self.text.setText(f"<b>OpenProcess {release.version} is available</b> — you have "
                          f"{__version__}.")
        if not can_install:
            label = "How to Update"
        elif way in ("pip", "source"):
            label = "Update Now"
        else:
            label = "Install Now"
        self.install_button.setText(label)
        self.setVisible(True)
