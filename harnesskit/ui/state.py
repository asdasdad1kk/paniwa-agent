"""Shared application state and background project loading."""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QObject, QThreadPool, Signal

from ..config import HarnessConfig, save_config
from ..engine import ContentCache, RepoMapCache
from ..gitutils import GitInfo
from ..history import SessionStore
from ..models import FileEntry, ScanResult
from ..scanner import ScanOptions, scan_project
from .widgets import count_label
from .workers import TaskWorker


class AppContext(QObject):
    projectStarted = Signal(str)
    projectChanged = Signal()
    projectFailed = Signal(str)
    selectionChanged = Signal(object)
    settingsChanged = Signal()
    historyChanged = Signal()
    statusMessage = Signal(str)

    def __init__(self, config: HarnessConfig, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.config = config
        self.root: Path | None = None
        self.scan: ScanResult | None = None
        self.git: GitInfo | None = None
        self.selected: set[str] = set()
        self.active_file: str = ""
        self.content_cache = ContentCache()
        self.map_cache = RepoMapCache()
        self.store = SessionStore(keep=config.sessions_kept)
        self._generation = 0
        self._cancel_event: threading.Event | None = None
        self._scan_worker: TaskWorker | None = None

    # ------------------------------------------------------------------ project
    def scan_options(self) -> ScanOptions:
        return ScanOptions(
            max_file_mb=self.config.max_file_mb,
            max_files=self.config.max_files,
            extra_ignore=self.config.extra_ignore_patterns(),
            include_git=True,
        )

    def open_project(
        self,
        path: str | Path,
        selected: set[str] | None = None,
    ) -> None:
        target = Path(path).expanduser()
        if target.is_file():
            target = target.parent
        if not target.is_dir():
            self.projectFailed.emit(f"No existe una carpeta válida en: {target}")
            return
        target = target.resolve()
        self._generation += 1
        generation = self._generation
        self.content_cache.clear()
        self.map_cache.clear()
        self.root = target
        self.scan = None
        self.git = None
        self.selected = set()
        self.active_file = ""
        self.projectStarted.emit(str(target))

        if self._cancel_event is not None:
            self._cancel_event.set()
        cancel_event = threading.Event()
        self._cancel_event = cancel_event
        options = self.scan_options()
        options.should_cancel = cancel_event.is_set
        worker = TaskWorker(scan_project, target, options)
        options.on_progress = worker.signals.progress.emit
        worker.signals.progress.connect(
            lambda count: self.statusMessage.emit(f"Escaneando… {count} archivos")
        )
        worker.signals.finished.connect(
            lambda scan: self._scan_finished(scan, generation, selected)
        )
        worker.signals.error.connect(lambda message: self._scan_failed(message, generation))
        self._scan_worker = worker
        QThreadPool.globalInstance().start(worker)

    def _scan_finished(
        self,
        scan: ScanResult,
        generation: int,
        pending_selection: set[str] | None,
    ) -> None:
        if generation != self._generation:
            return
        self.scan = scan
        self.git = scan.git
        index = scan.index()
        if pending_selection is not None:
            self.selected = {rel for rel in pending_selection if rel in index}
        else:
            self.selected = {
                entry.rel for entry in scan.files if entry.is_changed and not entry.too_large
            }
        self.config.record_recent(scan.root)
        self.config.last_project = str(scan.root)
        save_config(self.config)
        self.projectChanged.emit()
        self.selectionChanged.emit(set(self.selected))
        self.statusMessage.emit(
            f"{count_label(len(scan.files), 'archivo', 'archivos')} · "
            f"{count_label(len(self.selected), 'preseleccionado', 'preseleccionados')} · "
            f"{scan.duration_ms} ms"
        )

    def _scan_failed(self, message: str, generation: int) -> None:
        if generation != self._generation:
            return
        self.projectFailed.emit(message)
        self.statusMessage.emit("No se pudo abrir el proyecto.")

    def rescan(self) -> None:
        if self.root is None:
            return
        self.open_project(self.root, set(self.selected))

    # ---------------------------------------------------------------- selection
    def update_selection(self, selected: set[str], *, announce: bool = True) -> None:
        if self.scan is None:
            self.selected = set()
            return
        valid = {rel for rel in selected if rel in self.scan.index()}
        if valid == self.selected:
            return
        self.selected = valid
        self.selectionChanged.emit(set(self.selected))
        if announce:
            noun = count_label(len(valid), "archivo", "archivos")
            self.statusMessage.emit(
                f"{noun} seleccionado{'s' if len(valid) != 1 else ''}"
            )

    def set_active_file(self, rel: str) -> None:
        self.active_file = rel

    def entry(self, rel: str) -> FileEntry | None:
        if self.scan is None:
            return None
        return self.scan.index().get(rel)

    @property
    def selected_tokens(self) -> int:
        if self.scan is None:
            return 0
        index = self.scan.index()
        return sum(
            index[rel].estimated_tokens for rel in self.selected if rel in index and not index[rel].too_large
        )

    @property
    def changed_count(self) -> int:
        if self.scan is None:
            return 0
        return sum(1 for entry in self.scan.files if entry.is_changed)

    @property
    def project_name(self) -> str:
        return self.root.name if self.root else ""

    # ----------------------------------------------------------------- settings
    def update_settings(self, **changes) -> None:
        for name, value in changes.items():
            if hasattr(self.config, name):
                setattr(self.config, name, value)
        save_config(self.config)
        self.settingsChanged.emit()

    def replace_config(self, config: HarnessConfig) -> None:
        self.config = config
        save_config(config)
        self.store.keep = config.sessions_kept
        self.settingsChanged.emit()

    def notify_history_changed(self) -> None:
        self.historyChanged.emit()


__all__ = ["AppContext"]
