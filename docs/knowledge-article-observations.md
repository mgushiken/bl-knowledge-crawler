# Knowledge記事の読取調査記録

調査日：2026-11-01

仕様変更により、添付ファイルの保存は対象外となった。以下の添付に関する記述は調査時点の事実・未確認範囲を残したものであり、今後の調査依頼や設計確定の条件ではない。本文内リンクは保持し、リンク先の添付は取得しない。

## 1. 方法・範囲

Playwriter CLI 0.9.0から `127.0.0.1:9223` のChromeへ直接CDP接続した。認証済みセッションを利用し、既存の日本語記事1件と、調査用タブで開いた英語記事1件を読み取った。入力JSONの更新、回答・評価・Follow・Printの操作、業務データの更新は行っていない。

対象は参照URL一覧の「全ての文書をエクスポートしてダウンロードしたデータを参照する方法」と「PingAM - Configuring Single Sign-On (SSO) & SAML Claims Mapping for BlackLine」。後者は画像・表を含む。調査用タブと接続セッションは終了し、ユーザーの既存タブは維持した。

Cookie・認証ヘッダー・画像URLのクエリ・ページHTML全文・画像バイト列は本記録やfixtureへ保存していない。以下は構造と集計値のみを記録する。

## 2. 観測した本文構造

| 項目 | 両記事で確認した構造 |
| --- | --- |
| 記事コンポーネント | `.acknowltngKnowledgeArticleItem` が1件 |
| タイトル | 記事内の `h1.head-page__title` が1件 |
| 本文 | 記事内の `.acknowltngKnowledgeArticleBody` が1件 |
| 本文項目 | `ul.article__item-list` 内の項目ラッパーと `li`、ラベル、`lightning-formatted-rich-text` |
| 項目例 | Question、Related To、Answer、Additional Information |
| 非表示項目 | 内容がない項目に `.slds-hide` が付く例を確認 |
| 評価欄 | 本文外の `.voting-block` 内に存在 |

日本語記事は本文内画像0件・表0件・リンク1件。英語記事は本文内画像1件・表1件。両記事の `Related To` は記事内部の分類項目であり、外部の関連記事一覧と区別する必要がある。

本文のラベルとその値を対で保持し、質問・回答だけに固定して他の本文項目を落とさない方針を取れる。上記クラスを全記事で保証されたセレクターとは扱わない。`data-aura-rendered-by` の値は記事ごとに異なり、固定セレクターの根拠にしない。

## 3. 読込と通信

英語記事は遷移の `DOMContentLoaded` 時点で期待する本文項目を検出できず、本文領域の可視待機後に検出できた。文書のイベントだけでは記事描画完了と判定できない。

この遷移ではdocumentと複数のAura XHR応答を観測した。記事以外のスクリプトに302も存在したため、全通信を一律に記事取得結果と扱わない。必要な記事API、成功・失敗と本文の対応、最終的な本文安定条件は未確定。

## 4. 画像1件の限定確認

- 本文画像は同一オリジンのHTTPS URLで、`servlet/rtaImage` とクエリを使用していた。クエリの値は記録しない。
- 当該画像の `loading` 属性は未指定。全画像の遅延読込の有無は確認していない。
- 記事ページ内から同一オリジンの認証を利用したGETでHTTP 200、51,604バイトを取得できた。画像はメモリ内だけで確認し、ファイルとして保存していない。
- HTTP `Content-Type` は `image/jpeg`、実データ先頭8バイトはPNGの署名に一致した。ヘッダーのみで拡張子を決定すると誤る事例である。

PNGの署名一致までの確認であり、完全デコードや本アプリの画像保存・参照置換が成功したことを意味しない。

## 5. 未確認事項

- 実際の添付欄、ダウンロード応答、元ファイル名と形式の取得。
- 別の記事構造、長い本文、遅延読込画像、複数画像、追加情報に値がある記事。
- 401～409・その他4xx・ログイン切れ・転送の実画面と対象通信の対応。
- 記事APIの照合条件、HTML・画像・添付を同じ記事の結果として確定する方法。
- Python版Playwright、Markdown変換、exeでの再現確認。

本記録は限定観測であり、全URLの巡回・保存・受入確認の完了とは扱わない。追加調査は6節に記載する。

## 6. 記事APIの追加調査

同日、調査用タブで以下の2記事を追加確認した。元の2記事と合わせ計4記事であり、入力JSONの更新や全件巡回は行っていない。

- What to check to verify if your 2511 release version need ACP file for S4/HANA upgrade
- What are the field requirements for the Journal Validation import template?

Auraリクエストのうち記事取得に関係するアクション名・引数名・応答の型とキーを確認した。個人情報取得APIの値、Cookie、認証トークン、記事IDの実値は記録しない。APIの追加発行・再送は行わず、画面遷移でブラウザが発行した通信を観測した。

| 処理 | 観測したアクション | 引数 |
| --- | --- | --- |
| URLから記事版IDを解決 | `RecordServiceComponentController/ACTION$getArticleVersionId` | `urlName` |
| 記事情報 | `apex://acknowltng.KnowledgeArticleItemController/ACTION$getKnowledgeArticle` | `articleId` |
| 本文項目 | `apex://acknowltng.KnowledgeArticleBodyCtrl/ACTION$getFieldSetData` | `articleId`、`recordTypeName` |

4件目の記事で、以下の対応をメモリ内で照合した。

- 同じ `urlName` に対する2件のID解決応答は一致した。解決要求の `urlName` は対象URLの末尾と一致した。
- 記事情報・本文項目の要求 `articleId` は解決結果と一致した。
- 記事情報応答の `articleId` は解決結果と一致し、`title` は画面タイトルと一致した。
- 本文項目要求の `recordTypeName` は記事情報応答と一致した。
- 一方、記事情報応答の `urlName`、本文項目応答の `articleId` と `title` は空文字だった。これらを無条件の必須一致項目にはできない。
- 本文項目の順序配列は `Question__c`、`Related_To__c`、`Answer__c`、`Additional_Information__c`。対応するラベル辞書と値辞書を返した。値辞書にはQuestionとAnswerの2項目だけが存在した。
- 記事情報応答側の本文項目配列は空であり、本文項目応答では4項目だった。記事情報の成功だけで本文取得済みとは判断できない。
- 本文項目応答の欠落キーは、当該記事で値のない項目と対応する。ただし、全記事・全種別で同じ契約とは断定しない。

いずれの記事でも実添付を確認できなかった。「ファイル」「テンプレート」などを含むタイトルだけでは、添付の存在を判定できない。添付欄・ダウンロード方式は引き続き未確認。

## 7. 画像取得方式と本文安定の追加確認

同日、既調査のPingAM記事を調査用タブで再確認した。対象のユニーク記事数は計4件のままであり、新たな記事の大量巡回は行っていない。調査タブとPlaywriterセッションは終了した。

- Playwriter経由の `context.request.get` を使い、本文画像をHTTP 200で取得できた。ブラウザコンテキストとCookieを共有する方式であり、Cookieの書出しや手動の認証ヘッダー設定は行っていない。
- この確認では転送を自動追跡しない設定を使用した。転送なしで51,604バイトを取得し、`Content-Type: image/jpeg` とPNG署名の不一致を再確認した。応答オブジェクトは確認後に解放し、画像ファイルを保存していない。
- 表示中の画像は `complete: true`、自然寸法577×281、`srcset` なし、`currentSrc` と `src` が一致した。ブラウザで表示可能な画像であることを確認した。
- 本文HTMLを250ms間隔で2回読み、当該時点では一致した。移動直後からの安定条件や全記事に対する250msの十分性を保証する確認ではない。
- 非表示項目ラッパーは `display: none` で、ラベルだけが存在する例だった。非表示だが本文データがあるケースは未確認。

この結果はJavaScript版APIをPlaywriter経由で確認したものであり、Python版・exeの動作確認ではない。画像URL、クエリ、認証値、画像バイト列、本文HTMLは本記録へ保存していない。
