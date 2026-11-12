"""A compact .gitignore matcher (no third-party dependencies).

It supports the patterns that matter in practice: comments, negations, root
anchoring, directory-only rules, ``*``, ``?``, ``**`` and character classes.
Rules are evaluated in order and the last matching rule wins, like Git.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


def _translate(pattern: str) -> str:
    """Translate a glob pattern to a regular expression body."""

    out: list[str] = []
    index = 0
    length = len(pattern)
    while index < length:
        char = pattern[index]
        if pattern.startswith("**/", index):
            out.append("(?:[^/]+/)*")
            index += 3
        elif pattern.startswith("/**", index) and index + 3 == length:
            out.append("/.*")
            index += 3
        elif pattern.startswith("**", index):
            out.append(".*")
            index += 2
        elif char == "*":
            out.append("[^/]*")
            index += 1
        elif char == "?":
            out.append("[^/]")
            index += 1
        elif char == "[":
            end = pattern.find("]", index + 1)
            if end == -1:
                out.append(r"\[")
                index += 1
            else:
                body = pattern[index + 1 : end]
                if body.startswith("!"):
                    body = "^" + body[1:]
                out.append("[" + body.replace("\\", r"\\") + "]")
                index = end + 1
        elif char == "\\" and index + 1 < length:
            out.append(re.escape(pattern[index + 1]))
            index += 2
        else:
            out.append(re.escape(char))
            index += 1
    return "".join(out)


@dataclass(frozen=True, slots=True)
class IgnoreRule:
    base: str
    pattern: str
    regex: re.Pattern[str]
    negated: bool = False
    dir_only: bool = False
    anchored: bool = False

    def matches(self, rel: str, is_dir: bool) -> bool:
        if self.dir_only and not is_dir:
            return False
        base = self.base
        if base:
            if rel == base:
                relative = ""
            elif rel.startswith(base + "/"):
                relative = rel[len(base) + 1 :]
            else:
                return False
        else:
            relative = rel
        if not relative:
            return False
        return bool(self.regex.match(relative))


class IgnoreMatcher:
    """Immutable matcher; ``with_rules`` returns a child matcher."""

    __slots__ = ("rules",)

    def __init__(self, rules: tuple[IgnoreRule, ...] = ()) -> None:
        self.rules = rules

    def with_rules(self, base: str, patterns: list[str]) -> "IgnoreMatcher":
        new_rules: list[IgnoreRule] = []
        for raw in patterns:
            rule = _parse_rule(raw, base)
            if rule is not None:
                new_rules.append(rule)
        if not new_rules:
            return self
        return IgnoreMatcher(self.rules + tuple(new_rules))

    def is_ignored(self, rel: str, is_dir: bool = False) -> bool:
        ignored = False
        for rule in self.rules:
            if rule.matches(rel, is_dir):
                ignored = not rule.negated
        return ignored


def _parse_rule(raw: str, base: str) -> IgnoreRule | None:
    line = raw.rstrip("\n\r")
    if not line or line.lstrip().startswith("#"):
        return None
    # Git ignores trailing spaces unless escaped; this simple trim is enough.
    line = line.rstrip()
    if not line:
        return None
    negated = line.startswith("!")
    if negated:
        line = line[1:]
    if not line:
        return None
    dir_only = line.endswith("/")
    if dir_only:
        line = line[:-1]
    anchored = line.startswith("/") or "/" in line
    if line.startswith("/"):
        line = line[1:]
    if not line:
        return None
    body = _translate(line)
    if anchored:
        regex = re.compile("^" + body + "$")
    else:
        regex = re.compile("(?:^|/)" + body + "$")
    return IgnoreRule(
        base=base,
        pattern=line,
        regex=regex,
        negated=negated,
        dir_only=dir_only,
        anchored=anchored,
    )


def parse_gitignore_text(text: str, base: str = "") -> list[str]:
    patterns = []
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        patterns.append(line)
    return patterns


__all__ = ["IgnoreMatcher", "IgnoreRule", "parse_gitignore_text"]
