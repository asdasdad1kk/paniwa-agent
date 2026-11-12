"""Persistent user configuration (stdlib only)."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import APP_NAME
from .models import GenerateOptions

APP_FOLDER = "HarnessStudio"


def data_dir() -> Path:
    """Return the per-user data directory, overridable with HARNESS_HOME."""

    override = os.environ.get("HARNESS_HOME")
    if override:
        return Path(override).expanduser()
    if os.name == "nt":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    elif os.uname().sysname == "Darwin":  # pragma: no cover - platform specific
        base = str(Path.home() / "Library" / "Application Support")
    else:  # pragma: no cover - platform specific
        base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / APP_FOLDER


def config_path() -> Path:
    return data_dir() / "config.json"


def sessions_dir() -> Path:
    return data_dir() / "sessions"


@dataclass
class HarnessConfig:
    theme: str = "auto"
    accent: str = "blue"
    font_size: int = 11
    mono_font: str = ""
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
    record_history: bool = True
    max_file_mb: float = 2.0
    max_files: int = 20_000
    extra_ignore: str = ""
    editor_command: str = "auto"
    recent_projects: list[str] = field(default_factory=list)
    window_geometry: str = ""
    window_state: str = ""
    last_project: str = ""
    sessions_kept: int = 200

    def to_generate_options(self) -> GenerateOptions:
        return GenerateOptions(
            budget_tokens=self.budget_tokens,
            format=self.format,
            include_repo_map=self.include_repo_map,
            repo_map_tokens=self.repo_map_tokens,
            include_git=self.include_git,
            include_diff=self.include_diff,
            include_related=self.include_related,
            related_depth=self.related_depth,
            line_numbers=self.line_numbers,
            redact=self.redact,
            diff_only=self.diff_only,
            truncate=self.truncate,
            include_untracked=self.include_untracked,
        )

    def extra_ignore_patterns(self) -> list[str]:
        return [
            line.strip()
            for line in self.extra_ignore.replace(",", "\n").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]

    def record_recent(self, path: str | Path) -> None:
        resolved = str(Path(path).expanduser().resolve())
        self.recent_projects = [
            item
            for item in self.recent_projects
            if Path(item).resolve() != Path(resolved)
        ]
        self.recent_projects.insert(0, resolved)
        del self.recent_projects[12:]

    def scan_signature(self) -> tuple[Any, ...]:
        return (self.max_file_mb, self.max_files, self.extra_ignore)


def _coerce(value: Any, default: Any) -> Any:
    if isinstance(default, bool):
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on", "si"}
        return bool(value)
    if isinstance(default, int) and not isinstance(default, bool):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default
    if isinstance(default, float):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default
    if isinstance(default, list):
        return [str(item) for item in value] if isinstance(value, list) else default
    if isinstance(default, str):
        return str(value) if value is not None else default
    return value


def load_config(path: Path | None = None) -> HarnessConfig:
    target = path or config_path()
    config = HarnessConfig()
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return config
    if not isinstance(raw, dict):
        return config
    for field_name, default_value in asdict(config).items():
        if field_name in raw:
            setattr(config, field_name, _coerce(raw[field_name], default_value))
    config.budget_tokens = max(2_000, min(1_000_000, config.budget_tokens))
    config.font_size = max(8, min(24, config.font_size))
    config.max_file_mb = max(0.05, min(50.0, config.max_file_mb))
    config.max_files = max(100, min(200_000, config.max_files))
    config.recent_projects = [p for p in config.recent_projects if Path(p).is_dir()]
    return config


def save_config(config: HarnessConfig, path: Path | None = None) -> Path:
    target = path or config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(asdict(config), ensure_ascii=False, indent=2)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=target.parent, delete=False, suffix=".tmp"
    ) as handle:
        handle.write(payload)
        temporary = Path(handle.name)
    os.replace(temporary, target)
    return target


def reset_config() -> HarnessConfig:
    config = HarnessConfig()
    save_config(config)
    return config


__all__ = [
    "APP_NAME",
    "HarnessConfig",
    "config_path",
    "data_dir",
    "load_config",
    "reset_config",
    "save_config",
    "sessions_dir",
]
