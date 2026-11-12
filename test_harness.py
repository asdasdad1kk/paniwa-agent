import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import harness


class HarnessTests(unittest.TestCase):
    def test_build_prompt_contains_task_description_and_selected_file(self):
        prompt = harness.build_prompt(
            "2",
            "El endpoint falla con entradas vacías",
            [("main.py", "def endpoint():\n    return None")],
            "## main\n M main.py",
        )

        self.assertIn("Bug fix", prompt)
        self.assertIn("El endpoint falla con entradas vacías", prompt)
        self.assertIn("--- Archivo: main.py ---", prompt)
        self.assertIn("## main\n M main.py", prompt)

    def test_scan_files_skips_generated_directories(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "app.py").write_text("print('ok')", encoding="utf-8")
            (root / ".gitignore").write_text("node_modules/", encoding="utf-8")
            (root / ".env").write_text("SECRET=value", encoding="utf-8")
            generated = root / "node_modules"
            generated.mkdir()
            (generated / "dependency.js").write_text("ignored", encoding="utf-8")

            self.assertEqual(
                [root / ".env", root / ".gitignore", root / "app.py"],
                harness.scan_files(root),
            )

    def test_create_project_writes_files_and_optional_zip(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            destination = Path(temporary_directory) / "new-api"
            archive_path = harness.create_project("1", destination, True)

            self.assertTrue((destination / "main.py").is_file())
            self.assertTrue(archive_path.is_file())
            with zipfile.ZipFile(archive_path) as archive:
                self.assertIn("main.py", archive.namelist())
                self.assertIn("requirements.txt", archive.namelist())

    def test_all_project_templates_create_expected_files(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            for key, template in harness.PROJECT_TEMPLATES.items():
                with self.subTest(template=template["name"]):
                    destination = root / f"project-{key}"
                    harness.create_project(key, destination, False)
                    for relative_path in template["files"]:
                        self.assertTrue((destination / relative_path).is_file())
                    package_json = destination / "package.json"
                    if package_json.exists():
                        json.loads(package_json.read_text(encoding="utf-8"))
                    for relative_path, content in template["files"].items():
                        if relative_path.endswith(".py"):
                            compile(content, relative_path, "exec")

    def test_create_project_does_not_overwrite_existing_path(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            destination = Path(temporary_directory) / "existing"
            destination.mkdir()
            existing_file = destination / "keep.txt"
            existing_file.write_text("keep", encoding="utf-8")

            with self.assertRaises(FileExistsError):
                harness.create_project("1", destination, False)

            self.assertEqual("keep", existing_file.read_text(encoding="utf-8"))

    def test_create_project_does_not_overwrite_existing_zip(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            destination = Path(temporary_directory) / "new-api"
            archive_path = Path(temporary_directory) / "new-api.zip"
            archive_path.write_text("keep", encoding="utf-8")

            with self.assertRaises(FileExistsError):
                harness.create_project("1", destination, True)

            self.assertFalse(destination.exists())
            self.assertEqual("keep", archive_path.read_text(encoding="utf-8"))

    @patch("harness.subprocess.run")
    @patch("harness.shutil.which", return_value="C:\\Program Files\\Git\\git.exe")
    def test_git_output_uses_subprocess_and_requested_read_only_command(
        self, _which, run
    ):
        run.return_value.returncode = 0
        run.return_value.stdout = " M main.py\n"
        run.return_value.stderr = ""

        output = harness.git_output(Path("project"), "diff")

        self.assertEqual("M main.py", output)
        self.assertEqual(
            ["C:\\Program Files\\Git\\git.exe", "-C", "project", "diff"],
            run.call_args.args[0],
        )

    @patch("harness.subprocess.run")
    @patch("harness.shutil.which", return_value=None)
    def test_git_output_reports_when_git_is_not_installed(self, _which, run):
        with self.assertRaisesRegex(RuntimeError, "Git no está instalado"):
            harness.git_output(Path("project"), "status")
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
