# 詳細設計書 — BlackLine Knowledge URL一覧作成アプリ

作成日：2026-11-01

状態：Python実装を作成済み。実施した検証と配布確認の制約は[実装検証記録](implementation-validation.md)を参照する。

## 1. 根拠と設計範囲

[要件定義書](requirements.md)、[基本設計書](basic-design.md)、[画面観察記録](references/knowledge-ui-observations.md)を根拠とする。要件は要件定義書、動作・保存契約は基本設計書を正本とし、本書はモジュール・データ・アルゴリズム・例外処理・テストを具体化する。観察記録の過去の未確認事項を現在の仕様として扱わない。

収集は通常の画面操作による1回の走査、最大1,000リンク。JSONは前回保存URLを失わない累積一覧。記事本文・画像は出力しない。JSON外部契約・設定項目・採用版は基本設計を参照し、本書では実装上必要な規則を補足する。

## 2. ファイル・モジュール構成

実装の配置は以下のとおり。

```text
run_knowledge_urls.py
src/bl_knowledge_url_list/
  __init__.py
  app.py
  config.py
  model.py
  browser.py
  network.py
  collector.py
  storage.py
  operations.py
tests/
  test_core.py               # 設定・履歴・保存・累積・走査・通信解析
  test_browser.py            # 実ブラウザー＋完全ダミー通信で画面・異常系を確認
  fixtures/knowledge/        # ダミー画面・ダミー応答のみ
scripts/build.ps1
requirements.txt
requirements-build.txt
settings.example.toml
```

| モジュール | 責務と主要インターフェース |
| --- | --- |
| app | `main() -> int`、`run(settings, app_dir=..., session_factory=..., now=...) -> RunResult`。処理順・例外・終了コードを管理 |
| config | `get_app_dir()`、`load_settings(path) -> Settings`。TOML・値・パス検証 |
| model | 値オブジェクト、固定定数、`AppError`。I/Oなし |
| browser | `BrowserSession.open()`、`initialize_filters()`、`read_snapshot()`、`close()`。ロケーターと画面操作 |
| network | `ActionMonitor`。要求・応答・失敗イベントの対応付けと必要項目の抽出 |
| collector | `collect(session, monitor, deadline) -> CollectionResult`。待機・ページ送り・上限・変化検出 |
| storage | `create_run()`、`load_previous()`、`merge_urls()`、`publish()`。履歴・累積統合・公開 |
| operations | `Deadline`、安全なログ出力、エラー表示。ブラウザー例外の無加工出力を防止 |

`app`が各機能を組み合わせる。`network`はDOMを操作せず、`storage`はブラウザーを参照しない。クラス・関数の前には責務と意図をブロックコメントで記載する。Shadow DOM・URLエンコード差への処理には観察記録を参照した理由を残す。汎用クローラーフレームワークは作らない。

## 3. 内部データと不変条件

設定・結果・実行状態には単純なdataclassを使い、外部JSONへ暗黙に全フィールドをシリアライズしない。通信要求・フィルターの射影は小さな辞書で保持する。

| 型 | 主な項目 |
| --- | --- |
| Settings | output_dir: Path、chrome_endpoint: str、page_interval_seconds/operation_timeout_seconds/run_timeout_seconds: float |
| RunContext | started_at: offset付きdatetime、run_dir: Path、published: bool、expected_hash: Optional[str] |
| PreviousRun | directory: Path、document、sha256: str。前回選定値はrun内のローカル変数 |
| filters（辞書） | articleTypes/category/search/customFilters/view/orderBy/pageUrl/isMultiCategory |
| action（辞書） | id、method、filters、number、size。要求オブジェクト＋seqに対応付け |
| Observation | seq、action、value（urlName列またはcount）。本文等を保持しない |
| PageSnapshot | number/total、urls、labels、next_terminal、loading。チェック状態はロケーターで別途照合 |
| CollectionResult | urls（収集順・重複あり）、collected_at。raw_countと基準件数等はcollector内で管理 |
| RunResult | completed_json: Optional[Path]、published: bool、exit_code: int、error_code: Optional[str] |

不変条件は、公開URL列の重複なし、前回全URLの包含、今回新出URLだけis_new=true、収集raw_count≤1,000、保存件数には上限なし。時刻比較に壁時計、待機時間計測にmonotonicを使い、時計変更で期限を延長しない。

## 4. エントリーポイントと設定

1. exeでは `Path(sys.executable).parent`、ソース実行ではルートの `run_knowledge_urls.py` の親をアプリ配置先とする。カレントディレクトリやPyInstaller内部展開先を設定基準にしない。
2. 配置先の `settings.toml` をtomllibで読み込む。基本設計9節で定めた項目をルートキーとして必須にし、未知キー・型不正・欠落はCONFIG_ERRORとする。
3. output_dirは空でない文字列。相対値は設定ファイルの親基準で解決する。存在しない親はmkdir(parents=True, exist_ok=True)で作成し、ファイルを指定していた場合は失敗とする。
4. endpointはurlsplitで解析し、http、ホストが127.0.0.1/localhost/::1、portが1～65535、認証情報・クエリー・フラグメントなし、パスが空または/だけであることを検証する。DNS名から外部接続先を受け入れない。
5. 時間は真偽値と区別してint/floatを受け付け、有限値を必須とする。操作・全体は正、ページ間隔は0以上。全設定を読み込んで検証した後に実行領域を作る。
6. 設定例作成時は、各値の用途、秒単位、出力親フォルダーと設定ファイルの区別、相対パスの基準、接続先の用途をコメントに記載する。

CLI引数による別設定・別URLの指定機能は追加しない。ソース起動は `python run_knowledge_urls.py`。実装用依存はPython標準ライブラリと基本設計で採用したPlaywrightを中心とし、テストはunittestを基準にする。

ユーザー追加指示により、開発・テスト・ビルドは本リポジトリ専用の`.venv`に統一する。2026-11-01時点で公式Windows配布の最新安定版と確認したPython 3.15.2を`.python-version`に固定する。他プロジェクトの仮想環境は実行環境として使わない。OneDriveのハードリンク制約を避け、uvによる依存配置はlink-mode=copyとする。

## 5. 全体処理と終了コード

```text
設定検証 → 開始日時・全体期限確定 → 実行領域排他作成 → running記録
→ 前回選定・検証 → Playwright接続・作業タブ作成
→ フィルター初期化 → 1回走査 → 取得完了日時確定
→ 累積統合 → JSON検証・公開 → 作業タブ閉鎖・切断 → 終了
```

- 同秒衝突はmkdir(exist_ok=False)のFileExistsErrorで判定する。衝突先にログ・状態を書き込まない。連番や自動再試行を行わない。
- 公開前のAppError・予期しない例外・KeyboardInterruptは完成JSONを作らず、可能ならfailed状態と診断ログを残して終了1。
- 公開後のタブ閉鎖・切断失敗は、ユーザー回答により、成果物を正常完了のまま保持して終了1。preparedや完成JSONをfailedへ戻さない。公開済みパスとCLEANUP_ERRORを標準エラーに表示する。
- すべて成功した場合だけ終了0。閉鎖と切断は別々に試し、一方の失敗でももう一方の後始末を行う。公開後の必須ログ書込みを追加しない。
- 別プロセスとのロックや同秒の同時起動禁止機能は作らない。他の実行がrunningとして選ばれたら履歴条件により停止する。完全な同時実行の排他を保証せず、履歴選定の競合はテストで扱う。

## 6. 履歴とJSONの検証

### 6.1 前回実行

`load_previous(output_dir, current_run_dir)`は保存先直下を列挙し、今回ディレクトリを除外する。名前は正規表現 `[0-9]{8}_[0-9]{6}` とstrptimeの両方で確認する。ファイル・解析不能名があれば停止し、空なら初回。開始日時最大の1件を選ぶ。古い履歴へのフォールバックはない。

選定した履歴のrun-state.json・完成JSON・一時ファイルを検査する。prepared、開始日時一致、ハッシュ一致、完成JSONの意味的な妥当性を必須とする。failed/running/未知状態、一時ファイル残存、欠落・読取不能はHISTORY_ERROR。公開後のCLEANUP_ERRORや終了コード1だけを理由に、正常な成果物を拒否しない。ログ内のerror文字列ではなく、状態と成果物で継続条件を判定する。全履歴の本文を毎回読み直すことや、破損した古い履歴の自動修復は行わない。

### 6.2 JSONの読取

UTF-8で読み、object_pairs_hookで重複キーを拒否し、parse_constantでNaN/Infinityを拒否する。ルートとurls要素についてキー集合を検証する。schema_versionは `type(value) is int` かつ1、is_newは `type(value) is bool`。URLは文字列、urlsは配列、日時は秒精度・UTCオフセット必須で有効な日付とする。

source_urlとarticle_typeは基本設計の固定値に一致させる。URLは基本設計4.1節の形式を検証し、文字列完全一致で重複がないことを確認する。URLのデコード・小文字化・クエリー除去を同一性判定に利用しない。前回JSONのis_newは型だけ検証し、今回区分への引継ぎはしない。

### 6.3 累積統合

```text
previous_set = 前回urlsのurl集合（初回は空）
result = 空、seen = 空
今回URLを収集順に走査:
  urlがseenにないなら:
    {url, is_new: urlがprevious_setにない} をresultへ追加
    urlをseenへ追加
前回URLを前回順に走査:
  urlがseenにないなら:
    {url, is_new: false} をresultへ追加
    urlをseenへ追加
前回URL集合がresultのURL集合の部分集合であることを検証
```

計算量は今回＋前回の件数に対しO(n)。今回0件でも同じ処理を使用する。初回0件はurls=[]。記事の存在確認のために過去URLを開かず、404などを理由に保持URLを削除しない。

## 7. ファイル書込み・公開

内部ファイル名は `run-state.json`、`run-state.json.tmp`、`knowledge-qa-urls.json.tmp`、`app.log`。正常実行領域に状態・完成JSON・ログを置き、一時ファイルは残さない。

| 状態 | 厳密なキーと値 |
| --- | --- |
| running | state_version=1、status="running"、started_at=オフセット付き秒精度日時 |
| prepared | state_version=1、status="prepared"、started_at、json_sha256=完成JSONバイト列のSHA-256小文字64桁 |
| failed | state_version=1、status="failed"、started_at、error_code=許可されたエラーコード |

未知キー・未知版は停止。stateのstarted_atのローカル日時部分をディレクトリ名と照合する。JSON名は固定のため状態ファイルへ自由な参照パスを持たせない。

1. 新しい状態と一時JSONは排他新規作成で書く。UTF-8・BOMなし・LF・ensure_ascii=False・allow_nan=False・indent=2・末尾改行を使用する。
2. flushとos.fsync後に閉じる。完成JSONのハッシュはこの確定バイト列で求め、同じファイルを再読込・意味検証する。前回全URL包含とis_new判定も公開前に再検証する。
3. 状態更新はrun-state.json.tmpを書込み・同期後、同じ実行領域のrun-state.jsonへos.replaceする。置換してよいのは今回の内部状態だけ。
4. preparedを書き、公開準備完了のログをflushしてから、Windows上のos.renameで一時JSONを完成名へ変更する。既存完成名があれば失敗させる。完成JSONにはos.replaceを使わない。
5. rename成功直後にメモリー上のpublished=trueとする。公開後の必須ディスク更新は行わない。標準出力には公開パスを表示する。公開前の失敗痕跡を自動削除しない。

書込み・renameの各段階を故障注入テストする。preparedだけで完成JSONがない状態は正常ではない。完成JSONと正しいpreparedがあれば、その後プロセスが中断しても成果物は正常とする。同期フォルダー・ネットワーク共有での耐久性や原子性は対応環境の受入で確認する。

rename直後、published=true代入前にも中断が起こり得る。例外処理ではfailedを書き込む前に公開状態を照合する。一時JSONがなく、完成JSONとpreparedの開始日時・ハッシュが今回の検証済み内容に一致する場合は公開済みとして扱い、状態をfailedへ戻さない。完成名の衝突や照合不能を単に公開済みと見なさず、成果物を上書き・削除せず終了1とする。

## 8. Chromeと画面操作

### 8.1 接続と所有権

`sync_playwright().start()`後にchromium.connect_over_cdpへ設定endpointと期限内timeoutを渡す。既定コンテキストが利用できることを確認し、context.new_pageで所有タブを作る。既存タブをURLや番号から推測して流用しない。監視リスナーはgoto前に登録する。

対象一覧を開き、ログイン画面への遷移や認証系エラーはAUTH_ERRORとする。自動ログインを行わない。予想外URL・構造変更はPAGE_STRUCTURE_ERROR。終了時は所有page.close、リスナー解除、runtime.stopを試す。browser.close/context.closeを呼ばない。

### 8.2 ロケーター

| 対象 | 取得方針 |
| --- | --- |
| フィルター | `.filters`を範囲とする |
| QA記事種別 | get_by_role("checkbox", name="QA", exact=True)。1件に限定 |
| QAラベル | 直前に取得したinputのidと同じforを持つlabel。動的IDは固定しない |
| 全解除 | フィルター内のget_by_role("link", name="Clear All", exact=True) |
| CATEGORY選択状態 | `.slds-accordion__summary-content.selected` |
| 記事 | `a.articles-item__link`、種別は `.articles-item__head .slds-badge` |
| ページ | `.pagination__info`を正規化し `現在番号 of 総数` の全体一致で解析。余分な文言・重複要素は不正。正常0件では存在を要求しない |
| Next/Prev | `.pagination`内の同名button。終端はbutton--disabledクラス |
| 読み込み中 | 所有ページの一覧に関係する可視lightning-spinner/.slds-spinner |

チェック数とチェック状態はPlaywrightロケーター・expectで確認する。document直下のquerySelectorAllやXPathでShadow DOM内のinputを探索しない。クリック後は再取得し、古いidを使い回さない。forceクリックは採用しない。

Clear Allがあれば操作し、記事種別0・CATEGORY0とフィルター要求の一致を待つ。元から解除済みならその状態を確認する。QAラベルを操作した後は記事種別がQAだけ、他フィルターが空、記事取得要求も同条件であることを確認する。正常0件以外はページ1を要求する。QA選択済みという理由だけで一覧を収集し始めず、初期応答を監視に取り込む。

収集時のQA要求値は画面のQA input.valueから対応付け、articleTypesが1件というだけで同条件とは判断しない。category/search/orderBy/viewは空配列、customFiltersは空オブジェクト、isMultiCategoryはfalse、pageUrlは起点一覧と整合することを確認する。Clear All中はarticleTypesも空を期待する。未知のフィルター項目や型変更は無視せずRESPONSE_ERRORとする。

## 9. AJAX監視と一覧更新待機

### 9.1 イベント

ActionMonitorは所有ページのrequest/response/requestfinished/requestfailedを購読する。監視対象は起点と同じoriginの `/BlackLineCommunity/s/sfsites/aura`。POSTフォームのmessage.actionsから、KnowledgeArticleListControllerのgetKnowledgeArticles2とgetKnowledgeArticlesCount2だけを抽出する。他のアクション・計測通信は無視する。

要求ごとの連番とフェーズ開始seq、HTTP要求オブジェクト＋action_idをキーに対応付ける。action_id単独をブラウザー全体で一意と仮定しない。filterDataJsonはJSONとして解析し、必要なフィルター項目を直接比較する。汎用fingerprint型は追加しない。ログへ生の要求本文・トークン・フィルター値を出さない。

responseイベントだけでは本文の受信完了とは扱わない。requestfinished後に待機ループ側で本文を解析し、HTTP成功と対応actionのstate=SUCCESSを必須とする。一覧から文字列urlName、件数から真偽値を除く0以上の整数だけを抽出する。本文フィールドや要求全体を履歴・fixtureへ保存しない。イベントコールバックから再クリックしない。ヘッダー受信後にrequestfailedとなった要求も成功応答として採用しない。

requestfailed・対象HTTPエラー・action失敗・不正JSON・対応不能を記録し、制御側でAppErrorを発生させる。例外全文・応答error本文はログへ転送しない。ログイン切れが判別できればAUTH_ERROR、その他はNETWORK_ERRORまたはRESPONSE_ERRORとする。

### 9.2 操作フェーズと完了条件

操作前にphaseを開始し、その後に発生した対象要求を記録する。初期表示・Clear All・QA選択では一覧と件数の両方を待つ。ページ送りでは期待ページの一覧応答を必須とし、件数応答が発生した場合は初期件数と比較する。サイトがページ送りごとに件数を返すとは仮定しない。

Clear Allで複数要求が出るため、既知の対象要求が完了し、最後に発生した期待条件の結果と画面が一致することを確認する。古い条件の成功応答を今回の完了根拠にしない。受理後に新しい対象要求が発生したら、次操作前にその完了・整合を確認する。将来の未発生要求までないと保証するdebounceは導入しない。

共通の完了条件は、期待フィルター、HTTP/action成功、応答urlName列とDOMリンク列の一致、件数とページ表示の整合、読み込み終了。初期表示・Clear All中はQA以外も表示されるため、全記事QAという条件は課さず、QA選択後の収集段階だけQA表示と種別数を必須にする。正常0件ではページ番号・総数・記事ヘッダーの存在を要求しない。DOM消失・一時的な旧一覧は期限内の再観測とする。通信失敗や期限切れでは旧一覧や空DOMを採用しない。

照合時だけ、DOMリンクのURLパス末尾を1回パーセントデコードしてurlNameと比較する。不正な%表記・UTF-8復号不能・空slugはエラー。比較用デコード結果を保存URLへ戻さない。各URLのorigin・記事パス・形式は別途検証する。

Deadlineは全体と操作の残り時間の小さい方を各APIへ渡す。monotonic期限到達時は例外とし、0msがPlaywrightの無期限待機になる呼出しを避ける。短周期の再観測やページ間2秒は待機制御であり、一定時間経過だけで完了とは判定しない。同期APIのイベント配送を進めるためにPlaywrightの待機を使い、長いtime.sleepで監視を止めない。

## 10. ページ走査・0件・変化検出

1. QA初期化後の件数C、itemsPerPage=S、UI総ページ数Tを記録する。Cは真偽値でない0以上の整数、Sは正の整数。C>0ならT=ceil(C/S)と整合することを確認する。サイト内部で件数が打ち切られる可能性は合意済みの収集範囲として扱う。
2. C=0なら記事応答[]、DOMリンク0、正しいフィルター、読み込み完了を確認して終了する。ページ番号や空表示の固定文言は要求しない。件数だけ0やDOMだけ空では成功にしない。
3. C>0ならページ1から始める。ページkの件数はmin(S, C-(k-1)*S)を期待し、応答・DOM双方で確認する。観測したC/T/Sが変化したら停止する。
4. ページ全体のリンク・QA種別・応答を照合した後、収集枠の残りまでを収集順に追加する。上限は重複排除前の件数で数える。ページ途中で1,000件に達する場合も、ページ自体の検証を終えてから先頭の残り件数だけ採用する。
5. raw_count=1,000なら上限終端。未到達ならk=TかつNext終端で正常終了。k<TでNext終端、k=TでNext有効、番号不連続はCOLLECTION_CHANGED。
6. 次ページ操作前に最小ページ間隔と期限を確認し、Nextを1回操作する。モーダル処理後もすでに要求が発生した操作は再クリックせず、応答と現在ページで再開位置を判断する。
7. 収集完了後にURL重複排除・前回統合を行う。隣接ページの同じリンク列だけで失敗にせず、応答・ページ番号の照合で遷移を判断する。再走査は行わない。

検出できない同件数の入れ替わり・未訪問ページ間移動・上限外変化は、基本設計の合意済み限界をそのまま適用する。

## 11. アンケート

`dismiss_survey_if_present(page, deadline)`を操作前・更新待機中に呼ぶ。対象候補は可視のアンケート領域で、記事への評価を尋ねる内容、回答欄、下部CloseとSubmitという提示資料の特徴を組み合わせて識別する。単にページ内にCloseがあるだけでは対象としない。

認識した対象領域の中で、名前Close（大小文字差は許容）の可視ボタンを1件に限定してクリックする。Submit・回答欄・右上×は操作しない。消失を待ち、元のphaseとページ番号・既発生要求を再確認する。期限は延長しない。未知モーダル・複数候補・Closeなし・閉鎖失敗はMODAL_ERROR。

実物のDOMは未取得であり、iframe有無・コンテナーCSS・評価質問の厳密な文字列は確定できていない。上記の意味的な識別契約をダミー画面で検証し、実サイト用の具体セレクターは観測または提供資料との一致確認後に設定する。汎用的なClose検索への置換で埋めない。自然な表示待ちは基本設計の完了条件ではないが、未確認セレクターを実機検証済みとはしない。

## 12. エラーとログ

| コード | 主な原因 | 公開前の扱い |
| --- | --- | --- |
| CONFIG_ERROR | 設定欠落・不正・読取不能 | 起動エラーログ、終了1 |
| RUN_COLLISION | 同名実行領域あり | 既存領域へ書かず終了1 |
| HISTORY_ERROR | 前回未完了・JSON/状態/ハッシュ不整合 | failed、手動整理案内、終了1 |
| BROWSER_CONNECT_ERROR / AUTH_ERROR | 接続・認証利用不能 | failed、起動/再ログイン案内、終了1 |
| NETWORK_ERROR / RESPONSE_ERROR | 対象一覧の通信・応答失敗 | failed、完成JSONなし、終了1 |
| PAGE_STRUCTURE_ERROR / COLLECTION_CHANGED | 構造・件数・順序条件不整合 | failed、再調査/再実行案内、終了1 |
| MODAL_ERROR / TIMEOUT | モーダル閉鎖失敗・期限超過 | failed、終了1 |
| STORAGE_ERROR / INTERRUPTED / INTERNAL_ERROR | 保存失敗・中断・予期しない例外 | 可能ならfailed、終了1 |
| CLEANUP_ERROR | タブ閉鎖・切断失敗 | 公開後は成果物を維持し終了1 |

app.logはUTF-8で時刻・level・error_code・処理段階・ページ番号・件数を記録する。URL全文・タイトル・HTML・要求/応答本文・認証情報・例外repr/tracebackは出さない。対象保存ディレクトリのパスは手動整理のため表示する。入力由来の制御文字は除去する。

実行領域作成前の失敗はアプリ配置先 `logs/startup-<日時>-<乱数>.log` を排他新規作成する。乱数は起動ログの衝突回避だけに使い、実行領域名の連番・再試行には使わない。書込み不能なら標準エラーへ安全なメッセージを出す。過去のログや実行領域へ追記しない。

## 13. テストと製造順序

| 対象 | 必須ケース |
| --- | --- |
| 設定 | 必須キー・未知キー・bool/数値区別・NaN/inf・相対パス・日本語/空白・endpoint制限 |
| 履歴 | 初回・最新開始日時・今回除外・同名衝突・不正名・running/failed・欠落・ハッシュ違い・古い履歴へ戻らない |
| 累積 | 前回A/B→今回B/C、保持A、再出現A、今回重複、前回is_newに依存しない、累積1,000超 |
| 0件 | 初回空JSON、前回全件保持、APIだけ0/DOMだけ空は失敗、正常0と通信失敗の区別 |
| 公開 | 書込/flush/状態更新/rename各段階の中断、rename直後の中断、完成名既存、preparedのみ、前回URL欠落の公開拒否 |
| 画面 | Shadow DOM、動的id、複数QA、ラベル遮蔽、初期条件残存、Clear All複数要求 |
| 通信 | action_id対応・同一ID別要求・順序逆転・古い応答・別origin・不正応答・HTTP失敗・requestfailed・ヘッダー後の本文受信失敗・件数boolの拒否 |
| 走査 | 1/複数ページ・端数最終・1,000到達・ページ途中上限・重複URL・同一リンク隣接・番号飛び・件数変化 |
| 待機 | DOM消失・旧DOM残存・エンコード差・可視スピナー・全体/操作期限・0ms無限待機防止 |
| アンケート | なし・既知Close・Submit未操作・Close欠落/複数・未知dialog・既発生要求の二重クリック防止 |
| 後始末 | 公開前後の閉鎖/切断失敗、成果物保持、公開後終了1、両方のcleanupを試す、正常成果物を次回比較で受け入れる |

モック・ダミー画面に実データの秘密値を含めない。標準unittestの単体テストと、同梱ブラウザーを必要としないダミー画面検証を分ける。ダミー画面のブラウザー実行方法は実装時の検証環境で明示する。未実行テストを成功と記載しない。

製造は、設定・JSON/履歴/累積 → 保存公開 → 通信解析・ダミー画面 → CDP・収集 → エラー/モーダル → exeの順。独立に検証できる単位で進め、設計の不明点に依存する箇所は先に確定事項として実装しない。

ビルドはWindowsで基本設計の固定依存を使いonedirを作る。dist配下の一意な日時フォルダーを排他作成し、exeと依存物をそこへ配置する。既存成果物の削除や上書きを伴う出力先を使わない。Python未導入の受入環境・日本語パス・外部設定・ログ・終了コード・既存Chrome維持を確認する。

## 14. 参照とレビュー事項

- [Python 3.13 os.rename](https://docs.python.org/3.13/library/os.html#os.rename)：Windowsの既存宛先拒否を前提にする。実保存先での公開・中断確認は受入で行う。
- [Playwrightイベント](https://playwright.dev/python/docs/events)、[ロケーターとShadow DOM](https://playwright.dev/python/docs/locators#locate-in-shadow-dom)：監視登録と状態確認の根拠。
- アンケートの具体セレクターは未取得であり、11節の条件を満たす識別根拠が必要。自然再現しないことと、すべてのCloseボタンを操作してよいことを混同しない。
- 同時実行の完全な排他や電源断時の耐久性は、既存要件を超える保証として追加しない。保存先の競合・中断時の検出限界はレビューと配布説明へ残す。

実装・テスト・ビルドの実施範囲は実装検証記録に記載する。設計時の未実施記録と実装後の結果を混同しない。
