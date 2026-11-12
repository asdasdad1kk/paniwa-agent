"""Checkable project file tree with filters, statuses and context actions."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QFileInfo, QTimer, Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileIconProvider,
    QHeaderView,
    QMenu,
    QTreeWidgetItem,
    QWidget,
)
from qfluentwidgets import Action, FluentIcon as FIF, TreeWidget

from ..models import FileEntry, ScanResult
from ..tokens import format_tokens
from ..clipboard import copy_text
from .theme import status_color
from .widgets import notify

FILE_ROLE = Qt.ItemDataRole.UserRole


class FileTree(TreeWidget):
    selectionChanged = Signal()
    fileFocused = Signal(str)
    openRequested = Signal(str)
    diffRequested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setColumnCount(3)
        self.setHeaderLabels(["Archivo", "Tokens", "Git"])
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        header = self.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.setStretchLastSection(False)
        self.setColumnWidth(1, 78)
        self.setColumnWidth(2, 64)
        self.setUniformRowHeights(True)
        self.setAnimated(False)
        self.setIndentation(16)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.setExpandsOnDoubleClick(False)
        self.setSortingEnabled(False)

        self._entries: dict[str, FileEntry] = {}
        self._items: dict[str, QTreeWidgetItem] = {}
        self._guard = False
        self._filter_text = ""
        self._filter_mode = "Todos"
        self._icon_provider = QFileIconProvider()
        self._icon_cache: dict[str, object] = {}
        self._emit_timer = QTimer(self)
        self._emit_timer.setSingleShot(True)
        self._emit_timer.setInterval(0)
        self._emit_timer.timeout.connect(self.selectionChanged.emit)

        self.itemChanged.connect(self._on_item_changed)
        self.currentItemChanged.connect(self._on_current_changed)
        self.itemDoubleClicked.connect(self._on_double_click)
        self.customContextMenuRequested.connect(self._context_menu)
        self.itemExpanded.connect(lambda _item: None)

    # ------------------------------------------------------------------ loading
    def populate(self, scan: ScanResult, selected: set[str]) -> None:
        self._guard = True
        self.setUpdatesEnabled(False)
        self.clear()
        self._entries = scan.index()
        self._items = {}
        folder_icon = FIF.FOLDER.icon()
        for entry in scan.files:
            parts = entry.rel.split("/")
            parent_item = self.invisibleRootItem()
            prefix_parts: list[str] = []
            for part in parts[:-1]:
                prefix_parts.append(part)
                prefix = "/".join(prefix_parts) + "/"
                item = self._items.get(prefix)
                if item is None:
                    item = QTreeWidgetItem(parent_item, [part, "", ""])
                    item.setIcon(0, folder_icon)
                    item.setData(0, FILE_ROLE, prefix)
                    item.setFlags(
                        Qt.ItemFlag.ItemIsEnabled
                        | Qt.ItemFlag.ItemIsSelectable
                        | Qt.ItemFlag.ItemIsUserCheckable
                    )
                    item.setCheckState(0, Qt.CheckState.Unchecked)
                    item.setExpanded(prefix.count("/") <= 1)
                    self._items[prefix] = item
                parent_item = item

            item = QTreeWidgetItem(parent_item, [entry.name, "", ""])
            item.setData(0, FILE_ROLE, entry.rel)
            item.setIcon(0, self._icon_for(entry))
            item.setToolTip(
                0,
                f"{entry.rel}\n{entry.language} · {self._human_size(entry.size)}\n"
                f"{entry.change_label}"
                + (f"\nSensible: {entry.sensitive}" if entry.sensitive else ""),
            )
            flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
            if not entry.too_large:
                flags |= Qt.ItemFlag.ItemIsUserCheckable
                item.setCheckState(
                    0,
                    Qt.CheckState.Checked if entry.rel in selected else Qt.CheckState.Unchecked,
                )
            else:
                item.setForeground(0, QBrush(QColor(140, 140, 140)))
                item.setToolTip(0, item.toolTip(0) + "\nDemasiado grande: aumenta el límite en Ajustes.")
            item.setFlags(flags)
            if entry.git_code:
                short = entry.git_code.strip()
                item.setText(2, short)
                item.setForeground(2, QBrush(QColor(status_color(short))))
                item.setToolTip(2, entry.change_label)
            self._items[entry.rel] = item
        self._aggregate_directories(self.invisibleRootItem())
        self._guard = False
        self.setUpdatesEnabled(True)
        self._apply_filter()
        self._refresh_directory_states()

    def _icon_for(self, entry: FileEntry):
        key = entry.suffix or entry.name.lower()
        cached = self._icon_cache.get(key)
        if cached is not None:
            return cached
        icon = self._icon_provider.icon(QFileInfo(str(entry.path)))
        self._icon_cache[key] = icon
        return icon

    def _human_size(self, size: int) -> str:
        if size > 1024 * 1024:
            return f"{size / 1024 / 1024:.1f} MB"
        if size > 1024:
            return f"{size / 1024:.1f} kB"
        return f"{size} B"

    def _aggregate_directories(self, item: QTreeWidgetItem) -> int:
        total = 0
        for index in range(item.childCount()):
            child = item.child(index)
            rel = child.data(0, FILE_ROLE)
            if rel and str(rel).endswith("/"):
                total += self._aggregate_directories(child)
            else:
                entry = self._entries.get(str(rel))
                tokens = entry.estimated_tokens if entry else 0
                child.setText(1, format_tokens(tokens))
                total += tokens
        if item is not self.invisibleRootItem():
            item.setText(1, format_tokens(total))
        return total

    # ------------------------------------------------------------------ selection
    def selected_paths(self) -> set[str]:
        result: set[str] = set()
        for rel, item in self._items.items():
            if rel.endswith("/"):
                continue
            if item.checkState(0) == Qt.CheckState.Checked:
                result.add(rel)
        return result

    def apply_selection(self, selected: set[str]) -> None:
        self._guard = True
        for rel, item in self._items.items():
            if rel.endswith("/"):
                continue
            if item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                state = Qt.CheckState.Checked if rel in selected else Qt.CheckState.Unchecked
                if item.checkState(0) != state:
                    item.setCheckState(0, state)
        self._guard = False
        self._refresh_directory_states()
        self._apply_filter()

    def select_changed(self) -> None:
        selected = {
            rel
            for rel, entry in self._entries.items()
            if entry.is_changed and not entry.too_large
        }
        self.apply_selection(selected)
        self.selectionChanged.emit()

    def select_all(self) -> None:
        selected = {rel for rel, entry in self._entries.items() if not entry.too_large}
        self.apply_selection(selected)
        self.selectionChanged.emit()

    def select_source(self) -> None:
        selected = {
            rel
            for rel, entry in self._entries.items()
            if entry.is_source and not entry.too_large
        }
        self.apply_selection(selected)
        self.selectionChanged.emit()

    def clear_selection(self) -> None:
        self.apply_selection(set())
        self.selectionChanged.emit()

    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self._guard or column != 0:
            return
        rel = item.data(0, FILE_ROLE)
        if not rel:
            return
        self._guard = True
        state = item.checkState(0)
        if str(rel).endswith("/"):
            target = Qt.CheckState.Checked if state != Qt.CheckState.Unchecked else Qt.CheckState.Unchecked
            self._set_descendants(item, target)
            item.setCheckState(0, target)
        self._update_ancestors(item)
        self._guard = False
        self._apply_filter()
        self._emit_timer.start()

    def _set_descendants(self, item: QTreeWidgetItem, state: Qt.CheckState) -> None:
        for index in range(item.childCount()):
            child = item.child(index)
            if child.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                child.setCheckState(0, state)
            self._set_descendants(child, state)

    def _update_ancestors(self, item: QTreeWidgetItem) -> None:
        parent = item.parent()
        while parent is not None:
            checked = 0
            partial = 0
            total = 0
            for index in range(parent.childCount()):
                child = parent.child(index)
                if not (child.flags() & Qt.ItemFlag.ItemIsUserCheckable):
                    continue
                total += 1
                state = child.checkState(0)
                if state == Qt.CheckState.Checked:
                    checked += 1
                elif state == Qt.CheckState.PartiallyChecked:
                    partial += 1
            if total and checked == total:
                state = Qt.CheckState.Checked
            elif checked == 0 and partial == 0:
                state = Qt.CheckState.Unchecked
            else:
                state = Qt.CheckState.PartiallyChecked
            if parent.checkState(0) != state:
                parent.setCheckState(0, state)
            parent = parent.parent()

    def _refresh_directory_states(self) -> None:
        self._guard = True
        for rel, item in self._items.items():
            if not rel.endswith("/"):
                continue
            checked = 0
            partial = 0
            total = 0
            for index in range(item.childCount()):
                child = item.child(index)
                if not (child.flags() & Qt.ItemFlag.ItemIsUserCheckable):
                    continue
                total += 1
                state = child.checkState(0)
                if state == Qt.CheckState.Checked:
                    checked += 1
                elif state == Qt.CheckState.PartiallyChecked:
                    partial += 1
            if total and checked == total:
                state = Qt.CheckState.Checked
            elif checked == 0 and partial == 0:
                state = Qt.CheckState.Unchecked
            else:
                state = Qt.CheckState.PartiallyChecked
            item.setCheckState(0, state)
        self._guard = False

    # -------------------------------------------------------------------- filters
    def set_filter(self, text: str, mode: str) -> None:
        self._filter_text = text.strip().lower()
        self._filter_mode = mode
        self._apply_filter()

    def _matches(self, entry: FileEntry) -> bool:
        if self._filter_text and self._filter_text not in entry.rel.lower():
            return False
        if self._filter_mode == "Modificados":
            return entry.is_changed
        if self._filter_mode == "Seleccionados":
            return entry.rel in self.selected_paths()
        if self._filter_mode == "Código":
            return entry.is_source
        return True

    def _apply_filter(self) -> None:
        selected = self.selected_paths() if self._filter_mode == "Seleccionados" else None

        def visit(item: QTreeWidgetItem) -> bool:
            rel = item.data(0, FILE_ROLE)
            if not rel:
                return True
            if not str(rel).endswith("/"):
                entry = self._entries.get(str(rel))
                visible = bool(entry) and self._matches(entry)
                item.setHidden(not visible)
                return visible
            visible = False
            for index in range(item.childCount()):
                visible = visit(item.child(index)) or visible
            if self._filter_text and visible:
                item.setExpanded(True)
            item.setHidden(not visible)
            return visible

        for index in range(self.invisibleRootItem().childCount()):
            visit(self.invisibleRootItem().child(index))
        if selected is not None:
            # Selected mode uses live check states; refresh is triggered by changes.
            pass

    def expand_all(self) -> None:
        self.expandAll()

    def collapse_all(self) -> None:
        self.collapseAll()

    # --------------------------------------------------------------- interaction
    def _on_current_changed(self, current: QTreeWidgetItem | None, _previous) -> None:
        if current is None:
            return
        rel = current.data(0, FILE_ROLE)
        if rel and not str(rel).endswith("/"):
            self.fileFocused.emit(str(rel))

    def _on_double_click(self, item: QTreeWidgetItem, _column: int) -> None:
        rel = item.data(0, FILE_ROLE)
        if rel and not str(rel).endswith("/"):
            self.openRequested.emit(str(rel))

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt API
        item = self.currentItem()
        if item is not None and event.key() == Qt.Key.Key_Space:
            rel = item.data(0, FILE_ROLE)
            if rel and not str(rel).endswith("/") and item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                item.setCheckState(
                    0,
                    Qt.CheckState.Unchecked
                    if item.checkState(0) == Qt.CheckState.Checked
                    else Qt.CheckState.Checked,
                )
                event.accept()
                return
        if item is not None and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            rel = item.data(0, FILE_ROLE)
            if rel and not str(rel).endswith("/"):
                self.openRequested.emit(str(rel))
                event.accept()
                return
        super().keyPressEvent(event)

    def _context_menu(self, position) -> None:
        item = self.itemAt(position)
        if item is None:
            return
        rel = item.data(0, FILE_ROLE)
        if not rel or str(rel).endswith("/"):
            return
        rel = str(rel)
        entry = self._entries.get(rel)
        menu = QMenu(self)
        include_action = Action(
            FIF.ACCEPT if item.checkState(0) != Qt.CheckState.Checked else FIF.CANCEL,
            "Incluir en contexto" if item.checkState(0) != Qt.CheckState.Checked else "Quitar del contexto",
        )
        include_action.triggered.connect(
            lambda: item.setCheckState(
                0,
                Qt.CheckState.Checked
                if item.checkState(0) != Qt.CheckState.Checked
                else Qt.CheckState.Unchecked,
            )
        )
        open_action = Action(FIF.EDIT, "Abrir en editor")
        open_action.triggered.connect(lambda: self.openRequested.emit(rel))
        diff_action = Action(FIF.HISTORY, "Ver diff")
        diff_action.triggered.connect(lambda: self.diffRequested.emit(rel))
        copy_action = Action(FIF.COPY, "Copiar ruta")
        copy_action.triggered.connect(lambda: self._copy_path(rel))
        menu.addAction(include_action)
        menu.addSeparator()
        menu.addAction(open_action)
        if entry is not None and entry.is_changed:
            menu.addAction(diff_action)
        menu.addAction(copy_action)
        menu.exec(self.viewport().mapToGlobal(position))

    def _copy_path(self, rel: str) -> None:
        try:
            copy_text(rel)
            notify(self, "success", "Ruta copiada", rel, 1400)
        except Exception as error:
            notify(self, "error", "No se pudo copiar", str(error))


__all__ = ["FileTree"]
