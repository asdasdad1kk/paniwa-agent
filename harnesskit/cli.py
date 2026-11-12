"""Command line interface: interactive by default, scriptable with subcommands."""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import sys
from pathlib import Path

from . import APP_NAME, __version__
from .clipboard import copy_text
from .config import HarnessConfig, load_config, save_config
from .engine import ContentCache, RepoMapCache, generate_prompt
from .gitutils import (
    GitUnavailable,
    check_patch,
    combined_diff,
    git_diff,
    git_info,
    git_status,
)
from .history import SessionStore
from .models import FileEntry, ScanResult
from .promptlib import FORMAT_LABELS, TASK_ORDER, TASKS, resolve_task
from .response import build_patch, parse_response
from .scaffolds import SCAFFOLDS, create_project
from .scanner import ScanOptions, scan_project
from .tokens import estimate_tokens, format_bytes, format_tokens


def _count(count: int, singular: str, plural: str) -> str:
    return f"{count} {singular if count == 1 else plural}"


def _config_scan_options(config: HarnessConfig) -> ScanOptions:
    return ScanOptions(
        max_file_mb=config.max_file_mb,
        max_files=config.max_files,
        extra_ignore=config.extra_ignore_patterns(),
        include_git=True,
    )


def _print_scan_summary(scan: ScanResult) -> None:
    git = scan.git
    branch = f" · rama {git.branch}" if git and git.branch else ""
    print(
        f"{_count(len(scan.files), 'archivo de texto', 'archivos de texto')} · "
        f"{format_bytes(scan.total_bytes)} · escaneo {scan.duration_ms} ms{branch}",
        file=sys.stderr,
    )
    if git and git.files:
        changed = len(git.files)
        noun = _count(changed, "archivo con cambios", "archivos con cambios")
        print(f"Git: {noun} ({git.root})", file=sys.stderr)
    if scan.notes:
        for note in scan.notes[:4]:
            print(f"Nota: {note}", file=sys.stderr)


def _entry_line(entry: FileEntry) -> str:
    status = entry.git_code or "  "
    return (
        f"{status:<2} {entry.rel:<60} {entry.language:<18} "
        f"{format_tokens(entry.estimated_tokens):>8} tok"
    )


def _parse_selection_tokens(
    tokens: list[str], entries: list[FileEntry], current: set[str]
) -> set[str]:
    selected = set(current)
    by_rel = {entry.rel: entry for entry in entries}
    for token in tokens:
        lowered = token.lower()
        if lowered in {"all", "todo", "*"}:
            selected = {entry.rel for entry in entries if not entry.too_large}
            continue
        if lowered in {"none", "nada"}:
            selected.clear()
            continue
        if lowered in {"changed", "cambios", "modificados"}:
            selected.update(
                entry.rel for entry in entries if entry.is_changed and not entry.too_large
            )
            continue
        if lowered in {"source", "codigo", "código"}:
            selected.update(
                entry.rel for entry in entries if entry.is_source and not entry.too_large
            )
            continue
        match = re.fullmatch(r"(\d+)-(\d+)", token)
        if match:
            start, end = int(match.group(1)), int(match.group(2))
            for index in range(start, min(end, len(entries)) + 1):
                if index >= 1 and not entries[index - 1].too_large:
                    selected.add(entries[index - 1].rel)
            continue
        if token.isdigit():
            index = int(token)
            if 1 <= index <= len(entries):
                selected.add(entries[index - 1].rel)
            continue
        add = True
        pattern = token
        if token.startswith(("+", "-")):
            add = token[0] == "+"
            pattern = token[1:]
        if any(char in pattern for char in "*?["):
            matched = {
                entry.rel
                for entry in entries
                if fnmatch.fnmatch(entry.rel.lower(), pattern.lower())
                or fnmatch.fnmatch(entry.name.lower(), pattern.lower())
            }
            if add:
                selected.update(matched)
            else:
                selected.difference_update(matched)
            continue
        if pattern in by_rel:
            if add:
                selected.add(pattern)
            else:
                selected.discard(pattern)
    return selected


def _select_cli(
    scan: ScanResult,
    files_pattern: str | None,
    changed: bool,
    all_files: bool,
    source_only: bool,
) -> set[str]:
    entries = scan.files
    selected: set[str] = set()
    if changed:
        selected.update(entry.rel for entry in entries if entry.is_changed and not entry.too_large)
    if source_only:
        selected.update(entry.rel for entry in entries if entry.is_source and not entry.too_large)
    if all_files:
        selected.update(entry.rel for entry in entries if not entry.too_large)
    if files_pattern:
        tokens = [item for item in re.split(r"[,\s]+", files_pattern) if item]
        selected = _parse_selection_tokens(tokens, entries, selected)
    if not (changed or all_files or source_only or files_pattern):
        changed_entries = [entry for entry in entries if entry.is_changed and not entry.too_large]
        if changed_entries:
            selected = {entry.rel for entry in changed_entries}
    return selected


def _build_options(args: argparse.Namespace, config: HarnessConfig):
    options = config.to_generate_options()
    for attribute in (
        "budget_tokens",
        "format",
        "include_repo_map",
        "repo_map_tokens",
        "include_git",
        "include_diff",
        "include_related",
        "related_depth",
        "line_numbers",
        "redact",
        "diff_only",
        "truncate",
    ):
        value = getattr(args, attribute, None)
        if value is not None:
            setattr(options, attribute, value)
    options.custom_instructions = getattr(args, "instructions", "") or ""
    return options


def _emit_prompt(args: argparse.Namespace, bundle, config: HarnessConfig) -> int:
    print(
        f"{bundle.task_label} · "
        f"{_count(bundle.file_count, 'archivo', 'archivos')} · "
        f"~{format_tokens(bundle.tokens)} / {format_tokens(bundle.budget)} tokens",
        file=sys.stderr,
    )
    if bundle.context.excluded:
        print(
            "Excluidos: " + ", ".join(f"{item.rel} ({item.reason})" for item in bundle.context.excluded[:8]),
            file=sys.stderr,
        )
    for warning in bundle.warnings:
        print(f"Aviso: {warning}", file=sys.stderr)

    if getattr(args, "out", None):
        target = Path(args.out).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(bundle.text, encoding="utf-8")
        print(f"Prompt guardado en {target}", file=sys.stderr)
    if getattr(args, "print", True):
        print(bundle.text)
    if getattr(args, "copy", False):
        try:
            copy_text(bundle.text)
            print("Prompt copiado al portapapeles.", file=sys.stderr)
        except RuntimeError as error:
            print(f"No se pudo copiar: {error}", file=sys.stderr)
            return 1
    if getattr(args, "save", False):
        store = SessionStore(keep=config.sessions_kept)
        path = store.save_bundle(bundle)
        print(f"Sesión guardada en {path}", file=sys.stderr)
    return 0


def command_scan(args: argparse.Namespace) -> int:
    root = Path(args.path).expanduser()
    config = load_config()
    options = _config_scan_options(config)
    options.include_git = not args.no_git
    options.max_file_mb = args.max_file_mb
    try:
        scan = scan_project(root, options)
    except (OSError, NotADirectoryError) as error:
        print(f"No se pudo escanear: {error}", file=sys.stderr)
        return 2
    if args.json:
        payload = {
            "root": str(scan.root),
            "files": [
                {
                    "path": entry.rel,
                    "size": entry.size,
                    "language": entry.language,
                    "tokens": entry.estimated_tokens,
                    "git": entry.git_code,
                    "sensitive": entry.sensitive,
                    "too_large": entry.too_large,
                }
                for entry in scan.files[: args.limit]
            ],
            "count": len(scan.files),
            "git": scan.git.to_dict() if scan.git else None,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    _print_scan_summary(scan)
    for entry in scan.files[: args.limit]:
        print(_entry_line(entry))
    if len(scan.files) > args.limit:
        hidden = _count(len(scan.files) - args.limit, "archivo más", "archivos más")
        print(f"… {hidden} (usa --limit).")
    return 0


def command_prompt(args: argparse.Namespace) -> int:
    root = Path(args.path).expanduser()
    config = load_config()
    scan_options = _config_scan_options(config)
    scan_options.include_git = True
    scan_options.max_file_mb = args.max_file_mb
    try:
        scan = scan_project(root, scan_options)
    except (OSError, NotADirectoryError) as error:
        print(f"No se pudo escanear: {error}", file=sys.stderr)
        return 2
    _print_scan_summary(scan)
    selected = _select_cli(scan, args.files, args.changed, args.all, args.source)
    options = _build_options(args, config)
    try:
        bundle = generate_prompt(
            scan,
            args.task,
            args.request or "",
            options,
            selected,
            content_cache=ContentCache(),
            map_cache=RepoMapCache(),
        )
    except Exception as error:  # pragma: no cover - user-facing safety net
        print(f"No se pudo generar el prompt: {error}", file=sys.stderr)
        return 2
    return _emit_prompt(args, bundle, config)


def command_git(args: argparse.Namespace) -> int:
    root = Path(args.path).expanduser()
    try:
        if args.diff:
            text, truncated = git_diff(root, staged=args.staged)
            if truncated:
                print("Aviso: diff truncado.", file=sys.stderr)
            print(text.rstrip() or "(sin cambios)")
            return 0
        info = git_info(root)
        if info is None:
            print("La carpeta no es un repositorio Git.", file=sys.stderr)
            return 2
        if info.error:
            print(info.error, file=sys.stderr)
            return 2
        if args.json:
            print(json.dumps(info.to_dict(), ensure_ascii=False, indent=2))
        else:
            print(info.status_text or "(sin cambios)")
        return 0
    except GitUnavailable as error:
        print(str(error), file=sys.stderr)
        return 2


def command_scaffold(args: argparse.Namespace) -> int:
    if args.list or not args.key:
        print("Plantillas disponibles:\n")
        for key, scaffold in SCAFFOLDS.items():
            tags = ", ".join(scaffold.tags)
            print(f"  {key}  {scaffold.name:<24} {scaffold.description}")
            print(f"      {tags}")
        print("\nUso: python -m harnesskit scaffold 1 C:\\ruta\\proyecto --zip")
        return 0
    if not args.destination:
        print("Indica una ruta de destino.", file=sys.stderr)
        return 2
    try:
        archive = create_project(args.key, Path(args.destination).expanduser(), args.zip)
    except (OSError, ValueError) as error:
        print(f"No se pudo crear el proyecto: {error}", file=sys.stderr)
        return 2
    scaffold = SCAFFOLDS[args.key]
    print(f"Proyecto {scaffold.name} creado en {Path(args.destination).expanduser()}")
    if archive:
        print(f"ZIP: {archive}")
    if scaffold.next_steps:
        print("\nSiguientes pasos:")
        for step in scaffold.next_steps:
            print(f"  {step}")
    return 0


def command_check(args: argparse.Namespace) -> int:
    patch_path = Path(args.patch).expanduser()
    try:
        text = patch_path.read_text(encoding="utf-8")
    except OSError as error:
        print(f"No se pudo leer el patch: {error}", file=sys.stderr)
        return 2
    ok, output = check_patch(Path(args.path).expanduser(), text)
    print(output)
    return 0 if ok else 1


def command_parse(args: argparse.Namespace) -> int:
    if args.input == "-":
        text = sys.stdin.read()
    else:
        try:
            text = Path(args.input).expanduser().read_text(encoding="utf-8")
        except OSError as error:
            print(f"No se pudo leer la respuesta: {error}", file=sys.stderr)
            return 2
    parsed = parse_response(text)
    if args.json:
        print(
            json.dumps(
                {
                    "items": [
                        {
                            "path": item.path,
                            "kind": item.kind,
                            "language": item.language,
                            "lines": item.line_count,
                            "error": item.error,
                        }
                        for item in parsed.items
                    ],
                    "notes": parsed.notes,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(
            _count(len(parsed.items), "bloque detectado", "bloques detectados"),
            file=sys.stderr,
        )
        for item in parsed.items:
            mark = "!" if item.error else "·"
            lines = _count(item.line_count, "línea", "líneas")
            print(f" {mark} {item.path:<50} {item.kind:<8} {lines:>11}")
        for note in parsed.notes:
            print(f"Nota: {note}", file=sys.stderr)
    if args.patch_out:
        patch, warnings = build_patch(Path(args.path).expanduser(), parsed.items)
        if not patch:
            for warning in warnings:
                print(f"Aviso: {warning}", file=sys.stderr)
            return 1
        target = Path(args.patch_out).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(patch, encoding="utf-8")
        print(f"Patch guardado en {target}", file=sys.stderr)
        if args.check:
            ok, output = check_patch(Path(args.path).expanduser(), patch)
            print(output)
            return 0 if ok else 1
    return 0


def command_history(args: argparse.Namespace) -> int:
    store = SessionStore(keep=load_config().sessions_kept)
    if args.clear:
        removed = store.clear()
        result = "Eliminada 1 sesión." if removed == 1 else f"Eliminadas {removed} sesiones."
        print(result, file=sys.stderr)
        return 0
    summaries = store.list(limit=args.limit)
    if not summaries:
        print("No hay sesiones guardadas.")
        return 0
    for item in summaries:
        files = "archivo" if item.file_count == 1 else "archivos"
        print(
            f"{item.created_at}  {item.task_label:<26} {item.file_count:>3} {files:<8} "
            f"{format_tokens(item.tokens):>8} tok  {item.project_root}"
        )
    if args.export:
        target = Path(args.export).expanduser()
        target.mkdir(parents=True, exist_ok=True)
        for summary in summaries:
            record = store.load(summary.path)
            filename = target / f"{record.id}.md"
            filename.write_text(record.prompt, encoding="utf-8")
        result = (
            "Exportada 1 sesión"
            if len(summaries) == 1
            else f"Exportadas {len(summaries)} sesiones"
        )
        print(f"{result} a {target}", file=sys.stderr)
    return 0


def _prompt_multiline(label: str) -> str:
    print(label)
    print("(escribe la tarea; deja una línea vacía para terminar)")
    lines: list[str] = []
    while True:
        try:
            line = input("  ")
        except EOFError:
            break
        if not line.strip():
            break
        lines.append(line)
    return "\n".join(lines).strip()


def _interactive_options(config: HarnessConfig) -> tuple[object, str, str]:
    options = config.to_generate_options()
    print("\nOpciones actuales:")
    print(
        f"  presupuesto {format_tokens(options.budget_tokens)} · formato "
        f"{FORMAT_LABELS.get(options.format, options.format)} · "
        f"diff {'sí' if options.include_diff else 'no'} · "
        f"mapa {'sí' if options.include_repo_map else 'no'} · "
        f"relacionados {'sí' if options.include_related else 'no'} · "
        f"redactar {'sí' if options.redact else 'no'}"
    )
    if input("¿Ajustar opciones? (s/N): ").strip().lower() not in {"s", "si", "sí", "y"}:
        return options, "", ""

    def ask_bool(label: str, current: bool) -> bool:
        answer = input(f"{label} [{'S' if current else 'n'}]: ").strip().lower()
        if not answer:
            return current
        return answer in {"s", "si", "sí", "y", "yes"}

    budget_text = input(f"Presupuesto de tokens [{options.budget_tokens}]: ").strip()
    if budget_text.isdigit():
        options.budget_tokens = max(2_000, int(budget_text))
    format_text = input("Formato [markdown/xml/plain/compact]: ").strip().lower()
    if format_text in FORMAT_LABELS:
        options.format = format_text
    options.include_diff = ask_bool("¿Incluir diff de Git?", options.include_diff)
    options.diff_only = ask_bool("¿Omitir archivos completos cubiertos por el diff?", options.diff_only)
    options.include_repo_map = ask_bool("¿Incluir mapa de símbolos?", options.include_repo_map)
    options.include_related = ask_bool("¿Incluir imports relacionados?", options.include_related)
    options.line_numbers = ask_bool("¿Numerar líneas?", options.line_numbers)
    options.redact = ask_bool("¿Redactar secretos?", options.redact)
    instructions = _prompt_multiline("Instrucciones adicionales (opcional):")
    return options, instructions, ""


def _interactive_file_selection(scan: ScanResult, config: HarnessConfig) -> set[str]:
    entries = scan.files
    if not entries:
        print("No se encontraron archivos de texto.")
        return set()
    selected = {entry.rel for entry in entries if entry.is_changed and not entry.too_large}
    print("\nArchivos (primeros 120; los cambios se preseleccionan):")
    for index, entry in enumerate(entries[:120], start=1):
        marker = "*" if entry.rel in selected else " "
        print(f" {marker}{index:>3}) {_entry_line(entry)}")
    if len(entries) > 120:
        print(f" … {len(entries) - 120} más; usa patrones (por ejemplo '*.py').")
    print(
        "\nSintaxis: 1-5,12  ·  cambios  ·  todo  ·  nada  ·  *.py  ·  +src/*  ·  -tests/*"
    )
    while True:
        total = sum(
            entry.estimated_tokens for entry in entries if entry.rel in selected and not entry.too_large
        )
        noun = _count(len(selected), "archivo", "archivos")
        print(f"Seleccionados: {noun} · ~{format_tokens(total)} tokens")
        answer = input("Selección (Enter para continuar): ").strip()
        if not answer:
            return selected
        tokens = [item for item in re.split(r"[,\s]+", answer) if item]
        selected = _parse_selection_tokens(tokens, entries, selected)


def interactive(initial_project: str | None = None) -> int:
    config = load_config()
    print(f"{APP_NAME} {__version__} — contexto local, sin proveedor de IA\n")
    project_text = initial_project or ""
    if not project_text and config.recent_projects:
        print("Proyectos recientes:")
        for index, path in enumerate(config.recent_projects[:5], start=1):
            print(f"  {index}) {path}")
    if not project_text:
        project_text = input("Ruta del proyecto (número o ruta): ").strip()
        if project_text.isdigit() and config.recent_projects:
            position = int(project_text)
            if 1 <= position <= len(config.recent_projects):
                project_text = config.recent_projects[position - 1]
    if not project_text:
        print("No se indicó ningún proyecto.", file=sys.stderr)
        return 2
    root = Path(project_text).expanduser()
    try:
        scan = scan_project(root, _config_scan_options(config))
    except (OSError, NotADirectoryError) as error:
        print(f"No se pudo abrir el proyecto: {error}", file=sys.stderr)
        return 2
    _print_scan_summary(scan)
    config.record_recent(scan.root)
    save_config(config)

    print("\nTareas:")
    for index, task in enumerate(TASKS, start=1):
        print(f"  {index:>2}) {task.label:<28} {task.short}")
    task_answer = input("\nElige una tarea [1]: ").strip() or "1"
    if task_answer.isdigit() and 1 <= int(task_answer) <= len(TASKS):
        task_key = TASKS[int(task_answer) - 1].key
    else:
        task_key = resolve_task(task_answer).key
    request = _prompt_multiline("\nDescribe el trabajo:")
    if not request:
        print("La descripción no puede estar vacía.", file=sys.stderr)
        return 2

    selected = _interactive_file_selection(scan, config)
    options, instructions, _ = _interactive_options(config)
    options.custom_instructions = instructions
    cache = ContentCache()
    maps = RepoMapCache()
    store = SessionStore(keep=config.sessions_kept)

    while True:
        bundle = generate_prompt(
            scan,
            task_key,
            request,
            options,
            selected,
            content_cache=cache,
            map_cache=maps,
        )
        print("\n" + "=" * 78)
        print("PROMPT PARA REVISAR Y PEGAR EN TU CHAT")
        print("=" * 78)
        print(bundle.text)
        print("=" * 78)
        print(
            f"{_count(bundle.file_count, 'archivo', 'archivos')} · "
            f"~{format_tokens(bundle.tokens)} / "
            f"{format_tokens(bundle.budget)} tokens"
        )
        for warning in bundle.warnings:
            print(f"Aviso: {warning}")
        if bundle.context.excluded:
            print("Excluidos:")
            for item in bundle.context.excluded[:10]:
                print(f"  - {item.rel}: {item.reason}")

        if input("\n¿Copiar al portapapeles? (S/n): ").strip().lower() in {"", "s", "si", "sí"}:
            try:
                copy_text(bundle.text)
                print("Copiado. Pégalo tú mismo en el chat.")
                path = store.save_bundle(bundle)
                print(f"Sesión guardada en {path}")
            except RuntimeError as error:
                print(f"No se pudo copiar: {error}")
        out = input("Guardar prompt en archivo (Enter para omitir): ").strip().strip('"')
        if out:
            target = Path(out).expanduser()
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(bundle.text, encoding="utf-8")
            print(f"Guardado en {target}")
        if input("\n¿Otra ronda con el mismo proyecto? (s/N): ").strip().lower() not in {
            "s",
            "si",
            "sí",
            "y",
        }:
            return 0
        request = _prompt_multiline("Nueva descripción:") or request
        selected = _interactive_file_selection(scan, config)
        options, instructions, _ = _interactive_options(config)
        options.custom_instructions = instructions


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="harnesskit",
        description=(
            "Harness Studio: prepara contexto y prompts de alta señal para cualquier chat de "
            "LLM. No llama a ningún proveedor de IA."
        ),
    )
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    subparsers = parser.add_subparsers(dest="command")

    gui = subparsers.add_parser("gui", help="Abrir la interfaz PySide6 + Fluent")
    gui.add_argument("project", nargs="?", help="Proyecto a abrir al iniciar")
    gui.set_defaults(func=_run_gui)

    scan = subparsers.add_parser("scan", help="Escanear un proyecto y listar archivos")
    scan.add_argument("path", nargs="?", default=".")
    scan.add_argument("--json", action="store_true", help="Salida JSON")
    scan.add_argument("--limit", type=int, default=80)
    scan.add_argument("--no-git", action="store_true")
    scan.add_argument("--max-file-mb", type=float, default=load_config().max_file_mb)
    scan.set_defaults(func=command_scan)

    prompt = subparsers.add_parser("prompt", help="Generar un prompt listo para pegar")
    prompt.add_argument("path", nargs="?", default=".")
    prompt.add_argument("--task", default="feature", help=f"Tarea: {', '.join(TASK_ORDER)}")
    prompt.add_argument("--request", "-r", default="", help="Descripción del trabajo")
    prompt.add_argument("--instructions", default="", help="Instrucciones adicionales")
    prompt.add_argument("--files", "-f", help="Patrones de archivos (coma/espacio)")
    prompt.add_argument("--changed", action="store_true", help="Incluir archivos modificados")
    prompt.add_argument("--all", action="store_true", help="Incluir todos los archivos de texto")
    prompt.add_argument("--source", action="store_true", help="Incluir solo código fuente")
    prompt.add_argument("--budget", dest="budget_tokens", type=int)
    prompt.add_argument("--format", dest="format", choices=sorted(FORMAT_LABELS))
    prompt.add_argument("--repo-map-tokens", dest="repo_map_tokens", type=int)
    prompt.add_argument("--related-depth", dest="related_depth", type=int, choices=(1, 2))
    prompt.add_argument("--diff", dest="include_diff", action=argparse.BooleanOptionalAction)
    prompt.add_argument("--repo-map", dest="include_repo_map", action=argparse.BooleanOptionalAction)
    prompt.add_argument("--related", dest="include_related", action=argparse.BooleanOptionalAction)
    prompt.add_argument("--line-numbers", dest="line_numbers", action=argparse.BooleanOptionalAction)
    prompt.add_argument("--redact", dest="redact", action=argparse.BooleanOptionalAction)
    prompt.add_argument("--diff-only", dest="diff_only", action=argparse.BooleanOptionalAction)
    prompt.add_argument("--truncate", dest="truncate", action=argparse.BooleanOptionalAction)
    prompt.add_argument("--out", "-o", help="Guardar el prompt en un archivo")
    prompt.add_argument("--copy", action="store_true", help="Copiar al portapapeles")
    prompt.add_argument("--save", action="store_true", help="Guardar en el historial local")
    prompt.add_argument("--print", dest="print", action=argparse.BooleanOptionalAction, default=True)
    prompt.add_argument("--max-file-mb", type=float, default=load_config().max_file_mb)
    prompt.set_defaults(func=command_prompt)

    git = subparsers.add_parser("git", help="Mostrar estado o diff de Git")
    git.add_argument("path", nargs="?", default=".")
    git.add_argument("--diff", action="store_true")
    git.add_argument("--staged", action="store_true")
    git.add_argument("--json", action="store_true")
    git.set_defaults(func=command_git)

    scaffold = subparsers.add_parser("scaffold", help="Crear un proyecto desde plantilla")
    scaffold.add_argument("key", nargs="?", help="Clave de plantilla")
    scaffold.add_argument("destination", nargs="?", help="Ruta nueva")
    scaffold.add_argument("--list", action="store_true")
    scaffold.add_argument("--zip", action="store_true")
    scaffold.set_defaults(func=command_scaffold)

    check = subparsers.add_parser("check", help="Verificar un patch con git apply --check")
    check.add_argument("patch")
    check.add_argument("path", nargs="?", default=".")
    check.set_defaults(func=command_check)

    parse = subparsers.add_parser("parse", help="Extraer archivos/diffs de una respuesta")
    parse.add_argument("input", help="Archivo con la respuesta o - para stdin")
    parse.add_argument("path", nargs="?", default=".", help="Proyecto para construir el patch")
    parse.add_argument("--json", action="store_true")
    parse.add_argument("--patch-out", help="Guardar patch unificado")
    parse.add_argument("--check", action="store_true")
    parse.set_defaults(func=command_parse)

    history = subparsers.add_parser("history", help="Listar/exportar el historial local")
    history.add_argument("--limit", type=int, default=40)
    history.add_argument("--export", help="Carpeta de destino para exportar Markdown")
    history.add_argument("--clear", action="store_true")
    history.set_defaults(func=command_history)

    return parser


def _run_gui(args: argparse.Namespace) -> int:
    from .ui.app import run_gui

    return run_gui(args.project)


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments:
        if not sys.stdin.isatty():
            print("Usa --help para ver los comandos disponibles.", file=sys.stderr)
            return 2
        return interactive()
    if arguments[0] == "interactive":
        return interactive(arguments[1] if len(arguments) > 1 else None)
    parser = build_parser()
    args = parser.parse_args(arguments)
    if not getattr(args, "command", None):
        parser.print_help()
        return 0
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        print("\nCancelado.", file=sys.stderr)
        return 130
    except BrokenPipeError:
        return 0


__all__ = ["build_parser", "interactive", "main"]
