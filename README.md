# Blot Notebook / wbquant

An offline desktop application for Western blot quantification and experiment tracking.
`app.py` provides the PySide6 GUI, while `core.py` handles calculations and data storage.

Download ready-to-use ZIP packages for Windows x64, Mac Apple Silicon, and Mac Intel from
[GitHub Releases](https://github.com/CYJ-777/BlotNotebook/releases). Python is not required to run these packages.

## Data storage

**Experiment data is saved in your Documents folder**, for both the downloaded app and the source version.
On first launch, the app creates its library automatically and opens the main window.

- **macOS:** `~/Documents/BlotNotebook`
- **Windows:** `BlotNotebook` inside your Documents folder, typically `C:\Users\<username>\Documents\BlotNotebook`

The library contains the `wbquant.sqlite3` database and copies of attached original files.
To back up your data, close the app and copy the entire `BlotNotebook` library folder.

If your Windows Documents folder has been relocated, the app uses the location reported by the OS.
The library location is remembered. If you previously selected a library, the app continues to use it without moving your data.
An error is shown if the library cannot be created.

## macOS security note

The current Mac packages do not have Developer ID signing or Apple notarization, so macOS may block the first launch.
After attempting to open the app, you can use **System Settings → Privacy & Security → Open Anyway**, as described in
[Apple's instructions](https://support.apple.com/en-us/102445).

For a copy downloaded from this repository's Releases that you trust, you can alternatively remove the download quarantine attribute in Terminal:

```sh
xattr -dr com.apple.quarantine "/path/to/BlotNotebook.app"
```

Replace the quoted path with the actual location of the extracted app. For example, if you moved it to Applications:

```sh
xattr -dr com.apple.quarantine "/Applications/BlotNotebook.app"
```

Then open the app again. This command removes the quarantine attribute recursively from that app bundle; it does not disable Gatekeeper system-wide.
Running `xattr` with only a path lists attributes and does not remove them.
Only apply this to an app whose source you have verified; it does not repair a corrupted download or establish that an app is safe.

## Run from source

Install uv, then run this command from the project root (the folder containing this README):

```sh
uv run app.py
```

uv prepares Python 3.13 and the required dependencies. Initial setup requires an internet connection.
The app uses the Documents library described above by default.

To use a specific library for one session:

```sh
uv run app.py --library ./data
```

`--library` applies only to that session and does not change the remembered location.

## Project structure

```text
app.py              GUI and application entry point
core.py             Calculations, imports, SQLite storage, and CSV export
pyproject.toml      Python requirements and dependencies
uv.lock             Locked dependency versions
BlotNotebook.spec   Shared macOS and Windows PyInstaller configuration
assets/             Application icon assets
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
