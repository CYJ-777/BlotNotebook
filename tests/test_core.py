import copy
import csv
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from core import Store, fresh, uid, now, number, parse_biorad, calculate, calculate_group, export_csv, validate, remove_attachment, experiment_folder, archive_display_name


def example():
    e = fresh()
    e.update(cell='A549', condition='shRNA test')
    e['lanes'] = [dict(number=i + 1, name=n) for i, n in enumerate(['shLuc', 'shA', 'shLuc', 'shB'])]
    for name, values in [('EGFR', [100, 60, 200, 50]), ('ACTB', [50, 50, 50, 50])]:
        e['proteins'].append(dict(id=uid(), name=name, label='', source_ids=[], imports=[],
                                  values={str(i + 1): v for i, v in enumerate(values)}))
    e['analyses'] = [dict(id=uid(), num=e['proteins'][0]['id'], den=e['proteins'][1]['id'], groups=[
        dict(id=uid(), name='A', lanes=[1, 2], ref=1), dict(id=uid(), name='B', lanes=[3, 4], ref=3)])]
    return e


class ParsingTests(unittest.TestCase):
    def test_real_header_and_preamble(self):
        text = '260428-1 EGFRcs\n2026-04-29 exposure\nLane No.\tAdj. Total Band Vol. (Int)\tTotal Band Vol. (Int)\n1\t2908950\t3781107\n2\t1059916\t1769802'
        self.assertEqual(parse_biorad(text), {'1': 2908950, '2': 1059916})

    def test_noncontiguous_out_of_order_and_scientific(self):
        self.assertEqual(parse_biorad('Lane\tAdj. Total Band Vol. (Int)\nLane 4\t1.2e3\nLane 2\t-5'), {'2': -5, '4': 1200})

    def test_other_column_and_csv(self):
        self.assertEqual(parse_biorad('Lane No.,Other\n1,"1,234"', 'Other'), {'1': 1234})

    def test_reject_duplicate_missing_nonfinite_and_combined_tables(self):
        for body in ['1\t3\n1\t4', '1\t', '1\tN/A', '1\tNaN', '1\tInf', '1\t3\nLane No.\tAdj. Total Band Vol. (Int)', '1\t3\nTotal\t3']:
            with self.subTest(body=body), self.assertRaises(ValueError):
                parse_biorad('Lane No.\tAdj. Total Band Vol. (Int)\n' + body)

    def test_numbers(self):
        self.assertEqual(number('1,234.56'), 1234.56)
        self.assertIsNone(number(''))
        with self.assertRaises(ValueError):
            number('1,23')


class CalculationTests(unittest.TestCase):
    def test_independent_duplicate_named_references(self):
        e = example()
        result = calculate(e, e['analyses'][0])
        self.assertEqual([r['ratio'] for r in result], [2, 1.2, 4, 1])
        self.assertEqual([r['relative'] for r in result], [1, .6, 1, .25])

    def test_larger_groups_and_phosphorylation(self):
        e = example()
        e['proteins'][0]['name'] = 'pEGFR'
        e['proteins'][1]['name'] = 'EGFR'
        e['analyses'][0]['groups'] = [dict(id=uid(), name='A', lanes=[1, 2, 3], ref=1)]
        result = calculate(e, e['analyses'][0])
        self.assertEqual([r['relative'] for r in result], [1, .6, 2, None])
        self.assertEqual(result[3]['status'], 'No normalization group')

    def test_zero_and_missing_are_not_zero_results(self):
        e = example()
        e['proteins'][1]['values']['1'] = 0
        e['proteins'][0]['values']['3'] = None
        result = calculate(e, e['analyses'][0])
        self.assertTrue(all(r['relative'] is None for r in result))
        self.assertEqual(result[0]['status'], 'Zero denominator')
        self.assertIn('Reference', result[1]['status'])

    def test_zero_reference_ratio_and_negative_warning(self):
        e = example()
        e['proteins'][0]['values']['1'] = 0
        e['proteins'][0]['values']['4'] = -50
        result = calculate(e, e['analyses'][0])
        self.assertEqual(result[1]['status'], 'Zero reference ratio')
        self.assertEqual(result[3]['relative'], -.25)
        self.assertIn('Negative', result[3]['status'])

    def test_invalid_group_configuration(self):
        e = example()
        e['analyses'][0]['groups'][0]['ref'] = 99
        with self.assertRaises(ValueError):
            validate(e)

    def test_overlapping_group_membership_is_allowed(self):
        e = example()
        e['analyses'][0]['groups'] = [
            dict(id=uid(), name='A', lanes=[1, 2, 3], ref=1),
            dict(id=uid(), name='B', lanes=[1, 4], ref=1),
        ]
        validate(e)
        result = calculate(e, e['analyses'][0])
        by_lane = {r['lane']: r for r in result}
        self.assertEqual(by_lane[1]['relative'], 1)
        self.assertEqual(by_lane[2]['relative'], .6)
        self.assertEqual(by_lane[4]['relative'], .5)

    def test_group_can_reference_a_lane_outside_its_members(self):
        e = example()
        group = dict(id=uid(), name='B', lanes=[3, 4], ref=1)
        e['analyses'][0]['groups'] = [group]
        validate(e)
        result = calculate_group(e, e['analyses'][0], group)
        self.assertEqual([row['lane'] for row in result], [3, 4])
        self.assertEqual([row['relative'] for row in result], [2, .5])
        self.assertTrue(all(row['reference'] == 1 for row in result))


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.s = Store(self.root / 'library')

    def tearDown(self):
        self.s.close()
        self.tmp.cleanup()

    def test_roundtrip_search_audit_and_optimistic_lock(self):
        e = example()
        e['proteins'][0]['imports'] = [dict(id=uid(), added=now(), column='Example', text='Original pasted text')]
        self.s.save(e)
        self.assertEqual(self.s.load(e['id']), e)
        for query in ['A549', 'EGFR', 'shA', 'shRNA', e['date'], 'A549 EGFR']:
            self.assertEqual(len(self.s.search(query)), 1)
        stale = copy.deepcopy(e)
        e['proteins'][0]['values']['2'] = 70
        self.s.save(e)
        self.assertTrue(any(
            h['kind'] == 'raw_value'
            and json.loads(h['old_value']) == 60
            and json.loads(h['new_value']) == 70
            for h in self.s.history(e['id'])
        ))
        with self.assertRaises(ValueError):
            self.s.save(stale)
        self.assertEqual(self.s.load(e['id'])['proteins'][0]['values']['2'], 70)
        self.assertEqual(self.s.healthcheck(), 'ok')
        document = self.root / 'library' / 'experiments' / e['folder'] / 'experiment.json'
        self.assertTrue(document.is_file())
        self.assertFalse((self.root / 'library' / 'wbquant.sqlite3').exists())
        self.assertTrue(document.with_name('experiment.json.bak').is_file())
        record = json.loads(document.read_text(encoding='utf-8'))
        self.assertEqual(record['schema_version'], 1)
        self.assertEqual(record['experiment']['id'], e['id'])

    def test_project_write_lock_rejects_concurrent_save(self):
        e = example()
        with self.s._write_lock(), self.assertRaisesRegex(ValueError, 'another window'):
            self.s.save(e)
        self.assertIsNone(self.s.load(e['id']))

    def test_archive_same_filename_and_relocation(self):
        e = example()
        for folder, contents in [('a', b'original exposure 1'), ('b', b'original exposure 2')]:
            source = self.root / folder / 'original.tif'
            source.parent.mkdir()
            source.write_bytes(contents)
            e['files'].append(self.s.archive_file(e, source))
        e['proteins'][0]['source_ids'] = [f['id'] for f in e['files']]
        self.s.save(e)
        self.assertNotEqual(e['files'][0]['archive'], e['files'][1]['archive'])
        self.assertEqual([f['filename'] for f in e['files']], ['original.tif', 'original.tif'])
        self.assertTrue(all(Path(f['archive']).parts[-2] == 'originals' for f in e['files']))
        self.assertTrue(all(f['id'] not in Path(f['archive']).parts for f in e['files']))
        import shutil
        self.s.close()
        shutil.copytree(self.root / 'library', self.root / 'moved')
        self.s = Store(self.root / 'moved')
        loaded = self.s.load(e['id'])
        self.assertEqual(self.s.archived_path(loaded['files'][0]).read_bytes(), b'original exposure 1')
        self.assertEqual(self.s.archived_path(loaded['files'][1]).read_bytes(), b'original exposure 2')

    def test_migrates_nested_json_archive_to_flat_layout(self):
        e = example()
        source = self.root / 'nested.tif'
        source.write_bytes(b'nested bytes')
        attachment = self.s.archive_file(e, source)
        e['files'] = [attachment]
        self.s.save(e)
        document = self.root / 'library' / 'experiments' / e['folder'] / 'experiment.json'
        flat = self.s.archived_path(attachment)
        nested = flat.parent / attachment['id'] / flat.name
        nested.parent.mkdir()
        flat.rename(nested)
        record = json.loads(document.read_text(encoding='utf-8'))
        nested_relative = nested.relative_to(self.s.root).as_posix()
        record['experiment']['files'][0]['archive'] = nested_relative
        document.write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

        self.s = Store(self.root / 'library')
        migrated = self.s.load(e['id'])['files'][0]
        self.assertEqual(Path(migrated['archive']).parts[-2], 'originals')
        self.assertNotIn(attachment['id'], Path(migrated['archive']).parts)
        self.assertEqual(self.s.archived_path(migrated).read_bytes(), b'nested bytes')
        self.assertFalse(nested.exists())

    def test_linked_archive_renames_without_touching_original_or_ids(self):
        e = example()
        source = self.root / 'raw.tif'
        source.write_bytes(b'original exposure')
        attachment = self.s.archive_file(e, source)
        attachment['filename'] = 'unreadable:name?.tif'
        e['files'] = [attachment]
        self.s.save(e)
        before_id, before_archive = attachment['id'], attachment['archive']
        e['proteins'][0]['source_ids'] = [before_id]
        self.s.save(e)
        self.assertEqual(attachment['id'], before_id)
        self.assertNotEqual(attachment['archive'], before_archive)
        self.assertTrue(Path(attachment['archive']).name.startswith('EGFR__'))
        self.assertEqual(source.read_bytes(), b'original exposure')
        self.assertEqual(self.s.archived_path(attachment).read_bytes(), b'original exposure')
        e['proteins'][1]['source_ids'] = [before_id]
        self.s.save(e)
        self.assertTrue(Path(attachment['archive']).name.startswith('EGFR+ACTB__'))
        loaded = self.s.load(e['id'])
        self.assertEqual(loaded['files'][0]['id'], before_id)
        self.assertEqual(self.s.archived_path(loaded['files'][0]).read_bytes(), b'original exposure')

    def test_archive_display_name_is_cross_platform_safe(self):
        f = dict(id='a', filename='CON?.tif')
        proteins = [dict(name='p/EGFR*', source_ids=['a'])]
        name = archive_display_name(f, proteins)
        self.assertEqual(name, 'pEGFR___CON.tif')
        self.assertNotRegex(name, r'[\\/:*?"<>|]')

    def test_export_horizontal_raw_relative_and_formula_escaping(self):
        e = example()
        e['cell'] = '=1+1'
        path = self.root / 'export.csv'
        export_csv(e, path)
        with path.open(encoding='utf-8-sig', newline='') as stream:
            rows = list(csv.reader(stream))
        self.assertEqual(rows[0][-4:], ['L1 | shLuc', 'L2 | shA', 'L3 | shLuc', 'L4 | shB'])
        self.assertEqual(rows[1][3], "'=1+1")
        relative = [r for r in rows if r[0] == 'Relative expression']
        self.assertEqual(relative[0][-4:], ['1.0', '0.6', '', ''])
        self.assertEqual(relative[1][-4:], ['', '', '1.0', '0.25'])

    def test_remove_attachment_unlinks_only_selected_id_and_preserves_history(self):
        e = example()
        source = self.root / 'wrong-upload.tif'
        source.write_bytes(b'original bytes')
        first = self.s.archive_file(e, source)
        second = self.s.archive_file(e, source)
        e['files'] = [first, second]
        for p in e['proteins']:
            p['source_ids'] = [first['id'], second['id']]
        self.s.save(e)
        expected = calculate(e, e['analyses'][0])
        remove_attachment(e, first['id'])
        self.s.save(e)
        loaded = self.s.load(e['id'])
        self.assertEqual([f['id'] for f in loaded['files']], [second['id']])
        self.assertTrue(all(p['source_ids'] == [second['id']] for p in loaded['proteins']))
        self.assertEqual(calculate(loaded, loaded['analyses'][0]), expected)
        self.assertEqual(source.read_bytes(), b'original bytes')
        self.assertEqual(self.s.archived_path(first).read_bytes(), b'original bytes')
        removals = [h for h in self.s.history(e['id']) if h['kind'] == 'file_removed']
        self.assertEqual(len(removals), 1)
        self.assertEqual(json.loads(removals[0]['old_value'])['id'], first['id'])
        self.assertEqual(removals[0]['new_value'], 'null')
        self.assertEqual(self.s.healthcheck(), 'ok')
        snapshot = copy.deepcopy(e)
        with self.assertRaises(ValueError):
            remove_attachment(e, first['id'])
        self.assertEqual(e, snapshot)

    def test_delete_experiment_removes_records_and_archive(self):
        e = example()
        source = self.root / 'delete-me.tif'
        source.write_bytes(b'archive bytes')
        f = self.s.archive_file(e, source)
        e['files'] = [f]
        e['proteins'][0]['source_ids'] = [f['id']]
        self.s.save(e)
        archive_dir = self.root / 'library' / 'experiments' / e['folder']
        self.assertTrue(archive_dir.exists())
        self.s.delete(e['id'])
        self.assertIsNone(self.s.load(e['id']))
        self.assertFalse(archive_dir.exists())
        with self.assertRaises(ValueError):
            self.s.delete(e['id'])

    def test_experiment_folder_is_readable_and_sanitized(self):
        e = fresh()
        e.update(id='261583e2-0000-0000-0000-000000000000', date='2026-09-08', cell='PC9', condition='MG132')
        self.assertEqual(experiment_folder(e), '2026-09-08_PC9_MG132_261583e2')
        e['cell'] = 'PC9/2*'
        self.assertEqual(experiment_folder(e), '2026-09-08_PC92_MG132_261583e2')

    def test_archive_folder_is_stable_after_metadata_change(self):
        e = example()
        e.update(id='261583e2-0000-0000-0000-000000000000', date='2026-09-08', cell='PC9', condition='MG132')
        source = self.root / 'blot.tif'
        source.write_bytes(b'stable bytes')
        f = self.s.archive_file(e, source)
        e['files'] = [f]
        self.s.save(e)
        folder_before = e['folder']
        e['cell'] = 'PC10'
        self.s.save(e)
        loaded = self.s.load(e['id'])
        self.assertEqual(loaded['folder'], folder_before)
        self.assertEqual(self.s.archived_path(loaded['files'][0]).read_bytes(), b'stable bytes')

    def test_imports_legacy_sqlite_without_modifying_database(self):
        """Import all relational records while preserving the source database byte-for-byte."""
        legacy_root = self.root / 'legacy-library'
        legacy_root.mkdir()
        database = legacy_root / 'wbquant.sqlite3'
        e = example()
        e.update(folder='legacy-folder', revision=4)
        attachment_id = uid()
        nested_relative = Path('experiments') / e['folder'] / 'originals' / attachment_id / 'legacy.tif'
        nested_source = legacy_root / nested_relative
        nested_source.parent.mkdir(parents=True)
        nested_source.write_bytes(b'legacy bytes')
        attachment = {
            'id': attachment_id, 'filename': 'legacy.tif',
            'original_path': '/old/computer/legacy.tif', 'extension': '.tif',
            'added': now(), 'archive': nested_relative.as_posix(),
            'sha256': hashlib.sha256(b'legacy bytes').hexdigest(),
        }
        e['files'] = [attachment]
        e['proteins'][0]['source_ids'] = [attachment_id]
        connection = sqlite3.connect(database)
        connection.executescript('''
            PRAGMA user_version=2;
            CREATE TABLE experiments(id TEXT PRIMARY KEY,date TEXT,cell TEXT,condition TEXT,notes TEXT,created TEXT,updated TEXT,revision INTEGER,folder TEXT);
            CREATE TABLE lanes(experiment_id TEXT,number INTEGER,name TEXT);
            CREATE TABLE protein_rows(id TEXT,experiment_id TEXT,name TEXT,label TEXT,position INTEGER);
            CREATE TABLE raw_values(protein_id TEXT,lane INTEGER,value REAL);
            CREATE TABLE imports(id TEXT,protein_id TEXT,added TEXT,column_name TEXT,raw_text TEXT);
            CREATE TABLE original_files(id TEXT,experiment_id TEXT,filename TEXT,original_path TEXT,extension TEXT,added TEXT,archive TEXT,sha256 TEXT);
            CREATE TABLE protein_sources(protein_id TEXT,file_id TEXT);
            CREATE TABLE normalization_sets(id TEXT,experiment_id TEXT,numerator TEXT,denominator TEXT,position INTEGER);
            CREATE TABLE normalization_groups(id TEXT,set_id TEXT,name TEXT,reference_lane INTEGER,position INTEGER);
            CREATE TABLE group_members(group_id TEXT,lane INTEGER);
            CREATE TABLE audit_log(id INTEGER PRIMARY KEY,experiment_id TEXT,changed TEXT,kind TEXT,object_key TEXT,old_value TEXT,new_value TEXT);
        ''')
        connection.execute('INSERT INTO experiments VALUES(?,?,?,?,?,?,?,?,?)',
                           (e['id'], e['date'], e['cell'], e['condition'], e['notes'], e['created'], e['updated'], e['revision'], e['folder']))
        connection.executemany('INSERT INTO lanes VALUES(?,?,?)',
                               [(e['id'], lane['number'], lane['name']) for lane in e['lanes']])
        for position, protein in enumerate(e['proteins']):
            connection.execute('INSERT INTO protein_rows VALUES(?,?,?,?,?)',
                               (protein['id'], e['id'], protein['name'], protein['label'], position))
            connection.executemany('INSERT INTO raw_values VALUES(?,?,?)',
                                   [(protein['id'], int(lane), value) for lane, value in protein['values'].items()])
            connection.executemany('INSERT INTO protein_sources VALUES(?,?)',
                                   [(protein['id'], file_id) for file_id in protein['source_ids']])
        connection.execute('INSERT INTO original_files VALUES(?,?,?,?,?,?,?,?)',
                           (attachment['id'], e['id'], attachment['filename'], attachment['original_path'],
                            attachment['extension'], attachment['added'], attachment['archive'], attachment['sha256']))
        for position, analysis in enumerate(e['analyses']):
            connection.execute('INSERT INTO normalization_sets VALUES(?,?,?,?,?)',
                               (analysis['id'], e['id'], analysis['num'], analysis['den'], position))
            for group_position, group in enumerate(analysis['groups']):
                connection.execute('INSERT INTO normalization_groups VALUES(?,?,?,?,?)',
                                   (group['id'], analysis['id'], group['name'], group['ref'], group_position))
                connection.executemany('INSERT INTO group_members VALUES(?,?)',
                                       [(group['id'], lane) for lane in group['lanes']])
        connection.commit()
        connection.close()
        before = hashlib.sha256(database.read_bytes()).hexdigest()

        imported = Store(legacy_root)
        loaded = imported.load(e['id'])
        expected = copy.deepcopy(e)
        flattened_name = archive_display_name(expected['files'][0], expected['proteins'])
        expected['files'][0]['archive'] = f"experiments/{e['folder']}/originals/{flattened_name}"
        self.assertEqual(loaded, expected)
        self.assertEqual(imported.project['migrated_from'], 'wbquant.sqlite3')
        self.assertTrue((legacy_root / 'project.json').is_file())
        self.assertTrue((legacy_root / 'experiments' / e['folder'] / 'experiment.json').is_file())
        self.assertEqual(hashlib.sha256(database.read_bytes()).hexdigest(), before)
        self.assertTrue(nested_source.is_file())
        self.assertEqual(imported.archived_path(loaded['files'][0]).read_bytes(), b'legacy bytes')

    def test_rejects_invalid_or_newer_project_json(self):
        for payload in [
            {'format': 'something-else', 'schema_version': 1},
            {'format': 'blot-notebook-project', 'schema_version': 999},
        ]:
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as directory:
                Path(directory, 'project.json').write_text(json.dumps(payload), encoding='utf-8')
                with self.assertRaises(ValueError):
                    Store(directory)


if __name__ == '__main__':
    unittest.main()
