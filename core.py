"""Offline WB data, strict Bio-Rad parsing, independent normalization and SQLite storage."""
from __future__ import annotations
import csv
import hashlib
import io
import json
import math
import re
import shutil
import sqlite3
import uuid
from datetime import datetime, date, timezone
from pathlib import Path


DEFAULT_COLUMN = 'Adj. Total Band Vol. (Int)'


def uid():
    return str(uuid.uuid4())


def now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


def fresh():
    return dict(id=uid(), date=date.today().isoformat(), cell='', condition='', notes='',
                created=now(), updated=now(), revision=0, folder=None,
                lanes=[], proteins=[], files=[], analyses=[])


def sanitize_part(value):
    text = (value or '').strip()
    text = re.sub(r'[\\/:*?"<>|\x00-\x1f]', '', text)
    text = re.sub(r'\s+', ' ', text).strip(' .')
    if text.upper() in {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}:
        text = '_' + text
    return text


def experiment_folder(e):
    parts = []
    date_part = sanitize_part((e.get('date') or '')[:10])
    if date_part:
        parts.append(date_part)
    for key in ('cell', 'condition'):
        part = sanitize_part(e.get(key))
        if part:
            parts.append(part)
    short = (e.get('id') or '')[:8]
    if short:
        parts.append(short)
    name = '_'.join(parts)
    return name or ('experiment_' + (e.get('id') or '')[:8])


def archive_display_name(file_record, proteins):
    """User-facing copy name; IDs and source metadata remain unchanged."""
    linked = []
    for protein in proteins:
        if file_record['id'] in protein.get('source_ids', []):
            name = sanitize_part(protein.get('name'))
            if name and name not in linked:
                linked.append(name)
    original = Path(file_record['filename'])
    stem = sanitize_part(original.stem) or 'file'
    suffix = sanitize_part(original.suffix.lstrip('.'))
    prefix = '+'.join(linked)
    visible = (f'{prefix}__{stem}' if prefix else stem)[:180].rstrip(' .') or 'file'
    return visible + (f'.{suffix}' if suffix else '')


def number(value):
    text = str(value).strip().replace('\u2212', '-')
    if not text:
        return None
    # Accept only unambiguous comma thousands grouping; do not guess decimal commas.
    if ',' in text:
        if not re.fullmatch(r'[+-]?\d{1,3}(,\d{3})+(\.\d+)?([eE][+-]?\d+)?', text):
            raise ValueError('Ambiguous number. Use a decimal point; commas may separate thousands.')
        text = text.replace(',', '')
    try:
        result = float(text)
    except ValueError:
        raise ValueError(f'Invalid intensity: {value!r}') from None
    if not math.isfinite(result):
        raise ValueError('Intensity must be a finite number.')
    return result


def key(text):
    return re.sub(r'[^a-z0-9]', '', text.lower())


def table_headers(text):
    delimiter = '\t' if '\t' in text else ','
    rows = list(csv.reader(io.StringIO(text.lstrip('\ufeff')), delimiter=delimiter))
    for i, row in enumerate(rows):
        lanes = [j for j, s in enumerate(row) if key(s) in ('lane', 'laneno', 'lanenumber', 'laneid')]
        if len(lanes) == 1:
            headers = [s.strip() for s in row]
            if len(set(headers)) != len(headers):
                raise ValueError('Duplicate or blank repeated column headings. Copy one complete table.')
            return rows, i, lanes[0], headers
    raise ValueError('Lane column not found. Copy the table including its header (for example Lane No.).')


def parse_biorad(text, column=DEFAULT_COLUMN):
    rows, header_row, lane_col, headers = table_headers(text)
    matches = [i for i, h in enumerate(headers) if key(h) == key(column)]
    if len(matches) != 1:
        raise ValueError(f'Intensity column not found: {column}. Select a column from the pasted table.')
    col = matches[0]
    result = {}
    for line, row in enumerate(rows[header_row + 1:], header_row + 2):
        if not any(s.strip() for s in row):
            continue
        if max(col, lane_col) >= len(row):
            raise ValueError(f'Line {line}: incomplete row. Paste only one protein table at a time.')
        lane_text = re.sub(r'^lane\s*', '', row[lane_col].strip(), flags=re.I)
        if not re.fullmatch(r'\d+(?:\.0+)?', lane_text):
            raise ValueError(f'Line {line}: invalid lane. Paste one protein table at a time.')
        lane = int(float(lane_text))
        if lane < 1 or lane > 10000:
            raise ValueError(f'Line {line}: lane number must be between 1 and 10000.')
        if str(lane) in result:
            raise ValueError(f'Lane {lane} occurs more than once. One band per lane is required.')
        try:
            value = number(row[col])
        except ValueError as exc:
            raise ValueError(f'Line {line}: {exc}') from None
        if value is None:
            raise ValueError(f'Line {line}: missing intensity for lane {lane}.')
        result[str(lane)] = value
    if not result:
        raise ValueError('No lane values found below the header.')
    return dict(sorted(result.items(), key=lambda item: int(item[0])))


def label(protein):
    return protein['name'] + (f" [{protein['label']}]" if protein['label'] else '')


def remove_attachment(exp, file_id):
    """Detach a file and its source links; retain archived bytes for audit traceability."""
    if not any(f['id'] == file_id for f in exp['files']):
        raise ValueError('This attachment is no longer in the experiment.')
    exp['files'] = [f for f in exp['files'] if f['id'] != file_id]
    for protein in exp['proteins']:
        protein['source_ids'] = [fid for fid in protein['source_ids'] if fid != file_id]


def validate(exp):
    date.fromisoformat(exp['date'])
    lane_ids = [l['number'] for l in exp['lanes']]
    if len(lane_ids) != len(set(lane_ids)):
        raise ValueError('Lane numbers must be unique.')
    protein_ids = {p['id'] for p in exp['proteins']}
    for p in exp['proteins']:
        if not p['name'].strip():
            raise ValueError('Enter a protein name.')
        for lane, val in p['values'].items():
            if int(lane) not in lane_ids or (val is not None and not math.isfinite(val)):
                raise ValueError('Invalid raw value or lane mapping.')
    for a in exp['analyses']:
        if a['num'] not in protein_ids or a['den'] not in protein_ids:
            raise ValueError('Select existing numerator and denominator rows.')
        for g in a['groups']:
            members = set(g['lanes'])
            if not g['name'].strip() or not members or g['ref'] not in lane_ids:
                raise ValueError('Each group needs a name, members and a reference lane in this experiment.')
            if not members.issubset(set(lane_ids)):
                raise ValueError('Group members must be lanes in this experiment.')


def calculate(exp, analysis):
    proteins = {p['id']: p for p in exp['proteins']}
    num, den = proteins[analysis['num']], proteins[analysis['den']]
    ratios, errors = {}, {}
    for l in exp['lanes']:
        lane = l['number']
        n, d = num['values'].get(str(lane)), den['values'].get(str(lane))
        if n is None or d is None:
            errors[lane] = 'Missing raw intensity'
        elif d == 0:
            errors[lane] = 'Zero denominator'
        else:
            ratio = n / d
            if math.isfinite(ratio):
                ratios[lane] = ratio
            else:
                errors[lane] = 'Ratio overflow'
    group_for_lane = {}
    for g in analysis['groups']:
        for lane in g['lanes']:
            group_for_lane.setdefault(lane, g)
    result = []
    for l in exp['lanes']:
        lane = l['number']
        g = group_for_lane.get(lane)
        relative = None
        status = errors.get(lane, '')
        if not status:
            if not g:
                status = 'No normalization group'
            elif g['ref'] not in ratios:
                status = 'Reference: ' + errors.get(g['ref'], 'missing ratio')
            elif ratios[g['ref']] == 0:
                status = 'Zero reference ratio'
            else:
                relative = ratios[lane] / ratios[g['ref']]
                if not math.isfinite(relative):
                    relative, status = None, 'Relative expression overflow'
                elif num['values'][str(lane)] < 0 or den['values'][str(lane)] < 0:
                    status = 'Negative intensity; review background correction'
                elif num['values'][str(g['ref'])] < 0 or den['values'][str(g['ref'])] < 0:
                    status = 'Negative reference intensity; review background correction'
        result.append(dict(lane=lane, sample=l['name'], ratio=ratios.get(lane), relative=relative,
                           group=g['name'] if g else '', reference=g['ref'] if g else '', status=status or 'OK'))
    return result


def calculate_group(exp, analysis, group):
    """Calculate a group using its own reference, even if that lane is outside the group's members."""
    proteins = {p['id']: p for p in exp['proteins']}
    numerator, denominator = proteins[analysis['num']], proteins[analysis['den']]
    ratios, errors = {}, {}
    for lane_info in exp['lanes']:
        lane = lane_info['number']
        n, d = numerator['values'].get(str(lane)), denominator['values'].get(str(lane))
        if n is None or d is None:
            errors[lane] = 'Missing raw intensity'
        elif d == 0:
            errors[lane] = 'Zero denominator'
        else:
            ratio = n / d
            if math.isfinite(ratio):
                ratios[lane] = ratio
            else:
                errors[lane] = 'Ratio overflow'
    lane_map = {lane['number']: lane for lane in exp['lanes']}
    reference_ratio = ratios.get(group['ref'])
    results = []
    for lane in group['lanes']:
        n, d = numerator['values'].get(str(lane)), denominator['values'].get(str(lane))
        relative, status = None, errors.get(lane, '')
        if not status:
            if group['ref'] not in ratios:
                status = 'Reference: ' + errors.get(group['ref'], 'missing ratio')
            elif reference_ratio == 0:
                status = 'Zero reference ratio'
            else:
                relative = ratios[lane] / reference_ratio
                if not math.isfinite(relative):
                    relative, status = None, 'Relative expression overflow'
                elif n < 0 or d < 0:
                    status = 'Negative intensity; review background correction'
                elif numerator['values'][str(group['ref'])] < 0 or denominator['values'][str(group['ref'])] < 0:
                    status = 'Negative reference intensity; review background correction'
        results.append(dict(lane=lane, sample=lane_map[lane]['name'], ratio=ratios.get(lane), relative=relative,
                            group=group['name'], reference=group['ref'], status=status or 'OK'))
    return results


SCHEMA = '''
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS experiments(
 id TEXT PRIMARY KEY,date TEXT NOT NULL,cell TEXT,condition TEXT,notes TEXT,
 created TEXT,updated TEXT,revision INTEGER NOT NULL,folder TEXT);
CREATE TABLE IF NOT EXISTS lanes(
 experiment_id TEXT REFERENCES experiments(id) ON DELETE CASCADE,number INTEGER,name TEXT,
 PRIMARY KEY(experiment_id,number));
CREATE TABLE IF NOT EXISTS protein_rows(
 id TEXT PRIMARY KEY,experiment_id TEXT REFERENCES experiments(id) ON DELETE CASCADE,
 name TEXT,label TEXT,position INTEGER);
CREATE TABLE IF NOT EXISTS raw_values(
 protein_id TEXT REFERENCES protein_rows(id) ON DELETE CASCADE,lane INTEGER,value REAL,
 PRIMARY KEY(protein_id,lane));
CREATE TABLE IF NOT EXISTS imports(
 id TEXT PRIMARY KEY,protein_id TEXT REFERENCES protein_rows(id) ON DELETE CASCADE,
 added TEXT,column_name TEXT,raw_text TEXT);
CREATE TABLE IF NOT EXISTS original_files(
 id TEXT PRIMARY KEY,experiment_id TEXT REFERENCES experiments(id) ON DELETE CASCADE,
 filename TEXT,original_path TEXT,extension TEXT,added TEXT,archive TEXT,sha256 TEXT);
CREATE TABLE IF NOT EXISTS protein_sources(
 protein_id TEXT REFERENCES protein_rows(id) ON DELETE CASCADE,
 file_id TEXT REFERENCES original_files(id) ON DELETE CASCADE,PRIMARY KEY(protein_id,file_id));
CREATE TABLE IF NOT EXISTS normalization_sets(
 id TEXT PRIMARY KEY,experiment_id TEXT REFERENCES experiments(id) ON DELETE CASCADE,
 numerator TEXT REFERENCES protein_rows(id),denominator TEXT REFERENCES protein_rows(id),position INTEGER);
CREATE TABLE IF NOT EXISTS normalization_groups(
 id TEXT PRIMARY KEY,set_id TEXT REFERENCES normalization_sets(id) ON DELETE CASCADE,
 name TEXT,reference_lane INTEGER,position INTEGER);
CREATE TABLE IF NOT EXISTS group_members(
 group_id TEXT REFERENCES normalization_groups(id) ON DELETE CASCADE,lane INTEGER,
 PRIMARY KEY(group_id,lane));
CREATE TABLE IF NOT EXISTS audit_log(
 id INTEGER PRIMARY KEY AUTOINCREMENT,experiment_id TEXT REFERENCES experiments(id),
 changed TEXT,kind TEXT,object_key TEXT,old_value TEXT,new_value TEXT);
CREATE INDEX IF NOT EXISTS experiments_date ON experiments(date);
CREATE INDEX IF NOT EXISTS protein_name ON protein_rows(name);
PRAGMA user_version=2;
'''


class Store:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.root / 'wbquant.sqlite3')
        self.db.row_factory = sqlite3.Row
        version = self.db.execute('PRAGMA user_version').fetchone()[0]
        if version not in (0, 1, 2):
            raise ValueError('This library was created by a newer application version.')
        self.db.executescript(SCHEMA)
        columns = {r[1] for r in self.db.execute('PRAGMA table_info(experiments)')}
        if 'folder' not in columns:
            self.db.execute('ALTER TABLE experiments ADD COLUMN folder TEXT')
        self.db.execute('PRAGMA user_version=2')
        self._migrate_archive_folders()

    def _migrate_archive_folders(self):
        rows = self.db.execute('SELECT id, folder FROM experiments').fetchall()
        for row in rows:
            moved_from = target = None
            try:
                with self.db:
                    eid = row['id']
                    if row['folder']:
                        continue
                    e = self.load(eid)
                    folder = experiment_folder(e) if e else ('experiment_' + eid[:8])
                    old_dir = self.root / 'experiments' / eid
                    new_dir = self.root / 'experiments' / folder
                    if old_dir.exists():
                        target = new_dir
                        suffix = 0
                        while target.exists() and target.resolve() != old_dir.resolve():
                            suffix += 1
                            target = self.root / 'experiments' / f'{folder}_{suffix}'
                        moved_from = old_dir if target != old_dir else None
                        if moved_from is not None:
                            old_dir.rename(target)
                            folder = target.name
                        old_prefix = 'experiments/' + eid + '/'
                        new_prefix = 'experiments/' + folder + '/'
                        self.db.execute(
                                "UPDATE original_files SET archive = replace(archive, ?, ?) "
                                "WHERE experiment_id=? AND archive LIKE ?",
                                (old_prefix, new_prefix, eid, old_prefix + '%'))
                        self.db.execute('UPDATE experiments SET folder=? WHERE id=?', (folder, eid))
                        continue
                    self.db.execute('UPDATE experiments SET folder=? WHERE id=?', (folder, eid))
            except Exception:
                if moved_from is not None and target.exists() and not moved_from.exists():
                    target.rename(moved_from)
                raise

    def search(self, text=''):
        rows = self.db.execute('''SELECT e.* FROM experiments e ORDER BY date DESC,updated DESC''').fetchall()
        tokens = text.casefold().split()
        result = []
        for row in rows:
            eid = row['id']
            names = [x[0] for x in self.db.execute('SELECT name FROM protein_rows WHERE experiment_id=?', (eid,))]
            names += [x[0] for x in self.db.execute('SELECT name FROM lanes WHERE experiment_id=?', (eid,))]
            haystack = ' '.join(str(v or '') for v in [*row, *names]).casefold()
            if all(t in haystack for t in tokens):
                result.append(dict(row))
        return result

    def protein_names(self):
        return [r[0] for r in self.db.execute('SELECT DISTINCT name FROM protein_rows ORDER BY name')]

    def load(self, eid):
        row = self.db.execute('SELECT * FROM experiments WHERE id=?', (eid,)).fetchone()
        if not row:
            return None
        e = dict(row)
        e['lanes'] = [dict(number=r['number'], name=r['name']) for r in self.db.execute(
            'SELECT * FROM lanes WHERE experiment_id=? ORDER BY number', (eid,))]
        e['files'] = [{k: r[k] for k in r.keys() if k != 'experiment_id'} for r in self.db.execute(
            'SELECT * FROM original_files WHERE experiment_id=? ORDER BY added', (eid,))]
        e['proteins'] = []
        for r in self.db.execute('SELECT * FROM protein_rows WHERE experiment_id=? ORDER BY position', (eid,)):
            p = dict(id=r['id'], name=r['name'], label=r['label'])
            p['values'] = {str(v['lane']): v['value'] for v in self.db.execute('SELECT * FROM raw_values WHERE protein_id=?', (r['id'],))}
            p['imports'] = [dict(id=i['id'], added=i['added'], column=i['column_name'], text=i['raw_text']) for i in self.db.execute('SELECT * FROM imports WHERE protein_id=? ORDER BY added', (r['id'],))]
            p['source_ids'] = [f[0] for f in self.db.execute('SELECT file_id FROM protein_sources WHERE protein_id=? ORDER BY file_id', (r['id'],))]
            e['proteins'].append(p)
        e['analyses'] = []
        for r in self.db.execute('SELECT * FROM normalization_sets WHERE experiment_id=? ORDER BY position', (eid,)):
            a = dict(id=r['id'], num=r['numerator'], den=r['denominator'], groups=[])
            for g in self.db.execute('SELECT * FROM normalization_groups WHERE set_id=? ORDER BY position', (r['id'],)):
                a['groups'].append(dict(id=g['id'], name=g['name'], ref=g['reference_lane'], lanes=[m[0] for m in self.db.execute('SELECT lane FROM group_members WHERE group_id=? ORDER BY lane', (g['id'],))]))
            e['analyses'].append(a)
        return e

    def save(self, e):
        validate(e)
        timestamp = now()
        renamed = []
        try:
            with self.db:
                self.db.execute('BEGIN IMMEDIATE')
                old = self.load(e['id'])
                if old and old['revision'] != e['revision']:
                    raise ValueError('This experiment changed in another window. Reopen it before editing.')
                revision = (old['revision'] if old else 0) + 1
                e['folder'] = e.get('folder') or (old or {}).get('folder')
                self._rename_archives_for_proteins(e, renamed)
                self.db.execute('''INSERT INTO experiments VALUES(?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(id) DO UPDATE SET date=excluded.date,cell=excluded.cell,
                    condition=excluded.condition,notes=excluded.notes,updated=excluded.updated,
                    revision=excluded.revision,folder=excluded.folder''',
                    (e['id'], e['date'], e['cell'], e['condition'], e['notes'], e['created'], timestamp, revision, e['folder']))
                old_values = {f"{p['id']}/L{k}": v for p in (old or {}).get('proteins', []) for k, v in p['values'].items()}
                new_values = {f"{p['id']}/L{k}": v for p in e['proteins'] for k, v in p['values'].items()}
                current_files = {f['id'] for f in e['files']}
                for f in (old or {}).get('files', []):
                    if f['id'] not in current_files:
                        self.db.execute('INSERT INTO audit_log(experiment_id,changed,kind,object_key,old_value,new_value) VALUES(?,?,?,?,?,?)',
                                        (e['id'], timestamp, 'file_removed', f['filename'], json.dumps(f, ensure_ascii=False), 'null'))
                for k in old_values.keys() | new_values.keys():
                    if k not in old_values or k not in new_values or old_values[k] != new_values[k]:
                        self.db.execute('INSERT INTO audit_log(experiment_id,changed,kind,object_key,old_value,new_value) VALUES(?,?,?,?,?,?)',
                                        (e['id'], timestamp, 'raw_value', k, json.dumps(old_values.get(k)), json.dumps(new_values.get(k))))
                self.db.execute('INSERT INTO audit_log(experiment_id,changed,kind,object_key,old_value,new_value) VALUES(?,?,?,?,?,?)',
                                (e['id'], timestamp, 'experiment', e['id'], json.dumps(old, ensure_ascii=False), json.dumps(e, ensure_ascii=False)))
                for table in ('normalization_sets', 'protein_rows', 'original_files', 'lanes'):
                    self.db.execute(f'DELETE FROM {table} WHERE experiment_id=?', (e['id'],))
                self.db.executemany('INSERT INTO lanes VALUES(?,?,?)', [(e['id'], l['number'], l['name']) for l in e['lanes']])
                for f in e['files']:
                    self.db.execute('INSERT INTO original_files VALUES(?,?,?,?,?,?,?,?)', (f['id'], e['id'], f['filename'], f['original_path'], f['extension'], f['added'], f['archive'], f['sha256']))
                for position, p in enumerate(e['proteins']):
                    self.db.execute('INSERT INTO protein_rows VALUES(?,?,?,?,?)', (p['id'], e['id'], p['name'], p['label'], position))
                    self.db.executemany('INSERT INTO raw_values VALUES(?,?,?)', [(p['id'], int(l), v) for l, v in p['values'].items()])
                    self.db.executemany('INSERT INTO protein_sources VALUES(?,?)', [(p['id'], fid) for fid in p['source_ids']])
                    self.db.executemany('INSERT INTO imports VALUES(?,?,?,?,?)', [(i['id'], p['id'], i['added'], i['column'], i['text']) for i in p['imports']])
                for pos, a in enumerate(e['analyses']):
                    self.db.execute('INSERT INTO normalization_sets VALUES(?,?,?,?,?)', (a['id'], e['id'], a['num'], a['den'], pos))
                    for gp, g in enumerate(a['groups']):
                        self.db.execute('INSERT INTO normalization_groups VALUES(?,?,?,?,?)', (g['id'], a['id'], g['name'], g['ref'], gp))
                        self.db.executemany('INSERT INTO group_members VALUES(?,?)', [(g['id'], l) for l in g['lanes']])
        except Exception:
            self._restore_archive_names(renamed)
            raise
        e['updated'], e['revision'] = timestamp, revision

    def _rename_archives_for_proteins(self, e, changes):
        for file_record in e['files']:
            current = self.archived_path(file_record)
            if not current.exists():
                continue
            target = current.with_name(archive_display_name(file_record, e['proteins']))
            if target == current:
                continue
            if target.exists():
                target = target.with_name(f'{target.stem}_{file_record["id"][:8]}{target.suffix}')
                if target.exists():
                    raise FileExistsError(f'Archive name is already in use: {target.name}')
            previous_archive = file_record['archive']
            current.rename(target)
            file_record['archive'] = target.relative_to(self.root).as_posix()
            changes.append((file_record, previous_archive, current, target))
        return changes

    @staticmethod
    def _restore_archive_names(changes):
        for file_record, previous_archive, old_path, new_path in reversed(changes):
            if new_path.exists() and not old_path.exists():
                new_path.rename(old_path)
            file_record['archive'] = previous_archive

    def delete(self, eid):
        row = self.db.execute('SELECT folder FROM experiments WHERE id=?', (eid,)).fetchone()
        if not row:
            raise ValueError('Experiment not found.')
        with self.db:
            self.db.execute('DELETE FROM audit_log WHERE experiment_id=?', (eid,))
            self.db.execute('DELETE FROM experiments WHERE id=?', (eid,))
        archive = self.root / 'experiments' / (row['folder'] or eid)
        if archive.exists():
            shutil.rmtree(archive)

    def history(self, eid):
        return [dict(r) for r in self.db.execute('SELECT * FROM audit_log WHERE experiment_id=? ORDER BY id DESC', (eid,))]

    def archive_file(self, e, path):
        src = Path(path).resolve(strict=True)
        if not src.is_file():
            raise ValueError('Only regular files can be archived.')
        fid = uid()
        if not e.get('folder'):
            e['folder'] = experiment_folder(e)
        relative = Path('experiments') / e['folder'] / 'originals' / fid / src.name
        destination = self.root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(src, destination)
            with destination.open('rb') as stream:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        return dict(id=fid, filename=src.name, original_path=str(src), extension=src.suffix,
                    added=now(), archive=relative.as_posix(), sha256=digest)

    def archived_path(self, f):
        path = (self.root / f['archive']).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError('Archive path points outside the library.')
        return path


def export_csv(e, path):
    """Horizontal data, all raw rows and all ratios; metadata included in every row."""
    def safe(v):
        # Prevent spreadsheet formula interpretation of user-entered names/notes.
        if isinstance(v, str) and v.lstrip().startswith(('=', '+', '-', '@')):
            return "'" + v
        return v
    headers = ['Record', 'Experiment ID', 'Date', 'Cell line', 'Condition', 'Notes', 'Protein / calculation',
               'Group', 'Reference lane', 'Source filenames', 'Detail']
    headers += [f"L{l['number']} | {l['name']}" for l in e['lanes']]
    with open(path, 'w', encoding='utf-8-sig', newline='') as stream:
        w = csv.writer(stream)
        w.writerow([safe(h) for h in headers])
        def row(kind, name='', group='', ref='', sources='', detail='', vals=None):
            cells = [kind, e['id'], e['date'], e['cell'], e['condition'], e['notes'], name, group, ref, sources, detail]
            cells += [(vals or {}).get(l['number'], '') for l in e['lanes']]
            w.writerow([safe(v) for v in cells])
        files = {f['id']: f for f in e['files']}
        proteins = {p['id']: p for p in e['proteins']}
        row('Experiment', detail='Exported ' + now())
        for p in e['proteins']:
            row('Raw intensity', label(p), sources='; '.join(files[f]['filename'] for f in p['source_ids']),
                detail='Row ID: ' + p['id'], vals={int(k): v for k, v in p['values'].items()})
        for a in e['analyses']:
            name = label(proteins[a['num']]) + ' / ' + label(proteins[a['den']])
            results = calculate(e, a)
            row('Ratio', name, detail='Calculation ID: ' + a['id'], vals={r['lane']: r['ratio'] for r in results})
            for g in a['groups']:
                group_results = calculate_group(e, a, g)
                row('Relative expression', name, g['name'], g['ref'], vals={r['lane']: r['relative'] for r in group_results})
            row('Status', name, vals={r['lane']: r['status'] for r in results})
        for f in e['files']:
            row('Original file', sources=f['filename'], detail=json.dumps(f, ensure_ascii=False))
