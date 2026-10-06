"""Render the app icons for the standalone builds from ``docs/logo/cpnpy-icon.svg``.

Each system wants its own icon format:

* **macOS** -- ``CPNpy.icns``.  Big Sur and later draw app icons on a 1024 px
  grid with the artwork filling about 80 % of it, so the logo is shrunk onto
  that grid; otherwise it would look larger than every other icon in the Dock.
* **Windows** -- ``CPNpy.ico``, holding every size from 16 to 256 px.
* **Linux** -- ``CPNpy.png`` (512 px), referenced by the ``.desktop`` file.

The generated files are committed, so building the apps does not need this
script.  Run it again only after changing the logo::

    python packaging/make_icons.py

It needs PySide6 (to render the SVG) and Pillow (to write .icns and .ico):
``pip install pillow``.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs" / "logo" / "cpnpy-icon.svg"
OUT = Path(__file__).resolve().parent / "icons"


def render(size: int, artwork_fraction: float = 1.0):
    """The SVG rendered as a ``size`` x ``size`` Pillow image with transparency.

    ``artwork_fraction`` < 1 leaves an even transparent margin around the logo.
    """
    from PIL import Image
    from PySide6.QtCore import QBuffer, QIODevice, QRectF, Qt
    from PySide6.QtGui import QGuiApplication, QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer

    QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    inner = size * artwork_fraction
    offset = (size - inner) / 2
    QSvgRenderer(str(SOURCE)).render(painter, QRectF(offset, offset, inner, inner))
    painter.end()

    # Hand the pixels to Pillow through an in-memory PNG.
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    from io import BytesIO
    return Image.open(BytesIO(bytes(buffer.data()))).convert("RGBA")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    # macOS: one 1024 px master on Apple's icon grid; Pillow writes every size.
    render(1024, artwork_fraction=0.8).save(OUT / "CPNpy.icns")

    # Windows: the usual sizes in one .ico.
    sizes = [16, 24, 32, 48, 64, 128, 256]
    render(256).save(OUT / "CPNpy.ico", sizes=[(s, s) for s in sizes])

    # Linux: a plain PNG for the .desktop entry.
    render(512).save(OUT / "CPNpy.png")

    for path in sorted(OUT.iterdir()):
        print(f"wrote {path.relative_to(ROOT)} ({path.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
