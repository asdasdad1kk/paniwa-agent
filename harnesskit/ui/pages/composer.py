"""Composer: task preset, options and prompt assembly."""

from __future__ import annotations

import hashlib
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QStackedWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    ComboBox,
    FluentIcon as FIF,
    PrimaryPushButton,
    SmoothScrollArea,
    SpinBox,
    TextEdit as FluentTextEdit,
    TitleLabel,
    TransparentPushButton,
    TransparentToolButton,
    TreeWidget,
)

from ...clipboard import copy_text
from ...engine import generate_prompt
from ...models import GenerateOptions, PromptBundle
from ...promptlib import FORMAT_LABELS, TASKS, resolve_task
from ...tokens import format_tokens
from ..state import AppContext
from ..theme import accent_hex, muted_color
from ..widgets import (
    Chip,
    CodeView,
    EmptyState,
    SectionCard,
    SwitchRow,
    TextDialog,
    TokenMeter,
    make_splitter,
    notify,
)
from ..workers import TaskWorker

_TIER_LABELS = {
    "cambio": "Cambios",
    "seleccionado": "Seleccionados",
    "relacionado": "Relacionados",
    "extra": "Extra",
}


class ComposerPage(QWidget):
    workspaceRequested = Signal()

    def __init__(self, ctx: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.setObjectName("composerPage")
        self.bundle: PromptBundle | None = None
        self._generation = 0
        self._syncing = False
        self._setting_prompt = False
        self._manual = False

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(450)
        self._debounce.timeout.connect(self.generate)

        root = QVBoxLayout(self)
        root.setContentsMargins(26, 20, 26, 20)
        root.setSpacing(14)

        header = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        title = TitleLabel("Compositor")
        subtitle = CaptionLabel(
            "La tarea, las restricciones y el contexto se combinan en un único prompt "
            "determinista. Revísalo y pégalo en el chat que prefieras."
        )
        subtitle.setWordWrap(True)
        muted_color(subtitle)
        titles.addWidget(title)
        titles.addWidget(subtitle)
        header.addLayout(titles, 1)
        self.copy_button = PrimaryPushButton(FIF.COPY, "Copiar prompt")
        self.copy_button.clicked.connect(self._copy_prompt)
        header.addWidget(self.copy_button, 0, Qt.AlignmentFlag.AlignTop)
        root.addLayout(header)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_empty())
        self.stack.addWidget(self._build_content())
        root.addWidget(self.stack, 1)

        ctx.projectChanged.connect(self._on_project_changed)
        ctx.selectionChanged.connect(lambda _selected: self._schedule())
        ctx.settingsChanged.connect(self._apply_config)

        self._apply_config()
        self._on_project_changed()

    # --------------------------------------------------------------------- UI
    def _build_empty(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        card = SectionCard(
            "Primero abre un proyecto",
            "El compositor necesita un árbol de archivos y, opcionalmente, el estado de Git.",
            FIF.EDIT,
        )
        empty = EmptyState(
            FIF.FOLDER,
            "No hay proyecto activo",
            "Abre una carpeta en el espacio de trabajo para elegir contexto y generar prompts.",
        )
        button = PrimaryPushButton(FIF.FOLDER, "Ir al espacio de trabajo")
        button.clicked.connect(self.workspaceRequested.emit)
        empty.add_action(button)
        card.add_widget(empty, 1)
        layout.addWidget(card, 1)
        return page

    def _build_content(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)

        splitter = make_splitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_controls())
        splitter.addWidget(self._build_prompt())
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 6)
        splitter.setSizes([430, 780])
        layout.addWidget(splitter, 1)
        return page

    def _build_controls(self) -> QWidget:
        area = SmoothScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 8, 8)
        layout.setSpacing(12)
        area.setWidget(content)
        area.enableTransparentBackground()

        # Task -------------------------------------------------------------
        task_card = SectionCard("Tarea", "", FIF.CODE)
        self.task_combo = ComboBox()
        for task in TASKS:
            self.task_combo.addItem(task.label, userData=task.key)
        self.task_combo.currentIndexChanged.connect(self._task_changed)
        task_card.add_widget(self.task_combo)
        self.task_description = CaptionLabel("")
        self.task_description.setWordWrap(True)
        self.task_description.setTextColor(QColor(105, 105, 105), QColor(165, 165, 165))
        task_card.add_widget(self.task_description)
        layout.addWidget(task_card)

        # Request ----------------------------------------------------------
        request_card = SectionCard(
            "Solicitud",
            "Sé concreto: qué debe cambiar, dónde y cómo se comprueba.",
            FIF.EDIT,
        )
        self.request_edit = FluentTextEdit()
        self.request_edit.setPlaceholderText(
            "Ejemplo: añade reintentos con backoff al cliente HTTP y cubre el caso "
            "de timeout con una prueba."
        )
        self.request_edit.setMinimumHeight(118)
        self.request_edit.textChanged.connect(self._schedule)
        request_card.add_widget(self.request_edit)
        quick_row = QHBoxLayout()
        quick_row.setSpacing(6)
        hint = CaptionLabel("Ctrl+Enter genera")
        muted_color(hint)
        quick_row.addWidget(hint, 1)
        self.generate_button = PrimaryPushButton(FIF.SYNC, "Generar")
        self.generate_button.clicked.connect(self.generate)
        quick_row.addWidget(self.generate_button)
        request_card.add_layout(quick_row)
        layout.addWidget(request_card)

        # Options ----------------------------------------------------------
        options_card = SectionCard(
            "Opciones de contexto",
            "El presupuesto se reparte entre diff, mapa y archivos, en ese orden de valor.",
            FIF.SETTING,
        )
        self.format_combo = ComboBox()
        for key, label in FORMAT_LABELS.items():
            self.format_combo.addItem(label, userData=key)
        self.format_combo.currentIndexChanged.connect(self._options_changed)
        self.budget_spin = SpinBox()
        self.budget_spin.setRange(2_000, 1_000_000)
        self.budget_spin.setSingleStep(5_000)
        self.budget_spin.setSuffix(" tokens")
        self.budget_spin.valueChanged.connect(self._options_changed)
        options_card.add_layout(self._field_row("Formato", self.format_combo))
        options_card.add_layout(self._field_row("Presupuesto", self.budget_spin))

        grid = QGridLayout()
        grid.setContentsMargins(0, 4, 0, 0)
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(2)
        self.switch_map = SwitchRow("Mapa del repositorio", "", True)
        self.switch_map.setToolTip("Esqueleto de archivos y símbolos; orienta sin gastar mucho.")
        self.switch_git = SwitchRow("Estado de Git", "", True)
        self.switch_git.setToolTip("Rama y archivos modificados, útil para tareas sobre cambios.")
        self.switch_diff = SwitchRow("Diff de Git", "", True)
        self.switch_diff.setToolTip("Los cambios reales son la señal más densa para bugfix y review.")
        self.switch_diff_only = SwitchRow("Solo diff", "", False)
        self.switch_diff_only.setToolTip("Omite el archivo completo cuando el diff ya lo cubre.")
        self.switch_related = SwitchRow("Imports relacionados", "", True)
        self.switch_related.setToolTip("Añade archivos importados por los seleccionados.")
        self.switch_lines = SwitchRow("Numerar líneas", "", False)
        self.switch_lines.setToolTip("Facilita referencias ruta:línea en la respuesta.")
        self.switch_redact = SwitchRow("Redactar secretos", "", True)
        self.switch_redact.setToolTip("Sustituye claves y tokens detectados antes de copiar.")
        self.switch_truncate = SwitchRow("Truncar si no cabe", "", True)
        self.switch_truncate.setToolTip("Incluye cabeza y cola del archivo en lugar de omitirlo.")
        switches = (
            self.switch_map,
            self.switch_git,
            self.switch_diff,
            self.switch_diff_only,
            self.switch_related,
            self.switch_lines,
            self.switch_redact,
            self.switch_truncate,
        )
        for index, widget in enumerate(switches):
            grid.addWidget(widget, index // 2, index % 2)
            widget.toggled.connect(self._options_changed)
        options_card.add_layout(grid)

        depth_row = QHBoxLayout()
        depth_row.setSpacing(10)
        depth_label = BodyLabel("Profundidad de relacionados")
        depth_row.addWidget(depth_label, 1)
        self.depth_combo = ComboBox()
        self.depth_combo.addItem("1 nivel", userData=1)
        self.depth_combo.addItem("2 niveles", userData=2)
        self.depth_combo.setFixedWidth(120)
        self.depth_combo.currentIndexChanged.connect(self._options_changed)
        depth_row.addWidget(self.depth_combo)
        options_card.add_layout(depth_row)

        map_row = QHBoxLayout()
        map_row.setSpacing(10)
        map_label = BodyLabel("Presupuesto del mapa")
        map_row.addWidget(map_label, 1)
        self.map_spin = SpinBox()
        self.map_spin.setRange(400, 12_000)
        self.map_spin.setSingleStep(500)
        self.map_spin.setSuffix(" tokens")
        self.map_spin.setFixedWidth(172)
        self.map_spin.valueChanged.connect(self._options_changed)
        map_row.addWidget(self.map_spin)
        options_card.add_layout(map_row)
        layout.addWidget(options_card)

        # Extra instructions ----------------------------------------------
        extra_card = SectionCard(
            "Instrucciones adicionales",
            "Se añaden al prompt tal cual. Úsalas para convenciones del equipo.",
            FIF.FONT,
        )
        self.extra_edit = FluentTextEdit()
        self.extra_edit.setPlaceholderText(
            "Ejemplo: usa solo la librería estándar; mantén los mensajes de error en español."
        )
        self.extra_edit.setFixedHeight(78)
        self.extra_edit.textChanged.connect(self._schedule)
        extra_card.add_widget(self.extra_edit)
        layout.addWidget(extra_card)
        layout.addStretch(1)
        return area

    def _build_prompt(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        prompt_card = SectionCard(
            "Prompt",
            "Editable: puedes retocar el texto antes de copiarlo. Nada se envía automáticamente.",
            FIF.DOCUMENT,
        )
        self.reset_button = TransparentPushButton("Usar generado")
        self.reset_button.setToolTip("Descarta tus ediciones y vuelve al último prompt generado.")
        self.reset_button.clicked.connect(self._reset_prompt)
        self.reset_button.setVisible(False)
        self.save_button = TransparentToolButton(FIF.SAVE, page)
        self.save_button.setToolTip("Guardar como archivo .md")
        self.save_button.clicked.connect(self._save_prompt)
        self.history_button = TransparentToolButton(FIF.HISTORY, page)
        self.history_button.setToolTip("Guardar en el historial local")
        self.history_button.clicked.connect(self._save_session)
        self.expand_button = TransparentToolButton(FIF.ZOOM, page)
        self.expand_button.setToolTip("Ver el prompt en una ventana grande")
        self.expand_button.clicked.connect(self._show_prompt_dialog)
        for button in (self.reset_button, self.save_button, self.history_button, self.expand_button):
            prompt_card.header_layout.addWidget(button)

        stats = QHBoxLayout()
        stats.setSpacing(6)
        self.files_chip = Chip("0 archivos", "accent")
        self.tokens_chip = Chip("0 tokens", "neutral")
        self.hash_chip = Chip("", "neutral")
        self.edited_chip = Chip("Editado", "warning")
        self.edited_chip.setVisible(False)
        for chip in (self.files_chip, self.tokens_chip, self.hash_chip, self.edited_chip):
            stats.addWidget(chip)
        stats.addStretch(1)
        self.status_label = CaptionLabel("Listo")
        muted_color(self.status_label)
        stats.addWidget(self.status_label)
        prompt_card.add_layout(stats)

        self.token_meter = TokenMeter()
        prompt_card.add_widget(self.token_meter)

        self.warnings_box = QVBoxLayout()
        self.warnings_box.setSpacing(4)
        prompt_card.add_layout(self.warnings_box)

        self.prompt_stack = QStackedWidget()
        self.prompt_empty = EmptyState(
            FIF.EDIT,
            "Escribe una solicitud",
            "El prompt se genera automáticamente al cambiar la tarea, la solicitud "
            "o los archivos seleccionados.",
        )
        self.prompt_view = CodeView(line_numbers=True, read_only=False)
        self.prompt_view.set_word_wrap(True)
        self.prompt_view.setPlaceholderText("El prompt aparecerá aquí…")
        self.prompt_view.textChanged.connect(self._prompt_edited)
        self.prompt_stack.addWidget(self.prompt_empty)
        self.prompt_stack.addWidget(self.prompt_view)
        prompt_card.add_widget(self.prompt_stack, 1)
        layout.addWidget(prompt_card, 3)

        context_card = SectionCard(
            "Contexto incluido",
            "Qué entró, cómo y a qué coste. Lo excluido se explica para que puedas corregirlo.",
            FIF.DOCUMENT,
        )
        self.context_tree = TreeWidget()
        self.context_tree.setColumnCount(3)
        self.context_tree.setHeaderLabels(["Archivo", "Modo", "Tokens"])
        self.context_tree.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.context_tree.setRootIsDecorated(True)
        self.context_tree.setAlternatingRowColors(False)
        self.context_tree.setUniformRowHeights(True)
        header = self.context_tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.resizeSection(1, 150)
        header.resizeSection(2, 84)
        self.context_tree.setIndentation(14)
        context_card.add_widget(self.context_tree, 1)
        self.context_footer = CaptionLabel("")
        self.context_footer.setWordWrap(True)
        muted_color(self.context_footer)
        context_card.add_widget(self.context_footer)
        layout.addWidget(context_card, 2)
        return page

    def _field_row(self, label: str, control: QWidget) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)
        text = BodyLabel(label)
        row.addWidget(text, 1)
        if isinstance(control, SpinBox):
            control.setFixedWidth(210)
        else:
            control.setFixedWidth(178)
        row.addWidget(control)
        return row

    # ---------------------------------------------------------------- options
    def _current_options(self) -> GenerateOptions:
        options = self.ctx.config.to_generate_options()
        options.format = self.format_combo.currentData() or options.format
        options.budget_tokens = int(self.budget_spin.value())
        options.include_repo_map = self.switch_map.isChecked()
        options.repo_map_tokens = int(self.map_spin.value())
        options.include_git = self.switch_git.isChecked()
        options.include_diff = self.switch_diff.isChecked()
        options.diff_only = self.switch_diff_only.isChecked()
        options.include_related = self.switch_related.isChecked()
        options.related_depth = int(self.depth_combo.currentData() or 1)
        options.line_numbers = self.switch_lines.isChecked()
        options.redact = self.switch_redact.isChecked()
        options.truncate = self.switch_truncate.isChecked()
        options.custom_instructions = self.extra_edit.toPlainText()
        return options

    def _apply_config(self) -> None:
        if not hasattr(self, "task_combo"):
            return
        config = self.ctx.config
        self._syncing = True
        try:
            index = self.format_combo.findData(config.format)
            if index >= 0:
                self.format_combo.setCurrentIndex(index)
            self.budget_spin.setValue(config.budget_tokens)
            self.switch_map.setChecked(config.include_repo_map)
            self.switch_git.setChecked(config.include_git)
            self.switch_diff.setChecked(config.include_diff)
            self.switch_diff_only.setChecked(config.diff_only)
            self.switch_related.setChecked(config.include_related)
            index = self.depth_combo.findData(config.related_depth)
            if index >= 0:
                self.depth_combo.setCurrentIndex(index)
            self.switch_lines.setChecked(config.line_numbers)
            self.switch_redact.setChecked(config.redact)
            self.switch_truncate.setChecked(config.truncate)
            self.map_spin.setValue(config.repo_map_tokens)
            self.prompt_view.set_accent(accent_hex(config))
        finally:
            self._syncing = False
        self.token_meter.update_values(0, config.budget_tokens)

    def _options_changed(self) -> None:
        if self._syncing:
            return
        self.ctx.update_settings(
            format=self.format_combo.currentData() or "markdown",
            budget_tokens=int(self.budget_spin.value()),
            include_repo_map=self.switch_map.isChecked(),
            repo_map_tokens=int(self.map_spin.value()),
            include_git=self.switch_git.isChecked(),
            include_diff=self.switch_diff.isChecked(),
            diff_only=self.switch_diff_only.isChecked(),
            include_related=self.switch_related.isChecked(),
            related_depth=int(self.depth_combo.currentData() or 1),
            line_numbers=self.switch_lines.isChecked(),
            redact=self.switch_redact.isChecked(),
            truncate=self.switch_truncate.isChecked(),
        )
        self._schedule()

    def _task_changed(self) -> None:
        task = resolve_task(self.task_combo.currentData() or "feature")
        self.task_description.setText(task.short)
        if not self._syncing:
            self._schedule()

    def _apply_task(self, key: str) -> None:
        index = self.task_combo.findData(key)
        if index >= 0:
            self._syncing = True
            self.task_combo.setCurrentIndex(index)
            self._syncing = False
        task = resolve_task(key)
        self.task_description.setText(task.short)

    # -------------------------------------------------------------- lifecycle
    def _on_project_changed(self) -> None:
        if self.ctx.scan is None:
            self.stack.setCurrentIndex(0)
            return
        self.stack.setCurrentIndex(1)
        self._schedule()

    def _schedule(self) -> None:
        if not hasattr(self, "request_edit") or self.ctx.scan is None:
            return
        self._debounce.start()

    def generate(self) -> None:
        self._debounce.stop()
        scan = self.ctx.scan
        if scan is None:
            return
        options = self._current_options()
        request = self.request_edit.toPlainText().strip()
        if not request:
            self.prompt_stack.setCurrentIndex(0)
            self.status_label.setText("Escribe una solicitud para generar")
            self._clear_context_tree()
            self.files_chip.setText("0 archivos")
            self.tokens_chip.setText("0 tokens")
            self.hash_chip.setText("")
            self.token_meter.update_values(0, options.budget_tokens)
            self.bundle = None
            self._render_warnings([])
            return
        self._generation += 1
        generation = self._generation
        task_key = self.task_combo.currentData() or "feature"
        selected = set(self.ctx.selected)
        self.generate_button.setEnabled(False)
        self.status_label.setText("Generando…")
        worker = TaskWorker(
            generate_prompt,
            scan,
            task_key,
            request,
            options,
            selected,
            content_cache=self.ctx.content_cache,
            map_cache=self.ctx.map_cache,
        )
        worker.signals.finished.connect(
            lambda bundle: self._generated(bundle, generation)
        )
        worker.signals.error.connect(lambda message: self._failed(message, generation))
        self._worker = worker
        from PySide6.QtCore import QThreadPool

        QThreadPool.globalInstance().start(worker)

    def _generated(self, bundle: PromptBundle, generation: int) -> None:
        if generation != self._generation:
            return
        self.bundle = bundle
        if not self._manual:
            self._set_prompt_text(bundle.text)
        self.prompt_stack.setCurrentIndex(1)
        self.generate_button.setEnabled(True)
        self.status_label.setText(f"Generado · {bundle.created_at.replace('T', ' ')}")
        self.files_chip.setText(
            f"{bundle.file_count} archivo{'s' if bundle.file_count != 1 else ''}"
        )
        self.tokens_chip.setText(f"≈ {format_tokens(bundle.tokens)} tokens")
        self.tokens_chip.set_tone("danger" if bundle.tokens > bundle.budget else "neutral")
        self.hash_chip.setText(f"#{bundle.prompt_hash}")
        self.token_meter.update_values(bundle.tokens, bundle.budget)
        self._render_warnings(bundle.warnings)
        self._render_context(bundle)
        self.reset_button.setVisible(self._manual)
        self.edited_chip.setVisible(self._manual)

    def _failed(self, message: str, generation: int) -> None:
        if generation != self._generation:
            return
        self.generate_button.setEnabled(True)
        self.status_label.setText("Error al generar")
        notify(self, "error", "No se pudo generar el prompt", message, 5200)

    def _set_prompt_text(self, text: str) -> None:
        self._setting_prompt = True
        try:
            self.prompt_view.set_content(text, "markdown")
        finally:
            self._setting_prompt = False
        self._manual = False
        self.edited_chip.setVisible(False)
        self.reset_button.setVisible(False)

    def _prompt_edited(self) -> None:
        if self._setting_prompt or self.bundle is None:
            return
        manual = self.prompt_view.toPlainText() != self.bundle.text
        if manual != self._manual:
            self._manual = manual
            self.edited_chip.setVisible(manual)
            self.reset_button.setVisible(manual)

    def _reset_prompt(self) -> None:
        if self.bundle is not None:
            self._set_prompt_text(self.bundle.text)

    # ---------------------------------------------------------------- rendering
    def _clear_warnings(self) -> None:
        while self.warnings_box.count():
            item = self.warnings_box.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
            layout = item.layout()
            if layout is not None:
                while layout.count():
                    child = layout.takeAt(0)
                    if child.widget() is not None:
                        child.widget().deleteLater()

    def _render_warnings(self, warnings: list[str]) -> None:
        self._clear_warnings()
        for warning in warnings[:6]:
            chip = Chip(warning, "warning")
            chip.setToolTip(warning)
            chip.setMaximumWidth(760)
            self.warnings_box.addWidget(chip, 0, Qt.AlignmentFlag.AlignLeft)

    def _clear_context_tree(self) -> None:
        if hasattr(self, "context_tree"):
            self.context_tree.clear()
            self.context_footer.setText("")

    def _render_context(self, bundle: PromptBundle) -> None:
        tree = self.context_tree
        tree.clear()
        groups: dict[str, list] = {}
        for item in bundle.context.files:
            groups.setdefault(item.tier, []).append(item)
        for tier in ("cambio", "seleccionado", "relacionado", "extra"):
            files = groups.get(tier)
            if not files:
                continue
            parent = QTreeWidgetItem(
                tree,
                [
                    f"{_TIER_LABELS.get(tier, tier)} ({len(files)})",
                    "",
                    format_tokens(sum(entry.tokens for entry in files)),
                ],
            )
            parent.setFirstColumnSpanned(False)
            font = parent.font(0)
            font.setBold(True)
            parent.setFont(0, font)
            for entry in files:
                child = QTreeWidgetItem(parent, [entry.rel, entry.mode, format_tokens(entry.tokens)])
                child.setToolTip(0, entry.rel)
                if entry.note:
                    child.setToolTip(1, entry.note)
            parent.setExpanded(True)
        excluded = bundle.context.excluded
        if excluded:
            parent = QTreeWidgetItem(tree, [f"Excluidos ({len(excluded)})", "", ""])
            font = parent.font(0)
            font.setBold(True)
            parent.setFont(0, font)
            for item in excluded[:60]:
                child = QTreeWidgetItem(parent, [item.rel, "excluido", ""])
                child.setToolTip(1, item.reason)
                child.setForeground(1, QColor("#B45309"))
            parent.setExpanded(False)
        included = len(bundle.context.files)
        notes = [
            "1 archivo incluido" if included == 1 else f"{included} archivos incluidos",
            "1 excluido" if len(excluded) == 1 else f"{len(excluded)} excluidos",
        ]
        if bundle.context.redactions == 1:
            notes.append("1 secreto redactado")
        elif bundle.context.redactions:
            notes.append(f"{bundle.context.redactions} secretos redactados")
        if bundle.context.diff_truncated:
            notes.append("diff truncado")
        if bundle.context.map_truncated:
            notes.append("mapa parcial")
        self.context_footer.setText(" · ".join(notes))

    # ----------------------------------------------------------------- actions
    def _copy_prompt(self) -> None:
        text = self.prompt_view.toPlainText().strip()
        if not text:
            notify(self, "warning", "Nada que copiar", "Genera el prompt primero.")
            return
        try:
            copy_text(text)
        except Exception as error:
            notify(self, "error", "No se pudo copiar", str(error))
            return
        if self.ctx.config.record_history and self.bundle is not None:
            try:
                self.ctx.store.save_bundle(self.bundle, text_override=text)
                self.ctx.notify_history_changed()
            except OSError as error:
                notify(self, "warning", "Copiado, pero no se guardó el historial", str(error))
                return
        notify(
            self,
            "success",
            "Prompt copiado",
            "Pégalo tú mismo en el chat. No se ha enviado nada.",
            2400,
        )

    def _save_prompt(self) -> None:
        text = self.prompt_view.toPlainText()
        if not text.strip():
            notify(self, "warning", "Nada que guardar", "Genera el prompt primero.")
            return
        task = resolve_task(self.task_combo.currentData() or "feature")
        suffix = self.bundle.prompt_hash if self.bundle else hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]
        default = str(Path.home() / f"prompt-{task.key}-{suffix}.md")
        target, _filter = QFileDialog.getSaveFileName(
            self, "Guardar prompt", default, "Markdown (*.md);;Texto (*.txt);;Todos (*)"
        )
        if not target:
            return
        try:
            Path(target).write_text(text, encoding="utf-8")
        except OSError as error:
            notify(self, "error", "No se pudo guardar", str(error))
            return
        notify(self, "success", "Prompt guardado", target, 2400)

    def _save_session(self) -> None:
        if self.bundle is None:
            notify(self, "warning", "Nada que guardar", "Genera el prompt primero.")
            return
        text = self.prompt_view.toPlainText()
        try:
            path = self.ctx.store.save_bundle(self.bundle, text_override=text)
        except OSError as error:
            notify(self, "error", "No se pudo guardar la sesión", str(error))
            return
        self.ctx.notify_history_changed()
        notify(self, "success", "Sesión guardada", path.name, 2400)

    def _show_prompt_dialog(self) -> None:
        text = self.prompt_view.toPlainText()
        if not text.strip():
            notify(self, "warning", "Nada que mostrar", "Genera el prompt primero.")
            return
        TextDialog("Prompt completo", text, self, "markdown", 1040, 760).exec()

    # --------------------------------------------------------------- shortcuts
    def load_session(self, record) -> None:
        """Restore a saved session into the composer controls."""

        self._apply_task(record.task)
        self._syncing = True
        try:
            self.request_edit.setPlainText(record.request)
            options = dict(record.options or {})
            self.extra_edit.setPlainText(str(options.get("custom_instructions", "")))
        finally:
            self._syncing = False
        updates = {
            "format": record.format,
            "budget_tokens": record.budget,
        }
        for key in (
            "include_repo_map",
            "repo_map_tokens",
            "include_git",
            "include_diff",
            "include_related",
            "related_depth",
            "line_numbers",
            "redact",
            "diff_only",
            "truncate",
        ):
            value = (record.options or {}).get(key)
            if value is not None:
                updates[key] = value
        self.ctx.update_settings(**updates)
        self._schedule()
        self.request_edit.setFocus()

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt API
        if (
            event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
            and event.modifiers() & Qt.KeyboardModifier.ControlModifier
        ):
            self.generate()
            event.accept()
            return
        super().keyPressEvent(event)


__all__ = ["ComposerPage"]
