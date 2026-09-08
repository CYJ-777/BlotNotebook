# Blot Notebook / wbquant

Western blot の定量計算と実験管理を行う、ローカル保存型のデスクトップアプリです。
`app.py` が PySide6 の GUI、`core.py` が定量処理とデータ保存を担当します。

ビルド済みアプリは [GitHub Releases](https://github.com/CYJ-777/BlotNotebook/releases) からダウンロードできます。
Windows x64、Mac Apple Silicon、Mac Intel 用の ZIP を提供します。Python のインストールは不要です。

## 起動

uv を用意し、この README があるプロジェクト直下で実行します。

```sh
uv run app.py
```

Python 3.13 と必要なライブラリは uv が準備します。初回の環境構築にはインターネット接続が必要です。
初回起動では実験データの保存先を自動作成し、そのままメイン画面が開きます。

- Mac：`~/Documents/BlotNotebook`
- Windows：ユーザーの「ドキュメント」内の `BlotNotebook`（通常は `C:\Users\ユーザー名\Documents\BlotNotebook`）

Windows のドキュメントを別の場所に移している場合は、OS が返す実際の場所を使用します。
保存先は記憶されます。以前に保存先を選択済みの場合は、その場所を引き続き使い、データの自動移動は行いません。
保存先を作成できない場合はエラーを表示します。

保存先を明示して起動することもできます。

```sh
uv run app.py --library ./data
```

`--library` はその起動にだけ適用され、記憶済みの保存先を変更しません。
保存先には `wbquant.sqlite3` と原本ファイルのコピーが作られます。
バックアップする際はアプリを閉じ、保存先フォルダ全体をコピーしてください。

## ファイル構成

```text
app.py              GUI・起動処理
core.py             定量計算・取込・SQLite保存・CSV出力
pyproject.toml      Python要件・依存ライブラリ
uv.lock             依存ライブラリの固定情報
tests/              自動テスト
examples/           取込用のサンプルTSV
docs/user-guide.md  詳細な操作説明
archive/            以前の検証資料・データ（通常の起動には不要）
```

## テスト

```sh
uv run python -m unittest discover -s tests -v
```

定量処理のテストに加え、一時フォルダを使って画面表示なしでGUIの起動とデータベース作成を確認します。

## アプリのビルド

Mac / Windows のそれぞれの環境で実行してください。

```sh
uv run --locked --group build pyinstaller --noconfirm BlotNotebook.spec
```

Mac は `dist/BlotNotebook.app`、Windows は `dist/BlotNotebook/BlotNotebook.exe` を起動します。
Windows は `_internal` を含むフォルダ全体が必要です。
詳しくは [ビルド手順](docs/build.md) を参照してください。GitHub Actions では手動ビルドと、バージョンタグによる Release 配布に対応しています。

## 構成変更

以前の `outputs/wbquant/` のソースはプロジェクト直下に移動しました。
旧パスを使用する起動設定は更新してください。起動対象は `app.py` です。
挨拶だけを表示していた `main.py`、旧Windowsビルド、古い配布ZIPは削除しました。
現在の `BlotNotebook.spec` は整理後の構成に対応した Mac / Windows 共通ビルド設定です。
依存関係は `pyproject.toml` と `uv.lock` で管理します。
以前の `work/` にあった検証資料とデータベースは `archive/legacy-work/` に保管しています。
その中の旧スクリプトや資料は当時の記録であり、現在の構成での実行対象ではありません。
実験データの形式と、アプリが記憶している保存先設定は変更していません。
