#!/usr/bin/env python3
"""Compatibility layer for the original Copilot Harness API.

New code should import from :mod:`harnesskit`; this module keeps the old
``harness.build_prompt`` / ``harness.scan_files`` / ``harness.create_project``
surface working for scripts and tests.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from harnesskit import APP_NAME, __version__
from harnesskit.clipboard import copy_text as copy_to_clipboard
from harnesskit.promptlib import resolve_task
from harnesskit.scaffolds import PROJECT_TEMPLATES, create_project
from harnesskit.scanner import (
    ALWAYS_IGNORED_DIRS as IGNORED_DIRECTORIES,
    TEXT_EXTENSIONS,
    TEXT_FILENAMES,
    ScanOptions,
    scan_project,
)

# Legacy task table: numeric keys and (label, instruction) tuples.
TASKS = {
    "1": ("Feature", resolve_task("feature").instruction),
    "2": ("Bug fix", resolve_task("bugfix").instruction),
    "3": ("Refactor", resolve_task("refactor").instruction),
    "4": ("Tests", resolve_task("tests").instruction),
    "5": ("Code review", resolve_task("review").instruction),
    "6": ("Documentación", resolve_task("docs").instruction),
}


def scan_files(project_path: Path) -> list[Path]:
    """Return candidate text files, excluding generated directories."""

    result = scan_project(project_path, ScanOptions(include_git=False))
    return [entry.path for entry in result.files]


def build_prompt(    task: str,
    description: str,
    files: list[tuple[str, str]],
    git_context: str = "",
) -> str:
    """Compose the original user-visible request format."""

    task_instruction = TASKS[task][1]
    sections = [
        "Trabaja como asistente de ingeniería de software.",
        f"Tarea: {TASKS[task][0]}",
        task_instruction,
        "Antes de proponer cambios, analiza el contexto y señala cualquier duda "
        "o supuesto. No inventes archivos ni APIs que no aparezcan en el contexto.",
        "Explica los cambios por archivo y sugiere comandos de verificación. "
        "No afirmes que ejecutaste comandos que no ejecutaste.",
        f"Solicitud del usuario:\n{description.strip()}",
    ]
    if git_context.strip():
        sections.append(f"Estado de Git (solo lectura):\n{git_context.strip()}")
    for name, content in files:
        sections.append(f"--- Archivo: {name} ---\n{content.rstrip()}")
    return "\n\n".join(sections)


def git_output(project_path: Path, command: str) -> str:
    """Run a read-only Git query when Git exists; report failures to the caller."""

    git_executable = shutil.which("git")
    if git_executable is None:
        raise RuntimeError("Git no está instalado; esta opción no está disponible.")
    if command not in {"status", "diff"}:
        raise ValueError(f"Comando Git no permitido: {command}")
    git_args = ["status", "--short", "--branch"] if command == "status" else ["diff"]
    args = [git_executable, "-C", str(project_path), *git_args]
    try:
        result = subprocess.run(args, capture_output=True, text=True, check=False)
    except OSError as error:
        raise RuntimeError(f"No se pudo ejecutar Git: {error}") from error
    if result.returncode:
        details = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(details or f"Git terminó con código {result.returncode}.")
    return result.stdout.strip() or "(sin cambios)"


def main() -> int:
    from harnesskit.cli import main as cli_main

    arguments = sys.argv[1:]
    if not arguments:
        from harnesskit.cli import interactive

        return interactive()
    return cli_main(arguments)


__all__ = [
    "APP_NAME",
    "IGNORED_DIRECTORIES",
    "PROJECT_TEMPLATES",
    "TASKS",
    "TEXT_EXTENSIONS",
    "TEXT_FILENAMES",
    "__version__",
    "build_prompt",
    "copy_to_clipboard",
    "create_project",
    "git_output",
    "main",
    "scan_files",
]


if __name__ == "__main__":
    raise SystemExit(main())
