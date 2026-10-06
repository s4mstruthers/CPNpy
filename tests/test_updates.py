"""Checking for updates and installing them (no network: GitHub is faked)."""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from cpnpy.gui.studio import updates  # noqa: E402
from cpnpy.gui.studio.updates import Release, is_newer, parse_version  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

GITHUB_ANSWER = {
    "tag_name": "v0.3.0",
    "html_url": "https://github.com/s4mstruthers/CPNpy/releases/tag/v0.3.0",
    "body": "## What's new\n- Folders stay in sync",
    "prerelease": False,
    "assets": [{"name": n, "browser_download_url": f"https://example.invalid/{n}",
                "digest": "sha256:" + "AB" * 32} for n in (
        "CPNpy-0.3.0-Linux-x64.tar.gz", "CPNpy-0.3.0-macOS-arm64.dmg",
        "CPNpy-0.3.0-macOS-x64.dmg", "CPNpy-0.3.0-Windows-x64.zip")]
    + [{"name": "CPNpy-0.2.0-old.zip", "browser_download_url": "https://example.invalid/old"}],
}


def test_one_version_number_everywhere():
    import cpnpy
    text = (ROOT / "pyproject.toml").read_text()
    assert 'dynamic = ["version"]' in text and 'attr = "cpnpy.__version__"' in text
    assert not re.search(r'^version\s*=\s*"', text, re.M)        # no second copy
    sys.path.insert(0, str(ROOT / "packaging"))
    try:
        import build
        assert build.version() == cpnpy.__version__
    finally:
        sys.path.remove(str(ROOT / "packaging"))
    assert updates.__version__ == cpnpy.__version__


def test_versions_compare_as_numbers():
    assert parse_version("v0.2.0") == (0, 2, 0, 1) == parse_version("0.2")
    assert is_newer("v0.10.0", "0.9.9") and not is_newer("v0.2.0", "0.2.0")
    assert not is_newer("0.1.9", "0.2.0")
    assert parse_version("0.3.0rc1") < parse_version("0.3.0") < parse_version("0.3.1")
    assert parse_version("nonsense") == (0,)


def test_the_right_download_for_each_system():
    release = Release.from_github(GITHUB_ANSWER)
    assert (release.version, release.tag, release.prerelease) == ("0.3.0", "v0.3.0", False)
    assert release.download_for("macOS", "arm64")[0] == "CPNpy-0.3.0-macOS-arm64.dmg"
    assert release.download_for("macOS", "x64")[0] == "CPNpy-0.3.0-macOS-x64.dmg"
    assert release.download_for("Windows", "x64")[0] == "CPNpy-0.3.0-Windows-x64.zip"
    assert release.download_for("Linux", "x64")[0] == "CPNpy-0.3.0-Linux-x64.tar.gz"
    assert release.download_for("Linux", "arm64") is None
    # GitHub's own SHA-256 of each upload (none for an old upload without one).
    assert release.checksum_for("CPNpy-0.3.0-macOS-arm64.dmg") == "ab" * 32
    assert release.checksum_for("CPNpy-0.2.0-old.zip") is None


def test_checksums(tmp_path):
    archive = tmp_path / "CPNpy.zip"
    archive.write_bytes(b"the app")
    digest = hashlib.sha256(b"the app").hexdigest()
    assert updates.verify(archive, digest) and updates.verify(archive, digest.upper())
    assert not updates.verify(archive, "0" * 64)
    assert not updates.verify(archive, "")


def test_running_from_source_never_updates_itself(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert updates.installed_app() is None
    with pytest.raises(RuntimeError, match="cannot update itself"):
        updates.prepare(Release.from_github(GITHUB_ANSWER))


@pytest.mark.skipif(sys.platform == "win32", reason="the shell script is for macOS and Linux")
def test_installer_swaps_the_app_once_it_has_quit(tmp_path):
    """The script waits for the app to quit, puts the new app in the old one's
    place (no leftovers) and starts it."""
    old, work = tmp_path / "CPNpy", tmp_path / ".cpnpy-update-x"
    new = work / "unpacked" / "CPNpy"
    marker = tmp_path / "started"
    for folder, text in ((old, "old"), (new, "new")):
        folder.mkdir(parents=True)
        (folder / "version.txt").write_text(text)
        program = folder / "CPNpy"
        program.write_text(f"#!/bin/sh\necho {text} > '{marker}'\n")
        program.chmod(0o755)
    # A process standing in for the app.  Started by a shell that exits at
    # once, so (like the real app) it is nobody's child here once it ends.
    pid = int(subprocess.run(["/bin/sh", "-c", "sleep 1 >/dev/null 2>&1 & echo $!"],
                             capture_output=True, text=True, check=True).stdout)
    script, command = updates.installer_script(new, old, pid, work, system="Linux")
    assert command == ["/bin/sh", str(script)]
    started = time.monotonic()
    subprocess.run(command, check=True, timeout=30)
    assert time.monotonic() - started >= 0.5            # it waited for the app to quit
    assert (old / "version.txt").read_text() == "new"
    assert not (tmp_path / "CPNpy.previous").exists() and not work.exists()
    for _ in range(100):                                # the new app was started
        if marker.exists():
            break
        time.sleep(0.05)
    assert marker.read_text().strip() == "new"


def test_installer_scripts_for_macos_and_windows(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    script, command = updates.installer_script(tmp_path / "new" / "CPNpy.app",
                                               tmp_path / "CPNpy.app", 42, work, system="macOS")
    text = script.read_text()
    assert "kill -0 42" in text and "xattr -dr com.apple.quarantine" in text
    assert f'open "{tmp_path / "CPNpy.app"}"' in text
    script, command = updates.installer_script(tmp_path / "new", tmp_path / "CPNpy", 42, work,
                                               system="Windows")
    text = script.read_text()
    assert command[:2] == ["cmd", "/c"] and '"PID eq 42"' in text
    assert "CPNpy.exe" in text and ".previous" in text


def _pump(app, seconds: float) -> None:
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def test_check_for_updates_in_the_app(monkeypatch):
    from PySide6.QtWidgets import QApplication

    from cpnpy.gui.studio import app as studio_app
    from cpnpy.gui.studio.app import StudioWindow

    application = QApplication.instance() or QApplication([])
    told, opened, shown = [], [], []
    monkeypatch.setattr(studio_app.QMessageBox, "information",
                        lambda *args, **kwargs: told.append(args[2]))
    monkeypatch.setattr(studio_app.QDesktopServices, "openUrl",
                        lambda url: opened.append(url.toString()))

    def fake_exec(dialog):
        shown.append(dialog)
        dialog.outcome = dialog.PAGE
        return 1
    monkeypatch.setattr(updates.UpdateDialog, "exec", fake_exec)

    window = StudioWindow()
    # Up to date.
    monkeypatch.setattr(updates, "fetch_latest", lambda: Release.from_github(
        dict(GITHUB_ANSWER, tag_name=f"v{updates.__version__}")))
    window.check_for_updates(manual=True)
    for _ in range(300):
        if told:
            break
        _pump(application, 0.01)
    assert told and "latest version" in told[0]

    # A newer one: from source it cannot install itself, so it offers the page.
    monkeypatch.setattr(updates, "fetch_latest", lambda: Release.from_github(
        dict(GITHUB_ANSWER, tag_name="v99.0.0")))         # newer than whatever runs
    window.check_for_updates(manual=True)
    for _ in range(300):
        if opened:
            break
        _pump(application, 0.01)
    assert opened == [GITHUB_ANSWER["html_url"]]
    assert len(shown) == 1
    # Tests never check by themselves (persist=False).
    shown.clear()
    window.check_automatically()
    _pump(application, 0.2)
    assert shown == []
    window.close()


def test_update_check_trusts_certifi_not_the_system(monkeypatch):
    """Regression (0.3.0): the standalone app's Python found no certificates,
    so checking GitHub failed with CERTIFICATE_VERIFY_FAILED.  The updater's
    connections use certifi's bundle, which works without the system's."""
    import ssl

    import certifi

    monkeypatch.setenv("SSL_CERT_FILE", "/nonexistent")       # as in the frozen app
    monkeypatch.setenv("SSL_CERT_DIR", "/nonexistent")
    assert ssl.create_default_context().cert_store_stats()["x509_ca"] == 0
    context = updates.ssl_context()
    assert context.cert_store_stats()["x509_ca"] > 50
    assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
    assert Path(certifi.where()).exists()

    used = []

    class Response:
        headers = {"Content-Length": "0"}

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self, *args):
            import json
            return json.dumps([GITHUB_ANSWER]).encode() if not args else b""

    def fake_urlopen(request, timeout, context=None):
        used.append(context)
        return Response()
    monkeypatch.setattr(updates, "urlopen", fake_urlopen)
    updates.fetch_latest()
    updates.download("https://example.invalid/x", Path(os.devnull))
    assert len(used) == 2 and all(c is not None and c.cert_store_stats()["x509_ca"] > 50
                                  for c in used)


def _github_list(*versions, prerelease=()):
    return [dict(GITHUB_ANSWER, tag_name=f"v{v}", body=f"- news in {v}",
                 prerelease=v in prerelease) for v in versions]


def test_notes_for_every_version_you_do_not_have(monkeypatch):
    import json

    # Two versions newer than 0.3.2: both their notes, newest first.
    monkeypatch.setattr(updates, "_get", lambda url, timeout: json.dumps(
        _github_list("0.3.1", "0.3.3", "0.4.0", "0.3.2", "0.5.0rc1",
                     prerelease=("0.5.0rc1",))).encode())
    latest = updates.fetch_latest(current="0.3.2")
    assert latest.version == "0.4.0"
    assert latest.notes.index("What's new in 0.4.0") < latest.notes.index("What's new in 0.3.3")
    assert "news in 0.4.0" in latest.notes and "news in 0.3.3" in latest.notes
    assert "0.3.2" not in latest.notes and "0.5.0rc1" not in latest.notes
    # One step behind: just that release's own notes.
    assert updates.fetch_latest(current="0.3.3").notes == "- news in 0.4.0"
    monkeypatch.setattr(updates, "_get", lambda url, timeout: b"[]")
    with pytest.raises(RuntimeError):
        updates.fetch_latest()


def test_release_notes_come_from_the_changelog():
    sys.path.insert(0, str(ROOT / "packaging"))
    try:
        import release_notes
    finally:
        sys.path.remove(str(ROOT / "packaging"))
    import cpnpy
    text = "# What's new\n\n## 0.4.0\n\n- A\n- B\n\n## 0.3.2\n\n- C\n"
    assert release_notes.section("v0.4.0", text) == "- A\n- B\n"
    assert release_notes.section("0.3.2", text) == "- C\n"
    assert release_notes.section("0.3.9", text) is None
    # The version being released always says what is new.
    assert release_notes.section(cpnpy.__version__) is not None or \
        release_notes.section("0.3.2") is not None


def test_a_new_version_at_launch_is_a_bar_not_a_dialog(monkeypatch):
    """The check at launch shows a bar at the top of the window: work goes on;
    What's New opens the notes, Install Now installs, Skip This Version and ✕
    put it away."""
    from PySide6.QtWidgets import QApplication

    from cpnpy.gui.studio.app import StudioWindow

    application = QApplication.instance() or QApplication([])
    dialogs, installs = [], []

    def fake_exec(dialog):
        dialogs.append(dialog)
        dialog.outcome = dialog.LATER
        return 0
    monkeypatch.setattr(updates.UpdateDialog, "exec", fake_exec)
    monkeypatch.setattr(updates, "fetch_latest", lambda: Release.from_github(
        dict(GITHUB_ANSWER, tag_name="v99.0.0", body="- Shiny things")))
    window = StudioWindow()
    window.show()
    monkeypatch.setattr(window, "_install_update", installs.append)
    monkeypatch.setattr(window, "_can_install", lambda release: True)
    bar = window.update_bar

    def check():
        window.check_for_updates(manual=False)
        for _ in range(300):
            if bar.isVisible():
                return
            _pump(application, 0.01)

    check()
    assert bar.isVisible() and dialogs == []                 # no dialog in the way
    assert "99.0.0 is available" in bar.text.text()
    assert bar.install_button.text() == "Install Now"
    bar.notes_button.click()                                 # What's New: the notes
    assert len(dialogs) == 1 and dialogs[0].findChild(updates.QTextBrowser) \
        .toPlainText().strip() == "Shiny things"
    assert bar.isVisible()                                   # "Later" leaves the bar
    bar.install_button.click()
    assert [r.version for r in installs] == ["99.0.0"] and not bar.isVisible()

    check()
    bar.skip_button.click()
    assert not bar.isVisible()
    check()
    bar.findChild(updates.QToolButton).click()               # ✕
    assert not bar.isVisible()
    window.close()


def test_running_from_source_only_says_how_to_update(monkeypatch):
    """From a git clone the bar offers How to Update, which explains `git pull`;
    nothing is downloaded or replaced."""
    from PySide6.QtWidgets import QApplication

    from cpnpy.gui.studio.app import StudioWindow

    application = QApplication.instance() or QApplication([])
    monkeypatch.delattr(sys, "frozen", raising=False)
    shown, installs = [], []

    def fake_exec(dialog):
        shown.append(dialog)
        dialog.outcome = dialog.LATER
        return 0
    monkeypatch.setattr(updates.UpdateDialog, "exec", fake_exec)
    monkeypatch.setattr(updates, "prepare", lambda *a, **k: installs.append(1))
    monkeypatch.setattr(updates, "fetch_latest", lambda: Release.from_github(
        dict(GITHUB_ANSWER, tag_name="v99.0.0")))
    window = StudioWindow()
    window.show()
    window.check_for_updates(manual=False)
    for _ in range(300):
        if window.update_bar.isVisible():
            break
        _pump(application, 0.01)
    bar = window.update_bar
    assert bar.isVisible() and bar.install_button.text() == "How to Update"
    bar.install_button.click()
    _pump(application, 0.1)
    assert installs == [] and len(shown) == 1
    assert "git pull" in " ".join(label.text() for label in shown[0].findChildren(
        updates.QLabel))
    window.close()
