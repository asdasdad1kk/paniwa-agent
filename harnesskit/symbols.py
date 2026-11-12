"""Deterministic repository maps and import-based context discovery.

No model is involved: Python files use ``ast`` and other languages use careful
regexes. The result is a compact outline that gives the assistant architectural
orientation without burning budget on full file contents.
"""

from __future__ import annotations

import ast
import json
import posixpath
import re
from pathlib import Path, PurePosixPath
from typing import Callable, Iterable

from .models import FileEntry
from .tokens import clip, estimate_tokens


class _SymbolCollector(ast.NodeVisitor):
    def __init__(self, source: str, max_symbols: int) -> None:
        self.source = source
        self.max_symbols = max_symbols
        self.symbols: list[str] = []

    def _add(self, text: str) -> None:
        if len(self.symbols) < self.max_symbols:
            self.symbols.append(text)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._add(_format_python_function(node, decorators=True))

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._add("async " + _format_python_function(node, decorators=True))

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        bases = ", ".join(_safe_unparse(base) for base in node.bases)
        methods: list[str] = []
        for child in node.body:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not child.name.startswith("_"):
                    methods.append(child.name)
        suffix = f" ({', '.join(methods[:6])})" if methods else ""
        headline = f"class {node.name}"
        if bases:
            headline += f"({clip(bases, 44)})"
        self._add(f"{headline} — L{node.lineno}{suffix}")

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id.isupper():
                self._add(f"{target.id} = … — L{node.lineno}")
        self.generic_visit(node)

    def generic_visit(self, node: ast.AST) -> None:
        # Only top-level definitions matter for a repo map.
        if isinstance(node, ast.Module):
            for child in node.body:
                self.visit(child)
        else:
            super().generic_visit(node)


def _safe_unparse(node: ast.AST | None) -> str:
    if node is None:
        return ""
    try:
        return ast.unparse(node)
    except Exception:  # pragma: no cover - very defensive
        return "…"


def _format_python_function(node: ast.FunctionDef | ast.AsyncFunctionDef, decorators: bool = False) -> str:
    arguments = node.args
    names: list[str] = []
    positional = list(arguments.posonlyargs) + list(arguments.args)
    defaults = [None] * (len(positional) - len(arguments.defaults)) + list(arguments.defaults)
    for arg, default in zip(positional, defaults):
        label = arg.arg
        if arg.annotation is not None:
            annotation = clip(_safe_unparse(arg.annotation), 24)
            label += f": {annotation}"
        if default is not None:
            label += "=…"
        names.append(label)
    if arguments.vararg is not None:
        names.append("*" + arguments.vararg.arg)
    elif arguments.kwonlyargs:
        names.append("*")
    for arg, default in zip(arguments.kwonlyargs, arguments.kw_defaults):
        label = arg.arg
        if default is not None:
            label += "=…"
        names.append(label)
    if arguments.kwarg is not None:
        names.append("**" + arguments.kwarg.arg)
    signature = f"{node.name}({', '.join(names)})"
    if node.returns is not None:
        signature += f" -> {clip(_safe_unparse(node.returns), 28)}"
    prefix = ""
    if decorators and node.decorator_list:
        decorator = _safe_unparse(node.decorator_list[0])
        prefix = f"@{clip(decorator, 36)} "
    return f"{prefix}def {signature} — L{node.lineno}"


def python_symbols(text: str, max_symbols: int = 60) -> list[str]:
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return []
    collector = _SymbolCollector(text, max_symbols)
    collector.visit(tree)
    return collector.symbols


_JS_PATTERNS: list[tuple[re.Pattern[str], Callable[[re.Match[str]], str]]] = [
    (
        re.compile(
            r"^\s*(?:export\s+(?:default\s+)?)?(?:abstract\s+)?class\s+(\w+)"
            r"(?:\s+extends\s+([\w.]+))?",
            re.MULTILINE,
        ),
        lambda m: f"class {m.group(1)}" + (f" extends {m.group(2)}" if m.group(2) else ""),
    ),
    (
        re.compile(
            r"^\s*(?:export\s+(?:default\s+)?)?(?:async\s+)?function\s+(\w+)\s*\(([^)]*)\)",
            re.MULTILINE,
        ),
        lambda m: f"function {m.group(1)}({clip(m.group(2), 40)})",
    ),
    (
        re.compile(
            r"^\s*(?:export\s+)?const\s+([A-Za-z_$][\w$]*)\s*(?::\s*[^=]+)?=\s*"
            r"(?:async\s*)?(?:\(([^)]*)\)|([A-Za-z_$][\w$]*))\s*=>",
            re.MULTILINE,
        ),
        lambda m: f"const {m.group(1)} = ({clip(m.group(2) or m.group(3) or '', 40)}) =>",
    ),
    (
        re.compile(r"^\s*(?:export\s+)?(?:declare\s+)?(interface|type|enum)\s+(\w+)", re.MULTILINE),
        lambda m: f"{m.group(1)} {m.group(2)}",
    ),
]

_GENERIC_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "Go": [
        re.compile(r"^\s*func\s+(?:\([^)]*\)\s*)?(\w+)\s*\(([^)]*)\)", re.MULTILINE),
        re.compile(r"^\s*type\s+(\w+)\s+(struct|interface)", re.MULTILINE),
    ],
    "Rust": [
        re.compile(r"^\s*(?:pub\s+)?(?:async\s+)?fn\s+(\w+)", re.MULTILINE),
        re.compile(r"^\s*(?:pub\s+)?(?:struct|enum|trait|type)\s+(\w+)", re.MULTILINE),
    ],
    "SQL": [
        re.compile(
            r"^\s*CREATE\s+(?:OR\s+REPLACE\s+)?(?:TABLE|VIEW|INDEX|FUNCTION|PROCEDURE)\s+([\w.\"]+)",
            re.IGNORECASE | re.MULTILINE,
        )
    ],
}

_GENERIC_KEYWORD = re.compile(
    r"^\s*(?:export\s+)?(?:public\s+|private\s+|protected\s+|internal\s+|static\s+|final\s+|"
    r"abstract\s+|async\s+|override\s+|open\s+|sealed\s+|data\s+)*"
    r"(?:class|interface|enum|record|struct|trait|fn|func|function|def)\s+([A-Za-z_]\w*)",
    re.MULTILINE,
)


def _line_of(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def regex_symbols(text: str, language: str, max_symbols: int = 60) -> list[str]:
    symbols: list[str] = []
    if language.startswith(("JavaScript", "TypeScript", "Vue", "Svelte", "JSX")):
        for pattern, formatter in _JS_PATTERNS:
            for match in pattern.finditer(text):
                symbols.append(f"{formatter(match)} — L{_line_of(text, match.start())}")
                if len(symbols) >= max_symbols:
                    return symbols
        return symbols
    if language == "Markdown":
        for match in re.finditer(r"^(#{1,3})\s+(.+?)\s*$", text, re.MULTILINE):
            symbols.append(f"{match.group(1)} {clip(match.group(2), 70)}")
            if len(symbols) >= max_symbols:
                break
        return symbols
    if language == "JSON":
        try:
            data = json.loads(text)
        except ValueError:
            return []
        if isinstance(data, dict):
            return [f'"{key}"' for key in list(data.keys())[:max_symbols]]
        return []
    if language in {"CSS", "SCSS", "Sass", "Less"}:
        for match in re.finditer(r"^([.#][\w-]+(?:[\s>+~][.#]?[\w-]+)*)\s*\{", text, re.MULTILINE):
            symbols.append(f"{match.group(1)} — L{_line_of(text, match.start())}")
            if len(symbols) >= max_symbols:
                break
        return symbols
    patterns = _GENERIC_PATTERNS.get(language, [])
    seen: set[str] = set()
    for pattern in patterns:
        for match in pattern.finditer(text):
            group = next((g for g in match.groups() if g), "")
            line = _line_of(text, match.start())
            signature = f"{match.group(0).strip().splitlines()[0][:80]} — L{line}"
            if signature not in seen:
                seen.add(signature)
                symbols.append(signature)
            if len(symbols) >= max_symbols:
                return symbols
    if not symbols and language not in {"Text", "Markdown", "CSV", "YAML", "TOML", "INI"}:
        for match in _GENERIC_KEYWORD.finditer(text):
            symbols.append(f"{match.group(0).strip()[:80]} — L{_line_of(text, match.start())}")
            if len(symbols) >= max_symbols:
                break
    return symbols


def file_symbols(rel: str, language: str, text: str, max_symbols: int = 30) -> list[str]:
    if language == "Python" or rel.endswith((".py", ".pyi")):
        return python_symbols(text, max_symbols)
    return regex_symbols(text, language, max_symbols)


def build_repo_map(
    entries: Iterable[FileEntry],
    selected: set[str],
    max_tokens: int = 4_000,
    max_files: int = 500,
    max_file_bytes: int = 256_000,
) -> tuple[str, bool]:
    """Build a compact tree with top-level symbols, bounded by ``max_tokens``."""

    candidates: list[tuple[int, int, FileEntry]] = []
    for entry in entries:
        if entry.too_large or entry.sensitive:
            continue
        if entry.language in {"CSV", "JSON", "Text", "Properties", "Dotenv"} and not entry.rel.endswith(
            ("package.json", "tsconfig.json", "pyproject.toml")
        ):
            continue
        priority = 0 if entry.rel in selected else (1 if entry.is_changed else 2)
        candidates.append((priority, entry.size, entry))
    candidates.sort(key=lambda item: (item[0], item[1], item[2].rel.lower()))
    candidates = candidates[:max_files]

    included: dict[str, list[str]] = {}
    used = 0
    truncated = len(candidates) < sum(1 for entry in entries if not entry.too_large)
    for _priority, _size, entry in candidates:
        try:
            text = entry.path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if len(text) > max_file_bytes:
            text = text[:max_file_bytes]
        symbols = file_symbols(entry.rel, entry.language, text, max_symbols=12)
        line = entry.rel
        if symbols:
            line += "  — " + clip(" · ".join(symbols), 160)
        cost = estimate_tokens(line) + 4
        if used + cost > max_tokens:
            truncated = True
            break
        included[entry.rel] = symbols
        used += cost

    if not included:
        return "", truncated

    tree: dict[str, object] = {}
    for rel in sorted(included, key=str.lower):
        parts = PurePosixPath(rel).parts
        node = tree
        for part in parts[:-1]:
            child = node.get(part)
            if not isinstance(child, dict):
                child = {}
                node[part] = child
            node = child
        node[parts[-1]] = included[rel]

    lines: list[str] = []

    def render(node: dict[str, object], depth: int) -> None:
        directories = [(name, value) for name, value in node.items() if isinstance(value, dict)]
        files = [(name, value) for name, value in node.items() if not isinstance(value, dict)]
        for name, value in sorted(directories, key=lambda pair: pair[0].lower()):
            lines.append("  " * depth + name + "/")
            render(value, depth + 1)  # type: ignore[arg-type]
        for name, symbols in sorted(files, key=lambda pair: pair[0].lower()):
            suffix = ""
            if symbols:
                suffix = "  — " + clip(" · ".join(symbols), 150)  # type: ignore[arg-type]
            lines.append("  " * depth + name + suffix)

    render(tree, 0)
    if truncated:
        lines.append("⋯ mapa parcial: hay archivos omitidos por presupuesto ⋯")
    return "\n".join(lines), truncated


_JS_IMPORT = re.compile(
    r"""(?:import\s+(?:[^'"]*?\s+from\s+)?|export\s+[^'"]*?\s+from\s+|require\s*\(\s*|@import\s+)['"]([^'"]+)['"]"""
)
_JS_EXTENSIONS = [".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts", ".vue", ".svelte", ".css", ".scss"]


def _python_imports(rel: str, text: str, known: set[str]) -> list[str]:
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return []
    found: list[str] = []
    package_parts = PurePosixPath(rel).parent.parts

    def resolve(base_parts: tuple[str, ...], module: str) -> None:
        module_path = module.replace(".", "/")
        for candidate in (
            posixpath.join(*base_parts, module_path + ".py") if base_parts else module_path + ".py",
            posixpath.join(*base_parts, module_path, "__init__.py") if base_parts else module_path + "/__init__.py",
        ):
            if candidate in known:
                found.append(candidate)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                resolve(tuple(), alias.name)
        elif isinstance(node, ast.ImportFrom):
            level = node.level or 0
            module = node.module or ""
            base = list(package_parts)
            if level > 0:
                for _ in range(max(0, level - 1)):
                    if base:
                        base.pop()
            resolve(tuple(base), module)
            for alias in node.names:
                if alias.name != "*":
                    resolve(tuple(base), f"{module}.{alias.name}" if module else alias.name)
    return found


def _js_imports(rel: str, text: str, known: set[str]) -> list[str]:
    directory = PurePosixPath(rel).parent
    found: list[str] = []
    for match in _JS_IMPORT.finditer(text):
        specifier = match.group(1)
        if not specifier.startswith("."):
            continue
        normalised = posixpath.normpath(posixpath.join(str(directory), specifier)) if str(directory) != "." else posixpath.normpath(specifier)
        if normalised.startswith(".."):
            continue
        candidates = [normalised] + [normalised + ext for ext in _JS_EXTENSIONS]
        candidates += [normalised + "/index" + ext for ext in _JS_EXTENSIONS]
        for candidate in candidates:
            if candidate in known:
                found.append(candidate)
                break
    return found


def extract_imports(rel: str, text: str, known: set[str]) -> list[str]:
    suffix = PurePosixPath(rel).suffix.lower()
    if suffix in {".py", ".pyi"}:
        return _python_imports(rel, text, known)
    if suffix in {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".mts", ".cts", ".vue", ".svelte"}:
        return _js_imports(rel, text, known)
    return []


def resolve_related(
    seed_contents: dict[str, str],
    known: set[str],
    reader: Callable[[str], str | None] | None = None,
    depth: int = 1,
    max_files: int = 25,
) -> list[str]:
    """BFS over local imports starting from the selected files."""

    visited = set(seed_contents)
    discovered: list[str] = []
    frontier = dict(seed_contents)
    for _level in range(max(1, depth)):
        next_frontier: dict[str, str] = {}
        for rel, text in frontier.items():
            for target in extract_imports(rel, text, known):
                if target in visited:
                    continue
                visited.add(target)
                discovered.append(target)
                if len(discovered) >= max_files:
                    return discovered
                if reader is not None:
                    content = reader(target)
                    if content is not None:
                        next_frontier[target] = content
        frontier = next_frontier
        if not frontier:
            break
    return discovered


__all__ = [
    "build_repo_map",
    "extract_imports",
    "file_symbols",
    "python_symbols",
    "regex_symbols",
    "resolve_related",
]
