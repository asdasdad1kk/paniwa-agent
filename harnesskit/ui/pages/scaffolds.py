"""Scaffolds: browse local templates and create a new project."""

from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    CaptionLabel,
    CardWidget,
    CheckBox,
    FluentIcon as FIF,
    LineEdit,
    PrimaryPushButton,
    PushButton,
    SmoothScrollArea,
    StrongBodyLabel,
    TitleLabel,
    TransparentPushButton,
    TreeWidget,
)

from ...clipboard import copy_text
from ...scaffolds import SCAFFOLDS, Scaffold, create_project
from ...tokens import format_tokens
from ..state import AppContext
from ..theme import muted_color
from ..widgets import Chip, SectionCard, count_label, make_splitter, notify


class ScaffoldCard(CardWidget):
    activated = Signal(str)

    def __init__(self, scaffold: Scaffold, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.scaffold = scaffold
        self._selected = False
        self.setBorderRadius(10)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(148)
        self.setMinimumWidth(236)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(6)
        header = QHBoxLayout()
        header.setSpacing(8)
        name = StrongBodyLabel(scaffold.name)
        font = name.font()
        font.setPointSize(12)
        name.setFont(font)
        header.addWidget(name, 1)
        icon = QLabel()
        icon.setPixmap(FIF.CODE.icon().pixmap(18, 18))
        header.addWidget(icon)
        layout.addLayout(header)
        description = CaptionLabel(scaffold.description)
        description.setWordWrap(True)
        muted_color(description)
        layout.addWidget(description)
        layout.addStretch(1)
        tags = QHBoxLayout()
        tags.setSpacing(4)
        for tag in scaffold.tags[:3]:
            tags.addWidget(Chip(tag, "accent"))
        tags.addStretch(1)
        layout.addLayout(tags)
        meta = CaptionLabel(count_label(len(scaffold.files), "archivo", "archivos"))
        muted_color(meta)
        layout.addWidget(meta)

    def set_selected(self, selected: bool) -> None:
        if self._selected != selected:
            self._selected = selected
            self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt API
        self.activated.emit(self.scaffold.key)
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().paintEvent(event)
        if not self._selected:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(QColor("#2F6DF6"))
        pen.setWidth(2)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 10, 10)


class CreateScaffoldDialog(QDialog):
    def __init__(self, scaffold: Scaffold, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.scaffold = scaffold
        self.setWindowTitle(f"Crear proyecto · {scaffold.name}")
        self.setMinimumWidth(560)
        self.result_path: Path | None = None
        self.result_zip = False

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)

        title = StrongBodyLabel(f"Nuevo proyecto {scaffold.name}")
        font = title.font()
        font.setPointSize(13)
        title.setFont(font)
        root.addWidget(title)
        description = CaptionLabel(scaffold.description)
        description.setWordWrap(True)
        muted_color(description)
        root.addWidget(description)

        base_label = CaptionLabel("Carpeta contenedora")
        muted_color(base_label)
        root.addWidget(base_label)
        base_row = QHBoxLayout()
        base_row.setSpacing(8)
        self.base_edit = LineEdit()
        self.base_edit.setText(str(Path.home()))
        self.base_edit.setPlaceholderText("Carpeta donde se creará el proyecto")
        browse = PushButton(FIF.FOLDER, "Examinar")
        browse.clicked.connect(self._browse)
        base_row.addWidget(self.base_edit, 1)
        base_row.addWidget(browse)
        root.addLayout(base_row)

        name_label = CaptionLabel("Nombre del proyecto")
        muted_color(name_label)
        root.addWidget(name_label)
        self.name_edit = LineEdit()
        self.name_edit.setPlaceholderText("mi-proyecto")
        self.name_edit.textChanged.connect(self._update_preview)
        root.addWidget(self.name_edit)

        self.zip_check = CheckBox("Crear también un archivo ZIP")
        root.addWidget(self.zip_check)

        self.preview = CaptionLabel("")
        self.preview.setWordWrap(True)
        muted_color(self.preview)
        root.addWidget(self.preview)

        root.addStretch(1)
        actions = QHBoxLayout()
        actions.addStretch(1)
        cancel = TransparentPushButton("Cancelar")
        cancel.clicked.connect(self.reject)
        create = PrimaryPushButton("Crear proyecto")
        create.clicked.connect(self._create)
        actions.addWidget(cancel)
        actions.addWidget(create)
        root.addLayout(actions)
        self._update_preview()

    def _browse(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        folder = QFileDialog.getExistingDirectory(self, "Carpeta contenedora", self.base_edit.text())
        if folder:
            self.base_edit.setText(folder)

    def _update_preview(self) -> None:
        base = Path(self.base_edit.text().strip() or ".").expanduser()
        name = self.name_edit.text().strip() or "(sin nombre)"
        self.preview.setText(str(base / name))

    def _create(self) -> None:
        base = Path(self.base_edit.text().strip()).expanduser()
        name = self.name_edit.text().strip()
        if not base.is_dir():
            notify(self, "warning", "Carpeta no válida", "Elige una carpeta contenedora existente.")
            return
        if not name:
            notify(self, "warning", "Falta el nombre", "Escribe un nombre para el proyecto.")
            return
        if re.search(r'[<>:"/\\|?*]', name):
            notify(self, "warning", "Nombre no válido", "Evita los caracteres <>:\"/\\|?*")
            return
        target = base / name
        if target.exists():
            notify(self, "warning", "Ya existe", f"{target} no se modificará.")
            return
        try:
            create_project(self.scaffold.key, target, self.zip_check.isChecked())
        except (OSError, ValueError) as error:
            notify(self, "error", "No se pudo crear el proyecto", str(error), 5000)
            return
        self.result_path = target
        self.result_zip = self.zip_check.isChecked()
        self.accept()


class ScaffoldsPage(QWidget):
    workspaceRequested = Signal()

    def __init__(self, ctx: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.setObjectName("scaffoldsPage")
        self._selected = next(iter(SCAFFOLDS))
        self._cards: dict[str, ScaffoldCard] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(26, 20, 26, 20)
        root.setSpacing(14)

        header = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        title = TitleLabel("Plantillas")
        subtitle = CaptionLabel(
            "Proyectos iniciales listos para usar, creados en disco sin descargar nada. "
            "Puedes abrirlos en el espacio de trabajo y generar su primer prompt."
        )
        subtitle.setWordWrap(True)
        muted_color(subtitle)
        titles.addWidget(title)
        titles.addWidget(subtitle)
        header.addLayout(titles, 1)
        root.addLayout(header)

        splitter = make_splitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_grid())
        splitter.addWidget(self._build_detail())
        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 4)
        splitter.setSizes([700, 520])
        root.addWidget(splitter, 1)
        self._select(self._selected)

    def _build_grid(self) -> QWidget:
        area = SmoothScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        grid = QGridLayout(content)
        grid.setContentsMargins(0, 0, 8, 8)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        for index, (key, scaffold) in enumerate(SCAFFOLDS.items()):
            card = ScaffoldCard(scaffold)
            card.activated.connect(self._select)
            self._cards[key] = card
            grid.addWidget(card, index // 2, index % 2)
        grid.setRowStretch((len(SCAFFOLDS) + 1) // 2, 1)
        area.setWidget(content)
        area.enableTransparentBackground()
        return area

    def _build_detail(self) -> QWidget:
        card = SectionCard()
        layout = QVBoxLayout()
        layout.setSpacing(8)
        self.detail_name = StrongBodyLabel("")
        font = self.detail_name.font()
        font.setPointSize(17)
        font.setBold(True)
        self.detail_name.setFont(font)
        layout.addWidget(self.detail_name)
        self.detail_tags = QHBoxLayout()
        self.detail_tags.setSpacing(4)
        layout.addLayout(self.detail_tags)
        self.detail_description = CaptionLabel("")
        self.detail_description.setWordWrap(True)
        muted_color(self.detail_description)
        layout.addWidget(self.detail_description)
        card.add_layout(layout)

        files_label = StrongBodyLabel("Archivos incluidos")
        card.add_widget(files_label)
        self.files_tree = TreeWidget()
        self.files_tree.setColumnCount(2)
        self.files_tree.setHeaderLabels(["Ruta", "Tamaño"])
        self.files_tree.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.files_tree.setRootIsDecorated(False)
        self.files_tree.setUniformRowHeights(True)
        files_header = self.files_tree.header()
        files_header.setStretchLastSection(False)
        files_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        files_header.resizeSection(1, 84)
        card.add_widget(self.files_tree, 1)

        steps_label = StrongBodyLabel("Siguientes pasos")
        card.add_widget(steps_label)
        self.steps_layout = QVBoxLayout()
        self.steps_layout.setSpacing(4)
        card.add_layout(self.steps_layout)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.copy_steps_button = TransparentPushButton("Copiar pasos")
        self.copy_steps_button.clicked.connect(self._copy_steps)
        self.create_button = PrimaryPushButton(FIF.ADD, "Crear proyecto")
        self.create_button.clicked.connect(self._create)
        actions.addWidget(self.copy_steps_button)
        actions.addStretch(1)
        actions.addWidget(self.create_button)
        card.add_layout(actions)
        return card

    # ------------------------------------------------------------------ state
    def _select(self, key: str) -> None:
        scaffold = SCAFFOLDS.get(key)
        if scaffold is None:
            return
        self._selected = key
        for card_key, card in self._cards.items():
            card.set_selected(card_key == key)
        self.detail_name.setText(scaffold.name)
        while self.detail_tags.count():
            item = self.detail_tags.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        for tag in scaffold.tags:
            self.detail_tags.addWidget(Chip(tag, "violet"))
        self.detail_tags.addStretch(1)
        self.detail_description.setText(scaffold.description)
        self.files_tree.clear()
        total = 0
        for rel, content in scaffold.files.items():
            size = len(content.encode("utf-8"))
            total += size
            item = QTreeWidgetItem(self.files_tree, [rel, f"{size:,} B".replace(",", ".")])
            lines = content.count(chr(10)) + 1
            item.setToolTip(1, count_label(lines, "línea", "líneas"))
        while self.steps_layout.count():
            item = self.steps_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        for step in scaffold.next_steps:
            label = CaptionLabel(f"›  {step}")
            label.setWordWrap(True)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.steps_layout.addWidget(label)
        if not scaffold.next_steps:
            self.steps_layout.addWidget(CaptionLabel("Abre el proyecto y ejecuta sus comandos."))
        self.steps_layout.addStretch(1)
        self.files_tree.setToolTip(
            f"{count_label(len(scaffold.files), 'archivo', 'archivos')} · "
            f"{format_tokens(total // 4)} tokens"
        )
        self.copy_steps_button.setEnabled(bool(scaffold.next_steps))

    # ---------------------------------------------------------------- actions
    def _copy_steps(self) -> None:
        scaffold = SCAFFOLDS[self._selected]
        try:
            copy_text("\n".join(scaffold.next_steps))
            notify(self, "success", "Pasos copiados", scaffold.name, 1600)
        except Exception as error:
            notify(self, "error", "No se pudo copiar", str(error))

    def _create(self) -> None:
        scaffold = SCAFFOLDS[self._selected]
        dialog = CreateScaffoldDialog(scaffold, self)
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.result_path is None:
            return
        target = dialog.result_path
        detail = f"{target}"
        if dialog.result_zip:
            detail += f"\nZIP: {target.parent / (target.name + '.zip')}"
        notify(self, "success", "Proyecto creado", detail, 4200)
        message = (
            f"Proyecto {scaffold.name} creado en:\n{target}\n\n"
            + ("Pasos sugeridos:\n" + "\n".join(f"  {step}" for step in scaffold.next_steps))
        )
        from ..widgets import confirm

        if confirm(self, "Proyecto creado", message + "\n\n¿Abrirlo ahora?"):
            self.ctx.open_project(target)
            self.workspaceRequested.emit()


__all__ = ["ScaffoldsPage"]
