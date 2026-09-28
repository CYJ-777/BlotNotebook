"""Integration coverage for the UI and archive changes merged into main."""
import csv
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication
from app import MainWindow, STYLE, asset_path
from core import Store, export_csv, uid
from test_core import example


class MergeTests(unittest.TestCase):
    def test_new_calculation_can_copy_independent_groups(self):
        application = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory:
            window = MainWindow(directory)
            try:
                experiment = example()
                gapdh = dict(
                    id=uid(), name='GAPDH', label='', source_ids=[], imports=[],
                    values={str(lane): 25.0 for lane in range(1, 5)},
                )
                tubulin = dict(
                    id=uid(), name='Tubulin', label='', source_ids=[], imports=[],
                    values={str(lane): 40.0 for lane in range(1, 5)},
                )
                experiment['proteins'].extend([gapdh, tubulin])
                window.exp = experiment
                window.store.save(experiment)
                window.render()
                source = experiment['analyses'][0]
                self.assertEqual(set(window.copy_group_checks), {g['id'] for g in source['groups']})
                self.assertTrue(all(check.isChecked() for check in window.copy_group_checks.values()))
                self.assertIn('EGFR', window.copy_groups_title.text())
                window.copy_group_checks[source['groups'][1]['id']].setChecked(False)
                window.numerator.setCurrentIndex(window.numerator.findData(source['num']))
                window.denominator.setCurrentIndex(window.denominator.findData(gapdh['id']))
                window.add_analysis()
                copied = window.analysis()
                self.assertEqual(copied['num'], source['num'])
                self.assertEqual(copied['den'], gapdh['id'])
                self.assertEqual(
                    [(g['name'], g['lanes'], g['ref']) for g in copied['groups']],
                    [(g['name'], g['lanes'], g['ref']) for g in source['groups'][:1]],
                )
                self.assertTrue(
                    set(g['id'] for g in copied['groups']).isdisjoint(g['id'] for g in source['groups'])
                )
                copied['groups'][0]['lanes'].append(4)
                self.assertNotEqual(copied['groups'][0]['lanes'], source['groups'][0]['lanes'])
                window.numerator.setCurrentIndex(window.numerator.findData(source['num']))
                window.denominator.setCurrentIndex(window.denominator.findData(tubulin['id']))
                window.clear_copy_groups()
                window.add_analysis()
                self.assertEqual(window.analysis()['groups'], [])
            finally:
                window.close()
                window.deleteLater()
                application.processEvents()

    def test_overlapping_groups_export_their_own_reference(self):
        e = example()
        e['analyses'][0]['groups'][1]['lanes'] = [1, 3, 4]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'results.csv'
            export_csv(e, path)
            with path.open(encoding='utf-8-sig', newline='') as stream:
                rows = list(csv.reader(stream))
            group_b = next(r for r in rows if r[0] == 'Relative expression' and r[7] == 'B')
            self.assertEqual(group_b[11:], ['0.5', '', '1.0', '0.25'])

    def test_partial_archive_rename_failure_restores_files_and_json(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = Store(root / 'library')
            try:
                e = example()
                for name in ['one.tif', 'two.tif']:
                    source = root / name
                    source.write_bytes(name.encode())
                    e['files'].append(store.archive_file(e, source))
                store.save(e)
                before = [f['archive'] for f in e['files']]
                e['proteins'][0]['source_ids'] = [f['id'] for f in e['files']]
                original_rename = Path.rename
                calls = []

                def fail_second(path, target):
                    calls.append(path)
                    if len(calls) == 2:
                        raise OSError('Simulated rename failure')
                    return original_rename(path, target)

                with patch.object(Path, 'rename', fail_second), self.assertRaises(OSError):
                    store.save(e)
                self.assertEqual([f['archive'] for f in e['files']], before)
                self.assertEqual([f['archive'] for f in store.load(e['id'])['files']], before)
                for f in e['files']:
                    self.assertEqual(store.archived_path(f).read_bytes(), f['filename'].encode())
            finally:
                store.close()

    def test_group_filter_range_clipboard_and_icons(self):
        application = QApplication.instance() or QApplication([])
        application.setStyleSheet(STYLE)
        with tempfile.TemporaryDirectory() as directory:
            window = MainWindow(directory)
            try:
                e = example()
                e['analyses'][0]['groups'][1].update(lanes=[3, 4], ref=1)
                window.exp = e
                window.store.save(e)
                window.render()
                window.tabs.setCurrentIndex(2)
                window.group_filter.setCurrentIndex(window.group_filter.findText('B'))
                application.processEvents()
                self.assertEqual(window.results.rowCount(), 2)
                self.assertEqual(set(window.lane_checks), {3, 4})
                window.copy_relative(False)
                self.assertEqual(application.clipboard().text(), '2.000\t0.500')
                window.from_lane.setValue(4)
                window.to_lane.setValue(4)
                window.apply_lane_range()
                window.copy_relative(False)
                self.assertEqual(application.clipboard().text(), '0.500')
                window.clear_lane_selection()
                self.assertFalse(window.copy_values_button.isEnabled())
                window.select_all_lanes()
                self.assertEqual(window.relative_table.columnCount(), 2)
                self.assertFalse(window.windowIcon().isNull())
                self.assertTrue(asset_path('blotnotebook-seal.ico').is_file())
                self.assertFalse(window.grab().isNull())
            finally:
                application.clipboard().clear()
                window.close()
                window.deleteLater()
                application.processEvents()

    def test_switch_project_replaces_store_and_updates_recent_projects(self):
        application = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / 'First'
            second = Path(directory) / 'Second'
            settings = Mock()
            settings.value.return_value = []
            window = MainWindow(first, settings)
            try:
                with (
                    patch('app.choose_project', return_value=second),
                    patch('app.default_project_path', return_value=Path(directory) / 'Default'),
                ):
                    window.switch_project()
                self.assertEqual(window.store.root, second.resolve())
                self.assertTrue((second / 'project.json').is_file())
                self.assertEqual(window.project_name.text(), 'Second')
                self.assertEqual(json.loads(settings.setValue.call_args.args[1]), [str(second.resolve())])
            finally:
                window.close()
                window.deleteLater()
                application.processEvents()
