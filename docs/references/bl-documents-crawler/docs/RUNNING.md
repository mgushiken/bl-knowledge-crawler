# ドキュメント取得アプリの実行

Windows 11とインストール済みChromeを使用します。exe配布時は`bl-documents-crawler`フォルダ全体（`_internal`を含む）が必要です。Pythonの別途インストールは不要です。Chrome本体と認証プロファイルは配布物へ追加しません。

## 起動前の準備

1. `settings.example.toml`をexe隣の`settings.toml`へコピーし、保存フォルダ・エラーフォルダ・完了日時ファイルを設定してください。既存の実設定は上書きしないでください。ソース実行時の設定配置はリポジトリルートです。相対パスは設定の所在が基準です。
2. 専用プロファイルを同期対象外に置き、Chromeを起動します。既存の9222ポートを別用途で使っている場合は、その接続を流用しないでください。

```powershell
& "${env:ProgramFiles(x86)}/Google/Chrome/Application/chrome.exe" --remote-debugging-address=127.0.0.1 --remote-debugging-port=9222 "--user-data-dir=$env:LOCALAPPDATA\BlackLineCrawler\ChromeProfile"
```

3. 専用ChromeでBlackLineへ手動ログインし、起点ページと左メニューを表示します。アプリはログイン操作を行いません。Cookie・パスワード・トークンを設定へ書かないでください。
4. `DEBUG`・`PWDEBUG`・`NODE_DEBUG`を設定していない実行環境で、アプリを実行します。

```powershell
& .\bl-documents-crawler.exe
$LASTEXITCODE
```

`crawl.mode`省略時またはsingleでは、設定した1ページを保存して終了します。正常終了は0、異常終了は1です。continuousは下記の準備後、起点カテゴリ配下を巡回します。作業ディレクトリには依存しません。同じ保存先・進捗へ同時実行しないでください。Chromeと既存タブは維持します。

## 複数ページ巡回の設定と対応範囲

2026-10-26に、確認済みの全行DOM構造へ限定したcontinuousを通常入口へ接続しました。既定は引き続きsingleで、crawl表を省略した旧設定もそのまま使えます。実設定は自動変更しません。

巡回する場合はsource.start_urlへ起点カテゴリを指定し、crawl.modeをcontinuousへ変更し、crawl.result_dirへ一巡結果用のフォルダを指定します。進捗ファイルは省略時LOCALAPPDATA/BlackLineCrawler/state/progress.jsonです。全出力先の説明・待機設定はsettings.example.tomlを参照してください。

対応するのは、展開・スクロール後も全行がDOMに残り、祖先・兄弟位置・件数・終端・記事IDを検証できるメニューです。DOM入替え、欠落、未知のURLなし見出し構造等で完全性を証明できなければ、部分一覧で進まずDISCOVERY_ERRORで全体停止します。記事リンクを押して一覧を広げず、固定一覧の親→子孫→次の同階層の順に取得します。

対象記事のresolve-redirectとget-article-detailを必須とし、get-article-dataは発行された場合に監視します。同じ記事ID・言語のAPIは版を問わず監視し、別版の先読みでも401/403なら全体停止します。必須APIの未観測・取得失敗・画像転送等は当該ページをスキップし、次の一巡で再取得します。転送だけで認証失効を検知できずスキップが続く場合がある、合意済みの制約は残ります。

正常・スキップの保存／出力・後片付け・進捗確定後に待機し、一巡後も同じ待機を1回だけ適用します。Ctrl+Cで終了し、通常の手動終了は0、後片付け等に失敗すれば1です。再起動時は正式な進捗から再開し、待機は再抽選して最初から行います。破損や起点・保存先変更で止まる場合は、アプリ停止を確認して進捗を別名へ退避してから再実行してください。記事・画像・履歴は自動削除しません。

実サイト用の進捗はschema_version=2で行内ID・言語・形式を内部保持します。schema_version=1は共通制御の識別子なし形式として読み込めますが、実サイト取得へ渡すIDがない状態では取得できません。自動補完・自動移行はしません。

基準待機時間は60～3600の整数秒、揺らぎは0～30の整数秒です。bool・小数・文字列・範囲外はsingleでも設定エラーになります。singleでは進捗内容を読まず、進捗専用フォルダ・一巡結果フォルダを作りません。追加キーを含む新設定は、crawl表に未対応の旧exeへ渡さないでください。実設定は自動更新しません。

テストは上記の共通基盤に加え、tests/test_article_api.pyとtests/test_menu.pyを含み、通常のcontinuous入口からダミーの列挙・取得・保存・一巡結果まで接続しています。2026-10-26にはソース実装で実サイト3ページの保存・ページ間の停止と再開、および別の画像付き記事1件・画像7件の保存を確認しました。詳細と最新の回帰結果は詳細設計27～28節を参照してください。実サイトへの配布exe実行と、Python未導入の別Windowsでの確認は未実施です。

continuousの本文取得は、必須API完了後にload・本文内の非lazy画像の読込終了・短時間の描画安定を待って比較基準を確定します。その後の変化は整合不成立としてスキップします。短時間安定したことを、将来の描画やAPIが終了した保証には使いません。

画像取得では通信・形式の失敗とローカルI/O・応答解放の失敗を分離しました。singleの画像転送は従来どおり停止し、画像を一時保存できなければSAVE_ERROR、応答を解放できなければCLEANUP_ERRORとして停止します。continuousは画像の301/302/303/307/308でページ全体をスキップします。

## 保存と障害時の対応

無変更ならMarkdownは上書きせず、正常な確認の完了日時だけを更新します。Markdown・画像の保存と後片付けの成功後に完了日時を更新します。OneDrive・SharePointのクラウド同期完了は待ちません。Downloads等の非同期フォルダも設定できます。

失敗時は設定したエラーフォルダのJSONを確認してください。設定不備・ログ書込失敗ではexe隣への代替出力と標準エラー表示を試みます。自動リトライ・再起動は行いません。認証エラーは専用Chromeで再ログインしてから再実行してください。

改名・移動後の旧記事削除に失敗した場合、次回はURL重複で停止します。画像参照・本文・created_atを確認して旧版を手動除去してください。最終フォルダの`.bl-*.tmp`や`%LOCALAPPDATA%/BlackLineCrawler/tmp/`の残留物は、アプリ停止を確認してから人が削除できます。旧画像は自動削除しません。

## 開発・ビルド

Python 3.13.16と固定依存を使用します。OneDrive外の環境を作り、有効化せずPythonを指定してください。

```powershell
$appEnv = Join-Path $env:LOCALAPPDATA ('BlackLineCrawler/app-envs/' + [guid]::NewGuid().ToString('N'))
uv venv --python 3.13 $appEnv
$appPython = Join-Path $appEnv 'Scripts/python.exe'
uv pip install --python $appPython --link-mode copy -r requirements-build.txt
& $appPython run_crawler.py
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
& $appPython -m unittest discover -s tests -v
./scripts/build.ps1 -PythonPath $appPython
```

通常テストはダミーサイトと新しいheadless Chromeだけを使用します。本番コードは`validation/`をインポートしません。ビルドは`dist/<日時-UUID>/`へ新規作成し、実設定や認証情報をコピーしません。ビルドログと最新exeのパスは`validation/output/`へ保存します。

2026-10-25にユーザーが実BlackLineで実行し、想定どおりのMarkdown出力・画像保存・表のMarkdown化を確認しました。1ページを取得する初期バージョンは完成です。Python未導入の別Windows 11での配布確認と、実サイトの認証切れ・仮想スクロール・特殊画像などの追加ケースは後日に残しています。
