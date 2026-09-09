"""Verify project selection and recent-project settings without touching user data."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import app
from core import Store


class ProjectSelectionTests(unittest.TestCase):
    def _launch(self, directory, selected=None, explicit=None, settings_values=None):
        settings_values = settings_values or {}
        settings = Mock()
        settings.value.side_effect = lambda key, default=None: settings_values.get(key, default)
        window = Mock()
        opened = []

        def open_project(root, application_settings):
            store = Store(root)
            opened.append(store.root)
            store.close()
            return window

        argv = ['app.py'] + (['--project', str(explicit)] if explicit else [])
        default = Path(directory) / 'Documents' / 'BlotNotebook'
        with (
            patch.object(app.sys, 'argv', argv),
            patch.object(app, 'QApplication') as application,
            patch.object(app, 'QIcon'),
            patch.object(app, 'QSettings', return_value=settings),
            patch.object(app, 'default_project_path', return_value=default),
            patch.object(app, 'choose_project', return_value=selected) as chooser,
            patch.object(app, 'MainWindow', side_effect=open_project),
            patch.object(app.QMessageBox, 'critical') as error,
        ):
            application.return_value.exec.return_value = 0
            result = app.main()
        return result, opened, settings, window, chooser, error, default

    def test_startup_chooses_project_and_remembers_it(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            selected = Path(directory) / 'Project A'
            selected.mkdir()
            result, opened, settings, window, chooser, error, default = self._launch(
                directory, selected=selected,
            )
            self.assertEqual(result, 0)
            self.assertEqual(opened, [selected.resolve()])
            self.assertTrue((selected / 'project.json').is_file())
            chooser.assert_called_once_with(None, settings, default)
            key, value = settings.setValue.call_args.args
            self.assertEqual(key, app.RECENT_PROJECTS_KEY)
            self.assertEqual(json.loads(value), [str(selected.resolve())])
            window.show.assert_called_once()
            error.assert_not_called()

    def test_explicit_project_bypasses_chooser_and_recent_settings(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            explicit = Path(directory) / 'override'
            result, opened, settings, _, chooser, error, _ = self._launch(directory, explicit=explicit)
            self.assertEqual(result, 0)
            self.assertEqual(opened, [explicit.resolve()])
            chooser.assert_not_called()
            settings.setValue.assert_not_called()
            error.assert_not_called()

    def test_cancel_project_chooser_exits_without_creating_project(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            result, opened, settings, window, chooser, error, _ = self._launch(directory, selected=None)
            self.assertEqual(result, 0)
            self.assertEqual(opened, [])
            chooser.assert_called_once()
            settings.setValue.assert_not_called()
            window.show.assert_not_called()
            error.assert_not_called()

    def test_recent_projects_are_deduplicated_and_include_legacy_library(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            root = Path(directory)
            newest = root / 'Newest'
            legacy = root / 'Legacy'
            newest.mkdir()
            legacy.mkdir()
            settings = Mock()
            settings.value.side_effect = lambda key, default=None: {
                app.RECENT_PROJECTS_KEY: json.dumps([str(newest), str(legacy), str(newest)]),
                app.LEGACY_LIBRARY_KEY: str(legacy),
            }.get(key, default)
            self.assertEqual(app.recent_projects(settings), [str(newest.resolve()), str(legacy.resolve())])

    def test_remember_project_keeps_only_ten_paths(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            roots = []
            for index in range(12):
                path = Path(directory) / str(index)
                path.mkdir()
                roots.append(path)
            settings = Mock()
            settings.value.side_effect = lambda key, default=None: (
                json.dumps([str(path) for path in roots]) if key == app.RECENT_PROJECTS_KEY else default
            )
            app.remember_project(settings, roots[-1])
            saved = json.loads(settings.setValue.call_args.args[1])
            self.assertEqual(saved[0], str(roots[-1].resolve()))
            self.assertEqual(len(saved), 10)


if __name__ == '__main__':
    unittest.main()
