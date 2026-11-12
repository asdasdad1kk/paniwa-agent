"""Fast, dependency-free token estimation and budget-aware truncation.

The estimator is intentionally conservative (slightly over-counts) so a prompt
that fits here fits in real tokenizers with a small safety margin.
"""

from __future__ import annotations

import re

_TOKEN_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|\d+(?:[._]\d+)*|[^\sA-Za-z0-9_]", re.UNICODE)
_CJK_PATTERN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]")


def _word_cost(token: str) -> int:
    length = len(token)
    if length <= 6:
        return 1
    # Long identifiers usually split into several BPE pieces.
    return (length + 4) // 5


def estimate_tokens(text: str) -> int:
    """Approximate the token count of ``text`` for modern chat tokenizers."""

    if not text:
        return 0
    total = 0
    for match in _TOKEN_PATTERN.finditer(text):
        token = match.group(0)
        if token[0].isalnum() or token[0] == "_":
            # CJK characters are usually one token each; strip them first so a
            # mixed identifier is not miscounted by slicing off a prefix.
            cjk = len(_CJK_PATTERN.findall(token))
            rest = _CJK_PATTERN.sub("", token)
            total += cjk + (_word_cost(rest) if rest else 0)
        else:
            total += 1
    total += text.count("\n")
    return max(1, int(total * 1.07))


def token_cost_of_header(rel: str, language: str = "") -> int:
    """Approximate overhead of a file heading plus code fences."""

    return estimate_tokens(f"### {rel} ({language})\n```{language.lower()}\n\n```\n") + 2


def format_tokens(value: int) -> str:
    if value >= 1_000_000:
        return f"{value / 1_000_000:.2f}M".replace(".", ",")
    if value >= 10_000:
        return f"{value / 1_000:.1f}k".replace(".", ",")
    if value >= 1_000:
        return f"{value / 1_000:.2f}k".replace(".", ",")
    return str(value)


def format_bytes(value: int) -> str:
    if value >= 1024 * 1024:
        return f"{value / (1024 * 1024):.1f} MB".replace(".", ",")
    if value >= 1024:
        return f"{value / 1024:.1f} kB".replace(".", ",")
    return f"{value} B"


def truncate_text(
    text: str,
    max_tokens: int,
    strategy: str = "head_tail",
) -> tuple[str, bool]:
    """Trim ``text`` to roughly ``max_tokens``.

    ``head_tail`` keeps the beginning and the end of the file (imports, public
    API, and final definitions) which is usually the most useful slice.
    """

    if max_tokens <= 0:
        return "", True
    if estimate_tokens(text) <= max_tokens:
        return text, False
    if max_tokens < 40:
        return "", True

    marker_tokens = 12
    available = max(8, max_tokens - marker_tokens)
    if strategy == "head":
        head_budget = available
        tail_budget = 0
    else:
        head_budget = int(available * 0.74)
        tail_budget = available - head_budget

    lines = text.splitlines(keepends=True)
    head_parts: list[str] = []
    used = 0
    head_index = 0
    for index, line in enumerate(lines):
        cost = estimate_tokens(line)
        if used + cost > head_budget:
            break
        head_parts.append(line)
        used += cost
        head_index = index + 1

    tail_parts: list[str] = []
    tail_index = len(lines)
    if tail_budget > 0:
        used_tail = 0
        for index in range(len(lines) - 1, head_index - 1, -1):
            cost = estimate_tokens(lines[index])
            if used_tail + cost > tail_budget:
                break
            tail_parts.append(lines[index])
            used_tail += cost
            tail_index = index
        tail_parts.reverse()

    omitted = max(0, tail_index - head_index)
    marker = f"\n⋯ [{omitted} líneas omitidas para respetar el presupuesto] ⋯\n"
    result = "".join(head_parts) + marker + "".join(tail_parts)

    # The estimate is approximate; shrink the tail until we are safely inside.
    guard = 0
    while estimate_tokens(result) > max_tokens and guard < 12:
        if tail_parts:
            tail_parts.pop(0)
        elif head_parts:
            head_parts.pop()
        else:
            break
        omitted += 1
        marker = f"\n⋯ [{omitted} líneas omitidas para respetar el presupuesto] ⋯\n"
        result = "".join(head_parts) + marker + "".join(tail_parts)
        guard += 1
    return result, True


def truncate_chars(text: str, max_chars: int) -> tuple[str, bool]:
    if max_chars <= 0:
        return "", True
    if len(text) <= max_chars:
        return text, False
    head = int(max_chars * 0.8)
    tail = max_chars - head
    cut = text.find("\n", head)
    if cut == -1 or cut > head + 400:
        cut = head
    return (
        text[:cut].rstrip()
        + f"\n\n⋯ [salida truncada: {len(text) - max_chars:,} caracteres omitidos] ⋯\n\n".replace(
            ",", "."
        )
        + text[-tail:].lstrip()
    ), True


def number_lines(text: str, start: int = 1) -> str:
    lines = text.splitlines()
    width = len(str(start + len(lines)))
    return "\n".join(f"{start + i:>{width}} | {line}" for i, line in enumerate(lines)) + "\n"


def clip(text: str, max_chars: int, suffix: str = "…") -> str:
    text = text.replace("\n", " ").strip()
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - 1)].rstrip() + suffix
