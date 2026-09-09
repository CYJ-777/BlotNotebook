"""Offline Western blot processing with portable JSON project storage."""
from __future__ import annotations
import copy
import csv
import hashlib
import io
import json
import math
import os
import re
import shutil
import sqlite3
import uuid
from contextlib import contextmanager
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


PROJECT_FORMAT = 'blot-notebook-project'
PROJECT_SCHEMA_VERSION = 1
EXPERIMENT_SCHEMA_VERSION = 1


def _read_json(path):
    with Path(path).open(encoding='utf-8') as stream:
        return json.load(stream)


def _atomic_json(path, payload, backup=False):
    """Write JSON by replacing a complete temporary file; optionally retain the previous file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f'.{path.name}.{uuid.uuid4().hex}.tmp')
    try:
        with temporary.open('w', encoding='utf-8', newline='\n') as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        if backup and path.exists():
            backup_path = path.with_name(path.name + '.bak')
            backup_temporary = backup_path.with_name(f'.{backup_path.name}.{uuid.uuid4().hex}.tmp')
            try:
                shutil.copy2(path, backup_temporary)
                os.replace(backup_temporary, backup_path)
            finally:
                backup_temporary.unlink(missing_ok=True)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class Store:
    """Store one portable project as versioned JSON files and archived source files.

    A project contains project.json and one experiment.json per experiment.
    If a legacy wbquant.sqlite3 exists without project.json, it is imported
    read-only. The original database and archived files remain untouched.
    """

    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.project_file = self.root / 'project.json'
        legacy = self.root / 'wbquant.sqlite3'
        if self.project_file.exists():
            self.project = _read_json(self.project_file)
            self._validate_project()
        elif legacy.exists():
            self._migrate_sqlite(legacy)
        else:
            self.project = {
                'format': PROJECT_FORMAT,
                'schema_version': PROJECT_SCHEMA_VERSION,
                'id': uid(),
                'name': self.root.name or 'Blot Notebook Project',
                'created': now(),
            }
            _atomic_json(self.project_file, self.project)
        self._refresh_index()
        self._migrate_json_archive_layout(preserve_legacy=legacy.exists())
        self._refresh_index()

    @property
    def name(self):
        """Return the display name recorded for this project."""
        return self.project.get('name') or self.root.name

    def close(self):
        """Close the store.

        JSON projects hold no persistent database connection, so this is a
        compatibility no-op for callers that explicitly close a project.
        """

    def healthcheck(self):
        """Validate every experiment document and return "ok" when readable."""
        self._refresh_index()
        for experiment_id in self._index:
            experiment = self.load(experiment_id)
            validate(experiment)
            for attachment in experiment['files']:
                self.archived_path(attachment)
        return 'ok'

    def _validate_project(self):
        if self.project.get('format') != PROJECT_FORMAT:
            raise ValueError('This folder is not a Blot Notebook project.')
        version = self.project.get('schema_version')
        if not isinstance(version, int) or version < 1:
            raise ValueError('The project metadata is invalid.')
        if version > PROJECT_SCHEMA_VERSION:
            raise ValueError('This project was created by a newer application version.')

    def _refresh_index(self):
        self._index = {}
        experiments_root = self.root / 'experiments'
        if not experiments_root.exists():
            return
        for document in experiments_root.glob('*/experiment.json'):
            record = self._read_record(document)
            experiment_id = record['experiment'].get('id')
            if not experiment_id:
                raise ValueError(f'Experiment ID is missing: {document}')
            if experiment_id in self._index:
                raise ValueError(f'Duplicate experiment ID: {experiment_id}')
            self._index[experiment_id] = document

    def _read_record(self, document):
        try:
            record = _read_json(document)
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f'Cannot read experiment JSON: {document}') from exc
        version = record.get('schema_version')
        if not isinstance(version, int) or version < 1:
            raise ValueError(f'Invalid experiment schema: {document}')
        if version > EXPERIMENT_SCHEMA_VERSION:
            raise ValueError('This experiment was created by a newer application version.')
        if not isinstance(record.get('experiment'), dict) or not isinstance(record.get('history', []), list):
            raise ValueError(f'Invalid experiment document: {document}')
        return record

    def _document_for(self, experiment):
        existing = self._index.get(experiment['id'])
        if existing:
            experiment['folder'] = existing.parent.name
            return existing
        folder = sanitize_part(experiment.get('folder')) or experiment_folder(experiment)
        candidate = self.root / 'experiments' / folder / 'experiment.json'
        suffix = 0
        while candidate.exists():
            record = self._read_record(candidate)
            if record['experiment'].get('id') == experiment['id']:
                break
            suffix += 1
            candidate = self.root / 'experiments' / f'{folder}_{suffix}' / 'experiment.json'
        experiment['folder'] = candidate.parent.name
        return candidate

    def search(self, text=''):
        """Return project experiments ordered by date and update time."""
        self._refresh_index()
        tokens = text.casefold().split()
        result = []
        for experiment_id in self._index:
            experiment = self.load(experiment_id)
            names = [protein['name'] for protein in experiment['proteins']]
            names += [lane['name'] for lane in experiment['lanes']]
            haystack = ' '.join(str(value or '') for value in [
                experiment['id'], experiment['date'], experiment['cell'],
                experiment['condition'], experiment['notes'], *names,
            ]).casefold()
            if all(token in haystack for token in tokens):
                result.append({
                    key: experiment.get(key)
                    for key in ('id', 'date', 'cell', 'condition', 'notes', 'created', 'updated', 'revision', 'folder')
                })
        return sorted(result, key=lambda item: (item.get('date') or '', item.get('updated') or ''), reverse=True)

    def protein_names(self):
        """Return unique protein names across this project."""
        names = {protein['name'] for experiment_id in self._index for protein in self.load(experiment_id)['proteins']}
        return sorted(names)

    def load(self, eid):
        """Load one experiment by ID, returning None when it is absent."""
        self._refresh_index()
        document = self._index.get(eid)
        if not document:
            return None
        experiment = self._read_record(document)['experiment']
        validate(experiment)
        return experiment

    def save(self, experiment):
        """Validate and atomically save an experiment with history and revision checks."""
        with self._write_lock():
            self._save_unlocked(experiment)

    def _save_unlocked(self, experiment):
        validate(experiment)
        self._refresh_index()
        document = self._index.get(experiment['id'])
        old_record = self._read_record(document) if document else None
        old = copy.deepcopy(old_record['experiment']) if old_record else None
        if old and old['revision'] != experiment['revision']:
            raise ValueError('This experiment changed in another window. Reopen it before editing.')

        timestamp = now()
        revision = (old['revision'] if old else 0) + 1
        experiment['folder'] = experiment.get('folder') or (old or {}).get('folder')
        document = self._document_for(experiment)
        renamed = []
        try:
            self._rename_archives_for_proteins(experiment, renamed)
            saved = copy.deepcopy(experiment)
            saved['updated'] = timestamp
            saved['revision'] = revision
            history = list((old_record or {}).get('history', []))
            next_history_id = max((entry.get('id', 0) for entry in history), default=0) + 1
            old_values = {
                f"{protein['id']}/L{lane}": value
                for protein in (old or {}).get('proteins', [])
                for lane, value in protein['values'].items()
            }
            new_values = {
                f"{protein['id']}/L{lane}": value
                for protein in experiment['proteins']
                for lane, value in protein['values'].items()
            }
            current_files = {attachment['id'] for attachment in experiment['files']}
            for attachment in (old or {}).get('files', []):
                if attachment['id'] not in current_files:
                    history.append({
                        'id': next_history_id, 'experiment_id': experiment['id'],
                        'changed': timestamp, 'kind': 'file_removed',
                        'object_key': attachment['filename'],
                        'old_value': json.dumps(attachment, ensure_ascii=False),
                        'new_value': 'null',
                    })
                    next_history_id += 1
            for object_key in old_values.keys() | new_values.keys():
                if object_key not in old_values or object_key not in new_values or old_values[object_key] != new_values[object_key]:
                    history.append({
                        'id': next_history_id, 'experiment_id': experiment['id'],
                        'changed': timestamp, 'kind': 'raw_value',
                        'object_key': object_key,
                        'old_value': json.dumps(old_values.get(object_key)),
                        'new_value': json.dumps(new_values.get(object_key)),
                    })
                    next_history_id += 1
            history.append({
                'id': next_history_id, 'experiment_id': experiment['id'],
                'changed': timestamp, 'kind': 'experiment',
                'object_key': experiment['id'],
                'old_value': json.dumps(old, ensure_ascii=False),
                'new_value': json.dumps(saved, ensure_ascii=False),
            })
            record = {
                'schema_version': EXPERIMENT_SCHEMA_VERSION,
                'experiment': saved,
                'history': history,
            }
            _atomic_json(document, record, backup=True)
        except Exception:
            self._restore_archive_names(renamed)
            raise
        experiment['updated'] = timestamp
        experiment['revision'] = revision
        self._index[experiment['id']] = document

    def delete(self, eid):
        """Delete an experiment document and its archived copies."""
        with self._write_lock():
            self._refresh_index()
            document = self._index.get(eid)
            if not document:
                raise ValueError('Experiment not found.')
            shutil.rmtree(document.parent)
            self._index.pop(eid, None)

    def history(self, eid):
        """Return newest-first history records for one experiment."""
        self._refresh_index()
        document = self._index.get(eid)
        if not document:
            return []
        return list(reversed(self._read_record(document).get('history', [])))

    def archive_file(self, experiment, path):
        """Copy a source file into the project and return its attachment metadata."""
        source = Path(path).resolve(strict=True)
        if not source.is_file():
            raise ValueError('Only regular files can be archived.')
        file_id = uid()
        if not experiment.get('folder'):
            experiment['folder'] = experiment_folder(experiment)
        originals = self.root / 'experiments' / experiment['folder'] / 'originals'
        originals.mkdir(parents=True, exist_ok=True)
        filename = archive_display_name({'id': file_id, 'filename': source.name}, [])
        destination = originals / filename
        if destination.exists():
            destination = originals / f'{destination.stem}_{file_id[:8]}{destination.suffix}'
        relative = destination.relative_to(self.root)
        try:
            shutil.copy2(source, destination)
            with destination.open('rb') as stream:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        return {
            'id': file_id, 'filename': source.name, 'original_path': str(source),
            'extension': source.suffix, 'added': now(),
            'archive': relative.as_posix(), 'sha256': digest,
        }

    def archived_path(self, attachment):
        """Resolve an archived attachment while preventing paths outside the project."""
        path = (self.root / attachment['archive']).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError('Archive path points outside the project.')
        return path

    def _rename_archives_for_proteins(self, experiment, changes):
        for file_record in experiment['files']:
            current = self.archived_path(file_record)
            if not current.exists():
                continue
            target = current.with_name(archive_display_name(file_record, experiment['proteins']))
            if target == current:
                continue
            if target.exists():
                target = target.with_name(f'{target.stem}_{file_record["id"][:8]}{target.suffix}')
                if target.resolve() == current.resolve():
                    continue
                if target.exists():
                    raise FileExistsError(f'Archive name is already in use: {target.name}')
            previous_archive = file_record['archive']
            current.rename(target)
            file_record['archive'] = target.relative_to(self.root).as_posix()
            changes.append((file_record, previous_archive, current, target))

    @staticmethod
    def _restore_archive_names(changes):
        for file_record, previous_archive, old_path, new_path in reversed(changes):
            if new_path.exists() and not old_path.exists():
                new_path.rename(old_path)
            file_record['archive'] = previous_archive

    def _migrate_json_archive_layout(self, preserve_legacy=False):
        """Flatten legacy attachment subfolders and atomically update their JSON paths."""
        with self._write_lock():
            for document in list(self._index.values()):
                record = self._read_record(document)
                changes = []
                try:
                    self._flatten_archive_paths(record['experiment'], changes, preserve_legacy)
                    if changes:
                        _atomic_json(document, record, backup=True)
                except Exception:
                    self._restore_flattened_archives(changes)
                    raise

    def _flatten_archive_paths(self, experiment, changes, copy_source=False):
        originals = self.root / 'experiments' / experiment['folder'] / 'originals'
        originals.mkdir(parents=True, exist_ok=True)
        for file_record in experiment['files']:
            current = self.archived_path(file_record)
            if not current.exists() or current.parent == originals:
                continue
            target = originals / archive_display_name(file_record, experiment['proteins'])
            if target.exists() and target.resolve() != current.resolve():
                target = originals / f'{target.stem}_{file_record["id"][:8]}{target.suffix}'
            if target.exists() and target.resolve() != current.resolve():
                raise FileExistsError(f'Archive name is already in use: {target.name}')
            previous_archive = file_record['archive']
            if copy_source:
                shutil.copy2(current, target)
            else:
                current.rename(target)
                try:
                    current.parent.rmdir()
                except OSError:
                    pass
            file_record['archive'] = target.relative_to(self.root).as_posix()
            changes.append((file_record, previous_archive, current, target, copy_source))

    @staticmethod
    def _restore_flattened_archives(changes):
        for file_record, previous_archive, old_path, new_path, copied in reversed(changes):
            if copied:
                new_path.unlink(missing_ok=True)
            elif new_path.exists() and not old_path.exists():
                old_path.parent.mkdir(parents=True, exist_ok=True)
                new_path.rename(old_path)
            file_record['archive'] = previous_archive

    @contextmanager
    def _write_lock(self):
        lock_path = self.root / '.blotnotebook.lock'
        with lock_path.open('a+b') as stream:
            stream.seek(0, os.SEEK_END)
            if stream.tell() == 0:
                stream.write(b'0')
                stream.flush()
            stream.seek(0)
            try:
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise ValueError('This project is being saved in another window. Try again.') from exc
            try:
                yield
            finally:
                stream.seek(0)
                if os.name == 'nt':
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def _migrate_sqlite(self, database):
        connection = sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True)
        connection.row_factory = sqlite3.Row
        try:
            version = connection.execute('PRAGMA user_version').fetchone()[0]
            if version not in (1, 2):
                raise ValueError('The legacy library version cannot be imported.')
            columns = {row[1] for row in connection.execute('PRAGMA table_info(experiments)')}
            rows = connection.execute('SELECT * FROM experiments ORDER BY date, updated').fetchall()
            for row in rows:
                experiment = self._load_legacy_experiment(connection, row, 'folder' in columns)
                history = [dict(entry) for entry in connection.execute(
                    'SELECT * FROM audit_log WHERE experiment_id=? ORDER BY id', (experiment['id'],)
                )]
                document = self.root / 'experiments' / experiment['folder'] / 'experiment.json'
                _atomic_json(document, {
                    'schema_version': EXPERIMENT_SCHEMA_VERSION,
                    'experiment': experiment,
                    'history': history,
                }, backup=document.exists())
            self.project = {
                'format': PROJECT_FORMAT,
                'schema_version': PROJECT_SCHEMA_VERSION,
                'id': uid(),
                'name': self.root.name or 'Blot Notebook Project',
                'created': now(),
                'migrated_from': database.name,
            }
            _atomic_json(self.project_file, self.project)
        finally:
            connection.close()

    def _load_legacy_experiment(self, connection, row, has_folder):
        experiment_id = row['id']
        experiment = dict(row)
        if not has_folder:
            experiment['folder'] = None
        experiment['lanes'] = [
            {'number': item['number'], 'name': item['name']}
            for item in connection.execute(
                'SELECT * FROM lanes WHERE experiment_id=? ORDER BY number', (experiment_id,)
            )
        ]
        experiment['files'] = [
            {key: item[key] for key in item.keys() if key != 'experiment_id'}
            for item in connection.execute(
                'SELECT * FROM original_files WHERE experiment_id=? ORDER BY added', (experiment_id,)
            )
        ]
        experiment['proteins'] = []
        for item in connection.execute(
            'SELECT * FROM protein_rows WHERE experiment_id=? ORDER BY position', (experiment_id,)
        ):
            protein = {'id': item['id'], 'name': item['name'], 'label': item['label']}
            protein['values'] = {
                str(value['lane']): value['value']
                for value in connection.execute('SELECT * FROM raw_values WHERE protein_id=?', (item['id'],))
            }
            protein['imports'] = [
                {'id': imported['id'], 'added': imported['added'],
                 'column': imported['column_name'], 'text': imported['raw_text']}
                for imported in connection.execute(
                    'SELECT * FROM imports WHERE protein_id=? ORDER BY added', (item['id'],)
                )
            ]
            protein['source_ids'] = [
                source[0] for source in connection.execute(
                    'SELECT file_id FROM protein_sources WHERE protein_id=? ORDER BY file_id', (item['id'],)
                )
            ]
            experiment['proteins'].append(protein)
        experiment['analyses'] = []
        for item in connection.execute(
            'SELECT * FROM normalization_sets WHERE experiment_id=? ORDER BY position', (experiment_id,)
        ):
            analysis = {
                'id': item['id'], 'num': item['numerator'],
                'den': item['denominator'], 'groups': [],
            }
            for group_row in connection.execute(
                'SELECT * FROM normalization_groups WHERE set_id=? ORDER BY position', (item['id'],)
            ):
                analysis['groups'].append({
                    'id': group_row['id'], 'name': group_row['name'],
                    'ref': group_row['reference_lane'],
                    'lanes': [
                        member[0] for member in connection.execute(
                            'SELECT lane FROM group_members WHERE group_id=? ORDER BY lane', (group_row['id'],)
                        )
                    ],
                })
            experiment['analyses'].append(analysis)
        if not experiment.get('folder'):
            archive_folders = {
                Path(attachment['archive']).parts[1]
                for attachment in experiment['files']
                if len(Path(attachment['archive']).parts) > 2
                and Path(attachment['archive']).parts[0] == 'experiments'
            }
            if archive_folders:
                experiment['folder'] = sanitize_part(next(iter(archive_folders))) or experiment_id
            elif (self.root / 'experiments' / experiment_id).exists():
                experiment['folder'] = experiment_id
            else:
                experiment['folder'] = experiment_folder(experiment)
        validate(experiment)
        return experiment


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
