"""Tiny QThreadPool wrapper for scans and prompt generation."""

from __future__ import annotations

import traceback
from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, Signal


class WorkerSignals(QObject):
    finished = Signal(object)
    error = Signal(str)
    progress = Signal(int)


class TaskWorker(QRunnable):
    def __init__(self, function: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        super().__init__()
        self.function = function
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()
        self.setAutoDelete(True)

    def run(self) -> None:  # pragma: no cover - exercised through the UI
        try:
            result = self.function(*self.args, **self.kwargs)
        except Exception as error:
            details = "".join(traceback.format_exception_only(type(error), error)).strip()
            self.signals.error.emit(details)
            return
        self.signals.finished.emit(result)


__all__ = ["TaskWorker", "WorkerSignals"]
