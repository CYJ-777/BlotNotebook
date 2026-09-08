Western blot の定量計算と実験管理を行うデスクトップアプリです。

## ダウンロードと起動

- **Windows x64**：`BlotNotebook-Windows-x64.zip` を展開し、`BlotNotebook/BlotNotebook.exe` を起動してください。`_internal` を含むフォルダ全体が必要です。
- **Mac Apple Silicon（Mシリーズ）**：`BlotNotebook-macOS-arm64.zip` を展開し、`BlotNotebook.app` を起動してください。
- **Mac Intel**：`BlotNotebook-macOS-x64.zip` を展開し、`BlotNotebook.app` を起動してください。

Python のインストールは不要です。初回起動時に「ドキュメント」内の `BlotNotebook` フォルダを自動作成します。以前に保存先を設定している場合は、その設定を引き継ぎます。

## 含まれる機能

- 実験・レーン・タンパク質データの管理
- Bio-Rad データの貼り付け取込、正規化計算、CSV 出力
- 原本ファイルの保管、変更履歴、SQLite による保存

## 検証と配布形式

GitHub Actions の各対象 OS で自動テスト、PyInstaller ビルド、生成アプリの起動テストを行います。`SHA256SUMS.txt` に ZIP の SHA-256 を記載しています。

この版には Windows の発行元署名、Mac の Developer ID 署名・公証は含まれません。ダウンロードしたアプリの初回起動時に OS の確認やブロックが表示される場合があります。
