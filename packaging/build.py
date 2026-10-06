"""Build the standalone CPNpy Studio app for the system this runs on.

Usage, from the project folder, in an environment with CPNpy and its GUI
installed (``pip install -e ".[gui]"``, or the conda environment)::

    pip install pyinstaller
    python packaging/build.py

Result, in ``dist/``:

=========  ==========================================================  ==================================
system     app                                                         file to share
=========  ==========================================================  ==================================
macOS      ``CPNpy.app``                                               ``CPNpy-<version>-macOS-<arch>.dmg``
Windows    ``CPNpy\\CPNpy.exe`` (with its folder)                      ``CPNpy-<version>-Windows-<arch>.zip``
Linux      ``CPNpy/CPNpy`` (with its folder)                           ``CPNpy-<version>-Linux-<arch>.tar.gz``
=========  ==========================================================  ==================================

The steps:

1. run PyInstaller on ``packaging/cpnpy.spec``;
2. smoke-test the result: start it with ``--cpnpy-self-test`` (builds the
   window off-screen and computes a state space through a worker process, as
   the app does), then run the worker on its own;
3. pack it into the file people download.

``--skip-tests`` skips step 2; ``--no-package`` skips step 3.
"""

from __future__ import annotations

import argparse
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

PACKAGING = Path(__file__).resolve().parent
ROOT = PACKAGING.parent
DIST = ROOT / "dist"


def version() -> str:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    return re.search(r'^version\s*=\s*"([^"]+)"', text, re.M).group(1)


def system_name() -> str:
    return {"darwin": "macOS", "win32": "Windows"}.get(sys.platform, "Linux")


def architecture() -> str:
    machine = platform.machine().lower()
    return {"amd64": "x64", "x86_64": "x64", "arm64": "arm64", "aarch64": "arm64"}.get(machine, machine)


def executable() -> Path:
    """The program inside the build that a user would start."""
    if sys.platform == "darwin":
        return DIST / "CPNpy.app" / "Contents" / "MacOS" / "CPNpy"
    if sys.platform == "win32":
        return DIST / "CPNpy" / "CPNpy.exe"
    return DIST / "CPNpy" / "CPNpy"


# ---------------------------------------------------------------------------
# 1. PyInstaller
# ---------------------------------------------------------------------------
def run_pyinstaller() -> None:
    print("== PyInstaller", flush=True)
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
                    "--distpath", str(DIST), "--workpath", str(ROOT / "build"),
                    str(PACKAGING / "cpnpy.spec")], check=True, cwd=ROOT)


# ---------------------------------------------------------------------------
# 2. Smoke tests
# ---------------------------------------------------------------------------
def smoke_test() -> None:
    program = executable()
    print(f"== Smoke test of {program.relative_to(ROOT)}", flush=True)
    environment = dict(os.environ, QT_QPA_PLATFORM="offscreen")

    # a) The GUI, plus a state space computed the way the app computes it:
    #    the frozen app starts a copy of itself as the worker process.
    model = ROOT / "examples" / "dining_philosophers.cpn"
    result = subprocess.run([str(program), "--cpnpy-self-test", str(model)], capture_output=True,
                            text=True, timeout=300, env=environment)
    if result.returncode != 0 or not result.stdout.rstrip().endswith("ok"):
        sys.exit(f"self-test failed (exit {result.returncode}):\n{result.stdout}\n{result.stderr}")
    print("   window and state space job: ok")

    # b) The worker on its own, with its messages visible if something breaks.
    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory) / "result.pickle"
        result = subprocess.run(
            [str(program), "--cpnpy-state-space-worker", str(model), "1000", str(output)],
            input="", capture_output=True, text=True, timeout=180, env=environment)
        if "done" not in result.stdout or not output.exists():
            sys.exit(f"state space worker failed (exit {result.returncode}):\n"
                     f"{result.stdout}\n{result.stderr}")
    print("   state space worker: ok")


# ---------------------------------------------------------------------------
# 3. The file to share
# ---------------------------------------------------------------------------
def package() -> Path:
    name = f"CPNpy-{version()}-{system_name()}-{architecture()}"
    print(f"== Packing {name}", flush=True)
    if sys.platform == "darwin":
        return _dmg(name)
    if sys.platform == "win32":
        return _zip(name)
    return _tarball(name)


def _dmg(name: str) -> Path:
    """A disk image showing CPNpy.app next to a shortcut to /Applications."""
    staging = DIST / "dmg"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir()
    # ditto copies an app bundle faithfully (symlinks, permissions, signatures).
    subprocess.run(["ditto", str(DIST / "CPNpy.app"), str(staging / "CPNpy.app")], check=True)
    (staging / "Applications").symlink_to("/Applications")
    target = DIST / f"{name}.dmg"
    target.unlink(missing_ok=True)
    subprocess.run(["hdiutil", "create", "-volname", "CPNpy", "-srcfolder", str(staging),
                    "-ov", "-format", "UDZO", str(target)], check=True)
    shutil.rmtree(staging)
    return target


def _zip(name: str) -> Path:
    target = DIST / f"{name}.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted((DIST / "CPNpy").rglob("*")):
            archive.write(path, Path("CPNpy") / path.relative_to(DIST / "CPNpy"))
    return target


def _tarball(name: str) -> Path:
    """The app folder plus what Linux needs to show it in the applications menu."""
    folder = DIST / "CPNpy"
    shutil.copy(PACKAGING / "icons" / "CPNpy.png", folder / "CPNpy.png")
    installer = folder / "install-desktop-entry.sh"
    shutil.copy(PACKAGING / "linux" / "install-desktop-entry.sh", installer)
    installer.chmod(0o755)
    target = DIST / f"{name}.tar.gz"
    with tarfile.open(target, "w:gz") as archive:
        archive.add(folder, arcname="CPNpy")
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--skip-tests", action="store_true", help="do not smoke-test the build")
    parser.add_argument("--no-package", action="store_true", help="do not make the .dmg/.zip/.tar.gz")
    options = parser.parse_args()

    run_pyinstaller()
    if not options.skip_tests:
        smoke_test()
    if not options.no_package:
        target = package()
        size = target.stat().st_size / 1_000_000
        print(f"== Done: {target.relative_to(ROOT)} ({size:.0f} MB)")


if __name__ == "__main__":
    main()
