"""Design tokens and the stylesheet for the Studio window.

Every colour is named by *role* and has a light and a dark value, resolved
through :func:`tokens` at the moment it is needed, so the whole window
follows the system appearance.

Chart colours follow a validated data-visualisation palette:

* **categorical** -- eight hues in a *fixed order*, assigned to activities by
  frequency rank (most frequent activity = slot 1).  The order was checked for
  colour-vision-deficiency separation between neighbours; a ninth activity
  never gets a generated hue but folds into a neutral grey "Other".  Colour
  always follows the activity, so filtering never repaints the survivors.
* **sequential** -- one blue ramp, light to dark, for magnitudes (frequency
  in the process map).
* **status** -- good / warning / critical, reserved for verdicts (sound,
  fitting) and always shown with an icon and a word, never colour alone.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QColor

from .. import theme


@dataclass(frozen=True)
class Tokens:
    page: str            # window background behind content
    sidebar: str         # source list background
    surface: str         # cards, canvas paper
    surface_alt: str     # table stripes, hovered rows, inputs
    border: str          # hairlines
    text: str
    text_secondary: str
    text_muted: str
    accent: str
    accent_soft: str
    accent_text: str     # text on accent fills
    grid: str
    axis: str
    canvas: str
    node_fill: str
    node_stroke: str
    silent_fill: str
    selection: str


LIGHT = Tokens(
    page="#f5f5f7", sidebar="#ebebee", surface="#ffffff", surface_alt="#f6f6f8",
    border="#e1e1e6", text="#1d1d1f", text_secondary="#52514e", text_muted="#86868b",
    accent="#0a84ff", accent_soft="#dcebff", accent_text="#ffffff",
    grid="#e1e0d9", axis="#c3c2b7", canvas="#fcfcfb", node_fill="#ffffff",
    node_stroke="#3a3a3c", silent_fill="#3a3a3c", selection="#0a84ff",
)

DARK = Tokens(
    page="#1c1c1e", sidebar="#242427", surface="#2a2a2d", surface_alt="#323236",
    border="#3a3a3e", text="#f5f5f7", text_secondary="#c3c2b7", text_muted="#98989d",
    accent="#0a84ff", accent_soft="#153a63", accent_text="#ffffff",
    grid="#2c2c2a", axis="#383835", canvas="#1a1a19", node_fill="#2a2a2d",
    node_stroke="#d1d1d6", silent_fill="#d1d1d6", selection="#409cff",
)


def tokens() -> Tokens:
    return DARK if theme.is_dark() else LIGHT


def qc(hex_value: str, alpha: float = 1.0) -> QColor:
    colour = QColor(hex_value)
    colour.setAlphaF(alpha)
    return colour


# ---------------------------------------------------------------------------
# Data colours
# ---------------------------------------------------------------------------
CATEGORICAL_LIGHT = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100",
                     "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
CATEGORICAL_DARK = ["#3987e5", "#d95926", "#199e70", "#c98500",
                    "#d55181", "#008300", "#9085e9", "#e66767"]
OTHER_LIGHT, OTHER_DARK = "#a8a7a0", "#6b6a66"

SEQUENTIAL_BLUE = ["#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec", "#5598e7",
                   "#3987e5", "#2a78d6", "#256abf", "#1c5cab", "#184f95", "#104281", "#0d366b"]

STATUS = {"good": "#0ca30c", "warning": "#fab219", "serious": "#ec835a", "critical": "#d03b3b"}
STATUS_ICON = {"good": "✓", "warning": "!", "serious": "!", "critical": "✕", "unknown": "?",
               "info": "i"}


def categorical(slot: int) -> str:
    palette = CATEGORICAL_DARK if theme.is_dark() else CATEGORICAL_LIGHT
    if 0 <= slot < len(palette):
        return palette[slot]
    return OTHER_DARK if theme.is_dark() else OTHER_LIGHT


def sequential(fraction: float) -> str:
    """A step of the blue ramp for a magnitude in [0, 1]."""
    fraction = min(max(fraction, 0.0), 1.0)
    # Do not use the palest steps for real data: they vanish into the surface.
    low, high = 1, len(SEQUENTIAL_BLUE) - 2
    return SEQUENTIAL_BLUE[round(low + fraction * (high - low))]


def text_on(fill: str) -> str:
    """Ink colour that stays legible on ``fill``."""
    colour = QColor(fill)
    luminance = 0.2126 * colour.redF() + 0.7152 * colour.greenF() + 0.0722 * colour.blueF()
    return "#0b0b0b" if luminance > 0.55 else "#ffffff"


class ActivityColours:
    """Stable activity -> colour assignment for one log (by frequency rank)."""

    def __init__(self, activities_by_frequency: list[str]) -> None:
        self.rank = {name: i for i, name in enumerate(activities_by_frequency)}

    def slot(self, activity: str) -> int:
        return self.rank.get(activity, 99)

    def colour(self, activity: str) -> str:
        return categorical(self.slot(activity))

    def is_other(self, activity: str) -> bool:
        return self.slot(activity) >= len(CATEGORICAL_LIGHT)


# ---------------------------------------------------------------------------
# Stylesheet
# ---------------------------------------------------------------------------
RADIUS = 10


def _arrow_images(colour: str) -> dict[str, str]:
    """Small up/down chevrons for spin boxes and combo boxes, as PNG files.

    A stylesheet that styles a spin box's buttons must also supply the
    arrows (Qt then stops drawing its own), and stylesheets can only take
    images from files -- so they are painted once per colour into a cache
    folder.  Returns ``{"up": path, "down": path}`` with forward slashes.
    """
    import tempfile
    from pathlib import Path
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QImage, QPainter, QPen
    folder = Path(tempfile.gettempdir()) / "cpnpy-ui"
    folder.mkdir(exist_ok=True)
    paths = {}
    for name, points in (("up", ((3, 10), (8, 5), (13, 10))),
                         ("down", ((3, 6), (8, 11), (13, 6)))):
        path = folder / f"chevron-{name}-{colour.lstrip('#')}.png"
        if not path.exists():
            image = QImage(32, 32, QImage.Format_ARGB32)
            image.fill(Qt.transparent)
            painter = QPainter(image)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.scale(2, 2)
            pen = QPen(QColor(colour), 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
            painter.setPen(pen)
            painter.drawPolyline([QPointF(x, y) for x, y in points])
            painter.end()
            image.save(str(path))
        paths[name] = path.as_posix()
    return paths


def stylesheet() -> str:
    t = tokens()
    arrows = _arrow_images(t.text_secondary)
    return f"""
    QWidget {{ color: {t.text}; }}
    QMainWindow, #studioRoot {{ background: {t.page}; }}
    QToolTip {{ background: {t.surface}; color: {t.text}; border: 1px solid {t.border};
                padding: 6px 8px; border-radius: 6px; }}

    /* ---- sidebar -------------------------------------------------------- */
    #sidebar {{ background: {t.sidebar}; border-right: 1px solid {t.border}; }}
    #sidebar QTreeWidget {{ background: transparent; border: none; outline: none; }}
    #sidebar QTreeWidget::item {{ padding: 5px 6px; border-radius: 7px; margin: 1px 6px; }}
    #sidebar QTreeWidget::item:hover {{ background: {qc(t.text, 0.06).name(QColor.HexArgb)}; }}
    #sidebar QTreeWidget::item:selected {{ background: {t.accent}; color: {t.accent_text}; }}
    #sidebarTitle {{ color: {t.text}; font-weight: 700; font-size: 15px; padding: 0 2px; }}
    #sidebarFooter QPushButton {{ background: transparent; border: none; color: {t.text_secondary};
        padding: 6px 8px; border-radius: 6px; text-align: left; }}
    #sidebarFooter QPushButton:hover {{ background: {qc(t.text, 0.06).name(QColor.HexArgb)}; }}

    /* ---- page chrome -------------------------------------------------- */
    #pageHeader {{ background: {t.page}; }}
    #pageTitle {{ font-size: 22px; font-weight: 700; }}
    #pageSubtitle {{ color: {t.text_muted}; }}
    #card {{ background: {t.surface}; border: 1px solid {t.border}; border-radius: {RADIUS}px; }}
    #cardTitle {{ font-weight: 600; font-size: 13px; }}
    #cardCaption, #muted {{ color: {t.text_muted}; }}
    #statLabel {{ color: {t.text_muted}; font-size: 12px; }}
    #statValue {{ font-size: 22px; font-weight: 600; }}
    #statSub {{ color: {t.text_muted}; font-size: 11px; }}
    #sectionLabel {{ color: {t.text_muted}; font-size: 11px; font-weight: 700;
                     letter-spacing: 0.6px; }}

    /* ---- segmented control ---------------------------------------------- */
    #segmented {{ background: {qc(t.text, 0.07).name(QColor.HexArgb)}; border-radius: 8px; }}
    #segmented QPushButton {{ background: transparent; border: none; border-radius: 6px;
        padding: 5px 11px; color: {t.text_secondary}; font-weight: 500; }}
    #segmented QPushButton:hover {{ color: {t.text}; }}
    #segmented QPushButton:checked {{ background: {t.surface}; color: {t.text};
        border: 1px solid {t.border}; }}
    #segmented[compact="true"] QPushButton {{ padding: 4px 8px; font-size: 12px; }}

    /* ---- buttons ------------------------------------------------------ */
    QPushButton {{ background: {t.surface}; border: 1px solid {t.border}; border-radius: 7px;
        padding: 6px 14px; }}
    QPushButton:hover {{ background: {t.surface_alt}; }}
    QPushButton:disabled {{ color: {t.text_muted}; }}
    QPushButton#primary {{ background: {t.accent}; border-color: {t.accent};
        color: {t.accent_text}; font-weight: 600; }}
    QPushButton#primary:hover {{ background: {QColor(t.accent).lighter(110).name()}; }}
    QPushButton#primary:disabled {{ background: {t.border}; border-color: {t.border};
        color: {t.text_muted}; }}
    QPushButton#ghost {{ background: transparent; border: none; color: {t.accent};
        padding: 4px 6px; }}
    QPushButton#ghost:hover {{ text-decoration: underline; }}
    QToolButton#canvasTool {{ background: {t.surface}; border: 1px solid {t.border};
        border-radius: 7px; padding: 4px 9px; }}
    QToolButton#canvasTool:hover {{ background: {t.surface_alt}; }}
    QToolButton#canvasTool:checked {{ background: {t.accent}; color: {t.accent_text};
        border-color: {t.accent}; }}

    /* ---- inputs ------------------------------------------------------- */
    QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox, QPlainTextEdit {{
        background: {t.surface}; border: 1px solid {t.border}; border-radius: 7px;
        padding: 4px 8px; selection-background-color: {t.accent}; }}
    QComboBox:focus, QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus,
    QDoubleSpinBox:focus {{ border-color: {t.accent}; }}
    QSpinBox, QDoubleSpinBox {{ padding-right: 20px; }}
    QSpinBox::up-button, QSpinBox::down-button,
    QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ subcontrol-origin: border;
        width: 18px; border: none; border-left: 1px solid {t.border};
        background: {t.surface_alt}; }}
    QSpinBox::up-button:hover, QSpinBox::down-button:hover,
    QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover {{
        background: {t.border}; }}
    QSpinBox::up-button, QDoubleSpinBox::up-button {{ subcontrol-position: top right;
        border-top-right-radius: 7px; border-bottom: 1px solid {t.border}; }}
    QSpinBox::down-button, QDoubleSpinBox::down-button {{ subcontrol-position: bottom right;
        border-bottom-right-radius: 7px; }}
    QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{ image: url("{arrows['up']}");
        width: 10px; height: 10px; }}
    QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{ image: url("{arrows['down']}");
        width: 10px; height: 10px; }}
    QSpinBox::up-arrow:disabled, QSpinBox::down-arrow:disabled,
    QDoubleSpinBox::up-arrow:disabled, QDoubleSpinBox::down-arrow:disabled {{ image: none; }}
    QComboBox {{ padding-right: 22px; }}
    QComboBox::drop-down {{ border: none; width: 20px; }}
    QComboBox::down-arrow {{ image: url("{arrows['down']}"); width: 10px; height: 10px; }}
    QComboBox QAbstractItemView {{ background: {t.surface}; border: 1px solid {t.border};
        selection-background-color: {t.accent}; outline: none; }}
    QSlider::groove:horizontal {{ height: 4px; background: {t.border}; border-radius: 2px; }}
    QSlider::sub-page:horizontal {{ background: {t.accent}; border-radius: 2px; }}
    QSlider::handle:horizontal {{ background: {t.surface}; border: 1px solid {t.axis};
        width: 16px; height: 16px; margin: -7px 0; border-radius: 8px; }}
    QRadioButton, QCheckBox {{ spacing: 8px; }}

    /* ---- tables and lists --------------------------------------------- */
    QTableView, QTreeView, QListView {{ background: {t.surface}; border: none;
        alternate-background-color: {t.surface_alt}; gridline-color: {t.border};
        selection-background-color: {t.accent_soft}; selection-color: {t.text}; outline: none; }}
    QHeaderView::section {{ background: {t.surface}; color: {t.text_muted}; border: none;
        border-bottom: 1px solid {t.border}; padding: 6px 8px; font-weight: 600;
        font-size: 11px; }}
    QTableCornerButton::section {{ background: {t.surface}; border: none; }}

    /* ---- scroll bars: thin overlays ------------------------------------- */
    QScrollArea {{ background: transparent; border: none; }}
    QScrollArea > QWidget > QWidget {{ background: transparent; }}
    QScrollBar:vertical, QScrollBar:horizontal {{ background: transparent;
        width: 10px; height: 10px; margin: 2px; }}
    QScrollBar::handle {{ background: {qc(t.text, 0.22).name(QColor.HexArgb)};
        border-radius: 4px; min-height: 30px; min-width: 30px; }}
    QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{
        background: none; border: none; height: 0; width: 0; }}

    QSplitter::handle {{ background: {t.border}; }}
    QGraphicsView {{ background: {t.canvas}; border: none; }}
    QStatusBar {{ background: {t.page}; color: {t.text_muted}; border-top: 1px solid {t.border}; }}
    QMenu {{ background: {t.surface}; border: 1px solid {t.border}; padding: 4px; }}
    QMenu::item {{ padding: 5px 18px; border-radius: 5px; }}
    QMenu::item:selected {{ background: {t.accent}; color: {t.accent_text}; }}
    QProgressBar {{ background: {t.border}; border: none; border-radius: 2px; max-height: 4px; }}
    QProgressBar::chunk {{ background: {t.accent}; border-radius: 2px; }}
    QTabWidget::pane {{ border: none; }}
    """
