"""Local prompt history. One JSON file per session, never sent anywhere."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .config import data_dir
from .models import PromptBundle, SessionRecord


@dataclass(slots=True)
class SessionSummary:
    id: str
    path: Path
    created_at: str
    task_label: str
    project_root: str
    file_count: int
    tokens: int
    request: str


class SessionStore:
    def __init__(self, base_dir: Path | str | None = None, keep: int = 200) -> None:
        self.base = Path(base_dir) if base_dir else data_dir() / "sessions"
        self.keep = keep

    def ensure(self) -> Path:
        self.base.mkdir(parents=True, exist_ok=True)
        return self.base

    def save_bundle(
        self,
        bundle: PromptBundle,
        note: str = "",
        text_override: str | None = None,
    ) -> Path:
        text = text_override if text_override is not None else bundle.text
        digest = hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:12]
        self.ensure()
        existing = list(self.base.glob(f"*-{digest}.json"))
        if existing:
            return existing[0]
        timestamp = datetime.now()
        session_id = f"{timestamp:%Y%m%d-%H%M%S}-{digest}"
        target = self.base / f"{session_id}.json"
        payload = {
            "version": 2,
            "id": session_id,
            "created_at": timestamp.isoformat(timespec="seconds"),
            "task": bundle.task,
            "task_label": bundle.task_label,
            "request": bundle.request,
            "project_root": str(bundle.project_root),
            "format": bundle.format,
            "tokens": bundle.tokens,
            "budget": bundle.budget,
            "files": [item.rel for item in bundle.context.files],
            "prompt": text,
            "options": bundle.options.to_dict(),
            "note": note,
            "prompt_hash": digest,
        }
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        self.prune()
        return target

    def list(self, limit: int = 200) -> list[SessionSummary]:
        if not self.base.is_dir():
            return []
        summaries: list[SessionSummary] = []
        for path in self.base.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError, UnicodeError):
                continue
            if not isinstance(data, dict) or "id" not in data:
                continue
            summaries.append(
                SessionSummary(
                    id=str(data.get("id", path.stem)),
                    path=path,
                    created_at=str(data.get("created_at", "")),
                    task_label=str(data.get("task_label", data.get("task", ""))),
                    project_root=str(data.get("project_root", "")),
                    file_count=len(data.get("files", []) or []),
                    tokens=int(data.get("tokens", 0) or 0),
                    request=str(data.get("request", "")),
                )
            )
        summaries.sort(key=lambda item: item.created_at, reverse=True)
        return summaries[:limit]

    def load(self, path: Path | str) -> SessionRecord:
        target = Path(path)
        data = json.loads(target.read_text(encoding="utf-8"))
        return SessionRecord(
            id=str(data.get("id", target.stem)),
            created_at=str(data.get("created_at", "")),
            task=str(data.get("task", "feature")),
            task_label=str(data.get("task_label", "")),
            request=str(data.get("request", "")),
            project_root=str(data.get("project_root", "")),
            format=str(data.get("format", "markdown")),
            tokens=int(data.get("tokens", 0) or 0),
            budget=int(data.get("budget", 120_000) or 120_000),
            files=[str(item) for item in data.get("files", []) or []],
            prompt=str(data.get("prompt", "")),
            options=dict(data.get("options", {}) or {}),
            note=str(data.get("note", "")),
            prompt_hash=str(data.get("prompt_hash", "")),
            path=str(target),
        )

    def delete(self, path: Path | str) -> bool:
        try:
            Path(path).unlink()
            return True
        except OSError:
            return False

    def clear(self) -> int:
        if not self.base.is_dir():
            return 0
        removed = 0
        for path in self.base.glob("*.json"):
            try:
                path.unlink()
                removed += 1
            except OSError:
                continue
        return removed

    def prune(self) -> None:
        if self.keep <= 0:
            return
        files = sorted(
            self.base.glob("*.json"),
            key=lambda path: path.stat().st_mtime if path.exists() else 0,
            reverse=True,
        )
        for path in files[self.keep :]:
            try:
                path.unlink()
            except OSError:
                continue

    def open_folder(self) -> Path:
        folder = self.ensure()
        if os.name == "nt":
            os.startfile(folder)  # type: ignore[attr-defined]
        return folder


__all__ = ["SessionStore", "SessionSummary"]
