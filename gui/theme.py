"""Visual theme: one place that decides what the application looks like.

Why a theme module
------------------
Colours, fonts and corner radii were previously scattered through the canvas
items and the panels.  Collecting them here means the look can be adjusted in
one file, and -- more importantly -- it makes **dark mode** possible: every
colour is resolved through :func:`palette`, which returns a different mapping
depending on the system appearance.

The palette follows macOS system conventions (the same greys and the same
accent blue AppKit uses), so the window sits comfortably next to native apps
rather than looking like a ported X11 program.

Nothing here imports from the rest of the GUI, so it can be used from any
module without circular imports.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase
from PySide6.QtWidgets import QApplication


# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Palette:
    """Every colour the application uses, named by role rather than by hue.

    Naming by role (``surface``, ``muted``, ``accent``) rather than by colour
    (``light_grey``, ``blue``) is what lets the same code render correctly in
    both appearances: the dark palette swaps the values, not the names.
    """

    # Chrome
    window: QColor            # the window background behind panels
    surface: QColor           # cards, list backgrounds, the canvas paper
    surface_raised: QColor    # hovered rows, input fields
    border: QColor            # hairlines and separators
    border_strong: QColor     # node outlines

    # Type
    text: QColor              # primary text
    text_muted: QColor        # secondary text, colour set annotations

    # Semantics
    accent: QColor            # selection, focus, primary buttons
    accent_soft: QColor       # selection fills
    success: QColor           # enabled transitions
    success_soft: QColor
    danger: QColor            # compile errors
    inscription: QColor       # arc expressions, initial markings
    marking: QColor           # live token contents

    # Canvas
    canvas: QColor
    grid: QColor


# The values match the Studio design tokens (``cpnpy.gui.studio.style``), so
# the CPN canvas and the process-mining canvases look like one application.
_LIGHT = Palette(
    window=QColor("#F5F5F7"),
    surface=QColor("#FFFFFF"),
    surface_raised=QColor("#F6F6F8"),
    border=QColor("#E1E1E6"),
    border_strong=QColor("#3A3A3C"),
    text=QColor("#1D1D1F"),
    text_muted=QColor("#86868B"),
    accent=QColor("#0A84FF"),
    accent_soft=QColor("#DCEBFF"),
    success=QColor("#2E9E4F"),
    success_soft=QColor("#DFF5E4"),
    danger=QColor("#D03B3B"),
    inscription=QColor("#2468C0"),
    marking=QColor("#B0430F"),
    canvas=QColor("#FCFCFB"),
    grid=QColor("#E1E0D9"),
)

_DARK = Palette(
    window=QColor("#1C1C1E"),
    surface=QColor("#2A2A2D"),
    surface_raised=QColor("#323236"),
    border=QColor("#3A3A3E"),
    border_strong=QColor("#D1D1D6"),
    text=QColor("#F5F5F7"),
    text_muted=QColor("#98989D"),
    accent=QColor("#0A84FF"),
    accent_soft=QColor("#153A63"),
    success=QColor("#30D158"),
    success_soft=QColor("#1E4028"),
    danger=QColor("#FF6B61"),
    inscription=QColor("#6DAAF0"),
    marking=QColor("#FF9F6B"),
    canvas=QColor("#1A1A19"),
    grid=QColor("#2C2C2A"),
)


def is_dark() -> bool:
    """Is the system (or the application palette) currently dark?

    Qt 6.5 exposes the system colour scheme directly.  On older builds we fall
    back to measuring the lightness of the window colour, which is reliable
    enough for the binary decision we need.
    """
    application = QApplication.instance()
    if application is None:
        return False
    hints = application.styleHints()
    scheme = getattr(hints, "colorScheme", None)
    if scheme is not None:
        try:
            return scheme() == Qt.ColorScheme.Dark
        except Exception:  # pragma: no cover - older Qt without the enum
            pass
    return application.palette().window().color().lightness() < 128


def palette() -> Palette:
    """The palette matching the current appearance."""
    return _DARK if is_dark() else _LIGHT


# ---------------------------------------------------------------------------
# Typography
# ---------------------------------------------------------------------------
def ui_font(size: int = 13, weight: QFont.Weight = QFont.Normal) -> QFont:
    """The system UI font.

    ``QFontDatabase.systemFont`` returns SF Pro on macOS, which is what makes
    the window look native rather than like a generic Qt application.
    """
    font = QFontDatabase.systemFont(QFontDatabase.GeneralFont)
    font.setPointSize(size)
    font.setWeight(weight)
    return font


def mono_font(size: int = 12) -> QFont:
    """The system monospace font, for inscriptions and markings.

    Inscriptions are code, and code in a proportional font is harder to scan --
    particularly the backquote in ``2`x``, which is nearly invisible otherwise.
    """
    font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
    font.setPointSize(size)
    return font


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------
#: Corner radius for cards, buttons and transition nodes.
RADIUS = 8
#: Standard gap between widgets.
GAP = 10


# ---------------------------------------------------------------------------
# Stylesheet
# ---------------------------------------------------------------------------
def stylesheet() -> str:
    """The application-wide Qt stylesheet.

    Qt stylesheets are CSS-like but not CSS: only a documented subset of
    properties works, and a rule that mentions an unsupported property is
    dropped whole.  Everything below is restricted to that subset, and the
    layout-critical parts (padding, radii) are chosen to give the roomy,
    low-contrast feel of a current macOS application: hairline separators
    instead of bevels, generous padding, and colour used only where it means
    something.
    """
    p = palette()

    def rgb(colour: QColor) -> str:
        return f"rgb({colour.red()},{colour.green()},{colour.blue()})"

    return f"""
    /* ---- base ------------------------------------------------------- */
    QMainWindow, QWidget {{
        background: {rgb(p.window)};
        color: {rgb(p.text)};
    }}

    /* ---- docks: flat cards, hairline separators, quiet titles -------- */
    QDockWidget {{
        titlebar-close-icon: none;
        titlebar-normal-icon: none;
        font-weight: 600;
        color: {rgb(p.text_muted)};
    }}
    QDockWidget::title {{
        background: {rgb(p.window)};
        padding: 9px 12px;
        border-bottom: 1px solid {rgb(p.border)};
        text-align: left;
    }}
    QDockWidget > QWidget {{
        background: {rgb(p.window)};
    }}

    /* ---- toolbar: flat, segmented ------------------------------------ */
    QToolBar {{
        background: {rgb(p.window)};
        border: none;
        border-bottom: 1px solid {rgb(p.border)};
        padding: 6px 10px;
        spacing: 4px;
    }}
    QToolBar QToolButton {{
        background: transparent;
        border: 1px solid transparent;
        border-radius: {RADIUS - 2}px;
        padding: 5px 12px;
        color: {rgb(p.text)};
    }}
    QToolBar QToolButton:hover {{
        background: {rgb(p.surface_raised)};
    }}
    QToolBar QToolButton:checked {{
        background: {rgb(p.accent)};
        color: white;
    }}
    QToolBar::separator {{
        background: {rgb(p.border)};
        width: 1px;
        margin: 4px 8px;
    }}

    /* ---- buttons ----------------------------------------------------- */
    QPushButton {{
        background: {rgb(p.surface)};
        border: 1px solid {rgb(p.border)};
        border-radius: {RADIUS - 2}px;
        padding: 6px 14px;
        color: {rgb(p.text)};
    }}
    QPushButton:hover {{ background: {rgb(p.surface_raised)}; }}
    QPushButton:pressed {{ background: {rgb(p.accent_soft)}; }}
    QPushButton:default {{
        background: {rgb(p.accent)};
        border-color: {rgb(p.accent)};
        color: white;
    }}

    /* ---- inputs ------------------------------------------------------ */
    QLineEdit, QPlainTextEdit, QComboBox, QSpinBox {{
        background: {rgb(p.surface)};
        border: 1px solid {rgb(p.border)};
        border-radius: {RADIUS - 2}px;
        padding: 5px 8px;
        selection-background-color: {rgb(p.accent)};
        selection-color: white;
    }}
    QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus {{
        border-color: {rgb(p.accent)};
    }}
    QComboBox::drop-down {{ border: none; width: 18px; }}
    /* Fusion draws spin box arrows as bare glyphs on top of our flat field,
       which renders as a stray dash. Give them a proper hit area instead. */
    QSpinBox::up-button, QSpinBox::down-button {{
        subcontrol-origin: border;
        width: 16px;
        border: none;
        border-left: 1px solid {rgb(p.border)};
        background: {rgb(p.surface_raised)};
    }}
    QSpinBox::up-button {{ subcontrol-position: top right; border-top-right-radius: {RADIUS - 2}px; }}
    QSpinBox::down-button {{ subcontrol-position: bottom right; border-bottom-right-radius: {RADIUS - 2}px; }}
    QSpinBox::up-arrow, QSpinBox::down-arrow {{ width: 7px; height: 7px; }}

    /* ---- lists ------------------------------------------------------- */
    QListWidget {{
        background: {rgb(p.surface)};
        border: 1px solid {rgb(p.border)};
        border-radius: {RADIUS}px;
        padding: 4px;
        outline: none;
    }}
    QListWidget::item {{
        padding: 5px 8px;
        border-radius: {RADIUS - 3}px;
    }}
    QListWidget::item:hover {{ background: {rgb(p.surface_raised)}; }}
    QListWidget::item:selected {{
        background: {rgb(p.accent)};
        color: white;
    }}

    /* ---- tabs: pill segmented control -------------------------------- */
    QTabWidget::pane {{ border: none; }}
    QTabBar {{ qproperty-drawBase: 0; }}
    QTabBar::tab {{
        background: transparent;
        color: {rgb(p.text_muted)};
        padding: 6px 14px;
        margin: 6px 2px;
        border-radius: {RADIUS - 2}px;
    }}
    QTabBar::tab:hover {{ background: {rgb(p.surface_raised)}; }}
    QTabBar::tab:selected {{
        background: {rgb(p.surface)};
        color: {rgb(p.text)};
        border: 1px solid {rgb(p.border)};
    }}

    /* ---- group boxes: label above a hairline card -------------------- */
    QGroupBox {{
        background: {rgb(p.surface)};
        border: 1px solid {rgb(p.border)};
        border-radius: {RADIUS}px;
        margin-top: 18px;
        padding: 8px;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        subcontrol-position: top left;
        left: 2px;
        padding: 0 2px;
        color: {rgb(p.text_muted)};
        font-weight: 600;
    }}

    /* ---- scrollbars: thin, no arrows --------------------------------- */
    QScrollBar:vertical, QScrollBar:horizontal {{
        background: transparent;
        width: 11px; height: 11px;
        margin: 2px;
    }}
    QScrollBar::handle {{
        background: {rgb(p.border)};
        border-radius: 5px;
        min-height: 28px; min-width: 28px;
    }}
    QScrollBar::handle:hover {{ background: {rgb(p.text_muted)}; }}
    QScrollBar::add-line, QScrollBar::sub-line,
    QScrollBar::add-page, QScrollBar::sub-page {{
        background: none; border: none; height: 0; width: 0;
    }}

    /* ---- misc -------------------------------------------------------- */
    QGraphicsView {{
        background: {rgb(p.canvas)};
        border: none;
    }}
    QStatusBar {{
        background: {rgb(p.window)};
        border-top: 1px solid {rgb(p.border)};
        color: {rgb(p.text_muted)};
    }}
    QStatusBar::item {{ border: none; }}
    QMenuBar {{ background: {rgb(p.window)}; }}
    QSplitter::handle {{ background: {rgb(p.border)}; }}
    """
