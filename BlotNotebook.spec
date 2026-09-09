# Run on the target OS: uv run --group build pyinstaller --noconfirm BlotNotebook.spec
import sys
from pathlib import Path

a = Analysis(
    [str(Path(SPECPATH) / 'app.py')], pathex=[SPECPATH],
    binaries=[], datas=[(str(Path(SPECPATH) / 'assets'), 'assets')], hiddenimports=[], hookspath=[], hooksconfig={},
    runtime_hooks=[], excludes=[], noarchive=False, optimize=0,
)
if sys.platform == 'win32':
    # Qt uses Windows' system ICU. Do not bundle conflicting development DLLs.
    a.binaries = [entry for entry in a.binaries
                  if Path(entry[0]).name.lower() not in {'icuuc.dll', 'icudt78.dll'}]

pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True, name='BlotNotebook',
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    console=False, disable_windowed_traceback=False, argv_emulation=False,
    target_arch=None, codesign_identity=None, entitlements_file=None,
    icon=str(Path(SPECPATH) / 'assets' / 'blotnotebook-seal.ico') if sys.platform == 'win32' else None,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='BlotNotebook')
if sys.platform == 'darwin':
    app = BUNDLE(coll, name='BlotNotebook.app', icon=None,
                 bundle_identifier='local.blotnotebook.desktop', version='0.1.0')
