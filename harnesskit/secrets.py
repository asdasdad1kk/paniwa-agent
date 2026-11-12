"""Lightweight secret detection and redaction before anything is copied.

This is a safety net, not a guarantee. Findings are surfaced in the UI and the
CLI so the developer can decide whether to include the file at all.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .models import SecretFinding

REDACTION = "«REDACTADO»"

_FIXED_RULES: list[tuple[str, str, re.Pattern[str], str]] = [
    (
        "Clave privada",
        "crítica",
        re.compile(
            r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----.*?-----END (?:[A-Z0-9 ]+ )?PRIVATE KEY-----",
            re.DOTALL | re.IGNORECASE,
        ),
        "«CLAVE-PRIVADA-REDACTADA»",
    ),
    (
        "AWS access key",
        "alta",
        re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
        REDACTION,
    ),
    (
        "GitHub token",
        "alta",
        re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,255}\b"),
        REDACTION,
    ),
    (
        "GitHub PAT",
        "alta",
        re.compile(r"\bgithub_pat_[A-Za-z0-9_]{30,255}\b"),
        REDACTION,
    ),
    (
        "OpenAI key",
        "alta",
        re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b"),
        REDACTION,
    ),
    (
        "Anthropic key",
        "alta",
        re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b"),
        REDACTION,
    ),
    (
        "Google API key",
        "alta",
        re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
        REDACTION,
    ),
    (
        "Stripe key",
        "alta",
        re.compile(r"\b(?:sk|pk|rk)_(?:live|test)_[0-9A-Za-z]{16,}\b"),
        REDACTION,
    ),
    (
        "Slack token",
        "alta",
        re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"),
        REDACTION,
    ),
    (
        "JWT",
        "media",
        re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
        REDACTION,
    ),
    (
        "Bearer token",
        "alta",
        re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{16,}"),
        "Bearer " + REDACTION,
    ),
    (
        "URL con credenciales",
        "alta",
        re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://[^/\s:@]+:)([^@\s/]{3,})(?=@)"),
        None,  # type: ignore[arg-type]
    ),
    (
        "Connection string",
        "alta",
        re.compile(
            r"(?i)\b(?:password|pwd)\s*=\s*[^;\s\"']{4,}(?=;|\s|$)"
        ),
        None,  # type: ignore[arg-type]
    ),
]

_GENERIC_ASSIGNMENT = re.compile(
    r"(?i)(\b(?:api[_-]?key|apikey|secret|client[_-]?secret|access[_-]?token|"
    r"auth[_-]?token|refresh[_-]?token|private[_-]?key|password|passwd|pwd)\b"
    r"\s*[:=]\s*[\"']?)([^\s\"',;#]{6,})"
)

_ALLOWED_VALUES = {
    "changeme",
    "change_me",
    "example",
    "password",
    "secret",
    "token",
    "undefined",
    "null",
    "none",
    "true",
    "false",
    "redacted",
    "your_token_here",
    "your-api-key",
    "your_api_key",
    "xxxxxxxx",
}


@dataclass(slots=True)
class _Occurrence:
    start: int
    end: int
    replacement: str
    kind: str
    severity: str
    preview: str


def _mask(value: str) -> str:
    value = value.strip()
    if len(value) <= 6:
        return value[0] + "•" * max(1, len(value) - 2) + value[-1]
    return f"{value[:3]}••••{value[-2:]}"


def _looks_like_secret_value(value: str) -> bool:
    lowered = value.lower()
    if lowered in _ALLOWED_VALUES or len(value) < 6:
        return False
    if value.startswith(("$", "<", "{", "%")):
        return False
    if "." in value or "(" in value or ")" in value:
        return False
    if lowered.startswith(("os.", "self.", "env", "get", "request", "config")):
        return False
    if len(set(value)) <= 2:
        return False
    if value.isalpha() and value.islower() and len(value) < 12:
        return False
    return True


def _collect(text: str) -> list[_Occurrence]:
    occurrences: list[_Occurrence] = []
    for kind, severity, pattern, replacement in _FIXED_RULES:
        for match in pattern.finditer(text):
            if replacement is None:
                if kind == "URL con credenciales":
                    repl = match.group(1) + REDACTION
                else:
                    repl = "password=" + REDACTION
            else:
                repl = replacement
            preview = _mask(match.group(0))
            occurrences.append(
                _Occurrence(match.start(), match.end(), repl, kind, severity, preview)
            )

    for match in _GENERIC_ASSIGNMENT.finditer(text):
        value = match.group(2)
        if not _looks_like_secret_value(value):
            continue
        prefix = match.group(1)
        occurrences.append(
            _Occurrence(
                match.start(),
                match.end(),
                prefix + REDACTION,
                "Asignación sensible",
                "media",
                _mask(value),
            )
        )
    occurrences.sort(key=lambda item: (item.start, -(item.end - item.start)))
    return occurrences


def scan_text(text: str, rel: str = "", redact: bool = True) -> tuple[str, list[SecretFinding]]:
    """Return (possibly redacted text, findings) for one file or prompt."""

    if not text:
        return text, []
    occurrences = _collect(text)
    if not occurrences:
        return text, []

    newlines = [index for index, char in enumerate(text) if char == "\n"]
    findings: list[SecretFinding] = []
    accepted: list[_Occurrence] = []
    last_end = -1
    for occurrence in occurrences:
        if occurrence.start <= last_end:
            continue
        accepted.append(occurrence)
        last_end = occurrence.end
        import bisect

        line = bisect.bisect_left(newlines, occurrence.start) + 1
        findings.append(
            SecretFinding(
                kind=occurrence.kind,
                path=rel,
                line=line,
                preview=occurrence.preview,
                severity=occurrence.severity,
            )
        )

    if not redact:
        return text, findings

    output = text
    for occurrence in reversed(accepted):
        output = output[: occurrence.start] + occurrence.replacement + output[occurrence.end :]
    return output, findings


def is_sensitive_path(rel: str) -> str:
    """Return a short reason when a path should get an extra warning."""

    name = rel.rsplit("/", 1)[-1].lower()
    suffix = "." + name.rsplit(".", 1)[-1] if "." in name else ""
    if name == ".env" or name.startswith(".env.") or name.endswith(".env"):
        return "archivo .env"
    if name in {
        ".npmrc",
        ".pypirc",
        ".netrc",
        ".pgpass",
        "id_rsa",
        "id_dsa",
        "id_ecdsa",
        "id_ed25519",
        "credentials",
        "kubeconfig",
        "secrets.yaml",
        "secrets.yml",
    }:
        return "credenciales"
    if suffix in {".pem", ".key", ".pfx", ".p12", ".jks", ".keystore", ".ppk"}:
        return "material criptográfico"
    return ""


__all__ = ["REDACTION", "is_sensitive_path", "scan_text"]
