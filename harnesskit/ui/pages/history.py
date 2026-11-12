"""History: browse, reuse and export locally saved prompt sessions."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
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
    SearchLineEdit,
    TitleLabel,
    TransparentPushButton,
    TransparentToolButton,
    TreeWidget,
)

from ...clipboard import copy_text
from ...history import SessionSummary
from ...tokens import format_tokens
from ..state import AppContext
from ..theme import muted_color
from ..widgets import (
    Chip,
    CodeView,
    ElidedLabel,
    EmptyState,
    SectionCard,
    StatTile,
    confirm,
    count_label,
    make_splitter,
    notify,
)


class HistoryPage(QWidget):
    reuseRequested = Signal(object)

    def __init__(self, ctx: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.setObjectName("historyPage")
        self._summaries: list[SessionSummary] = []
        self._current: SessionSummary | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(26, 20, 26, 20)
        root.setSpacing(14)

        header = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        title = TitleLabel("Historial")
        subtitle = CaptionLabel(
            "Cada prompt guardado vive en un JSON local dentro de tu carpeta de usuario. "
            "Puedes reutilizarlo, exportarlo o borrarlo sin tocar el proyecto."
        )
        subtitle.setWordWrap(True)
        muted_color(subtitle)
        titles.addWidget(title)
        titles.addWidget(subtitle)
        header.addLayout(titles, 1)
        self.folder_button = TransparentToolButton(FIF.FOLDER, self)
        self.folder_button.setToolTip("Abrir la carpeta del historial")
        self.folder_button.clicked.connect(self._open_folder)
        header.addWidget(self.folder_button, 0, Qt.AlignmentFlag.AlignTop)
        root.addLayout(header)

        stats = QHBoxLayout()
        stats.setSpacing(10)
        self.tile_sessions = StatTile("Sesiones", "0", FIF.HISTORY)
        self.tile_tokens = StatTile("Tokens totales", "0", FIF.DOCUMENT)
        self.tile_files = StatTile("Archivos referenciados", "0", FIF.CODE)
        self.tile_last = StatTile("Última sesión", "—", FIF.STOP_WATCH)
        for tile in (self.tile_sessions, self.tile_tokens, self.tile_files, self.tile_last):
            stats.addWidget(tile, 1)
        root.addLayout(stats)

        splitter = make_splitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_list())
        splitter.addWidget(self._build_detail())
        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 5)
        splitter.setSizes([600, 640])
        root.addWidget(splitter, 1)

        ctx.historyChanged.connect(self.refresh)
        self.refresh()

    # --------------------------------------------------------------------- UI
    def _build_list(self) -> QWidget:
        card = SectionCard(
            "Sesiones guardadas",
            "Ordenadas de más reciente a más antigua. Filtra por tarea, proyecto o solicitud.",
            FIF.HISTORY,
        )
        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)
        self.search = SearchLineEdit()
        self.search.setPlaceholderText("Filtrar historial…")
        self.search.textChanged.connect(self._refresh_table)
        refresh_button = TransparentToolButton(FIF.SYNC, self)
        refresh_button.setToolTip("Actualizar")
        refresh_button.clicked.connect(self.refresh)
        clear_button = TransparentPushButton("Vaciar")
        clear_button.clicked.connect(self._clear_all)
        filter_row.addWidget(self.search, 1)
        filter_row.addWidget(clear_button)
        filter_row.addWidget(refresh_button)
        card.add_layout(filter_row)

        self.table = TreeWidget()
        self.table.setColumnCount(4)
        self.table.setHeaderLabels(["Sesión", "Proyecto", "Archivos", "Tokens"])
        self.table.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.table.setRootIsDecorated(False)
        self.table.setUniformRowHeights(True)
        self.table.setAlternatingRowColors(False)
        header = self.table.header()
        header.setStretchLastSection(False)
        header.resizeSection(0, 190)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.resizeSection(2, 74)
        header.resizeSection(3, 82)
        self.table.currentItemChanged.connect(self._row_selected)
        card.add_widget(self.table, 1)
        self.list_footer = CaptionLabel("")
        muted_color(self.list_footer)
        card.add_widget(self.list_footer)
        return card

    def _build_detail(self) -> QWidget:
        card = SectionCard(
            "Detalle",
            "El texto guardado es exactamente el prompt que se copió o exportó.",
            FIF.DOCUMENT,
        )
        top = QHBoxLayout()
        top.setSpacing(6)
        self.detail_title = ElidedLabel("Selecciona una sesión")
        font = self.detail_title.font()
        font.setBold(True)
        font.setPointSize(11)
        self.detail_title.setFont(font)
        top.addWidget(self.detail_title, 1)
        self.meta_chip = Chip("", "accent")
        self.meta_chip.setVisible(False)
        top.addWidget(self.meta_chip)
        card.add_layout(top)

        self.detail_caption = CaptionLabel("")
        self.detail_caption.setWordWrap(True)
        muted_color(self.detail_caption)
        card.add_widget(self.detail_caption)

        self.detail_stack = QStackedWidget()
        self.detail_empty = EmptyState(
            FIF.HISTORY,
            "Selecciona una sesión",
            "Elige una sesión de la lista para revisar el prompt guardado, copiarlo, "
            "exportarlo o reutilizar sus opciones. También puedes guardar un prompt "
            "desde el compositor.",
        )
        self.prompt_view = CodeView(line_numbers=True, read_only=True)
        self.prompt_view.set_word_wrap(True)
        self.detail_stack.addWidget(self.detail_empty)
        self.detail_stack.addWidget(self.prompt_view)
        card.add_widget(self.detail_stack, 1)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.copy_button = TransparentPushButton(FIF.COPY, "Copiar")
        self.copy_button.clicked.connect(self._copy_current)
        self.export_button = TransparentPushButton(FIF.SAVE, "Exportar .md")
        self.export_button.clicked.connect(self._export_current)
        self.reuse_button = PushButton(FIF.SYNC, "Reutilizar")
        self.reuse_button.clicked.connect(self._reuse_current)
        self.delete_button = TransparentPushButton(FIF.DELETE, "Eliminar")
        self.delete_button.clicked.connect(self._delete_current)
        actions.addWidget(self.copy_button)
        actions.addWidget(self.export_button)
        actions.addStretch(1)
        actions.addWidget(self.delete_button)
        actions.addWidget(self.reuse_button)
        card.add_layout(actions)
        self._set_actions(False)
        return card

    # ------------------------------------------------------------------ data
    def refresh(self) -> None:
        try:
            self._summaries = self.ctx.store.list(limit=400)
        except OSError as error:
            notify(self, "error", "No se pudo leer el historial", str(error))
            self._summaries = []
        self._refresh_table()
        self._update_stats()

    def _update_stats(self) -> None:
        sessions = self._summaries
        self.tile_sessions.set_value(str(len(sessions)))
        self.tile_tokens.set_value(format_tokens(sum(item.tokens for item in sessions)))
        self.tile_files.set_value(str(sum(item.file_count for item in sessions)))
        if sessions:
            stamp = _pretty_date(sessions[0].created_at)
            self.tile_last.set_value(stamp)
        else:
            self.tile_last.set_value("—")
        self.list_footer.setText(
            f"{count_label(len(sessions), 'sesión', 'sesiones')} · "
            f"carpeta: {self.ctx.store.base}"
            if sessions
            else "Aún no hay sesiones guardadas."
        )

    def _refresh_table(self) -> None:
        query = self.search.text().strip().lower()
        self.table.blockSignals(True)
        self.table.clear()
        visible = 0
        for summary in self._summaries:
            haystack = f"{summary.task_label} {summary.project_root} {summary.request}".lower()
            if query and query not in haystack:
                continue
            visible += 1
            entry = QTreeWidgetItem(
                self.table,
                [
                    f"{_pretty_date(summary.created_at)} · {summary.task_label}",
                    Path(summary.project_root).name or summary.project_root,
                    str(summary.file_count),
                    format_tokens(summary.tokens),
                ],
            )
            entry.setData(0, Qt.ItemDataRole.UserRole, summary.id)
            entry.setToolTip(1, summary.project_root)
            entry.setToolTip(0, summary.request or summary.task_label)
            if query:
                entry.setForeground(1, QColor("#2F6DF6"))
        self.table.blockSignals(False)
        if visible and self.table.topLevelItemCount():
            self.table.setCurrentItem(self.table.topLevelItem(0))
        elif not visible:
            self._show_summary(None)
        self.list_footer.setText(
            f"{visible} de {count_label(len(self._summaries), 'sesión', 'sesiones')} · "
            f"{self.ctx.store.base}"
        )

    def _row_selected(self, current: QTreeWidgetItem | None, _previous=None) -> None:
        if current is None:
            self._show_summary(None)
            return
        session_id = current.data(0, Qt.ItemDataRole.UserRole)
        summary = next((item for item in self._summaries if item.id == session_id), None)
        self._show_summary(summary)

    def _show_summary(self, summary: SessionSummary | None) -> None:
        self._current = summary
        if summary is None:
            self.detail_title.setVisible(False)
            self.detail_caption.setVisible(False)
            self.meta_chip.setVisible(False)
            self.detail_stack.setCurrentWidget(self.detail_empty)
            self._set_actions(False)
            return
        try:
            record = self.ctx.store.load(summary.path)
        except (OSError, ValueError) as error:
            notify(self, "error", "No se pudo leer la sesión", str(error))
            self.detail_title.setVisible(False)
            self.detail_caption.setVisible(False)
            self.detail_stack.setCurrentWidget(self.detail_empty)
            self._set_actions(False)
            return
        self.detail_title.setText(
            f"{_pretty_date(record.created_at)} · {record.task_label}"
        )
        self.detail_title.setToolTip(record.id)
        self.detail_title.setVisible(True)
        self.meta_chip.setText(f"#{record.prompt_hash or '—'}")
        self.meta_chip.setVisible(True)
        self.detail_caption.setText(
            f"{record.project_root} · "
            f"{count_label(len(record.files), 'archivo', 'archivos')} · "
            f"≈ {format_tokens(record.tokens)} tokens · {record.format}"
            + (f"\n{record.request}" if record.request else "")
        )
        self.detail_caption.setVisible(True)
        self.prompt_view.set_content(record.prompt, "markdown")
        self.detail_stack.setCurrentWidget(self.prompt_view)
        self._set_actions(True)

    def _set_actions(self, enabled: bool) -> None:
        for button in (
            self.copy_button,
            self.export_button,
            self.reuse_button,
            self.delete_button,
        ):
            button.setEnabled(enabled)

    # ---------------------------------------------------------------- actions
    def _copy_current(self) -> None:
        if self._current is None:
            return
        try:
            record = self.ctx.store.load(self._current.path)
            copy_text(record.prompt)
        except (OSError, ValueError) as error:
            notify(self, "error", "No se pudo leer la sesión", str(error))
            return
        except Exception as error:
            notify(self, "error", "No se pudo copiar", str(error))
            return
        notify(self, "success", "Prompt copiado", "Pégalo tú mismo en el chat.", 1800)

    def _export_current(self) -> None:
        if self._current is None:
            return
        try:
            record = self.ctx.store.load(self._current.path)
        except (OSError, ValueError) as error:
            notify(self, "error", "No se pudo leer la sesión", str(error))
            return
        default = str(Path.home() / f"{record.id}.md")
        target, _filter = QFileDialog.getSaveFileName(
            self, "Exportar prompt", default, "Markdown (*.md);;Texto (*.txt)"
        )
        if not target:
            return
        try:
            Path(target).write_text(record.prompt, encoding="utf-8")
        except OSError as error:
            notify(self, "error", "No se pudo exportar", str(error))
            return
        notify(self, "success", "Prompt exportado", target, 2200)

    def _reuse_current(self) -> None:
        if self._current is None:
            return
        try:
            record = self.ctx.store.load(self._current.path)
        except (OSError, ValueError) as error:
            notify(self, "error", "No se pudo leer la sesión", str(error))
            return
        self.reuseRequested.emit(record)

    def _delete_current(self) -> None:
        if self._current is None:
            return
        if not confirm(
            self,
            "Eliminar sesión",
            "Se borrará el JSON local de esta sesión. El proyecto no se modifica.",
        ):
            return
        if self.ctx.store.delete(self._current.path):
            notify(self, "success", "Sesión eliminada", self._current.id, 1600)
            self._current = None
            self.refresh()
        else:
            notify(self, "error", "No se pudo eliminar", "Revisa los permisos del archivo.")

    def _clear_all(self) -> None:
        if not self._summaries:
            notify(self, "info", "No hay historial", "Nada que borrar.", 1600)
            return
        total = len(self._summaries)
        message = (
            "Se eliminará 1 sesión local. Esta acción no se puede deshacer."
            if total == 1
            else f"Se eliminarán {total} sesiones locales. "
            "Esta acción no se puede deshacer."
        )
        if not confirm(self, "Vaciar historial", message):
            return
        removed = self.ctx.store.clear()
        self._current = None
        self.refresh()
        result = "1 sesión eliminada." if removed == 1 else f"{removed} sesiones eliminadas."
        notify(self, "success", "Historial vaciado", result, 2000)

    def _open_folder(self) -> None:
        folder = self.ctx.store.ensure()
        try:
            if os.name == "nt":
                os.startfile(folder)  # type: ignore[attr-defined]
            else:
                from PySide6.QtGui import QDesktopServices
                from PySide6.QtCore import QUrl

                QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
        except Exception as error:
            notify(self, "error", "No se pudo abrir la carpeta", str(error))


def _pretty_date(stamp: str) -> str:
    try:
        parsed = datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        return stamp or "—"
    today = datetime.now().date()
    if parsed.date() == today:
        return f"Hoy {parsed:%H:%M}"
    return f"{parsed:%d/%m/%Y %H:%M}"


__all__ = ["HistoryPage"]
