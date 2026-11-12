"""Application bootstrap for the PySide6 + Fluent desktop interface."""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from .. import APP_ID, APP_NAME, __version__
from ..config import load_config
from .main_window import MainWindow
from .theme import apply_appearance, brand_icon


def run_gui(project: str | None = None) -> int:
    """Launch the desktop application and return the Qt exit code."""

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationName("Harness Studio")
    app.setApplicationVersion(__version__)
    app.setDesktopFileName(APP_ID)
    app.setWindowIcon(brand_icon())

    config = load_config()
    apply_appearance(config)

    window = MainWindow(config, project)
    window.show()
    return app.exec()


__all__ = ["run_gui"]
