#!/usr/bin/env python3
"""Exercise the recipe update guard in disposable repositories."""

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


GUARD = Path(__file__).with_name("check_recipe_update.py")
SOURCE = "recetas/R16_lentejas.md"
HTML = "docs/recetas/R16_lentejas.html"
RECIPE = "---\nid: R16\nversion: 2\nestado: pendiente_de_completar\n---\nLentejas.\n"


class RecipeUpdateGuardTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / "tools").mkdir()
        shutil.copyfile(GUARD, self.root / "tools/check_recipe_update.py")
        self.write(SOURCE, RECIPE)
        self.write(HTML, "<p>Lentejas.</p>\n")
        self.write("docs/semanas/2026-09-21.html", "Menú sin cambios.\n")
        self.git("init", "-q")
        self.git("add", ".")
        self.git("-c", "user.name=Guard Test", "-c", "user.email=guard@example.invalid", "commit", "-qm", "Base")
        self.base = self.git("rev-parse", "HEAD").strip()

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.root), *args], text=True)

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def update_recipe(self, source=None):
        self.write(SOURCE, source or RECIPE.replace("version: 2", "version: 3"))
        self.write(HTML, "<p>Lentejas con tomates cherry.</p>\n")

    def run_guard(self, recipe="R16_lentejas.md"):
        # An unrelated cwd verifies that paths are anchored to the script.
        return subprocess.run(
            [sys.executable, str(self.root / "tools/check_recipe_update.py"),
             "--base", self.base, "--recipe", recipe],
            cwd=tempfile.gettempdir(), capture_output=True, text=True,
        )

    def assert_rejected(self, text):
        result = self.run_guard()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(text, result.stderr)

    def test_accepts_recipe_pair_staged_and_unstaged(self):
        self.update_recipe()
        self.git("add", SOURCE)
        result = self.run_guard()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "OK: R16_lentejas.md")

    def test_no_changes(self):
        result = self.run_guard()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "NO_CHANGES")

    def test_rejects_weekly_change_even_if_only_staged(self):
        self.update_recipe()
        self.write("docs/semanas/2026-09-21.html", "Menú modificado.\n")
        self.git("add", "docs/semanas/2026-09-21.html")
        self.write("docs/semanas/2026-09-21.html", "Menú sin cambios.\n")
        self.assert_rejected("Cambios fuera")

    def test_rejects_untracked_file(self):
        self.update_recipe()
        self.write("extra.md", "No autorizado.\n")
        self.assert_rejected("sin seguimiento")

    def test_rejects_missing_html_change(self):
        self.write(SOURCE, RECIPE.replace("version: 2", "version: 3"))
        self.assert_rejected("Deben cambiar juntos")

    def test_rejects_metadata_changes(self):
        cases = [
            (RECIPE, "version debe aumentar"),
            (RECIPE.replace("version: 2", "version: 4"), "version debe aumentar"),
            (RECIPE.replace("version: 2", "version: true"), "version debe ser un entero"),
            (RECIPE.replace("version: 2", "version: 3").replace("id: R16", "id: R17"), "ID debe conservarse"),
            (RECIPE.replace("version: 2", "version: 3").replace("pendiente_de_completar", "confirmada"), "estado de validación"),
        ]
        for source, message in cases:
            with self.subTest(message=message, source=source):
                self.update_recipe(source + "\nPreparación actualizada.\n")
                self.assert_rejected(message)

    def test_rejects_deletion_and_rename(self):
        (self.root / HTML).unlink()
        self.assert_rejected("archivo regular")
        self.write(HTML, "<p>Lentejas.</p>\n")
        self.git("mv", SOURCE, "recetas/R16_otro.md")
        self.assert_rejected("archivo regular")

    def test_rejects_path_traversal(self):
        result = self.run_guard("../R16_lentejas.md")
        self.assertEqual(result.returncode, 1)
        self.assertIn("Nombre de receta no válido", result.stderr)


if __name__ == "__main__":
    unittest.main()
