"""Parse pasted LLM answers into files/diffs and build a safe patch."""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from .scanner import LANGUAGE_BY_EXT, language_for

_FENCE = re.compile(r"(?ms)^(`{3,})[ \t]*([^\n]*)\n(.*?)\n\1[ \t]*$")
_DIFF_START = re.compile(r"(?m)^diff --git ")
_FILE_HEADER = re.compile(
    r"""(?i)^\s*(?:#{1,6}\s*)?(?:file|archivo|path|ruta)\s*[:=]\s*[`*"']*([^\s`*"']+)"""
)
_SEPARATOR_HEADER = re.compile(r"^\s*(?:---+|===+|___+)\s*[`*\"']*([\w./\\-]+\.[\w]+)")
_HEADING_PATH = re.compile(r"^\s*#{1,6}\s+[`*\"']*([\w./\\-]+\.[A-Za-z0-9]+)[`*\"']*\s*$")
_BARE_PATH = re.compile(r"[`*\"']((?:[\w.-]+/)+[\w.-]+\.[A-Za-z0-9]+)[`*\"']")
_INFO_PATH = re.compile(r"(?:^|[\s(])([`*\"']?)([\w./\\-]+\.[A-Za-z0-9]{1,8})\1(?=$|[\s)])")

_LANGUAGE_ALIASES = {
    "py": "Python",
    "python": "Python",
    "js": "JavaScript",
    "javascript": "JavaScript",
    "jsx": "JavaScript (JSX)",
    "ts": "TypeScript",
    "typescript": "TypeScript",
    "tsx": "TypeScript (TSX)",
    "json": "JSON",
    "md": "Markdown",
    "markdown": "Markdown",
    "yml": "YAML",
    "yaml": "YAML",
    "sh": "Shell",
    "bash": "Shell",
    "ps1": "PowerShell",
    "html": "HTML",
    "css": "CSS",
    "sql": "SQL",
    "go": "Go",
    "rs": "Rust",
    "java": "Java",
    "kt": "Kotlin",
    "cs": "C#",
    "cpp": "C++",
    "c": "C",
    "rb": "Ruby",
    "php": "PHP",
    "dart": "Dart",
}

_EXTENSIONS = {
    "Python": ".py",
    "JavaScript": ".js",
    "JavaScript (JSX)": ".jsx",
    "TypeScript": ".ts",
    "TypeScript (TSX)": ".tsx",
    "JSON": ".json",
    "Markdown": ".md",
    "YAML": ".yml",
    "Shell": ".sh",
    "PowerShell": ".ps1",
    "HTML": ".html",
    "CSS": ".css",
    "SQL": ".sql",
    "Go": ".go",
    "Rust": ".rs",
    "Java": ".java",
    "Kotlin": ".kt",
    "C#": ".cs",
    "C++": ".cpp",
    "C": ".c",
    "Ruby": ".rb",
    "PHP": ".php",
    "Dart": ".dart",
}


@dataclass(slots=True)
class ParsedItem:
    path: str
    kind: str
    content: str
    language: str = "Text"
    start_line: int = 0
    error: str = ""

    @property
    def line_count(self) -> int:
        return self.content.count("\n") + 1 if self.content else 0

    @property
    def display_path(self) -> str:
        return self.path or "(fragmento)"


@dataclass(slots=True)
class ParsedResponse:
    items: list[ParsedItem] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    raw: str = ""

    @property
    def file_count(self) -> int:
        return sum(1 for item in self.items if item.kind == "file" and not item.error)

    @property
    def diff_count(self) -> int:
        return sum(1 for item in self.items if item.kind == "diff")

    @property
    def actionable(self) -> bool:
        return any(item.kind in {"file", "diff"} and not item.error for item in self.items)


def _clean_path(raw: str) -> str:
    raw = raw.strip().strip("`*\"'„“”()[]<>")
    raw = raw.replace("\\", "/")
    while raw.startswith("./"):
        raw = raw[2:]
    if raw.startswith("/") or re.match(r"^[A-Za-z]:", raw):
        raise ValueError("la ruta es absoluta")
    pure = PurePosixPath(raw)
    if not pure.parts or ".." in pure.parts:
        raise ValueError("la ruta contiene '..'")
    if len(raw) > 240:
        raise ValueError("la ruta es demasiado larga")
    return str(pure)


def _language_for(fence_info: str, path: str) -> str:
    token = fence_info.strip().split(" ")[0].strip("`{}.").lower() if fence_info.strip() else ""
    if token in _LANGUAGE_ALIASES:
        return _LANGUAGE_ALIASES[token]
    suffix = PurePosixPath(path).suffix.lower()
    if suffix in LANGUAGE_BY_EXT:
        return LANGUAGE_BY_EXT[suffix]
    if path:
        guessed = language_for(Path(path))
        if guessed:
            return guessed
    return "Text"


def _path_from_info(info: str) -> str:
    cleaned = info.strip()
    if not cleaned:
        return ""
    for match in _INFO_PATH.finditer(cleaned):
        candidate = match.group(2)
        if "/" in candidate or "." in candidate:
            if candidate.lower() not in _LANGUAGE_ALIASES:
                return candidate
    return ""


def _path_from_context(prefix: str) -> str:
    lines = [line for line in prefix.splitlines() if line.strip()][-6:]
    for line in reversed(lines):
        for pattern in (_FILE_HEADER, _SEPARATOR_HEADER, _HEADING_PATH):
            match = pattern.match(line)
            if match:
                return match.group(1)
        match = _BARE_PATH.search(line)
        if match and not line.strip().startswith(("//", "#", "*")):
            return match.group(1)
    return ""


def _path_from_diff(body: str) -> str:
    for line in body.splitlines()[:30]:
        if line.startswith("+++ "):
            candidate = line[4:].strip().split("\t")[0]
            if candidate != "/dev/null":
                return candidate[2:] if candidate.startswith(("a/", "b/")) else candidate
        if line.startswith("diff --git "):
            parts = line.split()
            if len(parts) >= 4:
                return parts[3][2:] if parts[3].startswith("b/") else parts[3]
    return ""


def parse_response(text: str) -> ParsedResponse:
    result = ParsedResponse(raw=text)
    if not text.strip():
        result.notes.append("La respuesta está vacía.")
        return result

    blocks = list(_FENCE.finditer(text))
    snippet_index = 0
    for match in blocks:
        info = match.group(2)
        body = match.group(3)
        prefix = text[: match.start()]
        is_diff = body.lstrip().startswith("diff --git") or (
            body.lstrip().startswith("--- ") and "\n+++ " in body[:800]
        )
        raw_path = _path_from_info(info) or _path_from_context(prefix)
        if is_diff:
            raw_path = _path_from_diff(body) or raw_path
            kind = "diff"
        else:
            kind = "file" if raw_path else "snippet"

        path = ""
        error = ""
        if raw_path:
            try:
                path = _clean_path(raw_path)
            except ValueError as exc:
                error = f"Ruta rechazada ({exc}): {raw_path}"
        language = _language_for(info, path)
        if kind == "snippet":
            snippet_index += 1
            extension = _EXTENSIONS.get(language, ".txt")
            path = f"snippet-{snippet_index}{extension}"
        start_line = text.count("\n", 0, match.start()) + 1
        result.items.append(
            ParsedItem(
                path=path,
                kind=kind,
                content=body,
                language=language,
                start_line=start_line,
                error=error,
            )
        )

    if not blocks:
        diff_positions = [m.start() for m in _DIFF_START.finditer(text)]
        if diff_positions:
            for index, position in enumerate(diff_positions):
                end = diff_positions[index + 1] if index + 1 < len(diff_positions) else len(text)
                body = text[position:end].rstrip()
                path = _path_from_diff(body)
                try:
                    cleaned = _clean_path(path) if path else ""
                except ValueError as exc:
                    cleaned = ""
                    result.notes.append(f"Ruta rechazada ({exc}): {path}")
                result.items.append(
                    ParsedItem(
                        path=cleaned,
                        kind="diff",
                        content=body,
                        language="Diff",
                        start_line=text.count("\n", 0, position) + 1,
                    )
                )
        elif "--- " in text[:500] and "+++ " in text[:1200]:
            body = text.strip()
            path = _path_from_diff(body)
            result.items.append(
                ParsedItem(path=path, kind="diff", content=body, language="Diff")
            )
        else:
            result.notes.append(
                "No se encontraron bloques de código delimitados. Pega la respuesta completa "
                "incluyendo los ``` o el diff unificado."
            )
    if not result.items:
        result.notes.append("No hay archivos ni diffs accionables.")
    return result


def _quote_path(path: str, prefix: str) -> str:
    candidate = f"{prefix}{path}" if prefix else path
    if not re.search(r"[\s\"\\]", candidate):
        return candidate
    escaped = candidate.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _ensure_newline(text: str) -> str:
    return text if text.endswith("\n") else text + "\n"


def build_patch(project_root: Path | str, items: list[ParsedItem]) -> tuple[str, list[str]]:
    """Create a unified patch. Nothing is written to the project."""

    root = Path(project_root)
    chunks: list[str] = []
    warnings: list[str] = []
    for item in items:
        if item.error:
            warnings.append(f"Omitido: {item.path or '(sin ruta)'} — {item.error}")
            continue
        if item.kind == "diff":
            chunks.append(_ensure_newline(item.content))
            continue
        if item.kind != "file":
            warnings.append(f"Fragmento sin ruta omitido: {item.path}")
            continue
        try:
            rel = _clean_path(item.path)
        except ValueError as exc:
            warnings.append(f"Ruta rechazada ({exc}): {item.path}")
            continue
        target = root / rel
        try:
            target.relative_to(root)
        except ValueError:
            warnings.append(f"Ruta fuera del proyecto: {rel}")
            continue

        original: str | None = None
        if target.is_file():
            try:
                original = target.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                warnings.append(f"No se pudo leer {rel}: {exc}")
        new_text = _ensure_newline(item.content)
        if original is not None:
            if _ensure_newline(original) == new_text:
                warnings.append(f"{rel} no cambia.")
                continue
            diff = difflib.unified_diff(
                _ensure_newline(original).splitlines(keepends=True),
                new_text.splitlines(keepends=True),
                fromfile=_quote_path(rel, "a/"),
                tofile=_quote_path(rel, "b/"),
                n=3,
            )
            chunks.append("".join(line if line.endswith("\n") else line + "\n" for line in diff))
        else:
            lines = new_text.splitlines()
            # Every line of a new file is an addition and must start with "+".
            body = "".join("+" + line + "\n" for line in lines)
            chunks.append(
                f"--- /dev/null\n+++ {_quote_path(rel, 'b/')}\n"
                f"@@ -0,0 +1,{len(lines)} @@\n{body}"
            )
    patch = "\n".join(chunk.rstrip("\n") for chunk in chunks if chunk.strip())
    if patch:
        patch += "\n"
    if not patch:
        warnings.append("No se pudo construir un patch con las rutas disponibles.")
    return patch, warnings


__all__ = ["ParsedItem", "ParsedResponse", "build_patch", "parse_response"]
