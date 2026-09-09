"""Verify first-launch storage selection without touching user settings or data."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import app
from core import Store


class LibraryDefaultsTests(unittest.TestCase):
    def _launch(self, directory, saved=None, explicit=None, documents=None):
        settings = Mock()
        settings.value.return_value = saved
        window = Mock()
        opened = []

        def open_library(root):
            store = Store(root)
            opened.append(store.root)
            store.db.close()
            return window

        argv = ['app.py'] + (['--library', str(explicit)] if explicit else [])
        with (
            patch.object(app.sys, 'argv', argv),
            patch.object(app, 'QApplication') as application,
            patch.object(app, 'QIcon'),
            patch.object(app, 'QSettings', return_value=settings),
            patch.object(app.QStandardPaths, 'writableLocation', return_value=(
                str(Path(directory) / 'Documents') if documents is None else documents
            )) as location,
            patch.object(app, 'MainWindow', side_effect=open_library),
            patch.object(app.QFileDialog, 'getExistingDirectory') as picker,
            patch.object(app.QMessageBox, 'critical') as error,
        ):
            application.return_value.exec.return_value = 0
            result = app.main()
        picker.assert_not_called()
        return result, opened, settings, window, location, error

    def test_first_launch_creates_documents_library_and_remembers_it(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            result, opened, settings, window, location, error = self._launch(directory)
            expected = Path(directory) / 'Documents' / 'BlotNotebook'
            self.assertEqual(result, 0)
            self.assertEqual(opened, [expected.resolve()])
            self.assertTrue((expected / 'wbquant.sqlite3').is_file())
            settings.setValue.assert_called_once_with('library', str(expected.resolve()))
            location.assert_called_once_with(app.QStandardPaths.StandardLocation.DocumentsLocation)
            window.show.assert_called_once()
            error.assert_not_called()

    def test_saved_library_is_preserved(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            saved = Path(directory) / 'existing'
            result, opened, _, _, location, error = self._launch(directory, saved=str(saved))
            self.assertEqual(result, 0)
            self.assertEqual(opened, [saved.resolve()])
            location.assert_not_called()
            error.assert_not_called()

    def test_explicit_library_overrides_saved_without_changing_setting(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            explicit = Path(directory) / 'override'
            result, opened, settings, _, location, error = self._launch(
                directory, saved=str(Path(directory) / 'saved'), explicit=explicit,
            )
            self.assertEqual(result, 0)
            self.assertEqual(opened, [explicit.resolve()])
            settings.setValue.assert_not_called()
            location.assert_not_called()
            error.assert_not_called()

    def test_unavailable_documents_reports_error_without_remembering_path(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            result, opened, settings, window, _, error = self._launch(directory, documents='')
            self.assertEqual(result, 1)
            self.assertEqual(opened, [])
            settings.setValue.assert_not_called()
            window.show.assert_not_called()
            error.assert_called_once()

    def test_creation_failure_reports_error_without_remembering_path(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            (Path(directory) / 'Documents').write_text('A file blocks directory creation')
            result, opened, settings, window, _, error = self._launch(directory)
            self.assertEqual(result, 1)
            self.assertEqual(opened, [])
            settings.setValue.assert_not_called()
            window.show.assert_not_called()
            error.assert_called_once()
