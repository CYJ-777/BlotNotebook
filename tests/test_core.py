import copy
import csv
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
        self.s.db.close()
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
        self.assertTrue(any(h['kind'] == 'raw_value' and h['old_value'] == '60.0' and h['new_value'] == '70' for h in self.s.history(e['id'])))
        with self.assertRaises(ValueError):
            self.s.save(stale)
        self.assertEqual(self.s.load(e['id'])['proteins'][0]['values']['2'], 70)
        self.assertEqual(self.s.db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')

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
        import shutil
        self.s.db.close()
        shutil.copytree(self.root / 'library', self.root / 'moved')
        self.s = Store(self.root / 'moved')
        loaded = self.s.load(e['id'])
        self.assertEqual(self.s.archived_path(loaded['files'][0]).read_bytes(), b'original exposure 1')
        self.assertEqual(self.s.archived_path(loaded['files'][1]).read_bytes(), b'original exposure 2')

    def test_new_archives_are_flat_and_same_names_get_stable_suffixes(self):
        e = example()
        first_source = self.root / 'first.tif'
        second_source = self.root / 'second.tif'
        first_source.write_bytes(b'first')
        second_source.write_bytes(b'second')
        first = self.s.archive_file(e, first_source)
        second = self.s.archive_file(e, second_source)
        self.assertEqual(Path(first['archive']).parts[-2], 'originals')
        self.assertEqual(Path(second['archive']).parts[-2], 'originals')
        self.assertNotEqual(first['archive'], second['archive'])
        self.assertEqual(self.s.archived_path(first).read_bytes(), b'first')
        self.assertEqual(self.s.archived_path(second).read_bytes(), b'second')

    def test_migrates_nested_attachment_folder_to_flat_archive(self):
        e = example()
        source = self.root / 'nested.tif'
        source.write_bytes(b'nested bytes')
        f = self.s.archive_file(e, source)
        e['files'] = [f]
        self.s.save(e)
        flat = self.s.archived_path(f)
        nested = flat.parent / f['id'] / flat.name
        nested.parent.mkdir()
        flat.rename(nested)
        legacy_archive = f"experiments/{e['folder']}/originals/{f['id']}/{flat.name}"
        self.s.db.execute('UPDATE original_files SET archive=? WHERE id=?', (legacy_archive, f['id']))
        self.s.db.commit()
        self.s.db.close()
        self.s = Store(self.root / 'library')
        loaded = self.s.load(e['id'])
        migrated = loaded['files'][0]
        self.assertEqual(Path(migrated['archive']).parts[-2], 'originals')
        self.assertNotIn(f['id'], Path(migrated['archive']).parts)
        self.assertEqual(self.s.archived_path(migrated).read_bytes(), b'nested bytes')

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
        import json
        removals = [h for h in self.s.history(e['id']) if h['kind'] == 'file_removed']
        self.assertEqual(len(removals), 1)
        self.assertEqual(json.loads(removals[0]['old_value'])['id'], first['id'])
        self.assertEqual(removals[0]['new_value'], 'null')
        self.assertEqual(list(self.s.db.execute('PRAGMA foreign_key_check')), [])
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
        self.assertEqual(list(self.s.db.execute('PRAGMA foreign_key_check')), [])
        self.assertEqual(self.s.db.execute('SELECT COUNT(*) FROM audit_log WHERE experiment_id=?', (e['id'],)).fetchone()[0], 0)
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

    def test_migrates_legacy_archive_folder(self):
        e = example()
        e.update(id='261583e2-0000-0000-0000-000000000000', date='2026-09-08', cell='PC9', condition='MG132')
        source = self.root / 'legacy.tif'
        source.write_bytes(b'legacy bytes')
        f = self.s.archive_file(e, source)
        e['files'] = [f]
        self.s.save(e)
        readable = e['folder']
        old_dir = self.root / 'library' / 'experiments' / readable
        legacy_dir = self.root / 'library' / 'experiments' / e['id']
        old_dir.rename(legacy_dir)
        legacy_archive = f"experiments/{e['id']}/originals/{f['id']}/legacy.tif"
        legacy_file = legacy_dir / 'originals' / f['id'] / 'legacy.tif'
        legacy_file.parent.mkdir()
        (legacy_dir / 'originals' / Path(f['archive']).name).rename(legacy_file)
        self.s.db.execute("UPDATE experiments SET folder=NULL WHERE id=?", (e['id'],))
        self.s.db.execute("UPDATE original_files SET archive=? WHERE id=?", (legacy_archive, f['id']))
        self.s.db.commit()
        self.s.db.close()
        self.s = Store(self.root / 'library')
        loaded = self.s.load(e['id'])
        self.assertTrue(loaded['folder'])
        self.assertTrue((self.root / 'library' / 'experiments' / loaded['folder']).exists())
        self.assertEqual(self.s.archived_path(loaded['files'][0]).read_bytes(), b'legacy bytes')


if __name__ == '__main__':
    unittest.main()
