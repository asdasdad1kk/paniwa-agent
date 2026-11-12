"""Repository scanning with gitignore support and language detection."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .ignore import IgnoreMatcher
from .models import FileEntry, ScanResult
from .secrets import is_sensitive_path

ALWAYS_IGNORED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".harness",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    "node_modules",
    "bower_components",
    "vendor",
    "dist",
    "build",
    "out",
    "target",
    "coverage",
    "htmlcov",
    ".next",
    ".nuxt",
    ".output",
    ".angular",
    ".svelte-kit",
    ".idea",
    ".vscode",
    ".vs",
    "bin",
    "obj",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".cache",
    ".parcel-cache",
    ".turbo",
    ".gradle",
    ".dart_tool",
    "Pods",
    "DerivedData",
    ".terraform",
    ".serverless",
    ".yarn",
    ".pnp",
    ".eggs",
    "site-packages",
}

DEFAULT_FILE_IGNORES = [
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
    "Pipfile.lock",
    "composer.lock",
    "Gemfile.lock",
    "Cargo.lock",
    "*.min.js",
    "*.min.css",
    "*.map",
    "*.pyc",
    "*.pyo",
    "*.class",
    "*.log",
]

LANGUAGE_BY_EXT: dict[str, str] = {
    ".py": "Python",
    ".pyi": "Python",
    ".pyw": "Python",
    ".js": "JavaScript",
    ".mjs": "JavaScript",
    ".cjs": "JavaScript",
    ".jsx": "JavaScript (JSX)",
    ".ts": "TypeScript",
    ".tsx": "TypeScript (TSX)",
    ".mts": "TypeScript",
    ".cts": "TypeScript",
    ".vue": "Vue",
    ".svelte": "Svelte",
    ".html": "HTML",
    ".htm": "HTML",
    ".css": "CSS",
    ".scss": "SCSS",
    ".sass": "Sass",
    ".less": "Less",
    ".json": "JSON",
    ".jsonc": "JSON",
    ".json5": "JSON",
    ".ndjson": "JSON",
    ".md": "Markdown",
    ".mdx": "MDX",
    ".rst": "reStructuredText",
    ".txt": "Text",
    ".yml": "YAML",
    ".yaml": "YAML",
    ".toml": "TOML",
    ".ini": "INI",
    ".cfg": "INI",
    ".conf": "Config",
    ".properties": "Properties",
    ".env": "Dotenv",
    ".sql": "SQL",
    ".go": "Go",
    ".rs": "Rust",
    ".java": "Java",
    ".kt": "Kotlin",
    ".kts": "Kotlin",
    ".swift": "Swift",
    ".c": "C",
    ".h": "C/C++ header",
    ".cpp": "C++",
    ".cc": "C++",
    ".cxx": "C++",
    ".hpp": "C++",
    ".hh": "C++",
    ".cs": "C#",
    ".rb": "Ruby",
    ".php": "PHP",
    ".dart": "Dart",
    ".scala": "Scala",
    ".ex": "Elixir",
    ".exs": "Elixir",
    ".erl": "Erlang",
    ".hs": "Haskell",
    ".lua": "Lua",
    ".r": "R",
    ".jl": "Julia",
    ".pl": "Perl",
    ".pm": "Perl",
    ".sh": "Shell",
    ".bash": "Shell",
    ".zsh": "Shell",
    ".fish": "Shell",
    ".ps1": "PowerShell",
    ".psm1": "PowerShell",
    ".bat": "Batch",
    ".cmd": "Batch",
    ".gradle": "Gradle",
    ".graphql": "GraphQL",
    ".gql": "GraphQL",
    ".proto": "Protobuf",
    ".prisma": "Prisma",
    ".tf": "Terraform",
    ".hcl": "HCL",
    ".xml": "XML",
    ".xaml": "XAML",
    ".plist": "Property list",
    ".svg": "SVG",
    ".csv": "CSV",
    ".tsv": "CSV",
    ".ipynb": "Jupyter Notebook",
    ".dockerfile": "Dockerfile",
    ".cmake": "CMake",
    ".asm": "Assembly",
    ".v": "Verilog",
    ".sv": "SystemVerilog",
    ".sol": "Solidity",
    ".zig": "Zig",
    ".nim": "Nim",
    ".clj": "Clojure",
    ".cljs": "ClojureScript",
    ".fs": "F#",
    ".fsx": "F#",
}

SPECIAL_FILENAMES: dict[str, str] = {
    ".gitignore": "Git",
    ".gitattributes": "Git",
    ".gitmodules": "Git",
    ".dockerignore": "Docker",
    ".editorconfig": "EditorConfig",
    ".prettierrc": "JSON",
    ".eslintrc": "JSON",
    ".babelrc": "JSON",
    ".npmrc": "Config",
    ".pypirc": "Config",
    ".netrc": "Config",
    "dockerfile": "Dockerfile",
    "makefile": "Makefile",
    "cmakelists.txt": "CMake",
    "justfile": "Just",
    "procfile": "Config",
    "gemfile": "Ruby",
    "rakefile": "Ruby",
    "vagrantfile": "Ruby",
    "license": "Text",
    "licence": "Text",
    "readme": "Markdown",
    "changelog": "Markdown",
    "requirements.txt": "Text",
    "pyproject.toml": "TOML",
    "package.json": "JSON",
    "tsconfig.json": "JSON",
}

TEXT_EXTENSIONS = set(LANGUAGE_BY_EXT)
TEXT_FILENAMES = set(SPECIAL_FILENAMES)

BINARY_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".bmp",
    ".ico",
    ".webp",
    ".avif",
    ".tiff",
    ".mp3",
    ".mp4",
    ".mov",
    ".avi",
    ".mkv",
    ".wav",
    ".flac",
    ".ogg",
    ".zip",
    ".gz",
    ".bz2",
    ".xz",
    ".7z",
    ".rar",
    ".tar",
    ".jar",
    ".war",
    ".exe",
    ".dll",
    ".so",
    ".dylib",
    ".bin",
    ".dat",
    ".db",
    ".sqlite",
    ".sqlite3",
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".woff",
    ".woff2",
    ".ttf",
    ".otf",
    ".eot",
    ".psd",
    ".ai",
    ".sketch",
    ".fig",
    ".blend",
    ".pyc",
    ".pyo",
    ".class",
    ".o",
    ".obj",
    ".lib",
    ".a",
    ".pdb",
}


@dataclass
class ScanOptions:
    max_file_mb: float = 2.0
    max_files: int = 20_000
    extra_ignore: list[str] = field(default_factory=list)
    respect_gitignore: bool = True
    include_git: bool = True
    hard_read_mb: float = 16.0
    should_cancel: Callable[[], bool] | None = None
    on_progress: Callable[[int], None] | None = None


def language_for(path: Path) -> str | None:
    name = path.name.lower()
    if name in SPECIAL_FILENAMES:
        return SPECIAL_FILENAMES[name]
    suffix = path.suffix.lower()
    if suffix in LANGUAGE_BY_EXT:
        return LANGUAGE_BY_EXT[suffix]
    if name.startswith(".env."):
        return "Dotenv"
    if name.endswith(".egg-info"):
        return None
    return None


def _sniff_text(path: Path) -> bool:
    try:
        with open(path, "rb") as handle:
            data = handle.read(4096)
    except OSError:
        return False
    if not data:
        return True
    if b"\x00" in data:
        return False
    for encoding in ("utf-8", "cp1252"):
        try:
            data.decode(encoding)
            return True
        except UnicodeDecodeError:
            continue
    printable = sum(1 for byte in data if 32 <= byte < 127 or byte in (9, 10, 13))
    return printable / len(data) > 0.85


def _is_candidate(path: Path) -> bool:
    suffix = path.suffix.lower()
    if suffix in BINARY_EXTENSIONS:
        return False
    if language_for(path) is not None:
        return True
    return _sniff_text(path)


def _read_gitignore(directory: Path) -> list[str]:
    target = directory / ".gitignore"
    try:
        text = target.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return text.splitlines()


def scan_project(
    project_root: Path | str,
    options: ScanOptions | None = None,
) -> ScanResult:
    """Walk a project and return text-file metadata, optionally with Git state."""

    started = time.perf_counter()
    root = Path(project_root).expanduser()
    if not root.is_dir():
        raise NotADirectoryError(f"No existe una carpeta válida en: {root}")
    root = root.resolve()
    opts = options or ScanOptions()

    matcher = IgnoreMatcher().with_rules("", list(DEFAULT_FILE_IGNORES))
    if opts.respect_gitignore:
        matcher = matcher.with_rules("", _read_gitignore(root))
        git_exclude = root / ".git" / "info" / "exclude"
        try:
            matcher = matcher.with_rules(
                "", git_exclude.read_text(encoding="utf-8", errors="replace").splitlines()
            )
        except OSError:
            pass
    matcher = matcher.with_rules("", list(opts.extra_ignore))

    entries: list[FileEntry] = []
    notes: list[str] = []
    ignored_dirs = 0
    skipped_binary = 0
    skipped_large = 0
    skipped_files = 0
    truncated = False
    max_bytes = int(opts.max_file_mb * 1024 * 1024)
    progress = opts.on_progress
    should_cancel = opts.should_cancel

    def walk(directory: Path, rel_prefix: str, current_matcher: IgnoreMatcher) -> None:
        nonlocal ignored_dirs, skipped_binary, skipped_large, skipped_files, truncated
        if truncated:
            return
        if should_cancel is not None and should_cancel():
            truncated = True
            return
        child_matcher = current_matcher
        if opts.respect_gitignore and rel_prefix:
            patterns = _read_gitignore(directory)
            if patterns:
                child_matcher = current_matcher.with_rules(rel_prefix.rstrip("/"), patterns)
        try:
            with os.scandir(directory) as iterator:
                items = sorted(iterator, key=lambda item: (not item.is_dir(), item.name.lower()))
        except OSError as error:
            notes.append(f"No se pudo leer {directory}: {error}")
            return

        for item in items:
            if truncated:
                return
            name = item.name
            rel = f"{rel_prefix}{name}"
            try:
                if item.is_symlink():
                    continue
                is_dir = item.is_dir(follow_symlinks=False)
            except OSError:
                continue
            if is_dir:
                if name in ALWAYS_IGNORED_DIRS or name.endswith(".egg-info"):
                    ignored_dirs += 1
                    continue
                if child_matcher.is_ignored(rel, True):
                    ignored_dirs += 1
                    continue
                walk(Path(item.path), rel + "/", child_matcher)
                continue

            if child_matcher.is_ignored(rel, False):
                skipped_files += 1
                continue
            path = Path(item.path)
            if path.suffix.lower() in BINARY_EXTENSIONS:
                skipped_binary += 1
                continue
            language = language_for(path)
            if language is None and not _sniff_text(path):
                skipped_binary += 1
                continue
            try:
                stat = item.stat(follow_symlinks=False)
            except OSError:
                continue
            too_large = stat.st_size > max_bytes
            if too_large:
                skipped_large += 1
                # Keep metadata so the UI can explain why a file is unavailable.
            entries.append(
                FileEntry(
                    path=path,
                    rel=rel,
                    size=stat.st_size,
                    mtime=stat.st_mtime,
                    language=language or "Text",
                    sensitive=is_sensitive_path(rel),
                    too_large=too_large,
                    estimated_tokens=max(1, stat.st_size // 4),
                )
            )
            if len(entries) >= opts.max_files:
                truncated = True
                notes.append(
                    f"Se alcanzó el límite de {opts.max_files} archivos; el escaneo se detuvo."
                )
                return
            if progress is not None and len(entries) % 400 == 0:
                progress(len(entries))

    walk(root, "", matcher)
    entries.sort(key=lambda entry: entry.rel.lower())

    result = ScanResult(
        root=root,
        files=entries,
        ignored_dirs=ignored_dirs,
        skipped_binary=skipped_binary,
        skipped_large=skipped_large,
        skipped_files=skipped_files,
        duration_ms=int((time.perf_counter() - started) * 1000),
        truncated_by_limit=truncated,
        notes=notes,
        gitignore_enabled=opts.respect_gitignore,
        token=int(time.time() * 1000),
    )
    if opts.include_git:
        try:
            from .gitutils import git_info

            info = git_info(root)
            result.git = info
            if info and not info.error:
                for entry in entries:
                    git_file = info.files.get(entry.rel)
                    if git_file is not None:
                        entry.git_code = git_file.code.strip()
                        entry.staged = git_file.staged
        except Exception as error:  # pragma: no cover - defensive
            notes.append(f"No se pudo leer el estado de Git: {error}")
    return result


def read_text_entry(entry: FileEntry, hard_read_mb: float = 16.0) -> str:
    """Read one scanned text file with encoding fallbacks."""

    limit = int(hard_read_mb * 1024 * 1024)
    if entry.size > limit:
        raise ValueError(
            f"{entry.rel} supera el límite de lectura ({entry.size / 1024 / 1024:.1f} MB)."
        )
    data = entry.path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def scan_files(project_path: Path, options: ScanOptions | None = None) -> list[Path]:
    """Compatibility helper returning absolute paths."""

    result = scan_project(project_path, options or ScanOptions(include_git=False))
    return [entry.path for entry in result.files]


__all__ = [
    "ALWAYS_IGNORED_DIRS",
    "BINARY_EXTENSIONS",
    "DEFAULT_FILE_IGNORES",
    "LANGUAGE_BY_EXT",
    "SPECIAL_FILENAMES",
    "TEXT_EXTENSIONS",
    "TEXT_FILENAMES",
    "ScanOptions",
    "language_for",
    "read_text_entry",
    "scan_files",
    "scan_project",
]
