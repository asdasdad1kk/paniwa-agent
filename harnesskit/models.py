"""Plain data models shared by the core engine, the CLI and the UI."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


STATUS_LABELS = {
    "M": "Modificado",
    "A": "Añadido",
    "D": "Eliminado",
    "R": "Renombrado",
    "C": "Copiado",
    "U": "Conflicto",
    "T": "Tipo cambiado",
    "??": "Sin seguimiento",
    "!!": "Ignorado",
}

STATUS_COLORS = {
    "M": "#d97706",
    "A": "#16a34a",
    "D": "#dc2626",
    "R": "#7c3aed",
    "C": "#0d9488",
    "U": "#dc2626",
    "??": "#6b7280",
}


def status_label(code: str) -> str:
    return STATUS_LABELS.get(code.strip() or "", code.strip() or "Sin cambios")


@dataclass(slots=True)
class FileEntry:
    """Metadata for one text file found by the scanner."""

    path: Path
    rel: str
    size: int
    mtime: float
    language: str = "Text"
    sensitive: str = ""
    too_large: bool = False
    git_code: str = ""
    staged: bool = False
    estimated_tokens: int = 0

    @property
    def name(self) -> str:
        return Path(self.rel).name

    @property
    def suffix(self) -> str:
        return self.path.suffix.lower()

    @property
    def is_changed(self) -> bool:
        code = self.git_code.strip()
        return bool(code) and code != "!!"

    @property
    def is_source(self) -> bool:
        return self.language not in {"Text", "Markdown", "JSON", "YAML", "TOML", "CSV", "SQL"}

    @property
    def status_char(self) -> str:
        code = self.git_code.strip()
        if code in {"??", "!!"}:
            return code
        return code[:1] if code else ""

    @property
    def change_label(self) -> str:
        code = self.status_char
        if not code:
            return "Sin cambios"
        label = STATUS_LABELS.get(code, code)
        return f"{label} · preparado" if self.staged else label

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["path"] = str(self.path)
        return data


@dataclass(slots=True)
class GitFile:
    rel: str
    code: str
    staged: bool = False

    @property
    def untracked(self) -> bool:
        return self.code.strip() == "??"


@dataclass(slots=True)
class GitInfo:
    root: Path
    branch: str = ""
    status_text: str = ""
    files: dict[str, GitFile] = field(default_factory=dict)
    ahead: int = 0
    behind: int = 0
    error: str = ""

    @property
    def is_dirty(self) -> bool:
        return any(not f.staged for f in self.files.values()) or any(
            f.untracked for f in self.files.values()
        )

    @property
    def changed_paths(self) -> list[str]:
        return sorted(self.files)

    @property
    def modified_paths(self) -> list[str]:
        return [
            rel
            for rel, item in self.files.items()
            if item.code.strip() not in {"??", "!!"}
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": str(self.root),
            "branch": self.branch,
            "status_text": self.status_text,
            "files": {k: {"code": v.code, "staged": v.staged} for k, v in self.files.items()},
            "ahead": self.ahead,
            "behind": self.behind,
            "error": self.error,
        }


@dataclass(slots=True)
class ScanResult:
    root: Path
    files: list[FileEntry]
    git: GitInfo | None = None
    ignored_dirs: int = 0
    skipped_binary: int = 0
    skipped_large: int = 0
    skipped_files: int = 0
    duration_ms: int = 0
    truncated_by_limit: bool = False
    notes: list[str] = field(default_factory=list)
    gitignore_enabled: bool = True
    token: int = 0

    def index(self) -> dict[str, FileEntry]:
        return {entry.rel: entry for entry in self.files}

    def selected_entries(self, selected: set[str]) -> list[FileEntry]:
        return [entry for entry in self.files if entry.rel in selected]

    @property
    def total_bytes(self) -> int:
        return sum(entry.size for entry in self.files)


@dataclass(slots=True)
class SecretFinding:
    kind: str
    path: str
    line: int
    preview: str
    severity: str = "alta"


@dataclass(slots=True)
class GenerateOptions:
    """Everything that influences how context and instructions are assembled."""

    budget_tokens: int = 120_000
    format: str = "markdown"
    include_repo_map: bool = True
    repo_map_tokens: int = 4_000
    include_git: bool = True
    include_diff: bool = True
    include_related: bool = True
    related_depth: int = 1
    line_numbers: bool = False
    redact: bool = True
    diff_only: bool = False
    truncate: bool = True
    include_untracked: bool = True
    custom_instructions: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GenerateOptions":
        allowed = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in allowed})


@dataclass(slots=True)
class ContextFile:
    rel: str
    language: str
    text: str
    tokens: int
    mode: str = "completo"
    status: str = ""
    note: str = ""
    tier: str = "seleccionado"

    @property
    def lines(self) -> int:
        return self.text.count("\n") + 1 if self.text else 0


@dataclass(slots=True)
class ExcludedFile:
    rel: str
    reason: str


@dataclass(slots=True)
class ContextBundle:
    files: list[ContextFile] = field(default_factory=list)
    excluded: list[ExcludedFile] = field(default_factory=list)
    repo_map: str = ""
    git_status: str = ""
    git_diff: str = ""
    tokens: int = 0
    redactions: int = 0
    secret_findings: list[SecretFinding] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    diff_truncated: bool = False
    map_truncated: bool = False

    @property
    def file_count(self) -> int:
        return len(self.files)


@dataclass(slots=True)
class PromptBundle:
    text: str
    task: str
    task_label: str
    request: str
    format: str
    options: GenerateOptions
    context: ContextBundle
    project_root: Path
    tokens: int = 0
    budget: int = 120_000
    created_at: str = ""
    warnings: list[str] = field(default_factory=list)
    prompt_hash: str = ""

    @property
    def file_count(self) -> int:
        return self.context.file_count

    @property
    def within_budget(self) -> bool:
        return self.tokens <= self.budget

    @property
    def summary(self) -> str:
        return (
            f"{self.task_label} · {self.file_count} archivos · "
            f"~{self.tokens:,} tokens".replace(",", ".")
        )


@dataclass(slots=True)
class SessionRecord:
    id: str
    created_at: str
    task: str
    task_label: str
    request: str
    project_root: str
    format: str
    tokens: int
    budget: int
    files: list[str]
    prompt: str
    options: dict[str, Any] = field(default_factory=dict)
    note: str = ""
    prompt_hash: str = ""
    path: str = ""

    @property
    def file_count(self) -> int:
        return len(self.files)

    def to_json(self) -> dict[str, Any]:
        return asdict(self)
