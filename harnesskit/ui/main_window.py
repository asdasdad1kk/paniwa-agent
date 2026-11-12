"""Main Fluent window and navigation wiring."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication
from qfluentwidgets import (
    FluentIcon as FIF,
    FluentWindow,
    NavigationItemPosition,
    setThemeColor,
)

from .. import APP_NAME, __version__
from ..config import HarnessConfig, save_config
from ..tokens import format_tokens
from .pages.composer import ComposerPage
from .pages.history import HistoryPage
from .pages.response import ResponsePage
from .pages.scaffolds import ScaffoldsPage
from .pages.settings import SettingsPage
from .pages.workspace import WorkspacePage
from .state import AppContext
from .theme import apply_appearance, brand_icon, mono_font
from .widgets import notify


class MainWindow(FluentWindow):
    def __init__(
        self,
        config: HarnessConfig,
        project: str | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.ctx = AppContext(config, self)
        self._last_status = ""

        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.setWindowIcon(brand_icon())
        self.resize(1380, 880)
        self.setMinimumSize(1080, 700)
        self.navigationInterface.setExpandWidth(228)

        self.workspace_page = WorkspacePage(self.ctx, self)
        self.workspace_page.setObjectName("workspacePage")
        self.composer_page = ComposerPage(self.ctx, self)
        self.response_page = ResponsePage(self.ctx, self)
        self.scaffolds_page = ScaffoldsPage(self.ctx, self)
        self.history_page = HistoryPage(self.ctx, self)
        self.settings_page = SettingsPage(self.ctx, self)

        self.addSubInterface(self.workspace_page, FIF.HOME, "Espacio de trabajo")
        self.addSubInterface(self.composer_page, FIF.EDIT, "Compositor")
        self.addSubInterface(self.response_page, FIF.CODE, "Respuesta")
        self.addSubInterface(self.scaffolds_page, FIF.ADD, "Plantillas")
        self.addSubInterface(self.history_page, FIF.HISTORY, "Historial")
        self.addSubInterface(
            self.settings_page,
            FIF.SETTING,
            "Ajustes",
            NavigationItemPosition.BOTTOM,
        )

        self._connect()
        self._apply_appearance()
        self._restore_geometry()

        self.ctx.statusMessage.connect(self._show_status)

        if project:
            self.ctx.open_project(project)
        elif config.last_project and Path(config.last_project).is_dir():
            self.ctx.open_project(config.last_project)

        self._install_shortcuts()

    # -------------------------------------------------------------------- wiring
    def _connect(self) -> None:
        self.workspace_page.composerRequested.connect(
            lambda: self.switchTo(self.composer_page)
        )
        self.workspace_page.scaffoldsRequested.connect(
            lambda: self.switchTo(self.scaffolds_page)
        )
        self.composer_page.workspaceRequested.connect(
            lambda: self.switchTo(self.workspace_page)
        )
        self.scaffolds_page.workspaceRequested.connect(
            lambda: self.switchTo(self.workspace_page)
        )
        self.history_page.reuseRequested.connect(self._reuse_session)

        self.ctx.projectChanged.connect(self._on_project_changed)
        self.ctx.projectFailed.connect(
            lambda message: notify(self, "error", "No se pudo abrir el proyecto", message, 5000)
        )
        self.ctx.settingsChanged.connect(self._apply_appearance)

    def _on_project_changed(self) -> None:
        if self.ctx.root is None:
            self.setWindowTitle(f"{APP_NAME} {__version__}")
            return
        scan = self.ctx.scan
        files = len(scan.files) if scan else 0
        self.setWindowTitle(
            f"{self.ctx.root.name} · {APP_NAME} — {files} archivos"
        )

    def _reuse_session(self, record) -> None:
        if not record.project_root or not Path(record.project_root).is_dir():
            notify(
                self,
                "warning",
                "Proyecto no disponible",
                "La carpeta de esa sesión ya no existe. Puedes copiar o exportar el prompt.",
                4200,
            )
        elif self.ctx.root is None or str(self.ctx.root) != record.project_root:
            self.ctx.open_project(record.project_root)
        self.composer_page.load_session(record)
        self.switchTo(self.composer_page)
        notify(
            self,
            "info",
            "Sesión cargada",
            "Revisa la solicitud y los archivos antes de generar de nuevo.",
            2400,
        )

    # ----------------------------------------------------------------- shortcuts
    def _install_shortcuts(self) -> None:
        shortcuts = (
            (QKeySequence("Ctrl+O"), self.workspace_page._choose_folder),
            (QKeySequence("Ctrl+R"), self.ctx.rescan),
            (QKeySequence("Ctrl+1"), lambda: self.switchTo(self.workspace_page)),
            (QKeySequence("Ctrl+2"), lambda: self.switchTo(self.composer_page)),
            (QKeySequence("Ctrl+3"), lambda: self.switchTo(self.response_page)),
            (QKeySequence("Ctrl+4"), lambda: self.switchTo(self.scaffolds_page)),
            (QKeySequence("Ctrl+5"), lambda: self.switchTo(self.history_page)),
            (QKeySequence("Ctrl+,"), lambda: self.switchTo(self.settings_page)),
        )
        for sequence, handler in shortcuts:
            shortcut = QShortcut(sequence, self)
            shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
            shortcut.activated.connect(handler)

    # ----------------------------------------------------------------- appearance
    def _apply_appearance(self) -> None:
        config = self.ctx.config
        apply_appearance(config)
        app = QApplication.instance()
        if app is not None:
            font = QFont(app.font())
            font.setPointSize(config.font_size)
            app.setFont(font)
        mono = mono_font(config=config)
        for view in (
            self.workspace_page.preview_view,
            self.composer_page.prompt_view,
            self.response_page.file_view,
            self.response_page.patch_view,
            self.history_page.prompt_view,
        ):
            view.setFont(mono)
            view._update_number_area_width()

    def _show_status(self, message: str) -> None:
        self._last_status = message
        self.workspace_page.set_status(message)

    # ---------------------------------------------------------------- geometry
    def _restore_geometry(self) -> None:
        config = self.ctx.config
        if config.window_geometry:
            try:
                self.restoreGeometry(QByteArray.fromBase64(config.window_geometry.encode("ascii")))
            except (ValueError, TypeError):
                pass

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
        try:
            self.ctx.config.window_geometry = bytes(self.saveGeometry().toBase64()).decode("ascii")
            self.ctx.config.last_project = str(self.ctx.root) if self.ctx.root else ""
            save_config(self.ctx.config)
        except OSError:
            pass
        super().closeEvent(event)


__all__ = ["MainWindow"]
