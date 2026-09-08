# macOS / Windows ビルド

PyInstaller は実行した OS 向けのアプリを生成します。Mac 版は Mac、Windows 版は Windows でビルドしてください。
ビルド先の CPU アーキテクチャは使用する Python に従います。このプロジェクトの Python は 3.13、GUI は PySide6 6.10.2 です。

## 共通コマンド

uv をインストールした上で、プロジェクト直下で実行します。

```sh
uv sync --locked --group build
uv run --locked python -m unittest discover -s tests -v
uv run --locked --group build pyinstaller --noconfirm BlotNotebook.spec
```

`--noconfirm` は既存の同名ビルド出力を置き換えます。実験ライブラリを `build/` や `dist/` に置かないでください。
通常のアプリ利用には PyInstaller は不要です。ビルド用依存は `build` グループで管理しています。

## macOS

成果物は `dist/BlotNotebook.app` です。Finder でダブルクリックして起動できます。
Apple Silicon の Python でビルドすると ARM64 版になります。Intel 版が必要なら Intel/x86_64 の環境で別途ビルドしてください。
生成される `dist/BlotNotebook/` はビルド中間成果物で、配布には `.app` 全体を使います。

パッケージ内の実行ファイルを起動テストする場合：

```sh
BLOTNOTEBOOK_EXECUTABLE="$PWD/dist/BlotNotebook.app/Contents/MacOS/BlotNotebook" uv run --locked python -m unittest discover -s tests -p test_startup.py -v
```

配布用 ZIP を作る場合（アプリ内のシンボリックリンクと実行権限を保持）：

```sh
ditto -c -k --sequesterRsrc --keepParent dist/BlotNotebook.app dist/BlotNotebook-macOS.zip
```

Developer ID 署名・Apple の公証はこの設定には含みません。他の Mac に配布する正式版では別途対応が必要です。

## Windows

Windows 10/11 x64 と x64 Python を使用します。
成果物は `dist/BlotNotebook/BlotNotebook.exe` です。
`_internal` を含む **`dist/BlotNotebook/` フォルダ全体**を配布してください。受け取り側に Python は不要です。
ビルド設定は、開発ツール由来の ICU DLL が Windows のシステム ICU と衝突するのを防ぎます。

PowerShell でパッケージの起動テストを実行する場合：

```powershell
$env:BLOTNOTEBOOK_EXECUTABLE = "$PWD/dist/BlotNotebook/BlotNotebook.exe"
uv run --locked python -m unittest discover -s tests -p test_startup.py -v
Remove-Item Env:BLOTNOTEBOOK_EXECUTABLE
```

## GitHub Actions

`.github/workflows/build.yml` は手動実行用です。GitHub にコードを置いた後、Actions の **Build desktop apps → Run workflow** から実行できます。
macOS と Windows でそれぞれソースのテスト、ビルド、生成アプリの起動テストを行い、成功した成果物をアップロードします。
このファイルの追加だけではビルドは実行されません。

起動テストは一時ライブラリを使用し、4つのタブ、SQLite の整合性、画面画像の生成を確認します。
実際のクリック操作や他の端末での配布動作まで保証するテストではありません。
