"""Visual identity, fonts and theme helpers."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QLinearGradient, QPainter, QPixmap
from PySide6.QtWidgets import QApplication
from qfluentwidgets import Theme, isDarkTheme, setTheme, setThemeColor

from ..config import HarnessConfig

ACCENTS: dict[str, str] = {
    "blue": "#2F6DF6",
    "violet": "#7C5CFF",
    "teal": "#0F9D8A",
    "green": "#16A34A",
    "orange": "#F97316",
    "red": "#E5484D",
    "pink": "#DB2777",
}

ACCENT_LABELS = {
    "blue": "Azul",
    "violet": "Violeta",
    "teal": "Turquesa",
    "green": "Verde",
    "orange": "Naranja",
    "red": "Rojo",
    "pink": "Rosa",
}

THEMES = {"auto": Theme.AUTO, "light": Theme.LIGHT, "dark": Theme.DARK}
THEME_LABELS = {"auto": "Automático", "light": "Claro", "dark": "Oscuro"}

_STATUS_COLORS = {
    "M": "#D97706",
    "A": "#16A34A",
    "D": "#DC2626",
    "R": "#7C3AED",
    "C": "#0D9488",
    "U": "#DC2626",
    "??": "#6B7280",
}


def accent_hex(config: HarnessConfig) -> str:
    return ACCENTS.get(config.accent, ACCENTS["blue"])


def status_color(code: str) -> str:
    return _STATUS_COLORS.get(code.strip(), "#6B7280")


def apply_appearance(config: HarnessConfig) -> None:
    setTheme(THEMES.get(config.theme, Theme.AUTO))
    setThemeColor(accent_hex(config))
    # qfluentwidgets styles its own widgets, but plain Qt widgets (splitter
    # handles, native combo popups, scrollbars) follow the application palette.
    # Align it with the resolved theme so nothing renders dark on a light UI.
    app = QApplication.instance()
    if app is not None:
        dark = isDarkTheme()
        try:
            app.styleHints().setColorScheme(
                Qt.ColorScheme.Dark if dark else Qt.ColorScheme.Light
            )
        except (AttributeError, RuntimeError):
            pass


def mono_font(size: int | None = None, config: HarnessConfig | None = None) -> QFont:
    families = set(QFontDatabase.families())
    preferred = []
    if config is not None and config.mono_font:
        preferred.append(config.mono_font)
    preferred += [
        "Cascadia Code",
        "Cascadia Mono",
        "JetBrains Mono",
        "Fira Code",
        "Consolas",
        "DejaVu Sans Mono",
        "Courier New",
    ]
    family = next((item for item in preferred if item in families), "")
    font = QFont(family)
    font.setStyleHint(QFont.StyleHint.Monospace)
    font.setFixedPitch(True)
    font.setPointSize(size if size is not None else (config.font_size if config else 11))
    return font


def muted_color(label) -> None:
    """Apply the muted text colour to both Fluent and plain Qt labels."""

    setter = getattr(label, "setTextColor", None)
    if callable(setter):
        setter(QColor(100, 100, 100), QColor(165, 165, 165))
        return
    # Plain QLabel: keep a neutral grey that reads acceptably in both themes.
    label.setStyleSheet((label.styleSheet() or "") + "color: #6B7280;")


def brand_pixmap(size: int = 256) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    rect = QRectF(2, 2, size - 4, size - 4)
    gradient = QLinearGradient(0, 0, size, size)
    gradient.setColorAt(0.0, QColor("#2F6DF6"))
    gradient.setColorAt(0.55, QColor("#5B5BF0"))
    gradient.setColorAt(1.0, QColor("#8B5CF6"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(gradient)
    painter.drawRoundedRect(rect, size * 0.23, size * 0.23)
    # Subtle inner highlight.
    painter.setBrush(QColor(255, 255, 255, 26))
    painter.drawRoundedRect(rect.adjusted(size * 0.07, size * 0.07, -size * 0.07, -size * 0.07), size * 0.18, size * 0.18)
    font = QFont("Cascadia Code")
    font.setBold(True)
    font.setPixelSize(int(size * 0.34))
    painter.setFont(font)
    painter.setPen(QColor(255, 255, 255, 245))
    painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "</>")
    painter.end()
    return pixmap


def brand_icon() -> QIcon:
    return QIcon(brand_pixmap(256))


__all__ = [
    "ACCENTS",
    "ACCENT_LABELS",
    "THEMES",
    "THEME_LABELS",
    "accent_hex",
    "apply_appearance",
    "brand_icon",
    "brand_pixmap",
    "mono_font",
    "muted_color",
    "status_color",
]
