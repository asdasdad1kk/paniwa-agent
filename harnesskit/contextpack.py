"""Budget-aware context packing.

The packer decides what fits, in which order, and records exactly what was left
out. It is deterministic: the same inputs always produce the same prompt.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import (
    ContextBundle,
    ContextFile,
    ExcludedFile,
    FileEntry,
    GenerateOptions,
    SecretFinding,
)
from .tokens import (
    estimate_tokens,
    number_lines,
    token_cost_of_header,
    truncate_text,
)


@dataclass(slots=True)
class PackCandidate:
    entry: FileEntry
    text: str
    tier: str = "seleccionado"
    note: str = ""


_TIER_ORDER = {"cambio": 0, "seleccionado": 1, "relacionado": 2, "extra": 3}


def _truncate_to_lines(text: str, max_tokens: int, note: str) -> tuple[str, bool]:
    if estimate_tokens(text) <= max_tokens:
        return text, False
    lines = text.splitlines()
    kept: list[str] = []
    used = 0
    for line in lines:
        cost = estimate_tokens(line) + 1
        if used + cost > max_tokens - 12:
            break
        kept.append(line)
        used += cost
    omitted = max(0, len(lines) - len(kept))
    result = "\n".join(kept)
    if omitted:
        result += f"\n⋯ [{note}: {omitted} líneas omitidas] ⋯"
    return result, bool(omitted)


def pack_context(
    candidates: list[PackCandidate],
    options: GenerateOptions,
    budget: int,
    *,
    repo_map: str = "",
    git_status: str = "",
    diff_sections: list[tuple[str, str]] | None = None,
    diff_files: set[str] | None = None,
    secret_findings: list[SecretFinding] | None = None,
    redactions: int = 0,
    excluded: list[ExcludedFile] | None = None,
    notes: list[str] | None = None,
) -> ContextBundle:
    """Fit as much high-value context as possible into ``budget`` tokens."""

    remaining = max(200, int(budget))
    bundle = ContextBundle(
        secret_findings=list(secret_findings or []),
        redactions=redactions,
        excluded=list(excluded or []),
        notes=list(notes or []),
    )
    diff_files = diff_files or set()

    # Git status is cheap and orients the model; keep it bounded.
    if options.include_git and git_status.strip():
        status_budget = min(1_500, max(120, remaining // 8))
        text, was_cut = _truncate_to_lines(git_status.strip(), status_budget, "estado truncado")
        bundle.git_status = text
        if was_cut:
            bundle.notes.append("El estado de Git se truncó.")
        remaining -= estimate_tokens(text)

    # Diffs first: they are the densest signal for change-focused work.
    sections = [(label, text) for label, text in (diff_sections or []) if text.strip()]
    if options.include_git and options.include_diff and sections and remaining > 300:
        diff_budget = min(max(500, int(remaining * 0.48)), 45_000)
        diff_used = 0
        rendered: list[str] = []
        for label, text in sections:
            chunk_budget = diff_budget - diff_used
            if chunk_budget < 200:
                bundle.diff_truncated = True
                break
            chunk, was_cut = _truncate_to_lines(text, chunk_budget, "diff truncado")
            rendered.append(f"### {label}\n{chunk}")
            diff_used += estimate_tokens(chunk) + 6
            if was_cut:
                bundle.diff_truncated = True
                break
        if rendered:
            bundle.git_diff = "\n\n".join(rendered)
            remaining -= estimate_tokens(bundle.git_diff)
        if bundle.diff_truncated:
            bundle.notes.append("El diff se truncó para respetar el presupuesto.")

    # Architecture overview, bounded independently.
    if options.include_repo_map and repo_map.strip() and remaining > 400:
        map_budget = min(options.repo_map_tokens, max(300, int(remaining * 0.18)))
        text, was_cut = _truncate_to_lines(repo_map.strip(), map_budget, "mapa truncado")
        bundle.repo_map = text
        bundle.map_truncated = was_cut
        if was_cut:
            bundle.notes.append("El mapa del repositorio se truncó.")
        remaining -= estimate_tokens(text)

    # Order: changed files, explicit selection, related imports. Small files
    # first within a tier so the budget covers as many useful files as possible.
    ordered = sorted(
        candidates,
        key=lambda candidate: (
            _TIER_ORDER.get(candidate.tier, 9),
            estimate_tokens(candidate.text),
            candidate.entry.rel.lower(),
        ),
    )

    for candidate in ordered:
        entry = candidate.entry
        if entry.too_large:
            bundle.excluded.append(
                ExcludedFile(entry.rel, "supera el tamaño máximo configurado")
            )
            continue
        if (
            options.diff_only
            and options.include_git
            and options.include_diff
            and entry.rel in diff_files
        ):
            bundle.excluded.append(ExcludedFile(entry.rel, "cubierto por el diff"))
            continue

        text = candidate.text
        if options.line_numbers:
            text = number_lines(text)
        tokens = estimate_tokens(text)
        header = token_cost_of_header(entry.rel, entry.language)
        if remaining - (tokens + header) >= 120:
            bundle.files.append(
                ContextFile(
                    rel=entry.rel,
                    language=entry.language,
                    text=text,
                    tokens=tokens,
                    mode="completo",
                    status=entry.change_label if entry.is_changed else "",
                    note=candidate.note,
                    tier=candidate.tier,
                )
            )
            remaining -= tokens + header
            continue

        if options.truncate and remaining > 420:
            allowance = max(240, remaining - header - 80)
            truncated, _ = truncate_text(text, allowance)
            if truncated.strip():
                kept_tokens = estimate_tokens(truncated)
                mode = "truncado"
                note = candidate.note
                if options.line_numbers:
                    note = (note + " · " if note else "") + "vista parcial con líneas numeradas"
                bundle.files.append(
                    ContextFile(
                        rel=entry.rel,
                        language=entry.language,
                        text=truncated,
                        tokens=kept_tokens,
                        mode=mode,
                        status=entry.change_label if entry.is_changed else "",
                        note=(note + " · " if note else "") + "vista parcial (cabeza y cola)",
                        tier=candidate.tier,
                    )
                )
                remaining -= kept_tokens + header
                bundle.notes.append(f"{entry.rel} se incluyó truncado.")
                continue

        bundle.excluded.append(ExcludedFile(entry.rel, "no cabe en el presupuesto"))
        if remaining < 200:
            break

    bundle.tokens = (
        estimate_tokens(bundle.git_status)
        + estimate_tokens(bundle.git_diff)
        + estimate_tokens(bundle.repo_map)
        + sum(item.tokens + token_cost_of_header(item.rel, item.language) for item in bundle.files)
    )
    return bundle


__all__ = ["PackCandidate", "pack_context"]
