"""PySide6 + Fluent Widgets desktop interface for Harness Studio."""

from __future__ import annotations

__all__ = ["run_gui"]


def run_gui(project: str | None = None) -> int:
    """Lazy entry point so importing the core never pulls in Qt."""

    from .app import run_gui as _run

    return _run(project)
