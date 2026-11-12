"""Workspace: project summary, file selection and preview."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    ComboBox,
    FluentIcon as FIF,
    IndeterminateProgressRing,
    PrimaryPushButton,
    PushButton,
    SearchLineEdit,
    StrongBodyLabel,
    TitleLabel,
    TransparentPushButton,
    TransparentToolButton,
)

from ...gitutils import GitUnavailable, file_diff
from ...scanner import read_text_entry
from ...tokens import format_bytes, format_tokens
from ..file_tree import FileTree
from ..state import AppContext
from ..theme import accent_hex, muted_color, status_color
from ..widgets import (
    Chip,
    CodeView,
    ElidedLabel,
    EmptyState,
    SectionCard,
    StatTile,
    TextDialog,
    TokenMeter,
    confirm,
    count_label,
    make_splitter,
    notify,
)


class WorkspacePage(QWidget):
    composerRequested = Signal()
    scaffoldsRequested = Signal()

    def __init__(self, ctx: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self._syncing = False
        self._current_rel = ""
        self.setAcceptDrops(True)
        self.setObjectName("workspacePage")

        root = QVBoxLayout(self)
        root.setContentsMargins(26, 20, 26, 20)
        root.setSpacing(14)

        header = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        title = TitleLabel("Espacio de trabajo")
        subtitle = CaptionLabel(
            "Elige el contexto exacto que necesita el asistente. Nada sale de este equipo "
            "hasta que tú lo copies."
        )
        subtitle.setWordWrap(True)
        muted_color(subtitle)
        titles.addWidget(title)
        titles.addWidget(subtitle)
        header.addLayout(titles, 1)
        self.recent_combo = ComboBox()
        self.recent_combo.setFixedWidth(210)
        self.recent_combo.setToolTip("Proyectos recientes")
        self.recent_combo.currentIndexChanged.connect(self._open_recent)
        header.addWidget(self.recent_combo, 0, Qt.AlignmentFlag.AlignTop)
        self.open_button = PrimaryPushButton(FIF.FOLDER, "Abrir carpeta")
        self.open_button.clicked.connect(self._choose_folder)
        header.addWidget(self.open_button, 0, Qt.AlignmentFlag.AlignTop)
        root.addLayout(header)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_empty())
        self.stack.addWidget(self._build_loading())
        self.stack.addWidget(self._build_content())
        root.addWidget(self.stack, 1)

        self.status_line = CaptionLabel("")
        self.status_line.setWordWrap(True)
        muted_color(self.status_line)
        root.addWidget(self.status_line)

        self._refresh_recent()
        self._apply_config()
        ctx.projectStarted.connect(self._on_project_started)
        ctx.projectChanged.connect(self._on_project_changed)
        ctx.projectFailed.connect(self._on_project_failed)
        ctx.selectionChanged.connect(self._on_selection_changed)
        ctx.settingsChanged.connect(self._apply_config)

    # ------------------------------------------------------------------- build UI
    def _build_empty(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        card = SectionCard(
            "Contexto local, sin proveedor de IA",
            "Harness Studio indexa tu repositorio en local, selecciona el contexto relevante "
            "y prepara un prompt que puedes pegar en cualquier chat. El harness nunca envía "
            "nada por red ni modifica tu proyecto.",
            FIF.HOME,
        )
        empty = EmptyState(
            FIF.FOLDER,
            "Abre una carpeta para empezar",
            "Arrastra un proyecto aquí o selecciona una carpeta. Se excluyen automáticamente "
            "dependencias, builds y directorios ignorados por .gitignore.",
        )
        select_button = PrimaryPushButton(FIF.FOLDER_ADD, "Seleccionar carpeta")
        select_button.clicked.connect(self._choose_folder)
        create_button = PushButton(FIF.ADD, "Crear proyecto")
        create_button.clicked.connect(self.scaffoldsRequested.emit)
        empty.add_action(select_button)
        empty.add_action(create_button)
        card.add_widget(empty, 1)
        self.recent_layout = QHBoxLayout()
        self.recent_layout.setSpacing(8)
        card.add_layout(self.recent_layout)
        layout.addWidget(card, 1)
        hint = CaptionLabel("Consejo: pulsa Ctrl+O para abrir una carpeta y Ctrl+R para reescanear.")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        muted_color(hint)
        layout.addWidget(hint)
        return page

    def _build_loading(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.loading_ring = IndeterminateProgressRing()
        self.loading_ring.setFixedSize(44, 44)
        layout.addWidget(self.loading_ring, 0, Qt.AlignmentFlag.AlignCenter)
        self.loading_label = CaptionLabel("Escaneando el proyecto…")
        self.loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        muted_color(self.loading_label)
        layout.addWidget(self.loading_label)
        return page

    def _build_content(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        project_card = SectionCard()
        project_row = QHBoxLayout()
        project_row.setSpacing(10)
        project_icon = QLabel()
        project_icon.setPixmap(FIF.FOLDER.icon().pixmap(26, 26))
        project_icon.setFixedSize(26, 26)
        project_row.addWidget(project_icon)
        project_text = QVBoxLayout()
        project_text.setSpacing(3)
        self.project_path = ElidedLabel("")
        font = self.project_path.font()
        font.setPointSize(11)
        font.setBold(True)
        self.project_path.setFont(font)
        project_text.addWidget(self.project_path)
        self.project_chips = QHBoxLayout()
        self.project_chips.setSpacing(6)
        self.branch_chip = Chip("Sin Git", "neutral")
        self.files_chip = Chip("0 archivos", "accent")
        self.changed_chip = Chip("0 cambios", "warning")
        self.size_chip = Chip("0 B", "neutral")
        for chip in (self.branch_chip, self.files_chip, self.changed_chip, self.size_chip):
            self.project_chips.addWidget(chip)
        self.project_chips.addStretch(1)
        project_text.addLayout(self.project_chips)
        project_row.addLayout(project_text, 1)
        self.copy_path_button = TransparentToolButton(FIF.COPY, page)
        self.copy_path_button.setToolTip("Copiar ruta")
        self.copy_path_button.clicked.connect(self._copy_project_path)
        self.explorer_button = TransparentToolButton(FIF.FOLDER, page)
        self.explorer_button.setToolTip("Abrir en el explorador")
        self.explorer_button.clicked.connect(self._open_project_folder)
        self.rescan_button = TransparentToolButton(FIF.SYNC, page)
        self.rescan_button.setToolTip("Volver a escanear (Ctrl+R)")
        self.rescan_button.clicked.connect(self.ctx.rescan)
        for button in (self.copy_path_button, self.explorer_button, self.rescan_button):
            project_row.addWidget(button)
        project_card.add_layout(project_row)
        layout.addWidget(project_card)

        stats = QHBoxLayout()
        stats.setSpacing(10)
        self.tile_files = StatTile("Archivos", "0", FIF.DOCUMENT)
        self.tile_changed = StatTile("Con cambios", "0", FIF.HISTORY)
        self.tile_languages = StatTile("Lenguajes", "0", FIF.CODE)
        self.tile_scan = StatTile("Escaneo", "0 ms", FIF.STOP_WATCH)
        for tile in (self.tile_files, self.tile_changed, self.tile_languages, self.tile_scan):
            stats.addWidget(tile, 1)
        layout.addLayout(stats)

        splitter = make_splitter(Qt.Orientation.Horizontal)

        files_card = SectionCard(
            "Archivos",
            "Marca lo que debe ver el asistente. Espacio alterna; los cambios de Git se "
            "preseleccionan al abrir el proyecto.",
            FIF.DOCUMENT,
        )
        filters = QHBoxLayout()
        filters.setSpacing(8)
        self.search = SearchLineEdit()
        self.search.setPlaceholderText("Filtrar por ruta…")
        self.search.textChanged.connect(self._filter_changed)
        self.filter_combo = ComboBox()
        self.filter_combo.addItems(["Todos", "Modificados", "Seleccionados", "Código"])
        self.filter_combo.setFixedWidth(135)
        self.filter_combo.currentTextChanged.connect(self._filter_changed)
        filters.addWidget(self.search, 1)
        filters.addWidget(self.filter_combo)
        files_card.add_layout(filters)

        quick = QHBoxLayout()
        quick.setSpacing(6)
        changed_button = PushButton("Cambios")
        changed_button.clicked.connect(self._select_changed)
        all_button = PushButton("Todo")
        all_button.clicked.connect(self._select_all)
        none_button = PushButton("Nada")
        none_button.clicked.connect(self._clear_selection)
        quick.addWidget(changed_button)
        quick.addWidget(all_button)
        quick.addWidget(none_button)
        quick.addStretch(1)
        expand_button = TransparentToolButton(FIF.CHEVRON_DOWN_MED)
        expand_button.setToolTip("Expandir todo")
        expand_button.clicked.connect(lambda: self.tree.expand_all())
        collapse_button = TransparentToolButton(FIF.CHEVRON_RIGHT_MED)
        collapse_button.setToolTip("Contraer todo")
        collapse_button.clicked.connect(lambda: self.tree.collapse_all())
        quick.addWidget(expand_button)
        quick.addWidget(collapse_button)
        files_card.add_layout(quick)
        self.tree = FileTree()
        self.tree.selectionChanged.connect(self._tree_selection_changed)
        self.tree.fileFocused.connect(self._show_file)
        self.tree.openRequested.connect(self._open_in_editor)
        self.tree.diffRequested.connect(self._show_diff)
        files_card.add_widget(self.tree, 1)

        preview_card = SectionCard(
            "Vista previa",
            "Revisa el contenido exacto antes de enviarlo. Los secretos detectados se marcan.",
            FIF.VIEW,
        )
        self.preview_actions = self.preview_card_actions(preview_card)
        self.preview_meta = QHBoxLayout()
        self.preview_meta.setSpacing(6)
        self.preview_path = ElidedLabel("Ningún archivo seleccionado")
        font = self.preview_path.font()
        font.setPointSize(10)
        font.setBold(True)
        self.preview_path.setFont(font)
        self.preview_meta.addWidget(self.preview_path, 1)
        self.preview_status_chip = Chip("", "neutral")
        self.preview_language_chip = Chip("", "accent")
        self.preview_tokens_chip = Chip("", "neutral")
        for chip in (self.preview_status_chip, self.preview_language_chip, self.preview_tokens_chip):
            chip.setVisible(False)
            self.preview_meta.addWidget(chip)
        preview_card.add_layout(self.preview_meta)
        self.preview_stack = QStackedWidget()
        self.preview_empty = EmptyState(
            FIF.CODE,
            "Selecciona un archivo",
            "Haz clic en cualquier archivo del árbol para revisar su contenido y su coste en tokens.",
        )
        self.preview_view = CodeView(line_numbers=True)
        self.preview_stack.addWidget(self.preview_empty)
        self.preview_stack.addWidget(self.preview_view)
        preview_card.add_widget(self.preview_stack, 1)
        self.preview_footer = CaptionLabel("")
        self.preview_footer.setWordWrap(True)
        muted_color(self.preview_footer)
        preview_card.add_widget(self.preview_footer)

        splitter.addWidget(files_card)
        splitter.addWidget(preview_card)
        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 4)
        splitter.setSizes([640, 520])
        layout.addWidget(splitter, 1)

        footer = SectionCard()
        footer_row = QHBoxLayout()
        footer_row.setSpacing(14)
        summary = QVBoxLayout()
        summary.setSpacing(3)
        self.selection_label = StrongBodyLabel("0 archivos seleccionados")
        self.selection_caption = CaptionLabel("Sin contexto seleccionado")
        muted_color(self.selection_caption)
        summary.addWidget(self.selection_label)
        summary.addWidget(self.selection_caption)
        footer_row.addLayout(summary)
        self.token_meter = TokenMeter()
        footer_row.addWidget(self.token_meter, 1)
        clear_button = TransparentPushButton("Limpiar")
        clear_button.clicked.connect(self._clear_selection)
        self.composer_button = PrimaryPushButton(FIF.SEND, "Generar prompt")
        self.composer_button.clicked.connect(self.composerRequested.emit)
        footer_row.addWidget(clear_button)
        footer_row.addWidget(self.composer_button)
        footer.add_layout(footer_row)
        layout.addWidget(footer)
        return page

    def preview_card_actions(self, card: SectionCard) -> None:
        self.edit_button = TransparentToolButton(FIF.EDIT)
        self.edit_button.setToolTip("Abrir en el editor")
        self.edit_button.clicked.connect(lambda: self._open_in_editor(self._current_rel))
        self.diff_button = TransparentToolButton(FIF.HISTORY)
        self.diff_button.setToolTip("Ver diff de Git")
        self.diff_button.clicked.connect(lambda: self._show_diff(self._current_rel))
        self.edit_button.setEnabled(False)
        self.diff_button.setEnabled(False)
        card.header_layout.addWidget(self.edit_button)
        card.header_layout.addWidget(self.diff_button)

    # ------------------------------------------------------------------ signals
    def set_status(self, message: str) -> None:
        self.status_line.setText(message)

    def _on_project_started(self, path: str) -> None:
        self.loading_label.setText(f"Escaneando {Path(path).name}…")
        self.stack.setCurrentIndex(1)
        self.loading_ring.show()

    def _on_project_failed(self, message: str) -> None:
        self.stack.setCurrentIndex(0)
        self._refresh_recent()
        notify(self, "error", "No se pudo abrir el proyecto", message, 5000)

    def _on_project_changed(self) -> None:
        scan = self.ctx.scan
        if scan is None:
            self.stack.setCurrentIndex(0)
            return
        self.project_path.setText(str(scan.root))
        self.project_path.setToolTip(str(scan.root))
        self.branch_chip.setText(
            f"{self.ctx.git.branch}" if self.ctx.git and self.ctx.git.branch else "Sin Git"
        )
        self.branch_chip.set_tone("violet" if self.ctx.git and self.ctx.git.branch else "neutral")
        self.files_chip.setText(count_label(len(scan.files), "archivo", "archivos"))
        self.changed_chip.setText(f"{self.ctx.changed_count} cambios")
        self.size_chip.setText(format_bytes(scan.total_bytes))
        self.tile_files.set_value(str(len(scan.files)))
        self.tile_changed.set_value(str(self.ctx.changed_count))
        self.tile_languages.set_value(str(len({entry.language for entry in scan.files})))
        self.tile_scan.set_value(f"{scan.duration_ms} ms")
        self.tree.populate(scan, self.ctx.selected)
        self.stack.setCurrentIndex(2)
        self._refresh_recent()
        self._update_footer()
        first = next(
            (rel for rel in self.ctx.selected if rel in scan.index()),
            next((entry.rel for entry in scan.files if entry.is_source), ""),
        )
        if first:
            self._show_file(first)
        else:
            self._show_file("")

    def _on_selection_changed(self, selected: set[str]) -> None:
        if self._syncing:
            return
        self._syncing = True
        self.tree.apply_selection(selected)
        self._syncing = False
        self._update_footer()
        if self.filter_combo.currentText() == "Seleccionados":
            self.tree.set_filter(self.search.text(), "Seleccionados")

    def _tree_selection_changed(self) -> None:
        if self._syncing:
            return
        selected = self.tree.selected_paths()
        self._syncing = True
        self.ctx.update_selection(selected)
        self._syncing = False
        self._update_footer()
        if self.filter_combo.currentText() == "Seleccionados":
            self.tree.set_filter(self.search.text(), "Seleccionados")

    def _update_footer(self) -> None:
        count = len(self.ctx.selected)
        noun = count_label(count, "archivo", "archivos")
        self.selection_label.setText(
            f"{noun} seleccionado{'s' if count != 1 else ''}"
        )
        if count:
            self.selection_caption.setText(
                f"≈ {format_tokens(self.ctx.selected_tokens)} tokens estimados · "
                "los relacionados se añaden al generar"
            )
        else:
            self.selection_caption.setText("Sin contexto seleccionado")
        self.token_meter.update_values(self.ctx.selected_tokens, self.ctx.config.budget_tokens)
        self.composer_button.setEnabled(count > 0)

    def _apply_config(self) -> None:
        self._update_footer()
        self.preview_view.set_accent(accent_hex(self.ctx.config))
        self._refresh_recent()

    # ------------------------------------------------------------------ filters
    def _filter_changed(self) -> None:
        self.tree.set_filter(self.search.text(), self.filter_combo.currentText())

    def _select_changed(self) -> None:
        self.tree.select_changed()

    def _select_all(self) -> None:
        self.tree.select_all()

    def _clear_selection(self) -> None:
        self.tree.clear_selection()

    # ------------------------------------------------------------------ preview
    def _show_file(self, rel: str) -> None:
        if self.ctx.scan is None:
            return
        self._current_rel = rel
        entry = self.ctx.scan.index().get(rel)
        if entry is None:
            self.preview_stack.setCurrentIndex(0)
            self.preview_path.setText("Ningún archivo seleccionado")
            for chip in (self.preview_status_chip, self.preview_language_chip, self.preview_tokens_chip):
                chip.setVisible(False)
            self.preview_footer.setText("")
            self.edit_button.setEnabled(False)
            self.diff_button.setEnabled(False)
            return
        self.ctx.set_active_file(rel)
        self.preview_path.setText(rel)
        self.preview_status_chip.setText(entry.change_label)
        self.preview_status_chip.set_tone(
            "warning" if entry.is_changed else "neutral"
        )
        self.preview_language_chip.setText(entry.language)
        self.preview_tokens_chip.setText(f"≈ {format_tokens(entry.estimated_tokens)} tok")
        for chip in (self.preview_status_chip, self.preview_language_chip, self.preview_tokens_chip):
            chip.setVisible(True)
        self.edit_button.setEnabled(True)
        self.diff_button.setEnabled(entry.is_changed)
        self.preview_footer.setText(
            f"{self._human_size(entry.size)} · {entry.language} · {entry.change_label}"
            + (f" · Archivo sensible: {entry.sensitive}" if entry.sensitive else "")
        )
        if entry.too_large:
            self.preview_stack.setCurrentIndex(0)
            self.preview_empty.findChildren(QLabel)
            return
        try:
            text = self.ctx.content_cache.get(entry)
        except Exception as error:
            notify(self, "error", "No se pudo leer el archivo", str(error))
            text = None
        if text is None:
            self.preview_stack.setCurrentIndex(0)
            return
        preview_text = text
        if len(preview_text) > 300_000:
            preview_text = preview_text[:300_000] + "\n⋯ vista previa truncada ⋯\n"
        self.preview_view.set_content(preview_text, entry.language)
        self.preview_view.set_accent(accent_hex(self.ctx.config))
        self.preview_stack.setCurrentIndex(1)

    def _human_size(self, size: int) -> str:
        if size >= 1024 * 1024:
            return f"{size / 1024 / 1024:.1f} MB"
        if size >= 1024:
            return f"{size / 1024:.1f} kB"
        return f"{size} B"

    def _show_diff(self, rel: str) -> None:
        if not rel or self.ctx.root is None:
            return
        entry = self.ctx.entry(rel)
        try:
            text = file_diff(self.ctx.root, rel)
            if entry is not None and entry.git_code.strip() == "??":
                content = read_text_entry(entry)
                text = f"Archivo sin seguimiento (contenido completo):\n\n{content}"
        except (GitUnavailable, OSError, ValueError) as error:
            notify(self, "warning", "Diff no disponible", str(error))
            return
        dialog = TextDialog(f"Diff · {rel}", text, self, "diff", 980, 680)
        dialog.exec()

    # ------------------------------------------------------------------- actions
    def _choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Abrir proyecto", str(Path.home()))
        if folder:
            self.ctx.open_project(folder)

    def _refresh_recent(self) -> None:
        recents = self.ctx.config.recent_projects[:6]
        self.recent_combo.blockSignals(True)
        self.recent_combo.clear()
        self.recent_combo.addItem("Recientes…", userData=None)
        for path in recents:
            self.recent_combo.addItem(Path(path).name, userData=path)
        self.recent_combo.setCurrentIndex(0)
        self.recent_combo.blockSignals(False)
        self.recent_combo.setVisible(bool(recents))
        while self.recent_layout.count():
            item = self.recent_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        if not recents:
            return
        label = QLabel("Recientes")
        muted_color(label)
        self.recent_layout.addWidget(label)
        for path in recents[:4]:
            button = PushButton(Path(path).name)
            button.setToolTip(path)
            button.clicked.connect(lambda _checked=False, value=path: self.ctx.open_project(value))
            self.recent_layout.addWidget(button)
        self.recent_layout.addStretch(1)

    def _open_recent(self, index: int) -> None:
        path = self.recent_combo.itemData(index)
        if path:
            self.ctx.open_project(path)
        self.recent_combo.blockSignals(True)
        self.recent_combo.setCurrentIndex(0)
        self.recent_combo.blockSignals(False)

    def _copy_project_path(self) -> None:
        if self.ctx.root is None:
            return
        try:
            from ...clipboard import copy_text

            copy_text(str(self.ctx.root))
            notify(self, "success", "Ruta copiada", str(self.ctx.root), 1800)
        except Exception as error:
            notify(self, "error", "No se pudo copiar", str(error))

    def _open_project_folder(self) -> None:
        if self.ctx.root is None:
            return
        try:
            os.startfile(self.ctx.root)  # type: ignore[attr-defined]
        except Exception as error:
            notify(self, "error", "No se pudo abrir", str(error))

    def _open_in_editor(self, rel: str) -> None:
        if not rel or self.ctx.root is None:
            return
        path = self.ctx.root / rel
        try:
            command = self.ctx.config.editor_command.strip()
            if command and command.lower() != "auto":
                import shlex

                parts = shlex.split(command, posix=os.name != "nt")
                if not any("{path}" in part for part in parts):
                    parts.append(str(path))
                parts = [part.replace("{path}", str(path)) for part in parts]
                subprocess.Popen(parts, cwd=str(self.ctx.root))
                return
            code = shutil.which("code")
            if code:
                subprocess.Popen([code, "-g", f"{path}:1"], cwd=str(self.ctx.root))
            else:
                os.startfile(path)  # type: ignore[attr-defined]
        except Exception as error:
            notify(self, "error", "No se pudo abrir el editor", str(error))

    # --------------------------------------------------------------- drag & drop
    def dragEnterEvent(self, event) -> None:  # noqa: N802 - Qt API
        urls = event.mimeData().urls()
        if urls and Path(urls[0].toLocalFile()).is_dir():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802 - Qt API
        urls = event.mimeData().urls()
        if urls:
            path = Path(urls[0].toLocalFile())
            if path.is_dir():
                self.ctx.open_project(path)
                event.acceptProposedAction()


__all__ = ["WorkspacePage"]
