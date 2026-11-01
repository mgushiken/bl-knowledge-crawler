# 詳細設計書 — BlackLine Knowledge 取得アプリ

作成日：2026-11-01

状態：詳細設計レビュー用。合意済みの動作を実装単位へ整理し、ブラウザ処理・Windowsファイル操作・Python依存を限定検証した。専用 `.venv` と検証用依存版を固定し、依存同梱の検証exeをビルド・実行済み。残項目は14節、実施範囲は[詳細設計検証記録](detailed-design-validation.md)に記載する。アプリ本体・その自動テスト・本番exe・配布受入確認は未実施。

## 1. 根拠・設計の境界

[要件定義書](requirements.md)、[基本設計書](basic-design.md)、[限定調査記録](knowledge-article-observations.md)を根拠とする。外部契約・設定名・保存形式を本書で独立して変更しない。参照クローラーの停止・監視・進捗管理をそのまま移植しない。

以下は実装予定の構成であり、ファイルや関数が存在することを示さない。純粋処理とI/Oを分け、単純なdataclassと関数を中心とする。汎用クローラーフレームワーク・プラグイン機構は設けない。

## 2. ファイル・モジュール構成

```text
run_knowledge_crawler.py
src/bl_knowledge_crawler/
  __init__.py
  app.py
  model.py
  config.py
  input_store.py
  locking.py
  browser.py
  network.py
  extractor.py
  images.py
  document.py
  storage.py
  operations.py
tests/
  fixtures/knowledge/       # ダミーHTML・通信・画像のみ
scripts/build.ps1
settings.example.toml
```

| モジュール | 主要インターフェース・責務 |
| --- | --- |
| app | `main() -> int`、`run(settings, dependencies) -> RunResult`。逐次制御と例外の境界 |
| model | 値オブジェクト・固定例外・列挙値。I/Oなし |
| config | `get_app_dir()`、`load_settings(path) -> Settings`。TOML・型・パスの検証 |
| input_store | `load_input(path)`、`validate_entry(value, index)`、`mark_completed(index)`。JSON保持・原本比較・置換 |
| locking | `acquire_resources(input_path, output_dir)`。入力と保存先の排他 |
| browser | `BrowserSession.open()`、`new_work_page()`、`close_work_page()`、`disconnect()`。既存Chromeを維持 |
| network | `ActionMonitor.start(page, attempt_id)`、`resolve_article(deadline)`。要求・応答の相関 |
| extractor | `read_snapshot(page, article_data, deadline)`、`wait_stable(...)`。記事領域・項目・画像参照の抽出 |
| images | `fetch_images(context, refs, workspace, timeout)`。認証付きGET・形式検証・内容ハッシュ |
| document | `build_candidate(snapshot, images)`。Markdown・フロントマター・比較用ハッシュ |
| storage | `scan_existing(root)`、`plan_save(candidate, existing)`、`commit_save(plan)`。比較・保存・修復 |
| operations | `Deadline`、`write_error(error)`、`write_diagnostic(...)`、件数表示。秘密値を出力しない |

ブラウザ取得結果は、タブを閉じても利用できる値と一時画像パスで返す。Playwrightオブジェクトを保存層へ渡さず、ログ層へHTML・画像・通信の生オブジェクトを渡さない。時刻・乱数・待機・セッション生成は関数引数で差し替え可能にし、テストのための大きな基盤は追加しない。

## 3. 内部データ・例外

| 型 | 主なフィールド |
| --- | --- |
| Settings | input_path、output_dir、error_dir、interval_seconds、jitter_seconds、3種のtimeout_seconds |
| RunContext | run_id（UUID）、started_at、workspace、counts、execution_failed、cleanup_failed |
| InputDocument | 元のJSONツリー、読込バイト列のSHA-256、入力パス。元データを明示的に保持 |
| Entry | index（0始まり）、input_url、canonical_url、url_hash。正常なtrueだけ取得対象 |
| InvalidEntry | index、固定reason_code。入力値の全文は保持・出力しない |
| ArticleIdentity | attempt_id、url_name、article_version_id、record_type_name。実行メモリ内のみ |
| ArticleField | name、label、source_html、dom_html、表示状態。順序はAPIの宣言順 |
| PageSnapshot | input_url、canonical_url、final_url、title、fields、image_refs、比較用DOM射影 |
| ImageRef / ImageAsset | 項目・出現位置の識別子、取得URL（メモリ内のみ）／hash、extension、temp_path |
| DocumentCandidate | title、source_url、body、hash_body、content_hash、images、fetched_at |
| ExistingDocument | path、source_urlの復元可否、検証済みメタデータ、破損理由、本文 |
| SavePlan | kind（new / unchanged / update / repair）、target、同一URLの旧パス群、日時、画像反映計画 |
| RunResult | counts、exit_code、execution_error_code。ブラウザや入力全文を含めない |

HTML・取得URL等を含むフィールドはdataclassの `repr` へ出さない。画像ハッシュ・URLハッシュは小文字16進の全64桁、メタデータでは内容ハッシュに `sha256:` を付ける。

`ArticleError` は記事単位の失敗、`RunError` は全体停止とする。いずれも `code`、`stage`、`input_index`、安全な記事URL、任意のHTTPステータス、固定messageを持つ。生の例外文を利用者向け文字列へ連結しない。`KeyboardInterrupt` は最外周で捕捉し、終了コード1へ変換する。

## 4. 設定・JSONの読込

### 4.1 設定

exeでは `Path(sys.executable).parent`、ソースでは入口スクリプトの親を基準とする。PyInstallerの内部展開先やカレントディレクトリを設定基準にしない。

1. `tomllib` で設定を読み、基本設計3節のセクション・項目を検証する。未知キー・必須値欠落・型不正は `CONFIG_ERROR`。
2. 時間値は `type(value) in (int, float)`、有限値を要求し、真偽値は拒否する。待機は0以上、期限は正数、揺らぎは基準以下。
3. 空パス・ドライブ相対パス（`C:folder`）を拒否し、相対パスを設定ファイル基準で解決する。JSONは既存ファイル、出力・ログはフォルダとして扱う。
4. 出力とログの一致・包含関係、入力ファイルが出力・ログ生成で上書きされる配置を拒否する。副作用の前に設定を一通り検証する。
5. 出力・ログの親を必要に応じて作成する。ログ先を使えない設定障害では基本設計10.3節の代替先と標準エラーを用いる。

秒は内部で保持し、Playwright呼出し時だけミリ秒へ変換する。設定例の各値には用途・秒単位・ファイルとフォルダの違い・相対パス基準をコメントで説明する。

### 4.2 JSON

`object_pairs_hook` で重複キーを拒否し、`parse_constant` でNaN・Infinityを拒否する。最上位と `urls` の型を確認した後、配列を入力順で検証する。正常falseは取得せず、不正要素は値を変更せず失敗記録の対象にする。

URLは `urlsplit` で基本設計4.2節の許容形式を検証する。空の記事名、ユーザー情報、クエリ・フラグメント、余分なポートは不正要素。正常URLのパスを勝手にデコード・再エンコードしない。記事同一性用の正規化と、API要求の `urlName` 照合用のデコードを混同しない。

未知のJSON項目をfloat変換で丸めないため、非整数のJSON数値は `Decimal` として保持する。書き戻しは文字列・整数・有限Decimal・真偽値・null・配列・辞書を再帰的に出力し、文字列のエスケープは標準 `json` に任せる。Decimalを文字列型へ変換しない。再解析結果が、対象の真偽値以外について読込ツリーと等しいことを検証する。比較では真偽値と数値を型で区別し、Pythonの `True == 1` をJSON値の同一性とみなさない。この数値保持処理はダミーの極小数・大きな整数・未知の入れ子項目で確認する。

## 5. 排他・パス

### 5.1 ロック

入力JSONの実パスに対する隣接ロックファイルと、保存ルートの `.bl-knowledge-crawler.lock` を使う。入力ロックは `<入力ファイル名>.bl-knowledge-crawler.lock` とし、JSONの置換後も同じロックファイルを保持する。ロックファイルは存在してよく、存在自体を実行中の印としない。

`msvcrt.locking` の `LK_NBLCK` で先頭1バイトを非待機でロックする。必要な1バイトを準備し、ファイル位置を0へ戻してから取得する。正規化したロックパス順で全ロックを取得し、途中失敗時は取得済みを逆順で解放する。ハンドルは実行全体で保持し、終了時に解放・closeする。JSON読込・成果物変更は全ロック取得後に開始する。

既存の入力ファイルと出力フォルダは `resolve(strict=True)` 相当で実パスへ解決し、Windowsの大文字小文字を正規化してロック順を決める。入力の読込・置換は設定に指定された別名そのものではなく、解決済みの実パスへ行い、シンボリックリンク自体をJSONで置き換えない。未作成の出力先は検証後に作成し、作成後の実パスを確定する。

入力JSONは `os.stat()` で `st_nlink` を確認し、複数リンクなら `INPUT_HARDLINK_UNSUPPORTED` として取得開始前に全体を停止する。リンクを切断してコピーへ変えない。ハードリンク数を取得できない場合も、単一リンクだと推測して更新しない。排他取得後に再度同一性とリンク数を確認し、設定確認中のすり替えを検出する。

ジャンクション、8.3短縮名、ハードリンク識別と拒否の根拠は検証記録7節に記載する。シンボリックリンクの作成試験は権限不足で未実施であり、実環境での追加確認対象とする。別PC間は要件の運用制約による。

JSON書き戻し直前にも実パスの変更・複数ハードリンク化を確認し、検出時は入力変更として停止する。ロックはJSON本体とは別のファイルなので、JSON置換後にも維持される。ロックハンドルを持つ他プロセスの異常終了後はOSによって解放されることをダミーで確認した。

### 5.2 生成パス

タイトルのWindows禁止文字と制御文字は `_` に置換し、末尾の空白・ピリオドを除く。空なら `_`、予約名（CON・PRN・AUX・NUL・COM/LPT番号等）なら先頭へ `_` を付ける。元タイトルはフロントマターに保持する。

通常の名前衝突は基本設計8.1節のハッシュ延長で回避する。元URL不明ファイルで全64桁まで占有されていれば、`<タイトル>-<URL全ハッシュ>-recovered-<UUID>.md` を排他的に選ぶ。既存の正常な同一URL記事があればその配置を考慮し、毎回別名を作らない。

長いタイトルは次の規則で短縮する。

1. 初期版の互換上限を、1要素255 UTF-16コード単位、ローカル絶対パス259単位（終端nullを除く）とする。OSの長いパス設定を変更しない。
2. `utf16_units(s) = len(s.encode("utf-16-le")) // 2` とし、親フォルダ・区切り・ハッシュ・回復用接尾辞・`.md` に必要な長さを先に差し引く。
3. 残りの枠に収まる最長のタイトル先頭部分をUnicodeコードポイント単位で選ぶ。UTF-16のサロゲート途中で切らない。切出し後にも末尾空白・ピリオドと予約名を再検証する。
4. ハッシュを8桁から延長する場合は、その候補の接尾辞長で枠を再計算する。ハッシュや回復用識別子を短縮しない。元タイトル・`menu_path` は短縮しない。
5. タイトル1文字も残せない、または画像・一時ファイルを含む必要な保存パスが上限内に収まらない場合は `PATH_TOO_LONG` を記事単位の保存失敗にする。保存先短縮が必要なことを固定文で案内する。

同じ入力タイトルと接尾辞では同じ短縮名を使い、既存の正常な同一URL・同じタイトルの記事に延長済みのパスがあれば再利用する。フォルダ名・画像の全ハッシュは短縮しない。ローカル上限内でもOneDrive等の同期成功を保証するものではない。

作成・置換・削除の直前に解決済みパスが保存ルート内であることを確認する。同一URLと再確認できたMarkdownだけを旧版削除対象にし、ルート外参照やリンク経由の逸脱を許さない。

## 6. 実行制御と状態遷移

```text
config → lock → input/scan
→ [validate → fetch → convert → compare → save/repair → mark_completed → count → wait]
→ cleanup → summary → exit
```

`attempt_id` は取得要素ごとに生成する。保存済みのURL対応表は保存・修復後に更新し、重複入力が次の要素として現れたときも最新の状態で比較する。取得対象は配列順、不正要素は失敗記録、正常falseは処理しない。

`mark_completed` が成功するまで成功件数を増やさない。記事失敗なら失敗1件・ログ・後始末・規定待機の後に次へ進む。`RunError` またはログ保存失敗なら後続を開始しない。後片付けが失敗した場合も後続処理は開始せず、終了処理を継続してコード1を返す。

作業タブは要素ごとに作り、要素処理の `finally` で自分の監視解除・タブ閉鎖・当該一時領域の後片付けを試みてから次の記事間待機へ進む。Chrome接続は実行全体で保持し、最外周で解放する。JSON更新と成功計上の後にタブ閉鎖等が失敗した場合は成功件数を取り消さず、実行全体の終了処理エラーとしてコード1を返す。失敗を架空の追加URL1件として数えない。

待機は `uniform(interval - jitter, interval + jitter)`。時間制限の計測は `monotonic()`、記録日時はPCのタイムゾーン付き日時を使う。ページ期限はURL移動から初回安定まで共通の残り時間を各呼出しに渡す。残り時間0は「無期限」を意味するAPI値へ渡さず、自前の期限切れにする。

## 7. ブラウザ・Aura通信

### 7.1 セッションと監視

`connect_over_cdp("http://127.0.0.1:9223", timeout=...)` で接続し、既定コンテキストの作業タブだけを使う。ユーザータブを対象にしない。タブのイベントハンドラーは取得回に束縛し、URL移動前に登録、取得回終了時に自分のハンドラーだけを解除する。

Playwright同期APIのイベント内では、必要項目を抽出してメモリ内キューへ積む。DOM操作・別GET・保存をイベント内で行わない。例外をイベント外へ無加工で投げず、固定エラー情報を制御層が取り出す。

### 7.2 ActionMonitor

- キーは `(attempt_id, request_seq, action_id)`。action_id単独では別要求の同名IDを混同するため使わない。
- 対象要求のフォーム `message` をJSONとして読み、アクションのdescriptor・id・必要な引数だけを射影する。トークン等の他のフォーム値は取り込まない。
- 対象は基本設計6.2節の3アクション。応答を同じ要求へ対応付け、その中の同じaction_idと結合する。
- URL末尾に一致する `urlName` のID解決、解決IDを要求した記事情報、その記事ID・recordTypeNameを要求した本文項目の順で確定する。複数ID解決の結果不一致は `ARTICLE_ID_MISMATCH`。
- 対象アクションが `SUCCESS` で、有効な型の値を持つことを確認する。HTTP 200内のアクションERRORは `ARTICLE_API_ERROR`。
- 記事情報応答のIDとタイトル、本文項目応答の非空識別情報を照合する。調査で空だったキーを埋めたり、空だけで不一致にしない。
- HTML返却・JSON解析不能・対象アクション欠落・未完了は、画面だけで成功とせず期限内の確認後に失敗にする。

document・対象Aura要求・本文画像以外の応答は記事の成否へ使わない。401～409・その他4xxは、その取得回の関連通信であることを確認して分類する。ログイン画面を同時検出した場合の優先順位は基本設計10.1節に従う。

## 8. 本文抽出・完成判定

### 8.1 抽出対象

調査済みフィールドセット表示の候補ロケーターは記事 `.acknowltngKnowledgeArticleItem`、記事内タイトル `h1.head-page__title`、本文 `.acknowltngKnowledgeArticleBody` とする。件数が1、可視、タイトルが記事APIと一致することを確認する。

項目の順序・ラベル・値は `fieldSetFields`・`fieldSetLabels`・`fieldSetValues` を基準にする。本文の各項目ラッパーと対応付け、値のある全項目を確認する。値のないキーの欠落は許容する。空の非表示ラッパーは出力しない。非空データを可視DOMから取得できなければ、推測で省略せず記事を失敗にする。

実測した `lightning-formatted-rich-text` はopen Shadow DOMを持ち、ホストの `innerHTML` は空だった。値部分は確認済みのshadow root直下のspan内部から取得し、本文比較・Markdown生成・安定確認に同じ抽出結果を使う。Shadow DOMを横断できるPlaywrightロケーターと、通常のDOM APIの動作を混同しない。shadow rootの欠落・未知の構造を空本文として成功扱いにせず、APIに非空値がある場合は抽出失敗とする。項目ラッパーの可視性とAPIの項目順・ラベルの照合も別途行う。限定確認の根拠は検証記録8節を参照する。

### 8.2 API値とDOMの比較正規化

比較用射影はMarkdown生成用HTMLと分離し、両方に同じ規則を適用する。元データを変更せず、次の保守的な構造比較を行う。

- APIのリッチテキストとDOMの値部分を、同じブラウザで作成した未挿入の `template` の `content` として解析する。記事DOMへ挿入・複製せず、比較のために画像・iframe・スクリプトの取得や実行を起こさない。HTMLエンティティは解析時の解釈を使い、二重にデコードしない。
- `span`・`lightning-formatted-rich-text` は、意味を変えるstyle・lang・dir等の属性がない場合だけ透明なラッパーとして外す。Auraの変動する描画識別子を内容比較から除く。class・表示属性は表示状態の確認に使用してから比較対象を限定し、任意のclassを無条件に無視しない。未知の意味を持つラッパーを無条件に外さない。
- ラッパー除去後の隣接テキストを結合し、CRLF・CRをLFにそろえる。空白を一律に削除・圧縮しない。NBSPは通常空白と区別し、pre・code内の空白と改行を保持する。
- `b` と `strong`、`i` と `em` をそれぞれ同じ構造として扱う。段落・見出しレベル・リスト・表の行列・コードの構造は維持する。
- リンク先、画像参照・alt、表のcolspan・rowspan、番号付きリストの開始番号、意味を持つ属性を保持する。通常リンクの比較は同じ記事URL基準で解決し、クエリを削除しない。
- 属性の列挙順だけの差は無視し、属性名順の名前・値の組で比較する。未知属性・class・lang・dir・hiddenは保持する。template解析により両側へ同じように補完されるtbodyは解析後の構造で比較する。段落間などの整形目的に見える空白も、自動的に除去しない。
- 構造・意味のある属性・文字列のいずれかが一致しなければ `BODY_MISMATCH`。許容しない差を「見た目が似ている」ことで補完しない。

透明ラッパー・エンティティ等の基本規則はダミー9観点で確認済み。未挿入templateでも同じ9観点が成立し、画像・iframeを含む断片の解析でHTTP要求0件だった。実記事1件ではShadow DOMの値部分とAPIの非空2項目が構造比較で一致した。DOMに付く `lwc-*` の描画用属性はこの確認では除外したが、任意の属性を除外する根拠にはしない。実サイトのラッパー・属性すべてを実証したものではない。未知属性・整形だけの空白・ブラウザ補正後の表等の境界は追加ダミー検証で固定し、現時点で未確認の差を黙って無視しない。

追加のダミー20ケースでは、属性順・lang・dir・未知属性・class・style・NBSP・改行・整形空白・コード空白・二重エンティティ・tbody補完・セル結合・リスト開始番号・相対リンク・クエリ・alt・hidden・隣接テキストを確認した。全ケースの期待結果が一致したが、任意HTMLの同値判定やPython実装の検証ではない。詳細は検証記録9節を参照する。

### 8.3 安定確認

完成確認用の射影は、タイトル、項目順・ラベル・正規化本文、本文画像の参照と出現位置とする。変動するAura属性・操作ボタン・評価欄は含めない。250ms間隔で連続2回一致し、対象APIも成功してから候補を固定する。本文の空白を一律に圧縮した値だけで内容一致を判定しない。

遅延画像は本文内で表示位置へ移し、期限内に参照確定を待つ。画像取得前後で同じ射影を比較する。確定候補から変われば `SNAPSHOT_CHANGED` としてスキップし、ページを再読込しない。

## 9. 画像取得と形式検証

出現位置ごとに `currentSrc`、未設定なら `src` を解決する。同じ取得URLの画像は同じ記事の取得回内で1度取得し、結果を各位置へ割り当てる。本文上の画像順序・代替テキストは保持する。

### 9.1 参照方式別のバイト列取得

| 参照 | 処理 |
| --- | --- |
| HTTP(S) | `context.request.get(url, timeout=..., max_retries=0, max_redirects=0, fail_on_status_code=False)`。Cookieをコンテキストで共有 |
| data URI | 最初のカンマでメタデータと内容を分け、base64指定は厳密デコード、それ以外はURLパーセント符号化をバイト列として解く。`+` を空白へ変換しない。MIMEだけで形式を決めない |
| blob URL | 作業タブが有効な間に、当該ページ内のfetchとarrayBufferで取得。バイト列をbase64化してPythonへ返す。サイトが作成したblob URLを勝手にrevokeしない |
| その他 | `UNSUPPORTED_IMAGE` として当該記事を失敗にする |

HTTPの401～409は記事スキップ、その他4xxは全体停止、3xx・5xx・通信失敗は記事スキップ。応答は `finally` で `dispose()` し、ステータスやURLの生データを例外文へ埋めない。data・blobでも画像1件の期限を適用し、失敗時に他方式へ自動切替しない。

data URI・blobからの元バイト列取得はダミー画像で確認済み。ブラウザ内で生成したURL・base64・本文をログへ出さない。blob読取は期限内にAbortControllerで中断し、ページ終了後に再取得しない。ページ内の読取処理は記事DOMやサイトの保存状態を変更しない。

### 9.2 共通の形式検証

画像検証にはPillowを使用する。最初の対応形式はPNG・JPEG・GIF・WebP・BMPとし、実データの識別結果から `.png`・`.jpg`・`.gif`・`.webp`・`.bmp` を選ぶ。`verify()` 後に開き直してデコードを確認し、複数フレーム形式は各フレームを確認する。元のバイト列を保存し、再圧縮・形式変換はしない。HTTPのMIME不一致は診断情報とし、実データが有効なら許容する。

参照方式と画像形式は別に判定し、data URI・blobのラスタ画像も同じPillow検証へ渡す。Pillowのデコード制限を無効化して未知データを無理に受け入れない。SVGは9.3節で分け、その他の未対応形式は `UNSUPPORTED_IMAGE` で記事を失敗にする。画像を黙って落とさない。

### 9.3 自己完結した静的SVG

SVGはPillowへ渡さず、XML構造とブラウザの画像デコードを検証して元のバイト列を `.svg` として保存する。ラスタ化・XMLの書換えは行わない。参照方式によらず同じ規則を使う。

初期対応範囲は、SVG名前空間のルートを持ち、単独ファイルで画像表示できる静的SVGとする。XMLは標準 `xml.parsers.expat` で解析し、DOCTYPE・実体宣言・外部実体・外部スタイルシートの処理要求を検出したら未対応とする。外部実体の解析器を作らない。script、イベント属性、foreignObject、アニメーション、未知の名前空間や表示規則は未対応として区別する。style要素・style属性も、CSS解釈を追加するまでは未対応とする。

SVG内部の参照は `#id`、描画属性の `url(#id)` のような文書内参照だけを初期対応とする。別ファイル・外部フォント・外部画像等の依存物を再帰取得しない。未知の参照構文を無害と推測しない。これらは表示を省略して保存するための規則ではなく、完全な画像を保存できない場合に記事を失敗へ振り分ける条件である。

構造確認後、取得したバイト列から作業ページ内だけのBlobを作り、DOMへ追加しないImageの `decode()` と正の自然寸法を確認する。期限切れ・読込失敗は `IMAGE_INVALID`。自分が作成したBlob URLだけを `finally` でrevokeし、ページが持つ元のblob URLは変更しない。

基本図形と文書内グラデーションのダミーについて、XML判定とブラウザデコードを確認済み。Python試行でも静的2例と禁止構文・外部参照等の固定例を確認した。これは試行用の限定検証器であり、未知属性・参照文法を網羅した本番検証器ではない。実SVGと本番検証器、SVGの読込期限切れは未確認で、14節へ引き継ぐ。

## 10. Markdown・YAML・ハッシュ

### 10.1 Markdown生成と内容ハッシュ

項目ラベルをH2、各リッチテキスト値を本文として順に組み立て、markdownifyで変換する。同じ記事タイトルを先頭H1へ重複追加しない。検証済みのmarkdownify 1.2.3では `heading_style="ATX"`、`wrap=False`、`strip_pre=None` を使い、見出し・通常表・リンク・リスト開始番号・コード空白・brの出力をダミーで確認した。本番変換器でも生成物の確認を行う。

標準変換ではrowspanによる列位置が崩れたため、ユーザー合意により、結合セルのある表はHTMLとして維持する。`convert_table(el, text, parent_tags)` でrowspan・colspanが2以上のセルを検出し、当該tableの複製をHTMLとして出力する。不正な結合数を無条件に1へ補正しない。通常表はMarkdownへ変換する。HTML表の画像も同じ保存済み画像の参照解決関数を使い、複製のsrcを表示用相対パスまたはハッシュ用参照へ変更する。変換中に画像を再取得しない。両出力でrowspan・行数・セル数と画像置換を確認した試行は検証記録10節を参照する。

画像参照解決処理から、表示用本文には保存相対パス、ハッシュ用本文には `bl-image-sha256:<全64桁>` を出力する。通常の画像変換フックとHTML表の変換の両方で同じ処理を使う。同じ変換工程で生成し、完成MarkdownのURLを曖昧な文字列置換で再解析しない。通常リンク・添付リンクは元の参照関係を保持し、ダウンロードしない。

改行をLFにし、本文末尾のLFだけを1つに固定する。内容ハッシュは `sha256((title + "\n" + hash_body).encode("utf-8"))`。画像一覧は `(root_relative_path, hash)` を重複排除・パス順に並べ、本文上の出現順とは分離する。

### 10.2 YAMLと日時

フロントマターは基本設計8.2節のキー順で出力する。PyYAMLのSafeLoaderを継承した本アプリ専用ローダーで、mappingの重複キーを拒否し、暗黙のtimestamp変換を無効にする。PyYAMLのグローバル設定は変更しない。任意オブジェクトを生成せず、日時は明示的な文字列として出力・検証する。

既存値の型・ハッシュ形式・ルート相対画像パスを検証する。絶対パス・`..` による逸脱・解決後のルート外参照は不正とし、そのパスを読込・削除に使用しない。元URLを安全に復元できた破損と、元URL不明の破損を区別する。構文全体が壊れて安全に読めない場合は、行の見た目からsource_urlを推測して復元しない。

`fetched_at` は本文・画像取得後、`created_at`・`updated_at` は最終反映直前に採取する。更新時は初版日時を維持し、修復で復元不能な場合だけ再設定する。同一URLの候補のうち有効な日時をUTCの瞬間として比較し、最も早い値を引き継ぐ。

## 11. 保存計画・JSON書き戻し

`scan_existing` は保存ルート直下のMarkdownを走査し、正常・元URL復元可能な破損・元URL不明に分ける。元URL不明ファイルを入力記事とファイル名だけで結び付けない。新規・更新・修復・無変更を `SavePlan` に確定してから最終反映する。

### 11.1 無変更判定と既存ファイル

無変更は、正常な同一URL記事が1件だけで、タイトル・生成本文・content_hash・画像一覧・保存済み画像の実ハッシュがすべて一致する場合に限定する。フロントマターに記録されたハッシュだけを信頼しない。本文が人手編集等で変わっていても、今回取得した本文で修復する生成物として扱い、編集部分をマージしない。

元URLが読める破損・重複・画像欠落はrepair、内容の正常な変更はupdateとし、どちらも集計では更新とする。元URL不明の既存ファイルを保持して別名保存した場合はnew。修復でファイルを再生成しても初版日時は合意済みの引継ぎ・再設定規則に従う。

通常リンクが相対URLの場合は記事URLを基準に参照先を解決してMarkdownへ出力する。リンク先は取得せず、クエリを削除しない。これはローカル保存後も同じ参照先を指すためであり、添付のローカル保存を復活させるものではない。

### 11.2 反映と完了記録

1. `%LOCALAPPDATA%/BlackLineKnowledgeCrawler/tmp/<run_id>/<attempt_id>/` に今回の取得物を生成する。他の実行の残留物は削除しない。
2. 画像を最終配置と同じフォルダの一時ファイルに書き、flush・fsync・close後に置換する。既存同名画像は内容ハッシュを検証する。
3. Markdownを最終配置と同じフォルダの一時ファイルから置換する。直前にも対象の元URL・占有状態を再確認する。
4. 改名・重複は新版の検証後に同じ元URLの旧Markdownだけ削除する。更新・修復後に対応表を更新する。
5. 入力JSONの現在バイト列のハッシュが前回読込または書き戻し直後の値と一致することを確認する。
6. JSONツリーの当該indexだけをfalseにし、同じフォルダの一時ファイルへ保存・再読込・保持値検証をして置換する。失敗時はメモリ上の更新を確定済みと扱わない。
7. 成功したJSONのバイト列ハッシュを次の比較基準に更新し、処理結果を成功件数へ反映する。

画像・Markdown・JSONを単一トランザクションとは扱わない。JSON更新前に中断すれば `true` のまま再取得・比較する。書き戻し失敗時は成果物を維持して全体停止する。不要な旧画像の削除・失敗時の一括ロールバックは行わない。

JSONの外部変更検出は「確認時点のハッシュ一致」であり、OSによる比較と置換の不可分操作ではない。確認直後から置換直前に外部エディターが書く競合まで防げるとは主張しない。実行中の手作業編集禁止とロックを併用する。置換後の再確認で別内容を検出した場合も入力更新失敗として停止し、勝手な再上書き・旧版復元は行わない。

## 12. エラー・終了・ログ

| stage / codeの例 | 分類・処理 |
| --- | --- |
| config / CONFIG_ERROR | 全体停止、ログまたは代替出力 |
| lock / RESOURCE_BUSY | 待機せず全体停止 |
| input / INPUT_DOCUMENT_ERROR・INPUT_HARDLINK_UNSUPPORTED | 取得前に全体停止 |
| validate / INVALID_ENTRY | 失敗1件、当該要素の値を保持して続行 |
| fetch / HTTP_SKIP | 401～409、失敗1件、次のURL前に規定待機 |
| fetch / HTTP_FATAL | 400・410～499、全体停止 |
| fetch / AUTH_EXPIRED | 401～409のスキップ優先を除き、確定したログイン切れで全体停止 |
| fetch / ARTICLE_API_ERROR・ARTICLE_ID_MISMATCH・BODY_MISMATCH・SNAPSHOT_CHANGED | 記事失敗として続行 |
| image / IMAGE_INVALID・UNSUPPORTED_IMAGE | 記事失敗として続行 |
| convert・save / CONVERSION_ERROR・SAVE_ERROR | 記事失敗として続行 |
| input_update / INPUT_CHANGED・INPUT_UPDATE_ERROR | 全体停止。成果物と先行完了記録を維持 |
| log / LOG_WRITE_ERROR | 代替ログ・表示を試み、成否にかかわらず全体停止 |
| cleanup / CLEANUP_ERROR | 他の後始末も試み、コード1。成果物・完了記録を維持 |

全64桁でも別URLと保存名が衝突する場合は基本設計8.1節の異常終了とする。エラー優先順位はログ保存失敗・JSON更新失敗等の全体停止を記事スキップより優先する。HTTPとログイン画面の同時検出は基本設計の規則に従う。

Ctrl+Cは `KeyboardInterrupt` として扱い、後続URLを開始せずコード1にする。`finally` でタブ閉鎖、接続解放、一時領域の後片付け、ロック解放をそれぞれ試み、一つの失敗で残りを省略しない。既にfalseへ書き戻した要素は戻さない。強制終了・電源断のログや最終表示は保証しない。

ログは基本設計10.3節の項目だけから生成する。`input_index` はJSONの0始まり位置とし、不明ならnull。名前は `error-<UTC日時>-<run_id>-<UUID>.json`、修復等の診断情報は `diagnostic-...json` として区別する。ログ自体の失敗を同じロガーへ再帰的に渡さない。指定先失敗で代替保存できても続行しない。

## 13. 検証と根拠

本節は検証計画であり、実施結果ではない。通常のテストは標準unittestとダミー資料を基本とし、実装の固定値をなぞるだけのテストを作らない。

| 検証群 | 主な確認点 |
| --- | --- |
| 純粋処理 | 型・URL・数値保持、設定基準、正規化、内容ハッシュ、YAMLの安全な読込 |
| 通信・DOM | 多重アクション、別要求の同じid、前記事の遅延応答、空識別値、非空項目のDOM欠落 |
| 画像・変換 | MIMEとPNG署名不一致、壊れたデータ、画像差し替え、表・コード・リンクの保持 |
| 保存・中断 | 反映各段階の失敗、旧版削除失敗、JSON外部変更、初版日時、未知項目・配列順保持 |
| 排他・終了 | 同一入力・同一保存先、異常終了後の解除、Ctrl+C、後始末の独立試行 |
| ログ・集計 | 指定先失敗・代替先失敗、秘密値の非出力、JSON更新失敗の二重計上防止 |
| 配布 | Python未導入Windows 11、作業ディレクトリ非依存、一意なdist出力、旧exe維持 |

実装用クラス・関数の前には責務・意図のブロックコメントを置く。画像MIME不一致や空識別値など実測由来の例外処理は、必要となった理由と調査記録への参照を残す。

技術的な根拠（2026-11-01確認）：[PlaywrightリクエストAPI](https://playwright.dev/python/docs/api/class-apirequestcontext)、[Python msvcrt.locking](https://docs.python.org/3/library/msvcrt.html)、[Windows命名規則](https://learn.microsoft.com/en-us/windows/win32/fileio/naming-a-file)、[PyYAML SafeLoader](https://pyyaml.org/wiki/PyYAMLDocumentation)、[Pillowの画像形式](https://pillow.readthedocs.io/en/stable/handbook/image-file-formats.html)、[SVGの画像コンテキスト](https://developer.mozilla.org/en-US/docs/Web/SVG/Guides/SVG_as_an_image)、[HTML template](https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/template)。PyYAMLは既存フロントマターの読込、Pillowはラスタ画像の形式識別とデコード検証に用途を限定する。

## 14. 検証状況・残る確認

| 項目 | 必要な確認 |
| --- | --- |
| APIとDOMの正規化 | 3記事の非空2・4・4項目がShadow DOM抽出で一致。属性・空白・tbody補完等のダミー20ケースも確認済み。別表示形式・未知属性と本番Python版での再現は未確認 |
| 表示形式 | 通常フィールドセットでAdditional Information等の非空値も確認。非表示の非空値・複数画像・遅延画像はダミー確認済み。実サイトの別表示形式・同条件の実例は未確認 |
| 特殊画像 | ブラウザのdata/blob取得、失効blob拒否、AbortController中断、自己完結SVGのデコードを確認。ダミーPNGをPythonへ渡してPillowで確認し、Pythonで5形式・複数フレーム・壊れた画像とSVG禁止構文の固定例も確認。本番XML検証器・実SVG・SVGの期限切れは未確認 |
| ログイン切れ・HTTP | 未認証の一時コンテキストでSAML認証先への転送を観測したが、遷移が完了せず最終画面は未確認。ローカルダミーで400～499の応答取得、転送非追跡、タイムアウト時の非再送は確認。本番の認証確定条件・優先順位制御は未検証 |
| パス・排他 | ジャンクション・短縮名・ハードリンク数・別プロセス排他、UTF-16境界とハッシュ長別の短縮、上限内候補の実ファイル作成を確認。シンボリックリンクは権限不足。一時ファイル長の全候補、すり替え競合・同期先・本番実装は未確認 |
| 保存・復旧・終了 | 試行用の保存手順で各段階の失敗と完了記録前後の状態、外部変更ハッシュ検出を確認。本体未実装のため、無変更時の非更新・修復・ログ代替・集計・Ctrl+C・終了処理の結合試験は未実施 |
| 依存・配布 | Python 3.15.2と依存を固定し、検証exeのドライバー起動・画像検証・YAML・変換を別cwd・PythonなしPATHで確認。Playwriter切断・再接続後にもChromeと6タブを確認。本番Pythonの接続解放・本番exe・Python未導入の別Windows 11は未確認 |

共通処理の設計とサイト固有の検証待ちを分け、後者に依存する本番処理は確認後に実装する。要件や基本設計の契約変更が必要な場合は、理由・影響を示して合意後に各文書へ反映する。

試行コードの成功を未作成のアプリ本体の成功と読み替えない。全項目の対応表・実施条件・未実施理由は検証記録13節に集約する。実装依存の項目は実装後、環境依存の項目は対応環境が利用可能になってから検証する。
