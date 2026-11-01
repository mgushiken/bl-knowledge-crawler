# 設計検証用の試行コード

アプリ本体ではなく、依存ライブラリ・保存順序などの技術的な前提をダミーで確認するためのコード。成功しても本番アプリの受入合格とはしない。実施結果と残項目は [技術確認記録](../../docs/detailed-design-validation.md)10～13節を参照する。

## Pythonの試行

Windowsでリポジトリのルートから実行する。導入先は専用の `.venv`。PyYAMLのC拡張を使わず、PCのコンパイラーや権限設定は変更しない。

```powershell
uv venv --python 3.15.2 .venv
$env:PYYAML_FORCE_LIBYAML = '0'
$env:UV_LINK_MODE = 'copy'
uv pip install --python .venv/Scripts/python.exe -r requirements-validation.txt
.venv/Scripts/python.exe tools/validation/dependency_probes.py
.venv/Scripts/python.exe tools/validation/merged_table_probe.py
.venv/Scripts/python.exe tools/validation/dependency_smoke.py
```

既に `.venv` がある場合は環境作成を繰り返す必要はない。試行のファイル操作は `%LOCALAPPDATA%/BlackLineKnowledgeCrawler/design-checks/` 内の新規一時フォルダだけで行う。HTTPは127.0.0.1の一時サーバーだけを使い、ブラウザや実記事へPythonから接続しない。

## ブラウザの試行

Playwriterの自分専用セッションをポート9223へ接続し、`browser_fixture_probes.js` をCLIの `-s <自分のセッションID> -f tools/validation/browser_fixture_probes.js` で実行する。実行後にそのセッションを削除する。CLIの接続例は `playwriter session new --direct 127.0.0.1:9223 --tab-group validation`。

スクリプトは自分で作成したabout:blankタブだけを使い、finallyで閉じる。example.invalid向け要求はタブ内ルートで応答する。出力するbase64は自作の3×2 PNGだけであり、実画像・記事本文・Cookieは扱わない。最後の `DUMMY_BYTES=` の値をPythonで厳密base64復号・Pillow検証することで受渡しを再確認できる。

## 検証exeのビルド

毎回一意なdistサブフォルダを作り、以前のexeを保持する。これは依存の検証exeであり、本番クローラーのexeではない。

```powershell
$validationId = 'validation-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N')
$validationDist = Join-Path (Get-Location) ('dist/' + $validationId)
$validationWork = Join-Path $env:TEMP $validationId
New-Item -ItemType Directory -Path $validationDist,$validationWork | Out-Null
.venv/Scripts/python.exe -m PyInstaller --onefile --name dependency-smoke --distpath $validationDist --workpath (Join-Path $validationWork 'build') --specpath $validationWork tools/validation/dependency_smoke.py
& (Join-Path $validationDist 'dependency-smoke.exe')
```

同梱ドライバーの起動だけを確認し、Chromeの起動・接続は行わない。別cwd・Python関連変数なし・Windows標準ディレクトリだけのPATHでも起動を確認したが、Python未導入の別Windows 11での確認は別途必要となる。
