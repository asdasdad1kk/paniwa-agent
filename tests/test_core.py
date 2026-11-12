"""Core test-suite for harnesskit.

Covers the deterministic parts of the harness: token estimation, ignore rules,
secret redaction, scanning, prompt generation, response parsing, patch safety,
history storage, configuration and project scaffolds. The GUI is exercised by
the smoke script, not here, so these tests stay fast and headless.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from harnesskit.config import HarnessConfig, load_config, save_config
from harnesskit.contextpack import PackCandidate, pack_context
from harnesskit.engine import ContentCache, RepoMapCache, generate_prompt
from harnesskit.history import SessionStore
from harnesskit.ignore import IgnoreMatcher
from harnesskit.models import FileEntry, GenerateOptions
from harnesskit.promptlib import FORMAT_LABELS, TASKS, make_fence, resolve_task
from harnesskit.response import ParsedItem, build_patch, parse_response
from harnesskit.scaffolds import SCAFFOLDS, create_project
from harnesskit.scanner import ScanOptions, language_for, scan_project
from harnesskit.secrets import REDACTION, is_sensitive_path, scan_text
from harnesskit.symbols import build_repo_map, extract_imports, python_symbols, resolve_related
from harnesskit.tokens import (
    estimate_tokens,
    format_bytes,
    format_tokens,
    number_lines,
    truncate_text,
)


def _entry(rel: str, text: str = "", *, language: str = "Python", **extra) -> FileEntry:
    data = dict(
        path=Path(rel),
        rel=rel,
        size=len(text.encode("utf-8")),
        mtime=0.0,
        language=language,
        estimated_tokens=estimate_tokens(text),
    )
    data.update(extra)
    return FileEntry(**data)  # type: ignore[arg-type]


class TokenTests(unittest.TestCase):
    def test_empty_and_ascii_estimates(self) -> None:
        self.assertEqual(estimate_tokens(""), 0)
        self.assertGreater(estimate_tokens("hello world"), 0)
        self.assertLess(estimate_tokens("a"), estimate_tokens("a much longer sentence"))

    def test_cjk_counts_more_than_latin(self) -> None:
        self.assertGreater(estimate_tokens("你好世界"), estimate_tokens("abcd"))

    def test_truncate_keeps_head_and_tail(self) -> None:
        text = "\n".join(f"line {index}" for index in range(400))
        result, truncated = truncate_text(text, 120)
        self.assertTrue(truncated)
        self.assertIn("líneas omitidas", result)
        self.assertIn("line 0", result)
        self.assertIn("line 399", result)
        self.assertLessEqual(estimate_tokens(result), 160)

    def test_small_text_is_not_truncated(self) -> None:
        result, truncated = truncate_text("import os\n", 1_000)
        self.assertFalse(truncated)
        self.assertEqual(result, "import os\n")

    def test_formatting_is_spanish(self) -> None:
        self.assertEqual(format_tokens(999), "999")
        self.assertEqual(format_tokens(12_345), "12,3k")
        self.assertEqual(format_tokens(1_500_000), "1,50M")
        self.assertEqual(format_bytes(2_048), "2,0 kB")

    def test_number_lines_keeps_alignment(self) -> None:
        numbered = number_lines("alpha\nbeta\n")
        self.assertEqual(numbered.splitlines()[0], "1 | alpha")
        self.assertEqual(numbered.splitlines()[1], "2 | beta")


class IgnoreTests(unittest.TestCase):
    def test_glob_anchoring_and_negation(self) -> None:
        matcher = IgnoreMatcher().with_rules(
            "",
            ["*.log", "!keep.log", "/root.txt", "build/", "src/**/*.tmp"],
        )
        self.assertTrue(matcher.is_ignored("debug.log"))
        self.assertFalse(matcher.is_ignored("keep.log"))
        self.assertTrue(matcher.is_ignored("root.txt"))
        self.assertFalse(matcher.is_ignored("nested/root.txt"))
        self.assertTrue(matcher.is_ignored("build", is_dir=True))
        self.assertFalse(matcher.is_ignored("build", is_dir=False))
        self.assertTrue(matcher.is_ignored("src/one/two.tmp"))

    def test_nested_base_is_scoped(self) -> None:
        matcher = IgnoreMatcher().with_rules("sub", ["*.json"])
        self.assertTrue(matcher.is_ignored("sub/data.json"))
        self.assertFalse(matcher.is_ignored("data.json"))

    def test_comments_and_empty_lines_are_skipped(self) -> None:
        matcher = IgnoreMatcher().with_rules("", ["# comment", "", "  ", "*.bak"])
        self.assertEqual(len(matcher.rules), 1)
        self.assertTrue(matcher.is_ignored("file.bak"))


class SecretTests(unittest.TestCase):
    def test_known_key_is_redacted(self) -> None:
        text = "aws = AKIAABCDEFGHIJKLMNOP\n"
        cleaned, findings = scan_text(text, "config.py")
        self.assertNotIn("AKIAABCDEFGHIJKLMNOP", cleaned)
        self.assertIn(REDACTION, cleaned)
        self.assertEqual(findings[0].kind, "AWS access key")
        self.assertEqual(findings[0].path, "config.py")

    def test_generic_assignment_is_redacted(self) -> None:
        cleaned, findings = scan_text('password = "hunter2hunter2"\n')
        self.assertNotIn("hunter2hunter2", cleaned)
        self.assertTrue(any(item.kind == "Asignación sensible" for item in findings))

    def test_placeholder_values_are_left_alone(self) -> None:
        cleaned, findings = scan_text("api_key = 'changeme'\n")
        self.assertEqual(cleaned, "api_key = 'changeme'\n")
        self.assertEqual(findings, [])

    def test_redact_false_reports_but_keeps_text(self) -> None:
        text = "token = ghp_" + "a" * 36
        cleaned, findings = scan_text(text, redact=False)
        self.assertEqual(cleaned, text)
        self.assertTrue(findings)

    def test_sensitive_paths(self) -> None:
        self.assertEqual(is_sensitive_path(".env"), "archivo .env")
        self.assertEqual(is_sensitive_path("certs/server.pem"), "material criptográfico")
        self.assertEqual(is_sensitive_path("src/app.py"), "")


class ScannerTests(unittest.TestCase):
    def _make_project(self, root: Path) -> None:
        (root / "src").mkdir(parents=True)
        (root / "src" / "app.py").write_text("import os\n\nprint(os.name)\n", encoding="utf-8")
        (root / "src" / "notes.txt").write_text("plain text\n", encoding="utf-8")
        (root / "README.md").write_text("# demo\n", encoding="utf-8")
        (root / "ignored.log").write_text("noise\n", encoding="utf-8")
        (root / "secret").mkdir()
        (root / "secret" / "token.py").write_text("TOKEN = 'x'\n", encoding="utf-8")
        (root / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00")
        (root / ".gitignore").write_text("*.log\nsecret/\n", encoding="utf-8")
        (root / "node_modules").mkdir()
        (root / "node_modules" / "lib.js").write_text("module.exports = 1;\n", encoding="utf-8")

    def test_scan_respects_gitignore_and_binaries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._make_project(root)
            scan = scan_project(root, ScanOptions(include_git=False))
            rels = {entry.rel for entry in scan.files}
            self.assertIn("src/app.py", rels)
            self.assertIn("README.md", rels)
            self.assertNotIn("ignored.log", rels)
            self.assertNotIn("secret/token.py", rels)
            self.assertNotIn("image.png", rels)
            self.assertNotIn("node_modules/lib.js", rels)
            self.assertGreater(scan.ignored_dirs, 0)
            self.assertGreater(scan.skipped_binary, 0)

    def test_languages_and_sensitive_flags(self) -> None:
        self.assertEqual(language_for(Path("main.py")), "Python")
        self.assertEqual(language_for(Path("package.json")), "JSON")
        self.assertIsNone(language_for(Path("data.unknownext")))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text("SECRET=1\n", encoding="utf-8")
            (root / "app.py").write_text("x = 1\n", encoding="utf-8")
            scan = scan_project(root, ScanOptions(include_git=False))
            index = scan.index()
            self.assertEqual(index[".env"].sensitive, "archivo .env")
            self.assertEqual(index["app.py"].sensitive, "")

    def test_oversized_files_are_flagged_not_dropped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "big.py").write_text("x = 1\n" * 100, encoding="utf-8")
            scan = scan_project(
                root,
                ScanOptions(include_git=False, max_file_mb=0.0001),
            )
            entry = scan.index()["big.py"]
            self.assertTrue(entry.too_large)
            self.assertGreaterEqual(scan.skipped_large, 1)


class ContextPackTests(unittest.TestCase):
    def _options(self, **changes) -> GenerateOptions:
        options = GenerateOptions(
            include_git=False,
            include_diff=False,
            include_repo_map=False,
            include_related=False,
        )
        for key, value in changes.items():
            setattr(options, key, value)
        return options

    def test_tight_budget_excludes_large_files(self) -> None:
        big = "\n".join(f"value_{index} = {index}" for index in range(2_000))
        candidates = [
            PackCandidate(_entry("big.py", big), big),
            PackCandidate(_entry("small.py", "x = 1\n"), "x = 1\n"),
        ]
        bundle = pack_context(candidates, self._options(), budget=260)
        included = {item.rel for item in bundle.files}
        self.assertIn("small.py", included)
        self.assertNotIn("big.py", included)
        reasons = {item.rel: item.reason for item in bundle.excluded}
        self.assertIn("big.py", reasons)
        self.assertLessEqual(estimate_tokens(bundle.git_status), 260)

    def test_diff_only_skips_covered_files(self) -> None:
        text = "print('hi')\n"
        candidates = [PackCandidate(_entry("app.py", text), text)]
        options = self._options(include_git=True, include_diff=True, diff_only=True)
        bundle = pack_context(
            candidates,
            options,
            budget=10_000,
            diff_sections=[("cambios", "--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-x\n+y\n")],
            diff_files={"app.py"},
        )
        self.assertEqual(bundle.files, [])
        self.assertEqual(bundle.excluded[0].reason, "cubierto por el diff")
        self.assertIn("app.py", bundle.git_diff)

    def test_line_numbers_are_applied(self) -> None:
        text = "alpha\nbeta\n"
        candidates = [PackCandidate(_entry("app.py", text), text)]
        bundle = pack_context(candidates, self._options(line_numbers=True), budget=5_000)
        self.assertEqual(bundle.files[0].text.splitlines()[0], "1 | alpha")


class ResponseTests(unittest.TestCase):
    ANSWER = (
        "Aquí está el cambio:\n\n"
        "```python src/util.py\n"
        "def add(a, b):\n"
        "    return a + b\n"
        "```\n\n"
        "```diff\n"
        "diff --git a/README.md b/README.md\n"
        "--- a/README.md\n"
        "+++ b/README.md\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
        "```\n"
    )

    def test_parse_files_diffs_and_snippets(self) -> None:
        parsed = parse_response(self.ANSWER)
        self.assertEqual(parsed.file_count, 1)
        self.assertEqual(parsed.diff_count, 1)
        self.assertTrue(parsed.actionable)
        paths = {item.path for item in parsed.items}
        self.assertIn("src/util.py", paths)
        self.assertIn("README.md", paths)

    def test_parse_without_fences_reports_a_note(self) -> None:
        parsed = parse_response("Solo texto, sin bloques.")
        self.assertFalse(parsed.items)
        self.assertTrue(parsed.notes)

    def test_raw_unified_diff_without_fences_is_detected(self) -> None:
        parsed = parse_response(
            "diff --git a/a.txt b/a.txt\n--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-x\n+y\n"
        )
        self.assertEqual(parsed.diff_count, 1)

    def test_new_file_patch_prefixes_every_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            item = ParsedItem(path="src/new.py", kind="file", content="print('hi')\n")
            patch, warnings = build_patch(root, [item])
            self.assertEqual(warnings, [])
            self.assertIn("--- /dev/null", patch)
            self.assertIn("+++ b/src/new.py", patch)
            self.assertIn("+print('hi')", patch)
            self.assertFalse((root / "src" / "new.py").exists())

    def test_existing_file_becomes_minimal_diff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("old\n", encoding="utf-8")
            item = ParsedItem(path="README.md", kind="file", content="new\n")
            patch, warnings = build_patch(root, [item])
            self.assertEqual(warnings, [])
            self.assertIn("--- a/README.md", patch)
            self.assertIn("-old", patch)
            self.assertIn("+new", patch)

    def test_unchanged_file_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "same.txt").write_text("same\n", encoding="utf-8")
            item = ParsedItem(path="same.txt", kind="file", content="same\n")
            patch, warnings = build_patch(root, [item])
            self.assertEqual(patch, "")
            self.assertTrue(any("no cambia" in warning for warning in warnings))

    def test_path_traversal_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            item = ParsedItem(path="../evil.py", kind="file", content="x = 1\n")
            patch, warnings = build_patch(Path(tmp), [item])
            self.assertEqual(patch, "")
            self.assertTrue(any("Ruta" in warning for warning in warnings))


class EngineTests(unittest.TestCase):
    def _scan(self, root: Path):
        (root / "pkg").mkdir()
        (root / "pkg" / "core.py").write_text(
            "import os\n\n\ndef core(value):\n    return value + 1\n", encoding="utf-8"
        )
        (root / "pkg" / "util.py").write_text("def helper():\n    return 42\n", encoding="utf-8")
        return scan_project(root, ScanOptions(include_git=False))

    def test_prompt_contains_request_and_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            scan = self._scan(Path(tmp))
            bundle = generate_prompt(
                scan,
                "bugfix",
                "Corrige el cálculo de core.",
                GenerateOptions(include_git=False, include_diff=False),
                {"pkg/core.py"},
            )
            self.assertIn("Corrige el cálculo de core.", bundle.text)
            self.assertIn("def core(value):", bundle.text)
            self.assertIn("pkg/core.py", bundle.text)
            self.assertEqual(bundle.task_label, resolve_task("bugfix").label)
            self.assertGreater(bundle.tokens, 0)
            self.assertEqual(len(bundle.prompt_hash), 16)

    def test_related_imports_are_included(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pkg").mkdir()
            (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
            (root / "pkg" / "main.py").write_text(
                "from .util import helper\n\nprint(helper())\n", encoding="utf-8"
            )
            (root / "pkg" / "util.py").write_text("def helper():\n    return 1\n", encoding="utf-8")
            scan = scan_project(root, ScanOptions(include_git=False))
            bundle = generate_prompt(
                scan,
                "feature",
                "Explica el flujo.",
                GenerateOptions(
                    include_git=False,
                    include_diff=False,
                    include_related=True,
                    related_depth=1,
                ),
                {"pkg/main.py"},
            )
            rels = {item.rel for item in bundle.context.files}
            self.assertIn("pkg/main.py", rels)
            self.assertIn("pkg/util.py", rels)

    def test_prompt_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            scan = self._scan(Path(tmp))
            options = GenerateOptions(include_git=False, include_diff=False)
            first = generate_prompt(scan, "tests", "Añade pruebas.", options, {"pkg/core.py"})
            second = generate_prompt(scan, "tests", "Añade pruebas.", options, {"pkg/core.py"})
            self.assertEqual(first.text, second.text)
            self.assertEqual(first.prompt_hash, second.prompt_hash)

    def test_all_formats_include_the_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            scan = self._scan(Path(tmp))
            for fmt in FORMAT_LABELS:
                options = GenerateOptions(include_git=False, include_diff=False, format=fmt)
                bundle = generate_prompt(scan, "feature", f"Petición {fmt}", options, {"pkg/core.py"})
                self.assertIn(f"Petición {fmt}", bundle.text, fmt)

    def test_secrets_are_redacted_from_the_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config.py").write_text(
                'AWS_KEY = "AKIAABCDEFGHIJKLMNOP"\n', encoding="utf-8"
            )
            scan = scan_project(root, ScanOptions(include_git=False))
            bundle = generate_prompt(
                scan,
                "review",
                "Revisa la seguridad.",
                GenerateOptions(include_git=False, include_diff=False, redact=True),
                {"config.py"},
            )
            self.assertNotIn("AKIAABCDEFGHIJKLMNOP", bundle.text)
            self.assertIn(REDACTION, bundle.text)
            self.assertGreaterEqual(bundle.context.redactions, 1)
            self.assertTrue(
                any(
                    "Se redactó 1 posible secreto en 1 ubicación." in warning
                    for warning in bundle.warnings
                )
            )

    def test_redaction_warning_pluralizes_locations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.py").write_text(
                'AWS_KEY = "AKIAABCDEFGHIJKLMNOP"\n', encoding="utf-8"
            )
            (root / "b.py").write_text(
                'OTHER_KEY = "AKIAQRSTUVWXYZABCDEF"\n', encoding="utf-8"
            )
            scan = scan_project(root, ScanOptions(include_git=False))
            bundle = generate_prompt(
                scan,
                "review",
                "Revisa la seguridad.",
                GenerateOptions(include_git=False, include_diff=False, redact=True),
                {"a.py", "b.py"},
            )
            self.assertTrue(
                any(
                    "Se redactaron 2 posibles secretos en 2 ubicaciones." in warning
                    for warning in bundle.warnings
                )
            )

    def test_empty_selection_still_produces_a_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            scan = self._scan(Path(tmp))
            bundle = generate_prompt(
                scan,
                "feature",
                "Sin archivos.",
                GenerateOptions(
                    include_git=False,
                    include_diff=False,
                    include_repo_map=False,
                ),
                set(),
            )
            self.assertTrue(any("No hay archivos seleccionados" in item for item in bundle.warnings))

    def test_caches_reuse_reads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            scan = self._scan(Path(tmp))
            cache = ContentCache()
            maps = RepoMapCache()
            options = GenerateOptions(include_git=False, include_diff=False)
            generate_prompt(scan, "feature", "Uno.", options, {"pkg/core.py"},
                            content_cache=cache, map_cache=maps)
            self.assertIn("pkg/core.py", cache._items)  # noqa: SLF001 - white-box check


class HistoryTests(unittest.TestCase):
    def _bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "app.py").write_text("print('hi')\n", encoding="utf-8")
            scan = scan_project(root, ScanOptions(include_git=False))
            bundle = generate_prompt(
                scan,
                "feature",
                "Haz algo.",
                GenerateOptions(include_git=False, include_diff=False),
                {"app.py"},
            )
            # Detach paths from the temporary directory before it disappears.
            bundle.project_root = root
            return bundle

    def test_save_list_load_delete_and_dedupe(self) -> None:
        bundle = self._bundle()
        with tempfile.TemporaryDirectory() as tmp:
            store = SessionStore(tmp, keep=10)
            first = store.save_bundle(bundle)
            second = store.save_bundle(bundle)
            self.assertEqual(first, second)
            summaries = store.list()
            self.assertEqual(len(summaries), 1)
            self.assertEqual(summaries[0].file_count, 1)
            record = store.load(first)
            self.assertEqual(record.prompt, bundle.text)
            self.assertEqual(record.task, "feature")
            self.assertTrue(store.delete(first))
            self.assertEqual(store.list(), [])

    def test_prune_keeps_newest_sessions(self) -> None:
        bundle = self._bundle()
        with tempfile.TemporaryDirectory() as tmp:
            store = SessionStore(tmp, keep=2)
            for index in range(4):
                store.save_bundle(bundle, text_override=f"{bundle.text}\n{index}")
            self.assertEqual(len(store.list()), 2)

    def test_clear_removes_every_session(self) -> None:
        bundle = self._bundle()
        with tempfile.TemporaryDirectory() as tmp:
            store = SessionStore(tmp)
            store.save_bundle(bundle, text_override="one")
            store.save_bundle(bundle, text_override="two")
            self.assertEqual(store.clear(), 2)
            self.assertEqual(store.list(), [])


class ConfigTests(unittest.TestCase):
    def test_roundtrip_and_coercion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            config = HarnessConfig()
            config.budget_tokens = 30_000
            config.redact = False
            config.extra_ignore = "*.md, dist/"
            config.record_recent(tmp)
            save_config(config, path)
            loaded = load_config(path)
            self.assertEqual(loaded.budget_tokens, 30_000)
            self.assertFalse(loaded.redact)
            self.assertEqual(loaded.extra_ignore, "*.md, dist/")
            self.assertIn(str(Path(tmp).resolve()), loaded.recent_projects)

    def test_invalid_values_fall_back_and_clamp(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text('{"budget_tokens": 10, "font_size": 99, "redact": "no"}',
                            encoding="utf-8")
            loaded = load_config(path)
            self.assertEqual(loaded.budget_tokens, 2_000)
            self.assertEqual(loaded.font_size, 24)
            self.assertFalse(loaded.redact)

    def test_broken_json_returns_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text("{not json", encoding="utf-8")
            loaded = load_config(path)
            self.assertEqual(loaded.budget_tokens, HarnessConfig().budget_tokens)

    def test_extra_ignore_patterns(self) -> None:
        config = HarnessConfig(extra_ignore="*.md, dist/\n# comment\nbuild/")
        self.assertEqual(config.extra_ignore_patterns(), ["*.md", "dist/", "build/"])

    def test_to_generate_options_maps_fields(self) -> None:
        config = HarnessConfig(budget_tokens=42_000, format="xml", line_numbers=True)
        options = config.to_generate_options()
        self.assertEqual(options.budget_tokens, 42_000)
        self.assertEqual(options.format, "xml")
        self.assertTrue(options.line_numbers)


class ScaffoldTests(unittest.TestCase):
    def test_every_scaffold_writes_its_files(self) -> None:
        self.assertGreaterEqual(len(SCAFFOLDS), 9)
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            for key, scaffold in SCAFFOLDS.items():
                target = base / key
                result = create_project(key, target, make_zip=False)
                self.assertIsNone(result)
                for rel in scaffold.files:
                    self.assertTrue((target / rel).is_file(), f"{key}: {rel}")
                self.assertFalse((base / f"{key}.zip").exists())

    def test_zip_is_created_when_requested(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "fastapi-app"
            archive = create_project("1", target, make_zip=True)
            self.assertEqual(archive, Path(tmp) / "fastapi-app.zip")
            self.assertTrue((Path(tmp) / "fastapi-app.zip").is_file())

    def test_existing_path_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "taken"
            target.mkdir()
            (target / "keep.txt").write_text("original", encoding="utf-8")
            with self.assertRaises((FileExistsError, ValueError, OSError)):
                create_project("1", target, make_zip=False)
            self.assertEqual((target / "keep.txt").read_text(encoding="utf-8"), "original")

    def test_unknown_template_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises((KeyError, ValueError)):
                create_project("does-not-exist", Path(tmp) / "x", make_zip=False)


class SymbolTests(unittest.TestCase):
    TEXT = (
        "import os\n"
        "from .utils import helper\n\n"
        "class Greeter:\n"
        "    def greet(self):\n"
        "        return helper()\n\n"
        "def top(value: int) -> int:\n"
        "    return value\n"
    )

    def test_python_symbols(self) -> None:
        symbols = python_symbols(self.TEXT)
        joined = " ".join(symbols)
        self.assertIn("Greeter", joined)
        self.assertIn("top", joined)

    def test_relative_import_resolution(self) -> None:
        known = {"pkg/app.py", "pkg/utils.py", "pkg/other.py"}
        found = extract_imports("pkg/app.py", self.TEXT, known)
        self.assertIn("pkg/utils.py", found)

    def test_resolve_related_skips_seeds(self) -> None:
        known = {"pkg/app.py", "pkg/utils.py", "pkg/deep.py"}
        related = resolve_related({"pkg/app.py": self.TEXT}, known, depth=1)
        self.assertIn("pkg/utils.py", related)
        self.assertNotIn("pkg/app.py", related)

    def test_repo_map_contains_symbols(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "app.py"
            path.write_text(self.TEXT, encoding="utf-8")
            entry = FileEntry(
                path=path,
                rel="app.py",
                size=path.stat().st_size,
                mtime=0.0,
                language="Python",
            )
            repo_map, truncated = build_repo_map([entry], {"app.py"}, max_tokens=2_000)
            self.assertIn("app.py", repo_map)
            self.assertIn("Greeter", repo_map)
            self.assertFalse(truncated)


class PromptLibTests(unittest.TestCase):
    def test_task_presets_are_unique(self) -> None:
        keys = [task.key for task in TASKS]
        self.assertEqual(len(keys), len(set(keys)))

    def test_unknown_task_falls_back_to_feature(self) -> None:
        self.assertEqual(resolve_task("nope").key, "feature")

    def test_legacy_task_names_are_mapped(self) -> None:
        self.assertEqual(resolve_task("nueva-funcionalidad").key, "feature")

    def test_fence_grows_with_inner_backticks(self) -> None:
        fenced = make_fence("```py\nprint(1)\n```", "text")
        self.assertTrue(fenced.startswith("````"))
        self.assertTrue(fenced.endswith("````"))


if __name__ == "__main__":
    unittest.main()
