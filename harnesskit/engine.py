"""High-level orchestration: read, redact, pack, compose."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from .contextpack import PackCandidate, pack_context
from .gitutils import combined_diff
from .models import (
    ContextBundle,
    ExcludedFile,
    FileEntry,
    GenerateOptions,
    PromptBundle,
    ScanResult,
    SecretFinding,
)
from .promptlib import base_prompt_tokens, compose_prompt, resolve_task
from .scanner import read_text_entry
from .secrets import scan_text
from .symbols import build_repo_map, resolve_related
from .tokens import estimate_tokens


class ContentCache:
    """Per-file content cache keyed by mtime and size."""

    def __init__(self) -> None:
        self._items: dict[str, tuple[float, int, str]] = {}

    def get(self, entry: FileEntry, hard_read_mb: float = 16.0) -> str | None:
        cached = self._items.get(entry.rel)
        if cached is not None and cached[0] == entry.mtime and cached[1] == entry.size:
            return cached[2]
        try:
            text = read_text_entry(entry, hard_read_mb)
        except (OSError, ValueError):
            return None
        self._items[entry.rel] = (entry.mtime, entry.size, text)
        return text

    def put(self, rel: str, entry: FileEntry, text: str) -> None:
        self._items[rel] = (entry.mtime, entry.size, text)

    def clear(self) -> None:
        self._items.clear()


class RepoMapCache:
    """A repo map only changes when the scan or the map budget changes."""

    def __init__(self) -> None:
        self._key: tuple[int, int, int] | None = None
        self._value: str = ""
        self._truncated: bool = False

    def get(
        self,
        scan: ScanResult,
        selected: set[str],
        max_tokens: int,
        max_files: int = 500,
    ) -> tuple[str, bool]:
        key = (scan.token, max_tokens, max_files)
        if self._key == key:
            return self._value, self._truncated
        text, truncated = build_repo_map(
            scan.files, selected, max_tokens=max_tokens, max_files=max_files
        )
        self._key = key
        self._value = text
        self._truncated = truncated
        return text, truncated

    def clear(self) -> None:
        self._key = None
        self._value = ""
        self._truncated = False


@dataclass(slots=True)
class _ReadResult:
    candidates: list[PackCandidate]
    excluded: list[ExcludedFile]
    findings: list[SecretFinding]
    redactions: int
    notes: list[str]


def _read_many(
    entries: Iterable[FileEntry],
    tier: str,
    note: str,
    *,
    cache: ContentCache,
    redact: bool,
    known: dict[str, FileEntry],
    excluded: list[ExcludedFile],
    findings: list[SecretFinding],
    notes: list[str],
    hard_read_mb: float,
) -> tuple[list[PackCandidate], int]:
    candidates: list[PackCandidate] = []
    redactions = 0
    for entry in entries:
        if entry.too_large:
            excluded.append(ExcludedFile(entry.rel, "supera el tamaño máximo configurado"))
            continue
        text = cache.get(entry, hard_read_mb)
        if text is None:
            excluded.append(ExcludedFile(entry.rel, "no se pudo leer"))
            notes.append(f"No se pudo leer {entry.rel}.")
            continue
        if entry.sensitive:
            notes.append(f"Archivo sensible incluido: {entry.rel} ({entry.sensitive}).")
        cleaned, file_findings = scan_text(text, entry.rel, redact=redact)
        findings.extend(file_findings)
        if file_findings and redact:
            redactions += len(file_findings)
        candidates.append(PackCandidate(entry=entry, text=cleaned, tier=tier, note=note))
    return candidates, redactions


def generate_prompt(
    scan: ScanResult,
    task_key: str,
    request: str,
    options: GenerateOptions,
    selected: Iterable[str],
    *,
    content_cache: ContentCache | None = None,
    map_cache: RepoMapCache | None = None,
    hard_read_mb: float = 16.0,
) -> PromptBundle:
    """Generate a complete prompt bundle for the current project state."""

    cache = content_cache or ContentCache()
    maps = map_cache or RepoMapCache()
    index = scan.index()
    selected_set = {rel for rel in selected if rel in index}
    excluded: list[ExcludedFile] = [
        ExcludedFile(rel, "ya no existe o está ignorado") for rel in selected if rel not in index
    ]
    findings: list[SecretFinding] = []
    notes: list[str] = []

    selected_entries = [index[rel] for rel in sorted(selected_set, key=str.lower)]
    candidates: list[PackCandidate] = []
    redactions = 0

    for entry in selected_entries:
        tier = "cambio" if entry.is_changed else "seleccionado"
        new_candidates, new_redactions = _read_many(
            [entry],
            tier,
            "",
            cache=cache,
            redact=options.redact,
            known=index,
            excluded=excluded,
            findings=findings,
            notes=notes,
            hard_read_mb=hard_read_mb,
        )
        candidates.extend(new_candidates)
        redactions += new_redactions

    # Related files: direct local imports of the selected files.
    if options.include_related and candidates:
        seed_contents = {candidate.entry.rel: candidate.text for candidate in candidates}

        def reader(rel: str) -> str | None:
            entry = index.get(rel)
            if entry is None or entry.too_large:
                return None
            return cache.get(entry, hard_read_mb)

        related_rels = resolve_related(
            seed_contents,
            set(index),
            reader=reader,
            depth=max(1, options.related_depth),
            max_files=25,
        )
        related_entries = [
            index[rel]
            for rel in related_rels
            if rel in index and rel not in selected_set and not index[rel].too_large
        ]
        if related_entries:
            new_candidates, new_redactions = _read_many(
                related_entries,
                "relacionado",
                "importado por un archivo seleccionado",
                cache=cache,
                redact=options.redact,
                known=index,
                excluded=excluded,
                findings=findings,
                notes=notes,
                hard_read_mb=hard_read_mb,
            )
            candidates.extend(new_candidates)
            redactions += new_redactions

    repo_map = ""
    map_truncated = False
    if options.include_repo_map:
        repo_map, map_truncated = maps.get(
            scan, selected_set, max_tokens=max(400, min(options.repo_map_tokens, 12_000))
        )
        if map_truncated:
            notes.append("El mapa del repositorio es parcial por presupuesto.")

    git_status = ""
    diff_sections: list[tuple[str, str]] = []
    diff_files: set[str] = set()
    diff_truncated = False
    if options.include_git and scan.git is not None and not scan.git.error:
        git_status = scan.git.status_text
        if options.include_diff:
            diff_text, diff_truncated = combined_diff(scan.root, include_staged=True)
            if diff_text:
                diff_sections.append(("Cambios en el árbol de trabajo", diff_text))
            diff_files = {
                rel
                for rel, item in scan.git.files.items()
                if not item.untracked and item.code.strip() != "!!"
            }
            if options.redact and diff_text:
                cleaned_diff, diff_findings = scan_text(diff_text, "(git diff)", redact=True)
                if diff_findings:
                    findings.extend(diff_findings)
                    redactions += len(diff_findings)
                    diff_sections = [("Cambios en el árbol de trabajo", cleaned_diff)]

    base_tokens = base_prompt_tokens(task_key, request, options)
    budget = max(2_000, options.budget_tokens)
    context_budget = max(200, budget - base_tokens)

    bundle = pack_context(
        candidates,
        options,
        context_budget,
        repo_map=repo_map,
        git_status=git_status,
        diff_sections=diff_sections,
        diff_files=diff_files,
        secret_findings=findings,
        redactions=redactions,
        excluded=excluded,
        notes=notes,
    )
    if diff_truncated:
        bundle.diff_truncated = True
        bundle.notes.append("El diff se truncó para respetar el presupuesto.")
    if map_truncated:
        bundle.map_truncated = True

    text = compose_prompt(task_key, request, bundle, options)
    tokens = estimate_tokens(text)
    task = resolve_task(task_key)
    warnings: list[str] = []
    if not bundle.files and not bundle.git_diff and not bundle.repo_map:
        warnings.append("No hay contexto incluido: selecciona archivos o activa el diff de Git.")
    if findings:
        if options.redact:
            total = len(findings)
            places = len({finding.path for finding in findings})
            head = (
                "Se redactó 1 posible secreto"
                if total == 1
                else f"Se redactaron {total} posibles secretos"
            )
            place = "1 ubicación" if places == 1 else f"{places} ubicaciones"
            warnings.append(f"{head} en {place}.")
        elif len(findings) == 1:
            warnings.append(
                "Se detectó 1 posible secreto y la redacción está desactivada."
            )
        else:
            warnings.append(
                f"Se detectaron {len(findings)} posibles secretos y la redacción está desactivada."
            )
    sensitive = [entry.rel for entry in selected_entries if entry.sensitive]
    if sensitive:
        warnings.append("Archivos sensibles en el contexto: " + ", ".join(sensitive[:5]))
    if bundle.diff_truncated:
        warnings.append("El diff está truncado; revisa si faltan cambios relevantes.")
    if tokens > budget:
        warnings.append(
            f"El prompt supera el presupuesto ({tokens:,} > {budget:,} tokens).".replace(",", ".")
        )
    if not selected_set:
        warnings.append("No hay archivos seleccionados; el prompt usará solo repositorio y diff.")
    for note in dict.fromkeys(bundle.notes):
        if note not in warnings and (
            "trunc" in note.lower() or "sensible" in note.lower() or "no se pudo" in note.lower()
        ):
            warnings.append(note)

    prompt_hash = hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16]
    return PromptBundle(
        text=text,
        task=task.key,
        task_label=task.label,
        request=request,
        format=options.format,
        options=options,
        context=bundle,
        project_root=scan.root,
        tokens=tokens,
        budget=budget,
        created_at=datetime.now().isoformat(timespec="seconds"),
        warnings=warnings,
        prompt_hash=prompt_hash,
    )


__all__ = ["ContentCache", "RepoMapCache", "generate_prompt"]
