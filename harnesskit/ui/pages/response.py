"""Response reviewer: parse pasted answers, preview code and build a safe patch."""

from __future__ import annotations

import hashlib
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QStackedWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    CaptionLabel,
    FluentIcon as FIF,
    PrimaryPushButton,
    PushButton,
    SegmentedWidget,
    TextEdit as FluentTextEdit,
    TitleLabel,
    TransparentPushButton,
    TransparentToolButton,
    TreeWidget,
)

from ...clipboard import copy_text
from ...gitutils import check_patch
from ...response import ParsedResponse, build_patch, parse_response
from ...tokens import format_tokens
from ..state import AppContext
from ..theme import muted_color
from ..widgets import (
    Chip,
    CodeView,
    ElidedLabel,
    EmptyState,
    SectionCard,
    TextDialog,
    count_label,
    make_splitter,
    notify,
)
from ..workers import TaskWorker


class ResponsePage(QWidget):
    def __init__(self, ctx: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.setObjectName("responsePage")
        self.parsed: ParsedResponse | None = None
        self.patch = ""
        self.patch_warnings: list[str] = []
        self._items: list = []
        self._building = False

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(550)
        self._debounce.timeout.connect(self.analyze)

        root = QVBoxLayout(self)
        root.setContentsMargins(26, 20, 26, 20)
        root.setSpacing(14)

        header = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        title = TitleLabel("Respuesta")
        subtitle = CaptionLabel(
            "Pega la respuesta del asistente. El harness extrae archivos y diffs, construye "
            "un parche y lo verifica con git apply --check. Nunca modifica tu proyecto."
        )
        subtitle.setWordWrap(True)
        muted_color(subtitle)
        titles.addWidget(title)
        titles.addWidget(subtitle)
        header.addLayout(titles, 1)
        self.safety_chip = Chip("Solo lectura · no aplica cambios", "success")
        header.addWidget(self.safety_chip, 0, Qt.AlignmentFlag.AlignTop)
        root.addLayout(header)

        splitter = make_splitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_input())
        splitter.addWidget(self._build_preview())
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 6)
        splitter.setSizes([460, 760])
        root.addWidget(splitter, 1)

        ctx.projectChanged.connect(self._on_project_changed)

    # --------------------------------------------------------------------- UI
    def _build_input(self) -> QWidget:
        column = QWidget()
        layout = QVBoxLayout(column)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        input_card = SectionCard(
            "Respuesta del asistente",
            "Se aceptan bloques ``` con ruta, diffs unificados y fragmentos sin ruta.",
            FIF.EDIT,
        )
        self.input_edit = FluentTextEdit()
        self.input_edit.setPlaceholderText(
            "Pega aquí la respuesta completa, incluidos los bloques de código o el diff."
        )
        self.input_edit.setAcceptRichText(False)
        self.input_edit.textChanged.connect(self._schedule)
        input_card.add_widget(self.input_edit, 1)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        paste_button = PushButton(FIF.PASTE, "Pegar")
        paste_button.clicked.connect(self._paste)
        analyze_button = PrimaryPushButton(FIF.SEARCH, "Analizar")
        analyze_button.clicked.connect(self.analyze)
        clear_button = TransparentPushButton("Limpiar")
        clear_button.clicked.connect(self._clear)
        actions.addWidget(paste_button)
        actions.addWidget(clear_button)
        actions.addStretch(1)
        actions.addWidget(analyze_button)
        input_card.add_layout(actions)
        layout.addWidget(input_card, 3)

        blocks_card = SectionCard(
            "Bloques detectados",
            "Selecciona un bloque para revisarlo antes de construir el parche.",
            FIF.DOCUMENT,
        )
        self.blocks_tree = TreeWidget()
        self.blocks_tree.setColumnCount(3)
        self.blocks_tree.setHeaderLabels(["Ruta", "Tipo", "Líneas"])
        self.blocks_tree.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.blocks_tree.setRootIsDecorated(False)
        self.blocks_tree.setUniformRowHeights(True)
        blocks_header = self.blocks_tree.header()
        blocks_header.setStretchLastSection(False)
        blocks_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        blocks_header.resizeSection(1, 92)
        blocks_header.resizeSection(2, 66)
        self.blocks_tree.currentItemChanged.connect(self._block_selected)
        blocks_card.add_widget(self.blocks_tree, 1)
        self.blocks_footer = CaptionLabel("Sin analizar")
        self.blocks_footer.setWordWrap(True)
        muted_color(self.blocks_footer)
        blocks_card.add_widget(self.blocks_footer)
        layout.addWidget(blocks_card, 2)
        return column

    def _build_preview(self) -> QWidget:
        column = QWidget()
        layout = QVBoxLayout(column)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self.segments = SegmentedWidget()
        self.segments.addItem("file", "Bloque")
        self.segments.addItem("patch", "Parche")
        self.segments.setCurrentItem("file")
        self.segments.currentItemChanged.connect(self._segment_changed)
        layout.addWidget(self.segments)

        self.stack = QStackedWidget()

        file_card = SectionCard("Vista del bloque", "", FIF.CODE)
        self.file_path = ElidedLabel("Ningún bloque seleccionado")
        font = self.file_path.font()
        font.setBold(True)
        self.file_path.setFont(font)
        file_card.add_widget(self.file_path)
        self.file_language_chip = Chip("", "accent")
        self.file_lines_chip = Chip("", "neutral")
        file_card.header_layout.addWidget(self.file_language_chip)
        file_card.header_layout.addWidget(self.file_lines_chip)
        self.file_view = CodeView(line_numbers=True, read_only=True)
        self.file_empty = EmptyState(
            FIF.CODE,
            "Sin bloque",
            "Analiza una respuesta para revisar aquí cada archivo o diff detectado.",
        )
        self.file_stack = QStackedWidget()
        self.file_stack.addWidget(self.file_empty)
        self.file_stack.addWidget(self.file_view)
        file_card.add_widget(self.file_stack, 1)
        self.file_note = CaptionLabel("")
        self.file_note.setWordWrap(True)
        muted_color(self.file_note)
        file_card.add_widget(self.file_note)
        self.stack.addWidget(file_card)

        patch_card = SectionCard(
            "Parche propuesto",
            "Unified diff generado contra los archivos actuales. Revísalo antes de guardarlo.",
            FIF.HISTORY,
        )
        self.patch_status = Chip("Sin parche", "neutral")
        patch_card.header_layout.addWidget(self.patch_status)
        self.copy_patch_button = TransparentToolButton(FIF.COPY, patch_card)
        self.copy_patch_button.setToolTip("Copiar el parche")
        self.copy_patch_button.clicked.connect(self._copy_patch)
        self.save_patch_button = TransparentToolButton(FIF.SAVE, patch_card)
        self.save_patch_button.setToolTip("Guardar el parche en un archivo")
        self.save_patch_button.clicked.connect(self._save_patch)
        self.verify_button = TransparentToolButton(FIF.ACCEPT, patch_card)
        self.verify_button.setToolTip("Verificar con git apply --check")
        self.verify_button.clicked.connect(self._verify_patch)
        for button in (self.copy_patch_button, self.save_patch_button, self.verify_button):
            patch_card.header_layout.addWidget(button)
        self.patch_view = CodeView(line_numbers=True, read_only=True)
        self.patch_view.set_content(
            "El parche se construye automáticamente al analizar la respuesta.", "diff"
        )
        patch_card.add_widget(self.patch_view, 1)
        self.patch_footer = CaptionLabel("Nada se escribe en el proyecto.")
        self.patch_footer.setWordWrap(True)
        muted_color(self.patch_footer)
        patch_card.add_widget(self.patch_footer)
        self.stack.addWidget(patch_card)

        layout.addWidget(self.stack, 1)
        return column

    # --------------------------------------------------------------- lifecycle
    def _on_project_changed(self) -> None:
        if self.input_edit.toPlainText().strip():
            self.analyze()

    def _schedule(self) -> None:
        self._debounce.start()

    def _paste(self) -> None:
        text = QApplication.clipboard().text()
        if not text.strip():
            notify(self, "warning", "El portapapeles está vacío", "Copia primero la respuesta.")
            return
        self.input_edit.setPlainText(text)
        self.analyze()

    def _clear(self) -> None:
        self.input_edit.setPlainText("")
        self.blocks_tree.clear()
        self.blocks_footer.setText("Sin analizar")
        self.patch = ""
        self._items = []
        self.patch_status.setText("Sin parche")
        self.patch_status.set_tone("neutral")
        self.patch_footer.setText("Nada se escribe en el proyecto.")
        self.file_stack.setCurrentIndex(0)
        self.file_path.setText("Ningún bloque seleccionado")
        self.file_note.setText("")
        self.file_language_chip.setText("")
        self.file_lines_chip.setText("")
        self.patch_view.set_content(
            "El parche se construye automáticamente al analizar la respuesta.", "diff"
        )

    # ----------------------------------------------------------------- analysis
    def analyze(self) -> None:
        self._debounce.stop()
        text = self.input_edit.toPlainText()
        self.blocks_tree.blockSignals(True)
        self.blocks_tree.clear()
        self.blocks_tree.blockSignals(False)
        if not text.strip():
            self.parsed = None
            self.blocks_footer.setText("Sin analizar")
            self.file_stack.setCurrentIndex(0)
            return
        parsed = parse_response(text)
        self.parsed = parsed
        self._items = parsed.items
        for index, item in enumerate(parsed.items):
            kind_label = {"file": "archivo", "diff": "diff", "snippet": "fragmento"}.get(
                item.kind, item.kind
            )
            if item.error:
                kind_label = "inválido"
            entry = QTreeWidgetItem(
                self.blocks_tree,
                [item.display_path, kind_label, str(item.line_count)],
            )
            entry.setData(0, Qt.ItemDataRole.UserRole, index)
            if item.error:
                entry.setForeground(1, QColor("#DC2626"))
                entry.setToolTip(0, item.error)
            elif item.kind == "diff":
                entry.setForeground(1, QColor("#7C3AED"))
            elif item.kind == "file":
                entry.setForeground(1, QColor("#16A34A"))
            else:
                entry.setForeground(1, QColor("#6B7280"))
        if parsed.items:
            self.blocks_tree.setCurrentItem(self.blocks_tree.topLevelItem(0))
        counts = [
            count_label(parsed.file_count, "archivo", "archivos"),
            count_label(parsed.diff_count, "diff", "diffs"),
            count_label(len(parsed.items), "bloque", "bloques"),
        ]
        self.blocks_footer.setText(
            " · ".join(counts) + (f" · {parsed.notes[0]}" if parsed.notes else "")
        )
        self._build_patch()

    def _block_selected(self, current: QTreeWidgetItem | None, _previous=None) -> None:
        if current is None:
            return
        index = current.data(0, Qt.ItemDataRole.UserRole)
        if index is None or not (0 <= int(index) < len(self._items)):
            return
        item = self._items[int(index)]
        self.file_path.setText(item.display_path)
        self.file_language_chip.setText(item.language or "Text")
        self.file_lines_chip.setText(count_label(item.line_count, "línea", "líneas"))
        self.file_view.set_content(item.content, item.language)
        if item.error:
            self.file_note.setText(item.error)
        elif item.kind == "snippet":
            self.file_note.setText(
                "Fragmento sin ruta: no se incluirá en el parche, solo sirve como referencia."
            )
        elif item.kind == "diff":
            self.file_note.setText("Diff unificado: se añadirá tal cual al parche.")
        else:
            self.file_note.setText(
                "Se comparará con el archivo actual para generar un diff mínimo."
            )
        self.file_stack.setCurrentIndex(1)

    def _build_patch(self) -> None:
        if self.parsed is None or self.ctx.root is None:
            return
        self._building = True
        try:
            patch, warnings = build_patch(self.ctx.root, self.parsed.items)
        finally:
            self._building = False
        self.patch = patch
        self.patch_warnings = warnings
        if patch:
            self.patch_view.set_content(patch, "diff")
            files = patch.count("+++ ")
            noun = count_label(files, "archivo", "archivos")
            self.patch_status.setText(noun)
            self.patch_status.set_tone("success")
            footer = f"{noun} · {format_tokens(len(patch) // 4)} tokens aprox."
            if warnings:
                footer += " · " + warnings[0]
            self.patch_footer.setText(footer)
        else:
            self.patch_view.set_content(
                "\n".join(warnings) if warnings else "No se pudo construir un parche.",
                "text",
            )
            self.patch_status.setText("Sin parche")
            self.patch_status.set_tone("warning")
            self.patch_footer.setText(
                warnings[0] if warnings else "No hay archivos ni diffs accionables."
            )

    # ------------------------------------------------------------------ actions
    def _segment_changed(self, key: str) -> None:
        self.stack.setCurrentIndex(0 if key == "file" else 1)

    def _copy_patch(self) -> None:
        if not self.patch.strip():
            notify(self, "warning", "No hay parche", "Analiza una respuesta accionable primero.")
            return
        try:
            copy_text(self.patch)
            notify(self, "success", "Parche copiado", "Revísalo antes de aplicarlo.", 2000)
        except Exception as error:
            notify(self, "error", "No se pudo copiar", str(error))

    def _save_patch(self) -> None:
        if not self.patch.strip():
            notify(self, "warning", "No hay parche", "Analiza una respuesta accionable primero.")
            return
        digest = hashlib.sha256(self.patch.encode("utf-8", errors="replace")).hexdigest()[:8]
        default = str(Path.home() / f"harness-{digest}.patch")
        target, _filter = QFileDialog.getSaveFileName(
            self, "Guardar parche", default, "Parche (*.patch);;Diff (*.diff);;Todos (*)"
        )
        if not target:
            return
        try:
            Path(target).write_text(self.patch, encoding="utf-8", newline="\n")
        except OSError as error:
            notify(self, "error", "No se pudo guardar", str(error))
            return
        notify(self, "success", "Parche guardado", target, 2400)
        self.patch_footer.setText(
            f"Guardado en {target} · verifica con: git apply --check \"{target}\""
        )

    def _verify_patch(self) -> None:
        if not self.patch.strip():
            notify(self, "warning", "No hay parche", "Analiza una respuesta accionable primero.")
            return
        if self.ctx.root is None:
            notify(self, "warning", "Sin proyecto", "Abre el proyecto donde se aplicaría.")
            return
        if not self.ctx.scan or not self.ctx.scan.git:
            notify(
                self,
                "warning",
                "Git no disponible",
                "La verificación necesita que el proyecto sea un repositorio Git.",
            )
            return
        self.verify_button.setEnabled(False)
        self.patch_status.setText("Verificando…")
        self.patch_status.set_tone("accent")
        worker = TaskWorker(check_patch, self.ctx.root, self.patch)
        worker.signals.finished.connect(self._verified)
        worker.signals.error.connect(self._verify_failed)
        self._verify_worker = worker
        from PySide6.QtCore import QThreadPool

        QThreadPool.globalInstance().start(worker)

    def _verified(self, result: tuple[bool, str]) -> None:
        ok, output = result
        self.verify_button.setEnabled(True)
        self.patch_status.setText("Verificado" if ok else "No aplicable")
        self.patch_status.set_tone("success" if ok else "danger")
        self.patch_footer.setText(output.splitlines()[0] if output else "")
        dialog = TextDialog(
            "git apply --check: " + ("correcto" if ok else "con problemas"),
            output or ("El parche se puede aplicar." if ok else "Git rechazó el parche."),
            self,
            "text",
            880,
            520,
        )
        dialog.exec()

    def _verify_failed(self, message: str) -> None:
        self.verify_button.setEnabled(True)
        self.patch_status.setText("Error")
        self.patch_status.set_tone("danger")
        notify(self, "error", "No se pudo verificar", message, 5000)


__all__ = ["ResponsePage"]
