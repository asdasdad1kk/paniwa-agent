"""Settings: appearance, generation defaults, scanning and local data."""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFontDatabase
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    CaptionLabel,
    ComboBox,
    DoubleSpinBox,
    FluentIcon as FIF,
    LineEdit,
    PrimaryPushButton,
    PushButton,
    SmoothScrollArea,
    SpinBox,
    StrongBodyLabel,
    TextEdit as FluentTextEdit,
    TitleLabel,
    TransparentPushButton,
)

from ... import APP_NAME, APP_ID, __version__
from ...config import config_path, data_dir, reset_config
from ...promptlib import FORMAT_LABELS
from ..state import AppContext
from ..theme import ACCENTS, ACCENT_LABELS, THEME_LABELS, muted_color
from ..widgets import Chip, SectionCard, SettingsRow, SwitchRow, confirm, notify


class SettingsPage(QWidget):
    def __init__(self, ctx: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.setObjectName("settingsPage")
        self._loading = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        area = SmoothScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(26, 20, 26, 26)
        layout.setSpacing(14)
        area.setWidget(content)
        area.enableTransparentBackground()
        root.addWidget(area)

        header = QVBoxLayout()
        header.setSpacing(2)
        title = TitleLabel("Ajustes")
        subtitle = CaptionLabel(
            "Todo se guarda en tu perfil de usuario. El harness no contacta con ningún servicio."
        )
        subtitle.setWordWrap(True)
        muted_color(subtitle)
        header.addWidget(title)
        header.addWidget(subtitle)
        layout.addLayout(header)

        layout.addWidget(self._build_appearance())
        layout.addWidget(self._build_generation())
        layout.addWidget(self._build_scanning())
        layout.addWidget(self._build_workspace())
        layout.addWidget(self._build_data())
        layout.addWidget(self._build_about())
        layout.addStretch(1)

        ctx.settingsChanged.connect(self._load)
        self._load()

    # --------------------------------------------------------------------- UI
    def _build_appearance(self) -> QWidget:
        card = SectionCard("Apariencia", "Se aplica al instante en toda la aplicación.", FIF.PALETTE)
        self.theme_combo = ComboBox()
        for key, label in THEME_LABELS.items():
            self.theme_combo.addItem(label, userData=key)
        self.theme_combo.currentIndexChanged.connect(self._appearance_changed)
        self.accent_combo = ComboBox()
        for key, label in ACCENT_LABELS.items():
            self.accent_combo.addItem(label, userData=key)
            self.accent_combo.setItemIcon(self.accent_combo.count() - 1, _color_icon(ACCENTS[key]))
        self.accent_combo.currentIndexChanged.connect(self._appearance_changed)
        self.font_spin = SpinBox()
        self.font_spin.setRange(8, 24)
        self.font_spin.setSuffix(" pt")
        self.font_spin.valueChanged.connect(self._appearance_changed)

        fonts = ["Automática"] + _mono_families()
        self.mono_combo = ComboBox()
        for family in fonts:
            self.mono_combo.addItem(family, userData="" if family == "Automática" else family)
        self.mono_combo.currentIndexChanged.connect(self._appearance_changed)

        card.add_widget(SettingsRow("Tema", "Sigue al sistema o fija claro/oscuro.", self.theme_combo))
        card.add_widget(SettingsRow("Color de acento", "Afecta a botones, focos y resaltados.", self.accent_combo))
        card.add_widget(SettingsRow("Tamaño de letra", "Texto de la interfaz.", self.font_spin))
        card.add_widget(
            SettingsRow(
                "Fuente monoespaciada",
                "Se usa en el prompt, el código y los diffs.",
                self.mono_combo,
            )
        )
        return card

    def _build_generation(self) -> QWidget:
        card = SectionCard(
            "Valores por defecto del prompt",
            "El compositor puede sobrescribirlos en cada sesión.",
            FIF.EDIT,
        )
        self.format_combo = ComboBox()
        for key, label in FORMAT_LABELS.items():
            self.format_combo.addItem(label, userData=key)
        self.format_combo.currentIndexChanged.connect(self._generation_changed)
        self.budget_spin = SpinBox()
        self.budget_spin.setRange(2_000, 1_000_000)
        self.budget_spin.setSingleStep(5_000)
        self.budget_spin.setSuffix(" tokens")
        self.budget_spin.valueChanged.connect(self._generation_changed)
        self.map_spin = SpinBox()
        self.map_spin.setRange(400, 12_000)
        self.map_spin.setSingleStep(500)
        self.map_spin.setSuffix(" tokens")
        self.map_spin.valueChanged.connect(self._generation_changed)
        self.depth_combo = ComboBox()
        self.depth_combo.addItem("1 nivel", userData=1)
        self.depth_combo.addItem("2 niveles", userData=2)
        self.depth_combo.currentIndexChanged.connect(self._generation_changed)

        card.add_widget(SettingsRow("Formato", "Markdown funciona bien en la mayoría de chats.", self.format_combo))
        card.add_widget(SettingsRow("Presupuesto", "Tope aproximado del prompt completo.", self.budget_spin))
        card.add_widget(SettingsRow("Mapa del repositorio", "Tokens reservados al esqueleto de símbolos.", self.map_spin))
        card.add_widget(SettingsRow("Profundidad de imports", "Cuántos niveles seguir desde lo seleccionado.", self.depth_combo))

        self.switch_repo_map = SwitchRow("Incluir mapa del repositorio", "Ahorra contexto y orienta la arquitectura.")
        self.switch_git = SwitchRow("Incluir estado de Git", "Rama y archivos modificados.")
        self.switch_diff = SwitchRow("Incluir diff", "La señal más densa para cambios y revisiones.")
        self.switch_diff_only = SwitchRow("Omitir archivos cubiertos por el diff", "Evita duplicar el mismo contenido.")
        self.switch_related = SwitchRow("Incluir imports relacionados", "Descubre dependencias locales.")
        self.switch_lines = SwitchRow("Numerar líneas", "Facilita referencias ruta:línea.")
        self.switch_redact = SwitchRow("Redactar secretos", "Sustituye claves detectadas antes de copiar.")
        self.switch_truncate = SwitchRow("Truncar archivos grandes", "Conserva cabeza y cola si no cabe entero.")
        for widget in (
            self.switch_repo_map,
            self.switch_git,
            self.switch_diff,
            self.switch_diff_only,
            self.switch_related,
            self.switch_lines,
            self.switch_redact,
            self.switch_truncate,
        ):
            widget.toggled.connect(self._generation_changed)
            card.add_widget(widget)
        return card

    def _build_scanning(self) -> QWidget:
        card = SectionCard(
            "Escaneo de proyectos",
            "Los cambios aquí se aplican al volver a escanear.",
            FIF.SEARCH,
        )
        self.max_file_spin = DoubleSpinBox()
        self.max_file_spin.setRange(0.05, 50.0)
        self.max_file_spin.setDecimals(2)
        self.max_file_spin.setSingleStep(0.5)
        self.max_file_spin.setSuffix(" MB")
        self.max_file_spin.valueChanged.connect(self._scanning_changed)
        self.max_files_spin = SpinBox()
        self.max_files_spin.setRange(100, 200_000)
        self.max_files_spin.setSingleStep(500)
        self.max_files_spin.setSuffix(" archivos")
        self.max_files_spin.valueChanged.connect(self._scanning_changed)

        card.add_widget(
            SettingsRow(
                "Tamaño máximo por archivo",
                "Los archivos mayores se listan pero no se incluyen.",
                self.max_file_spin,
            )
        )
        card.add_widget(
            SettingsRow(
                "Límite de archivos",
                "Protege contra monorepos enormes.",
                self.max_files_spin,
            )
        )
        patterns_label = CaptionLabel("Patrones extra ignorados (uno por línea o separados por comas)")
        muted_color(patterns_label)
        card.add_widget(patterns_label)
        self.ignore_edit = FluentTextEdit()
        self.ignore_edit.setPlaceholderText("*.generated.cs\nmigrations/\nfixtures/*.json")
        self.ignore_edit.setFixedHeight(84)
        self.ignore_edit.textChanged.connect(self._scanning_changed)
        card.add_widget(self.ignore_edit)

        actions = QHBoxLayout()
        self.scan_hint = CaptionLabel("Sin cambios pendientes")
        muted_color(self.scan_hint)
        self.rescan_button = PrimaryPushButton(FIF.SYNC, "Reescanear ahora")
        self.rescan_button.clicked.connect(self._rescan)
        actions.addWidget(self.scan_hint, 1)
        actions.addWidget(self.rescan_button)
        card.add_layout(actions)
        return card

    def _build_workspace(self) -> QWidget:
        card = SectionCard(
            "Espacio de trabajo",
            "Cómo se abren los archivos y qué se recuerda entre sesiones.",
            FIF.FOLDER,
        )
        self.editor_edit = LineEdit()
        self.editor_edit.setPlaceholderText('auto  ·  code -g "{path}"  ·  notepad "{path}"')
        self.editor_edit.textChanged.connect(self._workspace_changed)
        card.add_widget(
            SettingsRow(
                "Comando de editor",
                'Con «auto» se intenta VS Code y, si no existe, el programa asociado. Usa {path}.',
                self.editor_edit,
            )
        )
        self.switch_history = SwitchRow("Guardar al copiar", "Añade al historial local cada prompt copiado.")
        self.switch_history.toggled.connect(self._workspace_changed)
        card.add_widget(self.switch_history)
        self.sessions_spin = SpinBox()
        self.sessions_spin.setRange(0, 5_000)
        self.sessions_spin.setSingleStep(25)
        self.sessions_spin.setSuffix(" sesiones")
        self.sessions_spin.valueChanged.connect(self._workspace_changed)
        card.add_widget(
            SettingsRow(
                "Sesiones conservadas",
                "Las más antiguas se eliminan automáticamente. 0 desactiva el límite.",
                self.sessions_spin,
            )
        )
        return card

    def _build_data(self) -> QWidget:
        card = SectionCard(
            "Datos locales",
            "Configuración, sesiones y nada más. Sin telemetría ni credenciales.",
            FIF.SAVE,
        )
        path_label = CaptionLabel(f"Carpeta de datos: {data_dir()}")
        path_label.setWordWrap(True)
        path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        muted_color(path_label)
        card.add_widget(path_label)
        config_label = CaptionLabel(f"Configuración: {config_path()}")
        config_label.setWordWrap(True)
        config_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        muted_color(config_label)
        card.add_widget(config_label)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        open_button = PushButton(FIF.FOLDER, "Abrir carpeta")
        open_button.clicked.connect(self._open_data_folder)
        export_button = PushButton(FIF.SAVE, "Exportar configuración")
        export_button.clicked.connect(self._export_config)
        reset_button = TransparentPushButton("Restablecer")
        reset_button.clicked.connect(self._reset)
        actions.addWidget(open_button)
        actions.addWidget(export_button)
        actions.addStretch(1)
        actions.addWidget(reset_button)
        card.add_layout(actions)
        return card

    def _build_about(self) -> QWidget:
        card = SectionCard("Acerca de", "", FIF.INFO)
        row = QHBoxLayout()
        row.setSpacing(10)
        text = QVBoxLayout()
        text.setSpacing(3)
        name = StrongBodyLabel(f"{APP_NAME} {__version__}")
        caption = CaptionLabel(
            "Ingeniería de contexto local para chats con LLM. Sin proveedor integrado, "
            "sin red, sin aplicación automática de respuestas."
        )
        caption.setWordWrap(True)
        muted_color(caption)
        text.addWidget(name)
        text.addWidget(caption)
        row.addLayout(text, 1)
        row.addWidget(Chip("100 % local", "success"))
        card.add_layout(row)
        card.add_widget(CaptionLabel(f"Identificador: {APP_ID}"))
        return card

    # ------------------------------------------------------------------ state
    def _load(self) -> None:
        if not hasattr(self, "theme_combo"):
            return
        config = self.ctx.config
        self._loading = True
        try:
            index = self.theme_combo.findData(config.theme)
            if index >= 0:
                self.theme_combo.setCurrentIndex(index)
            index = self.accent_combo.findData(config.accent)
            if index >= 0:
                self.accent_combo.setCurrentIndex(index)
            self.font_spin.setValue(config.font_size)
            index = self.mono_combo.findData(config.mono_font)
            self.mono_combo.setCurrentIndex(max(0, index))
            index = self.format_combo.findData(config.format)
            if index >= 0:
                self.format_combo.setCurrentIndex(index)
            self.budget_spin.setValue(config.budget_tokens)
            self.map_spin.setValue(config.repo_map_tokens)
            index = self.depth_combo.findData(config.related_depth)
            if index >= 0:
                self.depth_combo.setCurrentIndex(index)
            self.switch_repo_map.setChecked(config.include_repo_map)
            self.switch_git.setChecked(config.include_git)
            self.switch_diff.setChecked(config.include_diff)
            self.switch_diff_only.setChecked(config.diff_only)
            self.switch_related.setChecked(config.include_related)
            self.switch_lines.setChecked(config.line_numbers)
            self.switch_redact.setChecked(config.redact)
            self.switch_truncate.setChecked(config.truncate)
            self.max_file_spin.setValue(config.max_file_mb)
            self.max_files_spin.setValue(config.max_files)
            self.ignore_edit.setPlainText(config.extra_ignore)
            self.editor_edit.setText(config.editor_command)
            self.switch_history.setChecked(config.record_history)
            self.sessions_spin.setValue(config.sessions_kept)
        finally:
            self._loading = False

    def _appearance_changed(self) -> None:
        if self._loading:
            return
        self.ctx.update_settings(
            theme=self.theme_combo.currentData() or "auto",
            accent=self.accent_combo.currentData() or "blue",
            font_size=int(self.font_spin.value()),
            mono_font=str(self.mono_combo.currentData() or ""),
        )

    def _generation_changed(self) -> None:
        if self._loading:
            return
        self.ctx.update_settings(
            format=self.format_combo.currentData() or "markdown",
            budget_tokens=int(self.budget_spin.value()),
            repo_map_tokens=int(self.map_spin.value()),
            related_depth=int(self.depth_combo.currentData() or 1),
            include_repo_map=self.switch_repo_map.isChecked(),
            include_git=self.switch_git.isChecked(),
            include_diff=self.switch_diff.isChecked(),
            diff_only=self.switch_diff_only.isChecked(),
            include_related=self.switch_related.isChecked(),
            line_numbers=self.switch_lines.isChecked(),
            redact=self.switch_redact.isChecked(),
            truncate=self.switch_truncate.isChecked(),
        )

    def _scanning_changed(self) -> None:
        if self._loading:
            return
        self.ctx.update_settings(
            max_file_mb=float(self.max_file_spin.value()),
            max_files=int(self.max_files_spin.value()),
            extra_ignore=self.ignore_edit.toPlainText(),
        )
        self.scan_hint.setText("Hay cambios de escaneo pendientes")

    def _workspace_changed(self) -> None:
        if self._loading:
            return
        self.ctx.update_settings(
            editor_command=self.editor_edit.text().strip() or "auto",
            record_history=self.switch_history.isChecked(),
            sessions_kept=int(self.sessions_spin.value()),
        )

    def _rescan(self) -> None:
        if self.ctx.root is None:
            notify(self, "info", "Sin proyecto", "Abre una carpeta primero.", 1600)
            return
        self.ctx.rescan()
        self.scan_hint.setText("Sin cambios pendientes")

    # ---------------------------------------------------------------- actions
    def _open_data_folder(self) -> None:
        folder = data_dir()
        try:
            folder.mkdir(parents=True, exist_ok=True)
            if os.name == "nt":
                os.startfile(folder)  # type: ignore[attr-defined]
            else:
                from PySide6.QtCore import QUrl
                from PySide6.QtGui import QDesktopServices

                QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
        except Exception as error:
            notify(self, "error", "No se pudo abrir la carpeta", str(error))

    def _export_config(self) -> None:
        default = str(Path.home() / "harness-config.json")
        target, _filter = QFileDialog.getSaveFileName(
            self, "Exportar configuración", default, "JSON (*.json)"
        )
        if not target:
            return
        try:
            Path(target).write_text(
                json.dumps(asdict(self.ctx.config), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as error:
            notify(self, "error", "No se pudo exportar", str(error))
            return
        notify(self, "success", "Configuración exportada", target, 2200)

    def _reset(self) -> None:
        if not confirm(
            self,
            "Restablecer ajustes",
            "Se restauran los valores por defecto y se olvidan los proyectos recientes. "
            "El historial de prompts no se toca.",
        ):
            return
        config = reset_config()
        self.ctx.replace_config(config)
        self._load()
        notify(self, "success", "Ajustes restablecidos", "Se aplicaron los valores por defecto.", 2000)


def _mono_families() -> list[str]:
    families = set(QFontDatabase.families())
    preferred = [
        "Cascadia Code",
        "Cascadia Mono",
        "JetBrains Mono",
        "Fira Code",
        "Consolas",
        "DejaVu Sans Mono",
        "Courier New",
    ]
    return [family for family in preferred if family in families]


def _color_icon(color: str):
    from PySide6.QtGui import QIcon, QPixmap

    pixmap = QPixmap(16, 16)
    pixmap.fill(Qt.GlobalColor.transparent)
    from PySide6.QtGui import QPainter

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    painter.drawEllipse(1, 1, 14, 14)
    painter.end()
    return QIcon(pixmap)


__all__ = ["SettingsPage"]
