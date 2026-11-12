"""Read-only Git integration built on subprocess (no shell, no mutations)."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from .models import GitFile, GitInfo
from .tokens import truncate_chars


class GitUnavailable(RuntimeError):
    """Raised when Git is missing or a read-only query fails."""


def git_executable() -> str | None:
    return shutil.which("git")


def _run(
    root: Path,
    args: list[str],
    timeout: float = 20.0,
) -> subprocess.CompletedProcess[str]:
    executable = git_executable()
    if executable is None:
        raise GitUnavailable("Git no está instalado; esta opción no está disponible.")
    environment = os.environ.copy()
    environment.setdefault("GIT_OPTIONAL_LOCKS", "0")
    environment.setdefault("GIT_PAGER", "cat")
    environment.setdefault("GIT_TERMINAL_PROMPT", "0")
    command = [executable, "-C", str(root), *args]
    try:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=timeout,
            env=environment,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise GitUnavailable(f"No se pudo ejecutar Git: {error}") from error


def is_git_repo(root: Path | str) -> bool:
    root = Path(root)
    if not root.is_dir() or git_executable() is None:
        return False
    try:
        result = _run(root, ["rev-parse", "--is-inside-work-tree"])
    except GitUnavailable:
        return False
    return result.returncode == 0 and result.stdout.strip() == "true"


def _parse_branch(chunk: str) -> tuple[str, int, int]:
    # "## main...origin/main [ahead 2, behind 1]"
    text = chunk[3:].strip() if chunk.startswith("## ") else chunk.strip()
    ahead = behind = 0
    if " [" in text:
        head, tail = text.split(" [", 1)
        text = head.strip()
        inside = tail.rstrip("]")
        for part in inside.split(","):
            part = part.strip()
            if part.startswith("ahead "):
                ahead = int(part.split()[1]) if part.split()[1].isdigit() else 0
            elif part.startswith("behind "):
                behind = int(part.split()[1]) if part.split()[1].isdigit() else 0
    branch = text.split("...", 1)[0].strip()
    if branch.startswith("No commits yet on "):
        branch = branch.replace("No commits yet on ", "")
    return branch, ahead, behind


def git_info(root: Path | str) -> GitInfo | None:
    """Return branch, status and per-file flags, or ``None`` outside a repo."""

    root = Path(root)
    if not is_git_repo(root):
        return None
    try:
        top = _run(root, ["rev-parse", "--show-toplevel"])
        repo_root = Path(top.stdout.strip()) if top.returncode == 0 else root
        result = _run(
            root,
            ["-c", "core.quotepath=false", "status", "--porcelain=v1", "-z", "--branch"],
        )
    except GitUnavailable as error:
        return GitInfo(root=root, error=str(error))
    if result.returncode != 0:
        return GitInfo(
            root=repo_root,
            error=(result.stderr.strip() or result.stdout.strip() or "git status falló"),
        )

    chunks = result.stdout.split("\0")
    branch = ""
    ahead = behind = 0
    files: dict[str, GitFile] = {}
    index = 0
    while index < len(chunks):
        chunk = chunks[index]
        index += 1
        if not chunk:
            continue
        if chunk.startswith("## "):
            branch, ahead, behind = _parse_branch(chunk)
            continue
        if len(chunk) < 4:
            continue
        code = chunk[:2]
        rel = chunk[3:].replace("\\", "/")
        staged = code[0] not in {" ", "?"}
        files[rel] = GitFile(rel=rel, code=code.strip() or code, staged=staged)
        if "R" in code or "C" in code:
            index += 1  # original path follows as a separate NUL-terminated chunk

    lines = [f"## {branch}"] if branch else []
    # When the project opened in the UI is a subdirectory of the repo, Git
    # reports paths relative to the repository root. Remap them so they match
    # the scanner's ``rel`` values; files outside the opened folder are hidden.
    try:
        prefix = root.resolve().relative_to(repo_root.resolve()).as_posix()
    except (OSError, ValueError):
        prefix = ""
    if prefix and prefix != ".":
        remapped: dict[str, GitFile] = {}
        for rel, item in files.items():
            if not rel.startswith(prefix + "/"):
                continue
            short = rel[len(prefix) + 1 :]
            remapped[short] = GitFile(rel=short, code=item.code, staged=item.staged)
        files = remapped

    for rel in sorted(files):
        item = files[rel]
        lines.append(f"{item.code:<2} {rel}")
    status_text = "\n".join(lines)
    return GitInfo(
        root=repo_root,
        branch=branch,
        status_text=status_text,
        files=files,
        ahead=ahead,
        behind=behind,
    )


_DIFF_CACHE: dict[tuple[str, bool, int], tuple[float, str, bool]] = {}


def git_diff(
    root: Path | str,
    staged: bool = False,
    max_chars: int = 600_000,
    ttl: float = 2.0,
    refresh: bool = False,
) -> tuple[str, bool]:
    """Return ``(diff_text, truncated)`` for the working tree or the index."""

    root_path = Path(root).resolve()
    key = (str(root_path), staged, max_chars)
    now = time.time()
    if not refresh:
        cached = _DIFF_CACHE.get(key)
        if cached and now - cached[0] < ttl:
            return cached[1], cached[2]
    if git_executable() is None or not is_git_repo(root_path):
        return "", False
    args = [
        "-c",
        "core.quotepath=false",
        "diff",
        "--no-color",
        "--no-ext-diff",
        "--unified=3",
    ]
    if staged:
        args.append("--cached")
    args.extend(["--", "."])
    try:
        result = _run(root_path, args, timeout=30)
    except GitUnavailable:
        return "", False
    text = result.stdout if result.returncode == 0 else result.stderr
    text, truncated = truncate_chars(text.strip(), max_chars)
    _DIFF_CACHE[key] = (now, text, truncated)
    return text, truncated


def combined_diff(
    root: Path | str,
    include_staged: bool = True,
    max_chars: int = 600_000,
) -> tuple[str, bool]:
    sections: list[str] = []
    truncated = False
    unstaged, was_truncated = git_diff(root, staged=False, max_chars=max_chars)
    truncated = truncated or was_truncated
    if unstaged:
        sections.append("### Cambios sin preparar\n" + unstaged)
    if include_staged:
        staged, was_truncated = git_diff(root, staged=True, max_chars=max_chars)
        truncated = truncated or was_truncated
        if staged:
            sections.append("### Cambios preparados (staged)\n" + staged)
    return "\n\n".join(sections), truncated


def git_status(root: Path | str) -> str:
    info = git_info(root)
    if info is None:
        raise GitUnavailable("La carpeta no es un repositorio Git.")
    if info.error:
        raise GitUnavailable(info.error)
    return info.status_text.strip() or "(sin cambios)"


def git_output(root: Path | str, command: str) -> str:
    """Compatibility wrapper for read-only status/diff queries."""

    if command == "status":
        return git_status(root)
    if command == "diff":
        text, _ = git_diff(root, staged=False)
        return text.strip() or "(sin cambios)"
    raise ValueError(f"Comando Git no permitido: {command}")


def check_patch(root: Path | str, patch_text: str) -> tuple[bool, str]:
    """Run ``git apply --check`` on a patch without touching the worktree."""

    if git_executable() is None:
        return False, "Git no está instalado."
    if not is_git_repo(root):
        return False, "La carpeta del proyecto no es un repositorio Git."
    with tempfile.TemporaryDirectory(prefix="harness-patch-") as temporary:
        patch_path = Path(temporary) / "proposed.patch"
        patch_path.write_text(patch_text, encoding="utf-8", newline="\n")
        try:
            result = _run(
                Path(root),
                ["apply", "--check", "--verbose", "--whitespace=nowarn", str(patch_path)],
                timeout=30,
            )
        except GitUnavailable as error:
            return False, str(error)
    output = (result.stdout + result.stderr).strip()
    return result.returncode == 0, output or "git apply --check no reportó problemas."


def file_diff(root: Path | str, rel: str, staged: bool = False) -> str:
    root_path = Path(root)
    if git_executable() is None or not is_git_repo(root_path):
        raise GitUnavailable("Git no disponible.")
    args = ["-c", "core.quotepath=false", "diff", "--no-color", "--no-ext-diff"]
    if staged:
        args.append("--cached")
    args.extend(["--", rel])
    result = _run(root_path, args)
    if result.returncode != 0:
        raise GitUnavailable(result.stderr.strip() or "git diff falló")
    return result.stdout.strip() or "(sin diferencias)"


__all__ = [
    "GitUnavailable",
    "check_patch",
    "combined_diff",
    "file_diff",
    "git_diff",
    "git_executable",
    "git_info",
    "git_output",
    "git_status",
    "is_git_repo",
]
