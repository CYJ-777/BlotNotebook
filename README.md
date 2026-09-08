# Blot Notebook / wbquant

An offline desktop application for Western blot quantification and experiment tracking.
`app.py` provides the PySide6 GUI, while `core.py` handles calculations and data storage.

Download ready-to-use ZIP packages for Windows x64, Mac Apple Silicon, and Mac Intel from
[GitHub Releases](https://github.com/CYJ-777/BlotNotebook/releases). Python is not required to run these packages.

## Run from source

Install uv, then run this command from the project root (the folder containing this README):

```sh
uv run app.py
```

uv prepares Python 3.13 and the required dependencies. Initial setup requires an internet connection.
On first launch, the app creates its experiment library automatically and opens the main window.

- **macOS:** `~/Documents/BlotNotebook`
- **Windows:** `BlotNotebook` inside your Documents folder, typically `C:\Users\<username>\Documents\BlotNotebook`

If your Windows Documents folder has been relocated, the app uses the location reported by the OS.
The library location is remembered. If you previously selected a library, the app continues to use it without moving your data.
An error is shown if the library cannot be created.

To use a specific library for one session:

```sh
uv run app.py --library ./data
```

`--library` applies only to that session and does not change the remembered location.
The library contains `wbquant.sqlite3` and copies of attached original files.
To back up your data, close the app and copy the entire library folder.

## Project structure

```text
app.py              GUI and application entry point
core.py             Calculations, imports, SQLite storage, and CSV export
pyproject.toml      Python requirements and dependencies
uv.lock             Locked dependency versions
BlotNotebook.spec   Shared macOS and Windows PyInstaller configuration
tests/              Automated tests
examples/           Sample TSV files for import
docs/user-guide.md  Detailed usage instructions
docs/build.md       Build and release instructions
.github/workflows/  GitHub Actions build and release workflow
```

## Tests

```sh
uv run python -m unittest discover -s tests -v
```

Tests cover calculations, data storage, default library selection, and offscreen GUI startup with a temporary library.

## Build the application

Run the following command on each target operating system. Build the macOS app on macOS and the Windows app on Windows.

```sh
uv run --locked --group build pyinstaller --noconfirm BlotNotebook.spec
```

On macOS, open `dist/BlotNotebook.app`. On Windows, open `dist/BlotNotebook/BlotNotebook.exe`.
The Windows package requires the entire `BlotNotebook` folder, including `_internal`.

See the [build instructions](docs/build.md) for details. GitHub Actions supports manual builds and
publishes Release packages when a version tag is pushed. Build outputs are excluded from Git.

## Layout changes

Source files previously stored in `outputs/wbquant/` now live in the project root.
Update any launch configurations that reference the old paths. The application entry point is `app.py`.
The placeholder `main.py`, old Windows binaries, and outdated distribution ZIPs have been removed.
`BlotNotebook.spec` now provides a shared macOS and Windows build configuration for the current layout.
Dependencies are managed through `pyproject.toml` and `uv.lock`.

During cleanup, previous verification materials and databases from `work/` were preserved locally in
`archive/legacy-work/`. These historical files are not included in the repository or required to run the app.
The experiment data format and remembered library settings were preserved.
