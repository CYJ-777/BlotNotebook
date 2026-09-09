"""Exercise the documented GUI entry point using an isolated JSON Project."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class StartupTests(unittest.TestCase):
    def test_gui_starts_with_explicit_project(self):
        """The GUI must initialize all workflow tabs and a valid JSON project."""
        root = Path(__file__).resolve().parent.parent
        with tempfile.TemporaryDirectory(dir=root) as directory:
            project = Path(directory) / 'project'
            executable = os.environ.get('BLOTNOTEBOOK_EXECUTABLE')
            command = [executable] if executable else [sys.executable, str(root / 'app.py')]
            result = subprocess.run(
                [*command, '--project', str(project), '--smoke-test'],
                cwd=root,
                env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen'},
                capture_output=True, text=True, timeout=60,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            report = json.loads((project / 'smoke-test.json').read_text())
            self.assertTrue(report['started'])
            self.assertEqual(report['tabs'], 4)
            self.assertEqual(report['integrity'], 'ok')
            self.assertTrue((project / 'project.json').is_file())
            self.assertGreater((project / 'smoke-test.png').stat().st_size, 0)
