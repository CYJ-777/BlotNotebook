# Blot Notebook

An offline desktop MVP for Western blot quantification and experiment tracking. English interface. No image analysis, network requests or cloud storage.

## Run from source

From the project root, run `uv run app.py`. uv prepares Python 3.13 and the
PySide6 dependency. Initial setup requires an internet connection; routine use is offline.
At first launch, the app creates `BlotNotebook` inside your Documents folder and
opens the main window directly. On macOS this is `~/Documents/BlotNotebook`; on
Windows it uses the OS-configured Documents location. The library is remembered.
Previously selected libraries remain in use; existing data is not moved.
Use `uv run app.py --library /path/to/library` to choose a library for one run
without changing the remembered location. See [README](../README.md) for setup.

## Daily workflow

The workspace shows the current experiment above four workflow tabs, with your experiment library on the left. **Normalization** keeps the classic clear layout: numerator/denominator and **Add calculation** at the top, direct **+ Group / Edit group / Remove group / Export CSV** controls, and the full per-lane **Ratio / Relative expression / Status** table always visible. A horizontal relative-expression table with lane selection below the results offers **Copy values** and **Copy with sample names**. **Raw Data** separates files and protein intensities into cards: use **Open** for archived/original locations and **Row options** for protein/source editing and pasted source history. **Remove file** remains directly visible. The workspace header also includes **Delete experiment**. Pages scroll when content needs more room.

1. Select **New experiment**. Enter the date, cell line, treatment and notes.
2. Add lanes or paste sample names, one per line or as an Excel row. Repeated names are allowed; lane numbers identify samples independently.
3. In **Raw Data**, drag one or more original files into the drop area, or use **Add original files**. The app archives a copy and retains the original filename as metadata. Linked protein names are added to the archived copy name when saved. Same-name files get separate attachment directories.
4. Select **Protein row**. Enter any protein name and an optional measurement/exposure label. Link the row to its original file(s). Use separate rows for separate exposures of the same protein.
5. Select the row, then **Paste Bio-Rad data**. Paste one complete protein table with headers. Use **Read columns** if needed, select an intensity column, then **Preview** and **Import values**. The default is `Adj. Total Band Vol. (Int)`.
6. Repeat for additional proteins. Lanes are matched by their numbers, even if the pasted rows are out of order. Importing a subset leaves other lanes unchanged; no lane is filled with zero automatically.
7. In **Normalization**, select numerator and denominator and click **Add calculation**. Any different rows may be paired, including `pEGFR / EGFR`. You can save several calculations in the same experiment.
8. Add a group, check its member lanes, then select its reference lane. Add another group with its own reference. Groups may overlap, and the reference may be any lane in the experiment, including a lane outside the group. Group definitions belong to each calculation.
9. Review ratios, relative expression and statuses. A zero or missing denominator produces an unavailable result. A zero or unavailable reference prevents relative expression for its group. Negative background-adjusted intensities are retained and flagged for review.
10. **Save experiment** saves metadata. Imports, raw edits, lane-name changes, groups and attachments are saved immediately, together with current metadata. Unsaved metadata prompts on switching/closing. Reopen from the experiment list; search matches date, cell line, protein, condition, sample, notes or ID.
11. **Export CSV** exports horizontal raw intensities, ratios, group-relative rows, status rows and original-file metadata. CSV is UTF-8 with BOM and opens in Excel. It is a numeric snapshot of the current saved state, not a live formula workbook. Names beginning with spreadsheet formula characters are prefixed with an apostrophe for safe spreadsheet opening.
12. **Delete experiment** removes the selected experiment and its archived copies from the library after confirmation. Original files on disk are not touched.

The **Horizontal relative expression** panel sits below the results table in **Normalization**. **View group** filters the results and clipboard to one group using its own reference. **All groups** includes each group separately, so overlapping lanes can appear more than once. Select individual lanes, all lanes, or a lane-number range before copying. **Copy values** copies one row of numbers and **Copy with sample names** copies a sample-name row plus the number row. Both follow the displayed group/member order and leave unavailable values blank without shifting columns. Displayed and clipboard numbers use three decimal places. Stored calculations and CSV exports retain full precision. The clipboard includes TSV text and an HTML table with Arial 12pt formatting. HTML-aware paste targets can preserve red `luc` sample labels and black values; plain-text paste cannot preserve styling.

The UI uses Arial at 15px with taller table rows. Sample names containing `luc`, case-insensitively, are red in the lane table, raw-data headers and result views; other sample names are black. Internal UUID fragments are hidden from protein/calculation selectors. Measurement labels identify exposures; otherwise identical labels receive readable row numbers while retaining stable internal IDs.

## Traceability and backup

The library contains `wbquant.sqlite3` and `experiments/<date_cell_condition_short-ID>/originals/<attachment UUID>/<display filename>`. Experiment folder names remain stable after metadata edits. Older UUID folders are migrated automatically when the library opens. Original source files are not modified. Files are streamed to a SHA-256 hash after copying. The original absolute path and portable archive-relative path are both retained. **Open archived file** uses the operating system's associated application; TIFF rendering is outside this app.

Raw edits record old/new values and UTC timestamps in **History**. Complete snapshots preserve the earlier labels, imports and calculation settings. **View pasted source** displays the exact imported clipboard text. History is an application audit trail, not a tamper-proof regulated record.

To correct an accidental attachment, select it in **Raw Data** and click **Remove file**. Confirmation identifies the filename and linked protein rows. Removal detaches that attachment and its protein source links atomically; it does not change intensities or calculations. The original file is untouched. The archived bytes remain in the library for traceability, and a `file_removed` entry in **History** retains the file metadata and archive path. This is removal from the experiment, not permanent disk deletion. Same-name attachments are distinguished by their IDs.

To back up or move to another computer, close the app and copy the entire library folder, including the database and `experiments` directory. Open the copied library on the other computer. The old original path may be unavailable there; the archived copy remains accessible. Use the library on one computer at a time, on a local disk. This MVP is not a multi-user shared network database.

## Architecture and schema

`app.py`: native PySide6 windows, dialogs, file drop, tables and clipboard workflow.

`core.py`: strict tab/CSV parser, calculations, portable archives, CSV export and SQLite transactions.

SQLite schema: `experiments`, `lanes`, `protein_rows`, `raw_values`, `imports`, `original_files`, `protein_sources`, `normalization_sets`, `normalization_groups`, `group_members`, `audit_log`. UUIDs identify experiments, measurements, sources, calculations and groups. Lane identity is the number within an experiment. Updates are atomic; experiment revisions detect stale edits from another window. Schema version is 2; version 1 libraries are upgraded automatically.

The calculation is:

```text
ratio[lane] = numerator[lane] / denominator[lane]
relative[lane] = ratio[lane] / ratio[group.reference_lane]
```

The reference is identified by lane number, never by sample name.

## Validation

Run from the project root:

```sh
uv run python -m unittest discover -s tests -v
```

Tests cover core processing and an offscreen GUI startup with a temporary library.
See [Build instructions](build.md) for the shared macOS / Windows PyInstaller configuration and packaged startup checks.

## MVP boundaries

One band per lane; one protein table per paste. TSV from Bio-Rad/Excel and quoted CSV are accepted. English lane headers (`Lane No.`, `Lane`, `Lane Number`, `Lane ID`) are recognized. Invalid values, repeated lanes and combined tables are rejected, not summed or silently skipped. Commas are supported only as unambiguous thousands separators; decimal numbers use a period.

CSV export is included. Native `.xlsx`, automatic migration of historical workbooks, charting, GraphPad-specific exports, image previews, image analysis and AI features are not included. Protein rows can be relabeled and intensities corrected; protein-row deletion remains intentionally unexposed in this version, while experiments can be deleted from the workspace header. Removing a normalization group preserves its earlier settings in History.
