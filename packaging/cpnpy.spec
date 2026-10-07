# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller recipe for the standalone CPNpy Studio app.

Build with ``python packaging/build.py`` (which runs this file and then packs
the result), or directly with ``pyinstaller packaging/cpnpy.spec``.

PyInstaller collects a Python interpreter, the cpnpy package and the parts of
Qt the app imports into one folder, ``dist/CPNpy/``.  On macOS that folder is
then wrapped as ``dist/CPNpy.app``.  PyInstaller cannot cross-compile: each
system builds its own app, which is why the GitHub workflow runs this on a
macOS, a Windows and a Linux machine.

This file is Python, run by PyInstaller with a few names predefined:
``SPECPATH`` (this folder), ``Analysis``, ``PYZ``, ``EXE``, ``COLLECT`` and
``BUNDLE``.
"""

import re
import sys
from pathlib import Path

PACKAGING = Path(SPECPATH)
ROOT = PACKAGING.parent
ICONS = PACKAGING / "icons"

# One version number for everything: __version__ in cpnpy/__init__.py.
VERSION = re.search(r'^__version__\s*=\s*"([^"]+)"',
                    (ROOT / "cpnpy" / "__init__.py").read_text(encoding="utf-8"), re.M).group(1)

if sys.platform == "darwin":
    ICON = str(ICONS / "CPNpy.icns")
elif sys.platform == "win32":
    ICON = str(ICONS / "CPNpy.ico")
else:
    ICON = None                         # Linux: the icon goes in the .desktop file

analysis = Analysis(
    [str(PACKAGING / "cpnpy_studio.py")],
    pathex=[str(ROOT)],
    # Files the code opens by path at run time (the window icon, and the demo
    # exercises that File ▸ Open Demo Exercises copies to Documents).
    datas=[(str(ROOT / "cpnpy" / "gui" / "resources" / "cpnpy-icon.png"),
            "cpnpy/gui/resources"),
           (str(ROOT / "cpnpy" / "exercises"), "cpnpy/exercises"),
           # Help ▸ Writing Exercise Packs.
           (str(ROOT / "cpnpy" / "teaching" / "exercise-packs.md"), "cpnpy/teaching")],
    # Imported inside functions; listed so they are never missed.  certifi
    # brings its certificate file (PyInstaller's hook), which the update check
    # needs to reach GitHub: the bundled Python cannot use the system's.
    hiddenimports=["cpnpy.analysis.state_space_process", "certifi"],
    # Not needed by the app.  PM4Py is an optional extra (AGPL-3.0) and is
    # never bundled; the app hides its PM4Py options when it is missing.
    excludes=["pm4py", "tkinter", "pytest", "matplotlib", "numpy", "pandas", "scipy"],
    noarchive=False,
)

pyz = PYZ(analysis.pure)

executable = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,              # "one folder" build: starts faster than one file
    name="CPNpy",
    console=False,                      # a GUI app: no terminal window on Windows
    icon=ICON,
    argv_emulation=False,
    upx=False,
)

folder = COLLECT(executable, analysis.binaries, analysis.datas, name="CPNpy", upx=False)

if sys.platform == "darwin":
    app = BUNDLE(
        folder,
        name="CPNpy.app",
        icon=ICON,
        bundle_identifier="io.github.s4mstruthers.cpnpy",
        version=VERSION,
        info_plist={
            "CFBundleName": "CPNpy",
            "CFBundleDisplayName": "CPNpy Studio",
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION,
            "NSHighResolutionCapable": True,
            # Follow the system's light / dark appearance, as the app does from source.
            "NSRequiresAquaSystemAppearance": False,
            "LSApplicationCategoryType": "public.app-category.education",
            "NSHumanReadableCopyright": "MIT licence",
        },
    )
