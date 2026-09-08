from __future__ import annotations
import argparse
import copy
import json
import html
import sys
from pathlib import Path
from PySide6.QtCore import Qt, QDate, QUrl, QSettings, QTimer, QMimeData, QStandardPaths
from PySide6.QtGui import QDesktopServices, QKeySequence, QShortcut, QColor
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QPushButton, QLineEdit, QTextEdit, QPlainTextEdit, QComboBox,
    QTableWidget, QTableWidgetItem, QTabWidget, QSplitter, QListWidget,
    QListWidgetItem, QDialog, QDialogButtonBox, QDateEdit, QSpinBox,
    QFileDialog, QMessageBox, QInputDialog, QAbstractItemView, QHeaderView,
    QCompleter, QCheckBox, QMenu, QScrollArea, QFrame,
)
from core import Store, fresh, uid, now, label, number, parse_biorad, table_headers, DEFAULT_COLUMN, calculate, export_csv, validate, remove_attachment


STYLE = '''
QWidget {font-family: Arial, Aptos, sans-serif; font-size: 15px; color: #17191d;}
QMainWindow, QDialog {background: #f3f4f6;}
QWidget#page {background: #f3f4f6;}
QScrollArea {background: transparent; border: none;}
QWidget#sidebar {background: #e9edf2; border-radius: 12px;}
QWidget#card {background: white; border: 1px solid #e0e4e9; border-radius: 12px;}
QLabel#title {font-size: 25px; font-weight: 600; color: #19344e;}
QLabel#section {font-size: 18px; font-weight: 600; color: #18212d;}
QLabel#eyebrow {font-size: 12px; color: #62758a; font-weight: 600;}
QLabel#muted {font-size: 13px; color: #657080;}
QPushButton {background: white; border: 1px solid #d9dfe6; border-radius: 7px; padding: 9px 14px;}
QPushButton:hover {background: #edf3fa; border-color: #91abc8;}
QPushButton#primary {background: #285b8c; color: white; border: 1px solid #285b8c; font-weight: 600;}
QPushButton#primary:hover {background: #214b74;}
QPushButton:disabled {color: #929ba6; background: #f2f4f6; border-color: #e4e7eb;}
QPushButton#quiet {background: transparent; border: none; color: #4e647b; padding: 7px; text-align: left;}
QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QDateEdit, QSpinBox {background: #fcfdfe; border: 1px solid #dce1e7; border-radius: 6px; padding: 8px; selection-background-color: #285b8c;}
QLineEdit:focus, QTextEdit:focus, QComboBox:focus {border-color: #779cc2;}
QTableWidget {background: white; border: none; alternate-background-color: #fafbfc; selection-background-color: #e4eef8; selection-color: #17191d;}
QTableWidget::item {padding: 5px; border-bottom: 1px solid #eef0f3;}
QListWidget {background: transparent; border: none; outline: none;}
QListWidget::item {padding: 13px 10px; border-radius: 8px; margin-bottom: 5px;}
QListWidget::item:selected {background: white; color: #163d64;}
QListWidget::item:hover {background: #f5f7fa;}
QHeaderView::section {background: #f6f8fa; padding: 10px; border: none; border-bottom: 1px solid #e3e8ed; font-weight: 600;}
QTabWidget::pane {border: none; background: #f3f4f6;}
QTabBar::tab {padding: 12px 18px; margin-right: 8px; color: #677585; border-bottom: 3px solid transparent;}
QTabBar::tab:selected {color: #204f7d; border-bottom: 3px solid #285b8c; font-weight: 600;}
QLabel#drop {border: 1px dashed #b7c7d9; border-radius: 8px; padding: 14px; background: #f8fafc; color: #546b84; font-size: 14px;}
QMenu {background: white; border: 1px solid #d9dfe6; padding: 6px;}
QMenu::item {padding: 9px 18px;}
QMenu::item:selected {background: #e4eef8;}
QSplitter::handle {background: transparent;}
QStatusBar {color: #657080; font-size: 12px;}
'''



def button(text, fn, primary=False):
    b = QPushButton(text)
    if primary:
        b.setObjectName('primary')
    b.clicked.connect(fn)
    return b


def hint(text):
    l = QLabel(text)
    l.setObjectName('muted')
    l.setWordWrap(True)
    return l


def heading(text):
    widget = QLabel(text)
    widget.setObjectName('section')
    return widget


def card(parent_layout):
    widget = QWidget()
    widget.setObjectName('card')
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(18, 16, 18, 16)
    layout.setSpacing(12)
    parent_layout.addWidget(widget)
    return layout


def action_menu(text, actions):
    widget = QPushButton(text)
    menu = QMenu(widget)
    for name, callback in actions:
        menu.addAction(name, callback)
    widget.setMenu(menu)
    return widget


def table(headers, editable=False):
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.setAlternatingRowColors(True)
    t.setShowGrid(False)
    t.verticalHeader().setVisible(False)
    t.verticalHeader().setDefaultSectionSize(38)
    t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    if not editable:
        t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    t.horizontalHeader().setStretchLastSection(True)
    return t


def fill(t, rows):
    t.blockSignals(True)
    t.setRowCount(len(rows))
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            item = QTableWidgetItem('' if value is None else str(value))
            item.setToolTip(item.text())
            t.setItem(r, c, item)
    t.resizeColumnsToContents()
    for c in range(t.columnCount()):
        t.setColumnWidth(c, min(380, max(105, t.columnWidth(c))))
    t.blockSignals(False)


def formatted(value):
    return '' if value is None else format(value, '.10g')


def sample_color(name):
    return '#c62828' if 'luc' in name.casefold() else '#000000'


def protein_display_names(proteins):
    labels = [label(p) for p in proteins]
    return {p['id']: label(p) + (f' (row {i + 1})' if labels.count(label(p)) > 1 else '')
            for i, p in enumerate(proteins)}


def relative_clipboard(rows, with_names=False):
    values = ['' if r['relative'] is None else str(r['relative']) for r in rows]
    def safe_name(name):
        return "'" + name if name.lstrip().startswith(('=', '+', '-', '@')) else name
    lines = []
    html_rows = []
    if with_names:
        names = [safe_name(r['sample'].replace('\t', ' ').replace('\n', ' ').replace('\r', ' ')) for r in rows]
        lines.append('\t'.join(names))
        html_rows.append('<tr>' + ''.join(f'<td style="color:{sample_color(r["sample"])};font-family:Arial;font-size:12pt">{html.escape(n)}</td>' for r, n in zip(rows, names)) + '</tr>')
    lines.append('\t'.join(values))
    html_rows.append('<tr>' + ''.join(f'<td style="color:#000000;font-family:Arial;font-size:12pt">{v}</td>' for v in values) + '</tr>')
    return '\n'.join(lines), '<html><body><table>' + ''.join(html_rows) + '</table></body></html>'


class DropArea(QLabel):
    def __init__(self, callback):
        super().__init__('Drop original WB files here to archive a copy')
        self.setObjectName('drop')
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setAcceptDrops(True)
        self.callback = callback

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and all(u.isLocalFile() for u in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event):
        self.callback([u.toLocalFile() for u in event.mimeData().urls()])
        event.acceptProposedAction()


class PasteDialog(QDialog):
    def __init__(self, parent, protein):
        super().__init__(parent)
        self.setWindowTitle('Paste Bio-Rad Data — ' + label(protein))
        self.resize(850, 660)
        self.values = None
        self.parsed_text = None
        layout = QVBoxLayout(self)
        layout.addWidget(hint('Paste one protein table including its header. Lane numbers map to experiment lanes; missing lanes stay empty.'))
        self.text = QPlainTextEdit()
        self.text.setPlaceholderText('Lane No.\tAdj. Total Band Vol. (Int)\n1\t2908950\n2\t1059916')
        layout.addWidget(self.text)
        actions = QHBoxLayout()
        actions.addWidget(button('Paste from clipboard', self.clipboard))
        actions.addWidget(button('Read columns', self.columns))
        actions.addWidget(QLabel('Intensity column'))
        self.column = QComboBox()
        self.column.addItem(DEFAULT_COLUMN)
        actions.addWidget(self.column, 1)
        actions.addWidget(button('Preview', self.preview, True))
        layout.addLayout(actions)
        self.preview_table = table(['Lane', 'Intensity'])
        layout.addWidget(self.preview_table)
        self.message = hint('Preview and check the lane mapping before importing.')
        layout.addWidget(self.message)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.ok = box.button(QDialogButtonBox.StandardButton.Ok)
        self.ok.setText('Import values')
        self.ok.setEnabled(False)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        layout.addWidget(box)
        self.text.textChanged.connect(self.invalidate)
        self.column.currentTextChanged.connect(self.invalidate)

    def invalidate(self):
        self.ok.setEnabled(False)
        self.values = None

    def clipboard(self):
        self.text.setPlainText(QApplication.clipboard().text())
        self.columns()

    def columns(self):
        try:
            _, _, _, headers = table_headers(self.text.toPlainText())
            self.column.clear()
            self.column.addItems(headers)
            from core import key
            for i, h in enumerate(headers):
                if key(h) == key(DEFAULT_COLUMN):
                    self.column.setCurrentIndex(i)
                    break
        except ValueError as exc:
            self.message.setText(str(exc))

    def preview(self):
        try:
            self.values = parse_biorad(self.text.toPlainText(), self.column.currentText())
            fill(self.preview_table, [(k, repr(v)) for k, v in self.values.items()])
            self.message.setText(f'{len(self.values)} lanes found. Existing values for these lanes will be updated with an audit record.')
            self.ok.setEnabled(True)
        except ValueError as exc:
            self.message.setText(str(exc))
            self.ok.setEnabled(False)


class ProteinDialog(QDialog):
    def __init__(self, parent, exp, names, existing=None):
        super().__init__(parent)
        self.setWindowTitle('Protein row')
        self.resize(560, 420)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit(existing['name'] if existing else '')
        comp = QCompleter(names, self)
        comp.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.name.setCompleter(comp)
        self.exposure = QLineEdit(existing['label'] if existing else '')
        self.exposure.setPlaceholderText('Optional: 5.142 s, membrane A, repeat 2')
        form.addRow('Protein name', self.name)
        form.addRow('Measurement / exposure', self.exposure)
        layout.addLayout(form)
        layout.addWidget(hint('Link original files to this measurement (optional). Multiple files may be selected.'))
        self.sources = QListWidget()
        for f in exp['files']:
            item = QListWidgetItem(f['filename'])
            item.setData(Qt.ItemDataRole.UserRole, f['id'])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if existing and f['id'] in existing['source_ids'] else Qt.CheckState.Unchecked)
            item.setToolTip(f['original_path'])
            self.sources.addItem(item)
        layout.addWidget(self.sources)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        box.accepted.connect(self.accept_valid)
        box.rejected.connect(self.reject)
        layout.addWidget(box)

    def accept_valid(self):
        if not self.name.text().strip():
            QMessageBox.warning(self, 'Protein name required', 'Enter a protein name.')
            return
        self.accept()

    def data(self):
        return dict(name=self.name.text().strip(), label=self.exposure.text().strip(),
                    source_ids=sorted(self.sources.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.sources.count()) if self.sources.item(i).checkState() == Qt.CheckState.Checked))


class GroupDialog(QDialog):
    def __init__(self, parent, exp, occupied, existing=None):
        super().__init__(parent)
        self.setWindowTitle('Normalization group')
        self.resize(480, 510)
        layout = QVBoxLayout(self)
        self.name = QLineEdit(existing['name'] if existing else '')
        self.name.setPlaceholderText('Group A')
        layout.addWidget(QLabel('Group name'))
        layout.addWidget(self.name)
        layout.addWidget(hint('Select lanes by number. Identical sample names remain independent.'))
        self.members = QListWidget()
        for l in exp['lanes']:
            if l['number'] in occupied:
                continue
            item = QListWidgetItem(f"L{l['number']} · {l['name']}")
            item.setData(Qt.ItemDataRole.UserRole, l['number'])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if existing and l['number'] in existing['lanes'] else Qt.CheckState.Unchecked)
            self.members.addItem(item)
        layout.addWidget(self.members)
        layout.addWidget(QLabel('Reference lane (relative expression = 1)'))
        self.reference = QComboBox()
        layout.addWidget(self.reference)
        self.members.itemChanged.connect(self.update_refs)
        self.update_refs()
        if existing:
            self.reference.setCurrentIndex(self.reference.findData(existing['ref']))
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        box.accepted.connect(self.accept_valid)
        box.rejected.connect(self.reject)
        layout.addWidget(box)

    def update_refs(self):
        current = self.reference.currentData()
        self.reference.clear()
        for i in range(self.members.count()):
            item = self.members.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                self.reference.addItem(item.text(), item.data(Qt.ItemDataRole.UserRole))
        index = self.reference.findData(current)
        if index >= 0:
            self.reference.setCurrentIndex(index)

    def accept_valid(self):
        if not self.name.text().strip() or self.reference.currentData() is None:
            QMessageBox.warning(self, 'Incomplete group', 'Enter a group name and select at least one lane.')
            return
        self.accept()

    def data(self):
        return dict(name=self.name.text().strip(), ref=self.reference.currentData(),
                    lanes=[self.members.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.members.count()) if self.members.item(i).checkState() == Qt.CheckState.Checked])


class MainWindow(QMainWindow):
    def __init__(self, root):
        super().__init__()
        self.store = Store(root)
        self.exp = None
        self.dirty = False
        self.rendering = False
        self.setWindowTitle('Blot Notebook')
        self.resize(1320, 860)
        self.setMinimumSize(980, 680)
        outer = QWidget()
        self.setCentralWidget(outer)
        layout = QVBoxLayout(outer)
        layout.setContentsMargins(20, 16, 20, 12)
        split = QSplitter()
        split.setHandleWidth(20)
        layout.addWidget(split, 1)
        sidebar = QWidget()
        sidebar.setObjectName('sidebar')
        sl = QVBoxLayout(sidebar)
        sl.setContentsMargins(16, 22, 16, 16)
        sl.setSpacing(14)
        brand = QLabel('Blot Notebook')
        brand.setObjectName('title')
        sl.addWidget(brand)
        sl.addWidget(hint('Your local experiment library'))
        sl.addSpacing(10)
        sl.addWidget(button('+ New experiment', self.new_experiment, True))
        self.search = QLineEdit()
        self.search.setPlaceholderText('Search experiments…')
        self.search.setToolTip('Search date, cell line, protein, condition, sample name or experiment ID.')
        self.search.textChanged.connect(self.refresh_list)
        sl.addWidget(self.search)
        self.experiments = QListWidget()
        self.experiments.itemClicked.connect(self.select_experiment)
        sl.addWidget(self.experiments, 1)
        library = button('Open library folder', self.open_library)
        library.setObjectName('quiet')
        sl.addWidget(library)
        sl.addWidget(hint('Stored on this computer'))
        split.addWidget(sidebar)
        workspace = QWidget()
        wl = QVBoxLayout(workspace)
        wl.setContentsMargins(0, 6, 0, 0)
        wl.setSpacing(16)
        top = QHBoxLayout()
        title_column = QVBoxLayout()
        eyebrow = QLabel('EXPERIMENT WORKSPACE')
        eyebrow.setObjectName('eyebrow')
        title_column.addWidget(eyebrow)
        self.workspace_title = QLabel('Ready for your next blot')
        self.workspace_title.setObjectName('title')
        title_column.addWidget(self.workspace_title)
        self.workspace_subtitle = hint('Create an experiment or open one from the library.')
        title_column.addWidget(self.workspace_subtitle)
        top.addLayout(title_column, 1)
        self.delete_button = button('Delete experiment', self.delete_experiment)
        self.delete_button.setEnabled(False)
        top.addWidget(self.delete_button)
        top.addWidget(button('Save experiment', self.save, True))
        wl.addLayout(top)
        self.tabs = QTabWidget()
        wl.addWidget(self.tabs, 1)
        split.addWidget(workspace)
        split.setSizes([280, 1000])
        self.build_experiment()
        self.build_raw()
        self.build_norm()
        self.build_history()
        self.tabs.setEnabled(False)
        self.statusBar().showMessage('Create an experiment or select one from your library.')
        QShortcut(QKeySequence.StandardKey.Save, self, activated=self.save)
        self.refresh_list()

    def page(self, name):
        page = QWidget()
        page.setObjectName('page')
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 18, 0, 0)
        v.setSpacing(16)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(page)
        self.tabs.addTab(scroll, name)
        return v

    def build_experiment(self):
        v = self.page('Experiment')
        info = card(v)
        info.addWidget(heading('Experiment details'))
        self.identity = hint('')
        self.identity.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        form = QFormLayout()
        self.date = QDateEdit(QDate.currentDate())
        self.date.setDisplayFormat('yyyy-MM-dd')
        self.date.setCalendarPopup(True)
        self.cell = QLineEdit()
        self.condition = QLineEdit()
        self.notes = QTextEdit()
        self.notes.setMaximumHeight(95)
        form.addRow('Experiment date', self.date)
        form.addRow('Cell line', self.cell)
        form.addRow('Treatment / condition', self.condition)
        form.addRow('Notes (optional)', self.notes)
        info.addLayout(form)
        info.addWidget(self.identity)
        samples = card(v)
        v.setStretch(1, 1)
        lane_actions = QHBoxLayout()
        lane_actions.addWidget(heading('Samples'), 1)
        lane_actions.addWidget(button('Add lanes', self.add_lanes))
        lane_actions.addWidget(button('Paste sample names', self.paste_names))
        samples.addLayout(lane_actions)
        self.lanes = table(['Lane number', 'Sample name'], True)
        self.lanes.itemChanged.connect(self.lane_changed)
        samples.addWidget(self.lanes, 1)
        samples.addWidget(hint('Double-click a sample name to edit. Lane numbers stay stable.'))
        for field in (self.cell, self.condition):
            field.textChanged.connect(self.mark_dirty)
        self.notes.textChanged.connect(self.mark_dirty)
        self.date.dateChanged.connect(self.mark_dirty)

    def build_raw(self):
        v = self.page('Raw Data')
        files_card = card(v)
        actions = QHBoxLayout()
        actions.addWidget(heading('Original files'), 1)
        actions.addWidget(button('Add files…', self.choose_files))
        actions.addWidget(action_menu('Open', [('Archived copy', lambda: self.open_file(False)),
                                               ('Original location', lambda: self.open_file(True))]))
        self.remove_file_button = button('Remove file', self.remove_file)
        self.remove_file_button.setEnabled(False)
        actions.addWidget(self.remove_file_button)
        files_card.addLayout(actions)
        files_card.addWidget(DropArea(self.add_files))
        self.files = table(['Original filename', 'Extension', 'Added (UTC)', 'Original path'])
        self.files.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.files.itemSelectionChanged.connect(lambda: self.remove_file_button.setEnabled(bool(self.files.selectedItems())))
        self.files.setMaximumHeight(118)
        files_card.addWidget(self.files)
        protein_card = card(v)
        v.setStretch(1, 1)
        actions = QHBoxLayout()
        actions.addWidget(heading('Protein intensities'), 1)
        actions.addWidget(button('+ Protein row', self.add_protein))
        actions.addWidget(action_menu('Row options', [('Edit name / source links', self.edit_protein),
                                                    ('View pasted source', self.view_imports)]))
        actions.addWidget(button('Paste Bio-Rad data', self.paste_data, True))
        protein_card.addLayout(actions)
        self.raw = table(['Protein / measurement'], True)
        self.raw.itemChanged.connect(self.raw_changed)
        protein_card.addWidget(self.raw, 1)
        protein_card.addWidget(hint('Select a protein row to paste data. Double-click a value to edit.'))

    def build_norm(self):
        v = self.page('Normalization')
        actions = QHBoxLayout()
        actions.addWidget(QLabel('Numerator'))
        self.numerator = QComboBox()
        actions.addWidget(self.numerator, 1)
        actions.addWidget(QLabel('/ Denominator'))
        self.denominator = QComboBox()
        actions.addWidget(self.denominator, 1)
        actions.addWidget(button('Add calculation', self.add_analysis, True))
        v.addLayout(actions)
        self.analysis_choice = QComboBox()
        self.analysis_choice.currentIndexChanged.connect(self.render_analysis)
        v.addWidget(self.analysis_choice)
        v.addWidget(hint("Ratio = numerator / denominator. Relative expression = ratio / this group's reference ratio."))
        actions = QHBoxLayout()
        actions.addWidget(button('+ Group', self.add_group, True))
        actions.addWidget(button('Edit group', self.edit_group))
        actions.addWidget(button('Remove group', self.remove_group))
        actions.addStretch()
        actions.addWidget(button('Export CSV…', self.export))
        v.addLayout(actions)
        self.groups = table(['Group', 'Member lanes', 'Reference lane'])
        self.groups.setMaximumHeight(190)
        v.addWidget(self.groups)
        self.results = table(['Lane', 'Sample', 'Group', 'Reference', 'Ratio', 'Relative expression', 'Status'])
        v.addWidget(self.results, 1)
        copy_row = QHBoxLayout()
        copy_label = QLabel('Horizontal copy')
        copy_label.setObjectName('muted')
        copy_row.addWidget(copy_label)
        self.copy_values_button = button('Copy values', lambda: self.copy_relative(False))
        self.copy_names_button = button('Copy with sample names', lambda: self.copy_relative(True))
        for b in (self.copy_values_button, self.copy_names_button):
            b.setObjectName('quiet')
        copy_row.addWidget(self.copy_values_button)
        copy_row.addWidget(self.copy_names_button)
        copy_row.addStretch()
        v.addLayout(copy_row)
        v.addWidget(hint('Unassigned lanes retain their ratio but have no relative expression. Zero or missing denominators and invalid references are reported explicitly.'))

    def build_history(self):
        v = self.page('History')
        history_card = card(v)
        v.setStretch(0, 1)
        history_card.addWidget(heading('Change history'))
        history_card.addWidget(hint('Select a record to inspect its before and after values. All timestamps are UTC.'))
        self.history_table = table(['Changed (UTC)', 'Type', 'Protein / object', 'Old value', 'New value'])
        self.history_table.itemSelectionChanged.connect(self.history_detail)
        history_card.addWidget(self.history_table, 1)
        self.history_text = QPlainTextEdit()
        self.history_text.setReadOnly(True)
        self.history_text.setMaximumHeight(230)
        history_card.addWidget(self.history_text)

    def error(self, exc):
        QMessageBox.warning(self, 'Cannot complete action', str(exc))

    def mark_dirty(self, *_):
        if not self.rendering and self.exp:
            self.dirty = True
            self.statusBar().showMessage('Unsaved experiment information — Save or Ctrl/Cmd+S')

    def sync_fields(self):
        if self.exp:
            self.exp.update(date=self.date.date().toString('yyyy-MM-dd'), cell=self.cell.text(),
                            condition=self.condition.text(), notes=self.notes.toPlainText())
            self.workspace_title.setText(self.exp['cell'] or 'Untitled experiment')
            self.workspace_subtitle.setText(self.exp['date'] + ('  ·  ' + self.exp['condition'] if self.exp['condition'] else ''))

    def save(self, *_):
        if not self.exp:
            return True
        self.sync_fields()
        try:
            self.store.save(self.exp)
        except Exception as exc:
            self.error(exc)
            return False
        self.dirty = False
        self.refresh_list()
        self.render_history()
        self.statusBar().showMessage('Saved locally · ' + self.exp['updated'])
        return True

    def delete_experiment(self):
        if not self.exp:
            return
        title = self.exp['cell'] or 'Untitled experiment'
        answer = QMessageBox.question(
            self, 'Delete experiment',
            f'Delete "{title}"?\n\nThis removes the experiment and its archived copies from your library. Original files are not touched.',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.store.delete(self.exp['id'])
        except Exception as exc:
            self.error(exc)
            return
        self.exp = None
        self.dirty = False
        self.tabs.setEnabled(False)
        self.workspace_title.setText('Ready for your next blot')
        self.workspace_subtitle.setText('Create an experiment or open one from the library.')
        self.identity.setText('')
        self.cell.clear()
        self.condition.clear()
        self.notes.clear()
        self.date.setDate(QDate.currentDate())
        fill(self.lanes, [])
        fill(self.files, [])
        fill(self.raw, [])
        fill(self.groups, [])
        fill(self.results, [])
        self.numerator.clear()
        self.denominator.clear()
        self.analysis_choice.clear()
        self.copy_values_button.setEnabled(False)
        self.copy_names_button.setEnabled(False)
        self.delete_button.setEnabled(False)
        self.search.clear()
        self.refresh_list()
        self.statusBar().showMessage('Experiment deleted.')

    def mutate(self, fn):
        if not self.exp:
            return
        self.sync_fields()
        previous = copy.deepcopy(self.exp)
        try:
            fn()
            self.store.save(self.exp)
        except Exception as exc:
            self.exp = previous
            self.error(exc)
            self.render()
            return False
        self.dirty = False
        self.render()
        self.refresh_list()
        self.statusBar().showMessage('Saved locally · ' + self.exp['updated'])
        return True

    def can_leave(self):
        if not self.dirty:
            return True
        answer = QMessageBox.question(self, 'Unsaved experiment information', 'Save changes before leaving?',
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save)
        if answer == QMessageBox.StandardButton.Cancel:
            return False
        return self.save() if answer == QMessageBox.StandardButton.Save else True

    def closeEvent(self, event):
        if self.can_leave():
            self.store.db.close()
            event.accept()
        else:
            event.ignore()

    def refresh_list(self, *_):
        self.experiments.clear()
        for e in self.store.search(self.search.text()):
            item = QListWidgetItem(f"{e['date']}  ·  {e['cell'] or 'Untitled experiment'}\n{e['condition'] or 'No condition'}")
            item.setData(Qt.ItemDataRole.UserRole, e['id'])
            self.experiments.addItem(item)
            if self.exp and e['id'] == self.exp['id']:
                self.experiments.setCurrentItem(item)

    def new_experiment(self):
        if not self.can_leave():
            return
        e = fresh()
        try:
            self.store.save(e)
        except Exception as exc:
            self.error(exc)
            return
        self.exp = e
        self.dirty = False
        self.render()
        self.search.clear()
        self.refresh_list()
        self.tabs.setCurrentIndex(0)
        self.cell.setFocus()

    def select_experiment(self, item):
        eid = item.data(Qt.ItemDataRole.UserRole)
        if not self.can_leave():
            self.refresh_list()
            return
        self.exp = self.store.load(eid)
        self.dirty = False
        self.render()

    def render(self):
        if not self.exp:
            return
        self.rendering = True
        self.tabs.setEnabled(True)
        self.delete_button.setEnabled(True)
        e = self.exp
        selected_raw = self.raw.currentRow()
        selected_file = self.files.currentRow()
        self.identity.setText('Experiment ID: ' + e['id'])
        self.workspace_title.setText(e['cell'] or 'Untitled experiment')
        self.workspace_subtitle.setText(e['date'] + ('  ·  ' + e['condition'] if e['condition'] else ''))
        self.date.setDate(QDate.fromString(e['date'], 'yyyy-MM-dd'))
        self.cell.setText(e['cell'])
        self.condition.setText(e['condition'])
        self.notes.setPlainText(e['notes'])
        fill(self.lanes, [(l['number'], l['name']) for l in e['lanes']])
        for r in range(self.lanes.rowCount()):
            self.lanes.item(r, 0).setFlags(self.lanes.item(r, 0).flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.lanes.item(r, 1).setForeground(QColor(sample_color(e['lanes'][r]['name'])))
        fill(self.files, [(f['filename'], f['extension'], f['added'], f['original_path']) for f in e['files']])
        self.files.selectRow(selected_file)
        headers = ['Protein / measurement'] + [f"L{l['number']} · {l['name']}" for l in e['lanes']]
        self.raw.setColumnCount(len(headers))
        self.raw.setHorizontalHeaderLabels(headers)
        for c, lane in enumerate(e['lanes'], 1):
            self.raw.horizontalHeaderItem(c).setForeground(QColor(sample_color(lane['name'])))
        fill(self.raw, [[label(p)] + [repr(p['values'][str(l['number'])]) if p['values'].get(str(l['number'])) is not None else '' for l in e['lanes']] for p in e['proteins']])
        for r in range(self.raw.rowCount()):
            self.raw.item(r, 0).setFlags(self.raw.item(r, 0).flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.raw.selectRow(selected_raw)
        display_names = protein_display_names(e['proteins'])
        for combo in (self.numerator, self.denominator):
            selected = combo.currentData()
            combo.clear()
            for p in e['proteins']:
                combo.addItem(display_names[p['id']], p['id'])
            i = combo.findData(selected)
            if i >= 0:
                combo.setCurrentIndex(i)
        selected = self.analysis_choice.currentData()
        self.analysis_choice.blockSignals(True)
        self.analysis_choice.clear()
        proteins = {p['id']: p for p in e['proteins']}
        for a in e['analyses']:
            self.analysis_choice.addItem(display_names[a['num']] + ' / ' + display_names[a['den']], a['id'])
        i = self.analysis_choice.findData(selected)
        if i >= 0:
            self.analysis_choice.setCurrentIndex(i)
        self.analysis_choice.blockSignals(False)
        self.render_analysis()
        self.render_history()
        self.rendering = False

    def add_lanes(self):
        count, ok = QInputDialog.getInt(self, 'Add lanes', 'Number of additional lanes', 4, 1, 100)
        if ok:
            start = max([l['number'] for l in self.exp['lanes']], default=0) + 1
            self.mutate(lambda: self.exp['lanes'].extend(dict(number=i, name=f'Lane {i}') for i in range(start, start + count)))

    def paste_names(self):
        text, ok = QInputDialog.getMultiLineText(self, 'Sample names', 'Enter one sample per line, or paste a horizontal Excel row.\nNames map to existing lanes in lane-number order.', QApplication.clipboard().text())
        if not ok:
            return
        import re
        names = re.split(r'\t|\r?\n', text.strip())
        if not names or any(not n.strip() for n in names):
            self.error('Sample names must not be empty.')
            return
        if self.exp['lanes'] and len(names) != len(self.exp['lanes']):
            self.error(f"Expected {len(self.exp['lanes'])} sample names, received {len(names)}.")
            return
        def change():
            if not self.exp['lanes']:
                self.exp['lanes'] = [dict(number=i + 1, name=n.strip()) for i, n in enumerate(names)]
            else:
                for l, n in zip(self.exp['lanes'], names):
                    l['name'] = n.strip()
        self.mutate(change)

    def lane_changed(self, item):
        if self.rendering or item.column() != 1:
            return
        name = item.text().strip()
        r = item.row()
        if not name:
            self.error('Sample name cannot be blank.')
            self.render()
            return
        self.mutate(lambda: self.exp['lanes'][r].update(name=name))

    def choose_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, 'Add original WB files', '', 'All files (*)')
        if paths:
            self.add_files(paths)

    def add_files(self, paths):
        if not self.exp:
            return
        self.statusBar().showMessage('Archiving original files…')
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        archived = []
        try:
            for path in paths:
                archived.append(self.store.archive_file(self.exp, path))
            ok = self.mutate(lambda: self.exp['files'].extend(archived))
            if not ok:
                for f in archived:
                    self.store.archived_path(f).unlink(missing_ok=True)
        except Exception as exc:
            for f in archived:
                self.store.archived_path(f).unlink(missing_ok=True)
            self.error(exc)
        finally:
            QApplication.restoreOverrideCursor()

    def open_file(self, original):
        r = self.files.currentRow()
        if r < 0:
            self.error('Select an original file first.')
            return
        f = self.exp['files'][r]
        try:
            path = Path(f['original_path']).parent if original else self.store.archived_path(f)
            if not path.exists():
                raise ValueError('This location is unavailable. The archived copy may still be available in your library.')
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
                raise ValueError('No application could open this file. Use Library folder to locate the archived copy.')
        except Exception as exc:
            self.error(exc)

    def remove_file(self):
        if not self.exp or not self.files.selectedItems():
            return
        r = self.files.currentRow()
        if r < 0 or r >= len(self.exp['files']):
            return
        attachment = self.exp['files'][r]
        linked = [label(p) for p in self.exp['proteins'] if attachment['id'] in p['source_ids']]
        detail = 'Linked protein rows: ' + ', '.join(linked) if linked else 'No protein rows are linked to this file.'
        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Icon.Question)
        dialog.setWindowTitle('Remove attachment')
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        dialog.setText('Remove this file from the experiment?\n\n' + attachment['filename'])
        dialog.setInformativeText(detail + '\n\nIts source links will be removed. Raw intensities and calculations stay unchanged. '
                                  'The original file is untouched; the archived copy and removal record are retained in History.')
        dialog.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        dialog.button(QMessageBox.StandardButton.Yes).setText('Remove file')
        dialog.setDefaultButton(QMessageBox.StandardButton.Cancel)
        if dialog.exec() != QMessageBox.StandardButton.Yes:
            return
        if self.mutate(lambda: remove_attachment(self.exp, attachment['id'])):
            self.files.clearSelection()
            self.remove_file_button.setEnabled(False)
            self.statusBar().showMessage('Attachment removed. Original file untouched; archived copy retained for history.')

    def open_library(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.store.root)))

    def selected_protein(self):
        r = self.raw.currentRow()
        if r < 0:
            self.error('Select a protein row first.')
            return None
        return self.exp['proteins'][r]

    def add_protein(self):
        dialog = ProteinDialog(self, self.exp, self.store.protein_names())
        if dialog.exec():
            p = dict(id=uid(), values={}, imports=[], **dialog.data())
            self.mutate(lambda: self.exp['proteins'].append(p))
            self.raw.selectRow(len(self.exp['proteins']) - 1)

    def edit_protein(self):
        p = self.selected_protein()
        if p:
            d = ProteinDialog(self, self.exp, self.store.protein_names(), p)
            if d.exec():
                self.mutate(lambda: p.update(d.data()))

    def paste_data(self):
        p = self.selected_protein()
        if not p:
            return
        d = PasteDialog(self, p)
        if not d.exec():
            return
        overlap = [k for k, v in d.values.items() if k in p['values'] and p['values'][k] != v]
        if overlap and QMessageBox.question(self, 'Update existing raw values',
                f'{len(overlap)} existing values will change. Old and new values will be retained in History. Continue?') != QMessageBox.StandardButton.Yes:
            return
        def change():
            existing = {l['number'] for l in self.exp['lanes']}
            self.exp['lanes'].extend(dict(number=int(k), name=f'Lane {k}') for k in d.values if int(k) not in existing)
            self.exp['lanes'].sort(key=lambda l: l['number'])
            p['values'].update(d.values)
            p['imports'].append(dict(id=uid(), added=now(), column=d.column.currentText(), text=d.text.toPlainText()))
        self.mutate(change)

    def raw_changed(self, item):
        if self.rendering or item.column() == 0:
            return
        r, c = item.row(), item.column()
        try:
            val = number(item.text())
        except ValueError as exc:
            self.error(exc)
            self.render()
            return
        lane = str(self.exp['lanes'][c - 1]['number'])
        p = self.exp['proteins'][r]
        if p['values'].get(lane) == val:
            return
        self.mutate(lambda: p['values'].update({lane: val}))

    def view_imports(self):
        p = self.selected_protein()
        if not p:
            return
        d = QDialog(self)
        d.setWindowTitle('Original pasted tables — ' + label(p))
        d.resize(900, 600)
        v = QVBoxLayout(d)
        text = QPlainTextEdit()
        text.setReadOnly(True)
        text.setPlainText('\n\n'.join(f"{i['added']}  |  {i['column']}\n{i['text']}" for i in p['imports']) or 'No pasted imports yet.')
        v.addWidget(text)
        d.exec()

    def analysis(self):
        aid = self.analysis_choice.currentData()
        return next((a for a in self.exp['analyses'] if a['id'] == aid), None) if self.exp else None

    def add_analysis(self):
        n, d = self.numerator.currentData(), self.denominator.currentData()
        if not n or not d:
            self.error('Add protein rows first.')
            return
        if n == d:
            self.error('Choose different numerator and denominator rows.')
            return
        for a in self.exp['analyses']:
            if a['num'] == n and a['den'] == d:
                self.analysis_choice.setCurrentIndex(self.analysis_choice.findData(a['id']))
                return
        a = dict(id=uid(), num=n, den=d, groups=[])
        self.mutate(lambda: self.exp['analyses'].append(a))
        self.analysis_choice.setCurrentIndex(self.analysis_choice.findData(a['id']))

    def render_analysis(self, *_):
        a = self.analysis()
        if not a:
            fill(self.groups, [])
            fill(self.results, [])
            self.copy_values_button.setEnabled(False)
            self.copy_names_button.setEnabled(False)
            return
        names = {l['number']: l['name'] for l in self.exp['lanes']}
        fill(self.groups, [(g['name'], ', '.join(f'L{l}' for l in g['lanes']), f"L{g['ref']} · {names[g['ref']]}") for g in a['groups']])
        rows = calculate(self.exp, a)
        fill(self.results, [(r['lane'], r['sample'], r['group'], r['reference'], formatted(r['ratio']), formatted(r['relative']), r['status']) for r in rows])
        for i, r in enumerate(rows):
            self.results.item(i, 1).setForeground(QColor(sample_color(r['sample'])))
        for i, g in enumerate(a['groups']):
            self.groups.item(i, 2).setForeground(QColor(sample_color(names[g['ref']])))
        self.copy_values_button.setEnabled(bool(rows))
        self.copy_names_button.setEnabled(bool(rows))

    def copy_relative(self, with_names=False):
        a = self.analysis()
        if not a:
            return
        rows = calculate(self.exp, a)
        plain, rich = relative_clipboard(rows, with_names)
        mime = QMimeData()
        mime.setText(plain)
        mime.setHtml(rich)
        QApplication.clipboard().setMimeData(mime)
        missing = sum(r['relative'] is None for r in rows)
        self.statusBar().showMessage(f'Copied {len(rows)} lanes horizontally' +
                                    (f' · {missing} unavailable values kept as blank cells.' if missing else '.'))

    def add_group(self):
        self.group_dialog(False)

    def edit_group(self):
        self.group_dialog(True)

    def group_dialog(self, edit):
        a = self.analysis()
        if not a:
            self.error('Add or select a calculation first.')
            return
        index = self.groups.currentRow()
        if edit and index < 0:
            self.error('Select a group to edit.')
            return
        existing = a['groups'][index] if edit else None
        occupied = {l for g in a['groups'] if g is not existing for l in g['lanes']}
        d = GroupDialog(self, self.exp, occupied, existing)
        if d.exec():
            def change():
                if existing:
                    existing.update(d.data())
                else:
                    a['groups'].append(dict(id=uid(), **d.data()))
            self.mutate(change)

    def remove_group(self):
        a, r = self.analysis(), self.groups.currentRow()
        if not a or r < 0:
            return
        if QMessageBox.question(self, 'Remove group', 'Remove this group? Its settings remain in History.') == QMessageBox.StandardButton.Yes:
            self.mutate(lambda: a['groups'].pop(r))

    def render_history(self):
        if not self.exp:
            return
        self.history_rows = self.store.history(self.exp['id'])
        names = {p['id']: label(p) for p in self.exp['proteins']}
        rows = []
        for h in self.history_rows:
            obj = h['object_key']
            for pid, name in names.items():
                obj = obj.replace(pid, name)
            rows.append((h['changed'], h['kind'], obj,
                         h['old_value'] if h['kind'] == 'raw_value' else ('Attached' if h['kind'] == 'file_removed' else 'Previous snapshot'),
                         h['new_value'] if h['kind'] == 'raw_value' else ('Removed (archive retained)' if h['kind'] == 'file_removed' else 'Saved snapshot')))
        fill(self.history_table, rows)
        self.history_text.clear()

    def history_detail(self):
        r = self.history_table.currentRow()
        if r >= 0 and r < len(getattr(self, 'history_rows', [])):
            h = self.history_rows[r]
            self.history_text.setPlainText('OLD\n' + json.dumps(json.loads(h['old_value']), ensure_ascii=False, indent=2) + '\n\nNEW\n' + json.dumps(json.loads(h['new_value']), ensure_ascii=False, indent=2))

    def export(self):
        if not self.save():
            return
        path, _ = QFileDialog.getSaveFileName(self, 'Export horizontal raw and processed data',
            f"{self.exp['date']}_{self.exp['id'][:8]}.csv", 'CSV files (*.csv)')
        if path:
            if not path.lower().endswith('.csv'):
                path += '.csv'
            try:
                export_csv(self.exp, path)
                self.statusBar().showMessage('Exported: ' + path)
            except Exception as exc:
                self.error(exc)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--library', help='Local library folder containing the SQLite database and originals')
    parser.add_argument('--smoke-test', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    app = QApplication(sys.argv[:1])
    app.setApplicationName('Blot Notebook')
    app.setOrganizationName('BlotNotebook')
    app.setStyle('Fusion')
    app.setStyleSheet(STYLE)
    settings = QSettings()
    try:
        root = args.library or settings.value('library')
        if not root:
            documents = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
            if not documents:
                raise RuntimeError('Cannot locate your Documents folder. Start with --library to specify a folder.')
            root = Path(documents) / 'BlotNotebook'
        window = MainWindow(root)
    except Exception as exc:
        QMessageBox.critical(None, 'Cannot open library', str(exc))
        return 1
    if not args.library:
        settings.setValue('library', str(Path(root).resolve()))
    if args.smoke_test:
        from PySide6.QtGui import QFontDatabase
        window.ensurePolished()
        report = dict(started=True, tabs=window.tabs.count(), database=str(window.store.root / 'wbquant.sqlite3'),
                      integrity=window.store.db.execute('PRAGMA integrity_check').fetchone()[0],
                      available_fonts=len(QFontDatabase.families()))
        (window.store.root / 'smoke-test.json').write_text(json.dumps(report), encoding='utf-8')
        window.grab().save(str(window.store.root / 'smoke-test.png'))
        window.close()
        return 0
    window.show()
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
