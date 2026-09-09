# JSON Project storage

## Project layout

Each Project is a self-contained folder:

```text
MyProject/
├── project.json
└── experiments/
    └── 2026-09-09_PC9_MG132_ab12cd34/
        ├── experiment.json
        ├── experiment.json.bak
        └── originals/
            └── <display filename>
```

`project.json` identifies the folder as a Blot Notebook Project and records its format version. Each `experiment.json` contains the complete experiment and its change history. All archived files for an experiment live directly in its `originals` directory. Attachment UUIDs remain in JSON and add a short filename suffix when names collide. Paths to archived originals are relative to the Project root, so the entire folder can be moved between computers.

## Save safety

JSON is written to a complete temporary file in the destination directory, flushed to disk, and atomically moved over `experiment.json`. Before replacement, the previous valid document is copied to `experiment.json.bak`. An operating-system file lock prevents concurrent writes, and a revision number rejects saves from a stale second window. Project folders are intended for one local computer at a time; simultaneous editing over a shared or cloud-synchronized folder is not supported.

Do not edit JSON while the Project is open. If manual repair is necessary, close the app and back up the complete Project first. Files with a schema version newer than the application supports are rejected instead of being rewritten.

## Breaking storage change and SQLite migration

The active persistence format changed from the single `wbquant.sqlite3` database to per-experiment JSON documents. Existing libraries remain supported through a one-time, non-destructive import:

1. Open the folder containing `wbquant.sqlite3` from the Project chooser.
2. The app opens the database in read-only mode and writes `project.json` plus an `experiment.json` for each stored experiment.
3. Existing flat archives stay in place. Files in legacy per-attachment UUID folders are copied into the flat JSON layout, while their original copies remain available to the SQLite backup.
4. `wbquant.sqlite3` is neither modified nor deleted. Keep it until the imported Project has been checked and backed up.

After `project.json` exists, the app uses JSON and does not write new changes to the legacy database. Reopening the database with an older application therefore will not show edits made in the JSON version.

## Recent Projects

The application stores at most ten Project paths in the operating system's application settings. This list contains paths only; experiment content remains in each Project folder. Missing paths are omitted. The legacy single-library setting is included automatically so an existing installation offers its previous library in the chooser.
