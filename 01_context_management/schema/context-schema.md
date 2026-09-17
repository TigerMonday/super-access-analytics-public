# コンテキストストア スキーマ定義

`context/<client_id>/` 配下の各ファイルの正典スキーマ。クライアント実データは `.gitignore` 対象（`samples/sample-client/` が記入例）。

すべて id 参照（`related_kpi: kpi_001` 等）で相互リンクする。`kpis.yaml` の `kpi_id` 形式は `02_basic_measurement/measurement_design` と互換。

---

## ディレクトリ構成

```
context/<client_id>/
├── profile.yaml               # クライアント基本情報
├── measurement.yaml           # 計測環境レジストリ
├── kpis.yaml                  # KPI・ゴール定義・主要イベント
├── site-segments.yaml         # サイトセグメント（分析対象の定義。役割の違うセクションの切り分け）
├── customer-understanding.yaml # 3C・ペルソナ・態度変容ジャーニー（03由来）
├── initiatives.yaml           # 施策履歴
├── constraints.yaml           # 前提・制約(gotchas)・命名規則・未解決課題
├── stakeholders.yaml          # ステークホルダー
├── analysis-history.yaml      # 分析・アウトプット履歴
└── meetings/
    └── YYYY-MM-DD_<topic>.md  # 議事録（Markdown）
```

`<client_id>` は英数字・ハイフン・アンダースコアのみ（出力フォルダ名と一致させる）。

---

## profile.yaml — クライアント基本情報

```yaml
client:
  client_id: sample-client      # フォルダ名と一致
  name: 株式会社サンプル          # 正式名称  leak-ok: ダミー会社名の統一表記（実在の社名ではない）
  industry: SaaS                # 業種
  business: 中小企業向け会計SaaSの開発・提供   # 事業内容
  site_url: https://example.com
  business_model: toB           # toB / toC / both
  target: 中小企業の経理担当・経営者          # ターゲット像
  notes: |                      # 自由記述（背景・特記事項）
    2024年リブランディング。リード獲得が主目的。
aliases:                      # client_id の別名（旧clientフォルダ名・略称・表記ゆれ等）
  - sample-inc
  - サンプル株式会社  # leak-ok: ダミー会社名の統一表記（実在の社名ではない）
preferences:                   # 利用者側の運用上の好み（事業情報ではない）
  output_formats:              # 成果物の書き出し先。空リスト=MDのみ（変換しない）
    - html
  # gdoc / gsheet を含める場合はURLも必須（下記 preferences.google_doc_url / google_sheet_url 参照）
  # - gdoc
  # google_doc_url: null
  accent_color: "#1D4ED8"      # HTML/PDF成果物の差し色（未設定なら既定のゴールドのまま）
  logo_path: "assets/client-logo.svg"   # HTML/PDF成果物のロゴファイルパス（未設定なら既定のプレースホルダのまま）
  include_query_params: false  # ランディングページ等の集計でクエリパラメータを含めるか（既定false=パスのみ）
```

| キー | 必須 | 説明 |
|---|---|---|
| `client.client_id` | ✅ | フォルダ名と一致させる識別子 |
| `client.name` | ✅ | 正式名称 |
| `client.industry` | | 業種 |
| `client.business` | | 事業内容 |
| `client.site_url` | | 主要サイトURL |
| `client.business_model` | | `toB` / `toC` / `both` |
| `client.target` | | ターゲット像 |
| `client.notes` | | 背景・特記事項（自由記述） |
| `aliases` | | client_id の別名リスト。`load_context(別名)` で正規の `client_id` に解決される（同じ別名が複数クライアントに登録されている場合は `load_context()` が例外を投げる） |
| `preferences.output_formats` | | 成果物（MD）の書き出し先リスト。値は `common/report_export` の `--to` に渡せる4形式（`html` / `pdf` / `docx` / `xlsx`）に加え、Googleドキュメント/スプレッドシートへの書き込みを表す `gdoc` / `gsheet`（許容値は `schema.OUTPUT_FORMATS`）。複数指定可。**キー自体が無ければ「未設定＝一度も聞いていない」**、**空リスト `[]` は「MDのみで変換しない」という明示的な選択**として扱う（`ClientContext.output_formats` がこの2つを区別する）。保存は `writeback.save_output_format_preference()`。docs/standard-run-order.md §2-1・§4-2 参照 |
| `preferences.google_doc_url` | ▲ | `output_formats` に `gdoc` を含める場合は必須。書き込み先のGoogleドキュメントURL。**サービスアカウントは自分でファイルを作れない**（Google Drive API公式ドキュメント: "Service accounts don't have storage quota and can't own files."。共有ドライブでの回避策はGoogle Workspaceの有償エディションが前提で、無料アカウントの利用者では成立しない）ため、利用者が先に空のドキュメントを作り、サービスアカウントのメールアドレス（認証ファイルの `client_email` の値。**このリポジトリ・ログには書かない**）に編集者で共有した、その先のURLを保存する運用に固定する（自動作成はしない）。未設定なら `ClientContext.google_doc_url` は `None`。`gdoc` を選んでいるのにURLが空だと `schema.validate_output_format_preference()` が警告する。保存は `writeback.save_output_format_preference()` |
| `preferences.google_sheet_url` | ▲ | `output_formats` に `gsheet` を含める場合は必須。理由・運用は `google_doc_url` と同じ（サービスアカウントは自分でファイルを作れないため、利用者が用意し共有したURLが必須）。未設定なら `ClientContext.google_sheet_url` は `None` |
| `preferences.accent_color` | | HTML/PDF成果物の差し色（ゴールド）を自社ブランドカラーに変えたい場合の基準色。6桁HEX（例 `"#1D4ED8"`）。`common/report_export` の `--accent-color` にそのまま渡せる。**未設定なら既定のゴールド`#D4AF37`のまま**（`ClientContext.accent_color` が `None`）。保存は `writeback.save_brand_preferences()`。`report_export` は01に依存しない汎用ツールのため、値の受け渡しは呼び出し側が担う（`common/report_export/design_system/design-system.md`「差し色を自社ブランドカラーに変える」参照） |
| `preferences.logo_path` | | HTML/PDF成果物のロゴファイルパス。`common/report_export` の `--logo` にそのまま渡せる。**未設定なら既定のプレースホルダ（`logo-placeholder.svg`）のまま**（`ClientContext.logo_path` が `None`）。保存は `writeback.save_brand_preferences()` |
| `preferences.include_query_params` | | ランディングページ等の集計でクエリパラメータ（例: `/?renew=`）を含めるか。**既定は `false`（パスのみ）**。ECサイト・ブログのようにクエリ文字列そのものが別ページを表すサイトだけ、必要になった時点で明示的に `true` を設定する。`output_formats` と異なり「聞いたか未確認か」を区別する3値は持たない単純なbool（`ClientContext.include_query_params` は未設定時も常に `false` を返す）。01の通常登録フローで毎回聞く項目ではなく、02が実データを見て必要性に気づいた時点で確認・保存する運用（`site_segments` と同じ考え方）。保存は `writeback.save_query_param_preference()` |

---

## measurement.yaml — 計測環境レジストリ

他エージェントが毎回聞いていた各種IDを一元管理。`ga4` / `gtm` のキー名は `measurement_design` の `ga4.local.yaml` / `gtm.local.yaml` と互換。

```yaml
ga4:
  property_id: "123456789"
  auth_method: sa             # sa（サービスアカウント）/ oauth
gtm:
  gtm_account_id: "123456"
  gtm_container_id: "GTM-XXXXXXX"
search_console:
  site_url: "https://example.com/"   # SCのプロパティURL（sc-domain: 形式も可）
bigquery:
  project_id: "my-gcp-project"
  dataset: "analytics_123456789"     # GA4 BQ エクスポート先
ad_accounts:
  - platform: google_ads
    account_id: "123-456-7890"
  - platform: yahoo_ads
    account_id: "ABCDEFG"
  - platform: meta_ads
    account_id: "act_1234567890"  # leak-ok: Meta広告アカウントIDのダミー例（連番のプレースホルダで実IDではない）
```

各ブロックは任意。未契約・未設定のものは省略可。

---

## kpis.yaml — KPI・ゴール定義・主要イベント

`measurement_design/sample-client/inputs/kpis.yaml` の形式を踏襲。`key_events`（CV計算用イベント）を併記。

```yaml
kgi: 月間有効リード300件                # 事業のゴール（任意・自由記述）
kpis:
  - kpi_id: kpi_001
    name: 資料ダウンロード数
    target_metric: イベント数
    target_value:
      goal: 200
      unit: 件/月
    description: コーポレートサイト経由の資料ダウンロード完了
    related_pages:
      - page_id: page_download
    events:                            # このKPIを計測しているGA4イベント名（複数可）
      - file_download
    priority: 2                        # どれを主に見るか（1が最優先）。CVが1つしかないクライアントには聞かない
  - kpi_id: kpi_002
    name: お問い合わせ完了数
    target_metric: イベント数
    target_value:
      goal: 50
      unit: 件/月
    description: お問い合わせフォームの送信完了
    related_pages:
      - page_id: page_contact_complete
    events:
      - generate_lead
      - form_submit
    form_pages:
      - path: /contact/
        match_type: exact
    priority: 1                        # 例: 資料DLより問い合わせを増やす方を優先して見ていく方針の場合
key_events:                            # CV計算に使うGA4イベント名（全KPI横断の一覧）
  - file_download
  - generate_lead
  - form_submit
```

| キー | 必須 | 説明 |
|---|---|---|
| `kgi` | | 事業ゴール（自由記述） |
| `kpis[].kpi_id` | ✅ | `kpi_001` 形式の識別子 |
| `kpis[].name` | ✅ | KPI名 |
| `kpis[].target_metric` | | 指標種別 |
| `kpis[].target_value.goal` / `.unit` | | 目標値・単位 |
| `kpis[].description` | | 説明 |
| `kpis[].related_pages` | | 関連ページ（`page_id` 参照） |
| `kpis[].events` | | このKPIを計測しているGA4イベント名のリスト（登録時にCVの意味とあわせて必ず確認する）。**01の計測突合（KPIカバレッジ判定）はこれが登録されていれば最優先でGA4実態と突合する**。未登録のKPIのみ、01が一般的なイベント名を提案する |
| `kpis[].form_pages` | | リードサイトで、このKPIの完了イベントに対応するフォームページ。各要素は `path` と `match_type`（`exact` / `contains`）を持つ。04基本分析が候補を提示し、利用者が確認した値だけを `save_kpi_info()` で保存する。未確認ならフォーム通過率を作らない。ECサイトでは使わない |
| `kpis[].priority` | | **複数CVがあるクライアントで、どれを主に見るか**（1が最優先。以降2、3…と続く整数）。CVR改善（05↔06）はこれを見て、施策の改善・提案を優先KPIの改善を軸に組み立てる。**KPIが1つしかないクライアントには聞かない**（比較対象が無く優先度の意味が無いため）。**未設定を許容する**：既存クライアントの多くはまだ聞いていない状態なので、キー自体が無くてもエラーにしない（`ClientContext.primary_kpi` が `None` を返し、「未設定」と分かる形で後続処理に伝わる。狼狽して止まらないこと）。設定は `writeback.save_kpi_priorities()`。値の重複や一部だけの設定は `schema.validate_kpi_priorities()`（`ctx.validate()` 経由）が警告する |
| `key_events` | | CV計算に使うGA4イベント名リスト（全KPI横断） |

**優先度をどこで聞くか**：01のフル登録対話で `kpis.yaml` を埋める時点に、**KPIが2件以上あるときだけ**「どれを主に見ていくか」を確認する（1件なら聞くまでもないので聞かない）。02（計測チェック）の受付でもCVの**存在**（イベント名）は確認するが、優先度の**確定**は01登録側の役目とする（02は計測が入っているかどうかを見るエージェントで、施策の優先順位を決める場ではないため）。すでに01に登録済みで `kpis[].priority` があれば、02・04・05のどのエージェントも聞き直さずそれを使う。

---

## site-segments.yaml — サイトセグメント（分析対象の定義）

**分析対象を事前に定義させる入力欄ではない。** メディア（オウンドメディア・ブログ等、CVを直接狙っていない集客セクション）とサービス本体のようにサイト内に役割の違うセクションが混在していると、それを分けずに集計した場合にCVRが実態より低く出て「新規に弱い」のような誤った解釈につながる（数字自体は正しいのに解釈を誤る事故）。このファイルはその再発防止のための定義を持つ。

**運用の起点は利用者ではなくツール側。** 02・04は実行時にGA4のページ一覧（`hostName` / `pagePath`）を既に取得しているため、パスの構造から「役割の違うセクションがありそう」と気づいたら「`/media/` 配下が全体の6割を占めています。分けて集計しますか」のように利用者へ提案し、**確認が取れた結果だけ**を `writeback.save_site_segments()` で保存する。01の登録フロー（`prompts/context-manager.md`）はこれを毎回聞かない（役割の違うセクションを持たないサイトの方が多いため）。

**役割の名前を固定しない。** 「本体/メディア」の2値ではなく、採用サイト・サポート・ヘルプセンター・会員向けページなど、サイトによって何種類あってもよい自由記述（`name` / `description`）で持たせる。

**一致条件を書くのは切り出したいセクションだけ。** オウンドメディアのように役割が違うセクションは `match` で条件を書くが、それ以外（トップ・about・お問い合わせ・LP等、訪問者と目的が本体サイトと同じページ）は書かせない。本体サイトに相当するセグメントに `default: true` を付ければ、`match` に一致しなかったページは自動でそこに分類される。「その他」という3つ目のバケツは作らない。

```yaml
site_segments:
  - segment_id: seg_001
    name: オウンドメディア
    description: 集客記事
    match:
      path_prefix: /media/
  - segment_id: seg_002
    name: 本体サイト
    description: サービス紹介・会社紹介・問い合わせ。上のどれにも当てはまらないページ
    default: true                 # match に一致しないページは全部ここに落ちる
  - segment_id: seg_003
    name: 採用サイト
    description: 採用情報・エントリー導線
    match:
      host_name: recruit.example.com
```

| キー | 必須 | 説明 |
|---|---|---|
| `site_segments[].segment_id` | ✅ | `seg_001` 形式の識別子 |
| `site_segments[].name` | ✅ | セクションの呼び名（自由記述。「本体/メディア」に固定しない） |
| `site_segments[].description` | | 補足説明 |
| `site_segments[].match` | ▲ | `host_name` / `path_prefix` / `content_group` のいずれか1つ以上。`default: true` のセグメントを除き必須 |
| `site_segments[].match.host_name` | | ホスト名（完全一致・大小文字無視）。スカラーでもリストでもよく、リストの場合はいずれかに一致すればよい（OR） |
| `site_segments[].match.path_prefix` | | パスの前方一致。スカラーでもリストでもよい（OR） |
| `site_segments[].match.content_group` | | GA4のコンテンツグループ機能（`02_basic_measurement`が計測設計時に設定有無を判定する項目）で払い出された値との完全一致。**コンテンツグループが設定済みのサイトはこちらを優先し、`path_prefix`/`host_name`で同じ境界を二重に定義しない**（未設定なら`path_prefix`/`host_name`で代用する） |
| （`match`全体） | | `host_name` / `path_prefix` / `content_group` を複数指定した場合は **AND**（すべて満たす）。同じキー内のリストは **OR**（いずれかに一致すればよい）。**どのキーも指定しない（空の）セグメントは絶対に一致しない**（`default: true` のセグメントを除く。空条件を「すべてに一致」にすると、その他のセクションを丸ごと飲み込んでしまう事故につながるため安全側に倒す設計） |
| `site_segments[].default` | | `true` にすると、どの `match` にも一致しなかったページがここに分類される既定セグメント（通常は本体サイト）。**`match` とは同時に持たせない**（既定セグメントは条件で絞る役割ではないため。`schema.validate_site_segments` が警告する）。`true` は**1件だけ**にする（2件以上あるとどちらに落ちるか決まらず、これも警告する） |

**マッチの優先順位**：`default: true` を持たないセグメントの中で、定義順に見て最初に一致したセグメントを採用する（先勝ち）。パスが重なる場合は、具体的な条件（例: `/media/special/`）を広い条件（例: `/media/`）より先に書く。**どの `match` にも一致しなければ既定セグメント（`default: true`）に分類される**。明示的な `match` に一致するページが既定セグメントより優先される（既定は最後のフォールバック）。

**既定セグメント（最重要）**：**「その他」という3つ目のバケツは作らない設計にした。** 理由は、オウンドメディアのようなセクションを切り出しても、それ以外のページ（トップ・about・お問い合わせ・LP等）は訪問者も目的も本体サイトと同じであることが実データ上ほとんどで、利用者に埋めさせても結果は必ず「本体サイト」になるため、埋めさせる意味が無いから。ただし**「分けて集計した合計が全体と一致すること」という当初の目的は変えていない**——過去に「独立した3つの切り口の合計が全体を29,361件上回っていた」という事故（定義から漏れたページを黙って除外していた）があり、それを防ぐのが目的そのものだった。既定セグメントがあれば、どのページも必ずどれかのセグメントに入るため、この目的は合計チェックを待たずに定義上満たされる。`default: true` を1件も設定していない場合に限り、`schema.match_site_segment()` / `ClientContext.classify_page()` は今まで通り `None`（＝「その他」）を返す。この場合は呼び出し側（02等）が `None` の件数を集計から除外せず「その他」として必ず可視化すること。

**未設定でも止まらない**：`site_segments` が空・キー自体が無いクライアントは従来と同じ動作（`classify_page` は常に `None`）で、`ctx.validate()` の警告は0件。警告になるのは、定義した以上は中途半端であってはならない状態（`segment_id`の重複・`match`条件が空・`default: true`の過不足（0件または2件以上）・`default: true`なのに`match`も設定されている）に絞る。設定・検証は `writeback.save_site_segments()` / `schema.validate_site_segments()`。

---

## customer-understanding.yaml — 3C・ペルソナ・態度変容ジャーニー

`03_external_research`（市場・顧客理解エージェント）が作る統合レポートのうち、**長く使う前提情報**をここに保存する。分析より寿命が長いため、**作成日**と**根拠（どの調査から導いたか）**を必ず持たせる。古くなったことに気づけるようにするための最小限の仕組み。

**属性の羅列（年齢・職業・家族構成・趣味など）は書かない。** ペルソナ・ジャーニーは「態度変容フロー（何が起きたら次の段階に進むか）」を可視化するためのもので、`relevant_attributes` は**態度変容の説明に必要な属性だけ**を書く（例: 決裁権の有無は書くが、趣味は書かない）。

一次情報で確認できなかった項目は埋めない。`unresolved` に「何を確認できなかったか」を残す。

### 根拠の種類（4種類。区別して書く）

ペルソナ・障壁・刺激の根拠は、常に次の4種類のいずれかから来る。**どれも正当な根拠だが確度が違う**ので、成果物・01の両方で区別を残す（`evidence_type` / `persona_basis`）。レビュー・Q&Aへの投稿が少ない会社（多数派）でも、サービスから逆算する経路だけでペルソナを作ってよい。

| 種類 | 意味 | 主な材料 |
|---|---|---|
| `service_derived`（サービスからの逆算） | 自社が想定している顧客像。会社が「こういう人に売る」と決めている事実。**自社が書いたもの**が根拠 | サービスページ・料金ページ（サービスメニュー単位）。`competitor-desk-research` の「自社サービスメニュー×想定顧客マップ」 |
| `customer_voice`（顧客の声で裏付け） | 実在が確認できた**自社の**顧客。実際の発言・行動 | 自社に関するレビュー・Q&A・SNS・事例インタビューの引用。または利用者が問い合わせ・商談で直接聞いている顧客の声（03のヒアリングで確認） |
| `competitor_customer_voice`（競合事例で裏付け） | 同業・競合の公式事例に登場する実在の顧客。**その属性の顧客が実在すること**は確認できるが、**その人が自社を選ぶか**までは確認できない（`customer_voice` より一段弱い） | `competitor-case-study-research` / `competitor-company-deep-dive` の公式導入事例 |
| `desk_research`（デスクリサーチで確認した客観的事実） | 第三者を調べて確認できた客観的な事実。**誰かの発言ではなく、調べた結果そのもの**が根拠。**「見つからなかった」という不在の確認も事実として使ってよい**（例: 「ITreviewのレビュー0件、Q&Aサイトでの言及0件」） | レビューサイト・Q&Aサイトの件数・傾向、業界データ、公開情報。**第三者を調べた結果**であって、自社が書いたものではない点で `service_derived` と区別する |

根拠が無い思いつきは `hypothesis` のまま（他4値に格上げしない）。`competitor_customer_voice` は障壁（相手側の内部状態）の裏付けに使ってよいが、刺激（自社の訴求で効くか）に使う場合は「事例に触れること一般」のような会社を問わない機序であることを確認してから使う（自社固有の訴求の裏付けにはしない）。

**`service_derived` と `desk_research` の使い分け**：材料が自社発信（サービスページ・料金ページ等、会社が「こう売る」と決めた事実）なら `service_derived`。材料が第三者を調べた結果（レビューサイト・Q&Aサイト・業界データ・公開情報。会社の想定でも顧客の発言でもない）なら `desk_research`。「調べたが無かった」も後者の正当な事実。

### 最終段階（`stage_id: purchase`）の表示名

`stage_id` は06が段階を参照するための識別子なので5値固定のまま変えない。一方 `stage_name`（表示名）は自由記述で、**特に最終段階は業種でCVの実態が変わる**（EC・自己申告購入なら「購入」のままでよいが、コンサル・BtoBなら「相談」「契約」等）。01の `kpis.yaml` の `key_events` に紐づくKPIの `name` / `description`（登録時に業務上の意味を確認済み）から、その事業のCVの実態を表す名称を導いて上書きする。`kpis.yaml` が未登録なら既定の「購入」を暫定値とし、要確認として明記する。日常業務／課題の発生／調査／検討の4段階は業種で大きくは変わらないため、原則そのままでよい。

```yaml
created_date: "2026-08-30"        # このファイルを作成・更新した日（古さの判断基準）
source_report: outputs/sample-client/03_research/customer_understanding/00_3c_persona_journey_report.md
source_child_reports:              # 根拠にした子スキルの個別成果物（複数可。03の data/child_reports/ 配下）
  - outputs/sample-client/03_research/customer_understanding/data/child_reports/01_desk_research.md
  - outputs/sample-client/03_research/customer_understanding/data/child_reports/02_review_research.md
  - outputs/sample-client/03_research/customer_understanding/data/child_reports/03_qa_research.md

three_c:
  customer:
    summary: 現場担当者は導入決裁権を持たず、上長を説得する材料を探している。
    evidence: "03_qa_research.md「知恵袋: 会計SaaS 上司 説得」に類する投稿が複数"
  competitor:
    summary: 主要3社は価格訴求が中心で、導入後の運用支援を訴求する競合が少ない。
    evidence: 01_desk_research.md 比較マトリクス
  company:
    summary: 中小企業向け会計SaaS。toB、リード獲得が主目的。
    evidence: 01登録情報（profile.yaml） + 公式サイト

personas:
  - persona_id: persona_001
    name: 現場の経理担当者
    persona_basis: customer_voice_confirmed   # customer_voice_confirmed（顧客の声で実在確認） / competitor_customer_voice_confirmed（競合事例で実在確認のみ） / service_derived（サービスからの逆算のみ）
    distinguishing_factor: |
      決裁権を持たず「調査」「検討」段階で上長説得の材料探しが挟まる点が、
      決裁者（persona_002）と態度変容フローの分岐点になる。
    relevant_attributes:            # 態度変容の説明に必要な属性のみ
      - attribute: 決裁権
        detail: 無し。稟議には上長の承認が必要
        evidence_type: customer_voice
        evidence: 03_qa_research.md の投稿引用
    journey:
      - stage_id: daily_business
        stage_name: 日常業務
        situation: 手作業の経理処理に追われている。
        awareness_state: 業務が非効率だとは感じているが、ツール導入の発想は無い。
        barriers:
          - barrier_id: persona_001_daily_business_b1
            description: 忙しく、課題を言語化する余裕が無い。
            evidence_type: customer_voice
            evidence: 02_review_research.md のレビュー引用
        stimuli:
          - stimulus_id: persona_001_daily_business_s1
            description: 同業他社の効率化事例に触れる。
            evidence_type: hypothesis   # customer_voice / competitor_customer_voice / service_derived / desk_research / hypothesis の5値
            evidence: null              # customer_voice・competitor_customer_voice・service_derived・desk_research のときのみ必須
      - stage_id: problem_emergence
        stage_name: 課題の発生
        situation: 月次締め作業でミスが発生し、上長から指摘を受ける。
        awareness_state: 「このままではまずい」と課題を認識するが、解決策は未検討。
        barriers:
          - barrier_id: persona_001_problem_emergence_b1
            description: 何を検索すればよいか分からない。
            evidence_type: hypothesis
            evidence: null
        stimuli:
          - stimulus_id: persona_001_problem_emergence_s1
            description: 「経理 ミス 防止」等の検索広告での接触。
            evidence_type: hypothesis
            evidence: null
      - stage_id: research
        stage_name: 調査
        situation: 検索・比較サイト・知恵袋で情報収集する。
        awareness_state: 複数ツールの存在を認識しているが、違いが分からない。
        barriers:
          - barrier_id: persona_001_research_b1
            description: 上長を説得できる比較材料が見つからない。
            evidence_type: customer_voice
            evidence: 03_qa_research.md の投稿引用
          - barrier_id: persona_001_research_b2
            description: 第三者の評価（レビュー・Q&A）を探しても見つからず、比較材料にできない。
            evidence_type: desk_research   # 顧客の発言でも自社の想定でもなく、調べて確認した事実
            evidence: 02_review_research.md「ITreviewのレビュー0件、Q&Aサイトでの言及0件」
        stimuli:
          - stimulus_id: persona_001_research_s1
            description: 「上司を説得できた」という体験談・比較表コンテンツへの接触。
            evidence_type: customer_voice
            evidence: 03_qa_research.md「比較表を見せたら通った」という回答
      - stage_id: consideration
        stage_name: 検討
        situation: 候補を2〜3社に絞り、資料請求・問い合わせをする。
        awareness_state: 機能差は理解したが、導入後のサポート体制が不安。
        barriers:
          - barrier_id: persona_001_consideration_b1
            description: 導入後の運用イメージが持てない。
            evidence_type: customer_voice
            evidence: 02_review_research.md のレビュー引用
        stimuli:
          - stimulus_id: persona_001_consideration_s1
            description: 導入事例・サポート体制の具体的な説明。
            evidence_type: service_derived
            evidence: 01_desk_research.md 自社サービスページ「導入後30日間の伴走サポート」記載
      - stage_id: purchase
        stage_name: 問い合わせ   # 01のkpis.yaml kpi_002（お問い合わせ完了数 / events: generate_lead, form_submit）から導出。stage_idは固定のまま
        situation: 上長の承認を得て問い合わせ・契約する。
        awareness_state: 稟議のための資料が揃えば決裁が通ると認識している。
        barriers:
          - barrier_id: persona_001_purchase_b1
            description: 稟議書に転記できる形の資料が無い。
            evidence_type: hypothesis
            evidence: null
        stimuli:
          - stimulus_id: persona_001_purchase_s1
            description: 稟議用テンプレート・見積書の即時提供。
            evidence_type: hypothesis
            evidence: null

unresolved:                          # 一次情報で確認できず埋めなかった項目
  - persona_002（決裁者）の「調査」段階の障壁は根拠となる発言が見つからず未記入
```

| キー | 必須 | 説明 |
|---|---|---|
| `created_date` | ✅ | 作成・更新日（`YYYY-MM-DD`）。3C・ペルソナ・CJは分析より寿命が長いため、他エージェントはこの日付を見て古さを判断する |
| `source_report` | | 統合レポート（03の最終成果物）へのパス |
| `source_child_reports` | | 根拠にした子スキル個別成果物のパスのリスト |
| `three_c.customer` / `.competitor` / `.company` | | 3C各要素の要約と根拠（`evidence`）。`evidence` は子スキルの成果物ファイル名＋該当箇所、または01登録情報 |
| `personas[].persona_id` | ✅ | `persona_001` 形式の識別子 |
| `personas[].name` | ✅ | ペルソナの呼称（役割ベース。個人名は使わない） |
| `personas[].persona_basis` | ✅ | `customer_voice_confirmed`（顧客の声で実在確認できた）/ `competitor_customer_voice_confirmed`（競合事例で顧客層の実在は確認できたが、自社を選ぶかは未確認）/ `service_derived`（サービスからの逆算のみで、顧客の声による裏付けはまだ無い）の3値。このペルソナ全体をどの経路で主に構築したか。**`desk_research` はここには無い**：ペルソナの実在（誰が存在するか）を主張する経路は上記3つのみで、`desk_research` はいずれかのペルソナが既に存在する前提で、その障壁・刺激（`journey[].barriers[].evidence_type` / `stimuli[].evidence_type`）を裏付ける根拠としてのみ使う |
| `personas[].distinguishing_factor` | ✅（ペルソナが2人以上のとき） | **なぜこの人を分けたか**。属性の違いではなく、態度変容フロー（障壁・刺激）の違いを書く。ペルソナが1人のときは省略可 |
| `personas`（配列全体） | | **上限5人。** 5人を超える場合は切り捨てず、態度変容フロー（障壁・刺激）が近いペルソナ同士を統合する（`validate_customer_understanding()` が超過時に警告）。詳細は03の SKILL.md「ペルソナ構築」節 |
| `personas[].relevant_attributes` | | 態度変容の説明に必要な属性だけ。趣味・家族構成等の一般属性は書かない。各属性にも `evidence_type` / `evidence` を添える |
| `personas[].journey` | ✅ | 5段階（`daily_business` / `problem_emergence` / `research` / `consideration` / `purchase`）を固定順で並べる |
| `journey[].stage_id` | ✅ | 固定の5値のいずれか。06から段階を参照するための識別子。**変えない** |
| `journey[].stage_name` | | 表示名。自由記述。最終段階（`purchase`）のみ01の `kpis.yaml` から導いたCVの実態を表す名称に差し替える（前節参照）。それ以外の4段階は原則そのまま |
| `journey[].situation` | | その段階で何が起きているか（状況・行動） |
| `journey[].awareness_state` | | 何を認識していて、何をまだ認識していないか |
| `journey[].barriers[].barrier_id` | ✅ | `{persona_id}_{stage_id}_b{n}` 形式。06から障壁を参照するための識別子 |
| `journey[].barriers[].description` | ✅ | 何が引っかかって次に進まないか |
| `journey[].barriers[].evidence_type` | ✅ | `customer_voice` / `competitor_customer_voice` / `service_derived` / `desk_research` / `hypothesis` の5値。05（page_profile / create-page-plan）が障壁の根拠有無を見て確信度を変えるため、stimuliと同様に必須 |
| `journey[].barriers[].evidence` | `evidence_type` が `customer_voice` / `competitor_customer_voice` / `service_derived` / `desk_research` のとき必須 | 根拠にした発言・出典 |
| `journey[].stimuli[].stimulus_id` | ✅ | `{persona_id}_{stage_id}_s{n}` 形式 |
| `journey[].stimuli[].description` | ✅ | どういう刺激を与えたら次の段階へ動くか（**成果物の中心**） |
| `journey[].stimuli[].evidence_type` | ✅ | `customer_voice`（自社のレビュー・Q&A等の発言・行動、または利用者ヒアリングが根拠）/ `competitor_customer_voice`（競合の公式事例に登場する実在顧客が根拠。自社を選ぶかまでは確認できない点に注意）/ `service_derived`（自社サービスページ等、会社側の公式情報が根拠）/ `desk_research`（第三者を調べて確認した客観的事実が根拠。不在の確認も可）/ `hypothesis`（根拠なしの仮説）。埋めたくなる項目なので必ず明示する |
| `journey[].stimuli[].evidence` | `evidence_type` が `customer_voice` / `competitor_customer_voice` / `service_derived` / `desk_research` のとき必須 | 根拠にした発言・出典（子スキル成果物のファイル名＋引用） |
| `unresolved` | | 一次情報で確認できず埋めなかった項目のリスト。空欄を埋めずにここへ書く |

`load_context()` はこのファイルも読み込み、`ClientContext.customer_understanding` に格納する。`summary_markdown()` は `created_date` とペルソナ名・分岐理由を短く表示する（詳細は本ファイルを直接参照させる）。

---

## initiatives.yaml — 施策履歴

```yaml
initiatives:
  - initiative_id: init_001
    name: ホワイトペーパーLP公開
    period:
      start: "2026-03-01"
      end: "2026-03-31"           # 継続中は null
    description: 業界別ホワイトペーパー3本のLPを公開しリード獲得
    related_kpi: kpi_001           # kpis.yaml の kpi_id を参照
    result: |
      DL数が前月比 +45%。直帰率はやや上昇。
    outputs:                       # 関連アウトプットのパス
      - outputs/sample-client/2026-04-01_report.html
```

`period.end: null` で継続中。`result` は実施後に追記。

---

## constraints.yaml — 前提・制約(gotchas)・命名規則・未解決課題

分析の前提を揃え、誤分析を防ぐための注意点を集約。

```yaml
gotchas:                          # サイト固有の注意点（誤分析防止）
  - id: gotcha_001
    title: CVR分母はB2B入口にlandingPageで絞る
    detail: toC/toB混在サイト。全体セッション分母だと誤結論になる。
naming_conventions:               # クライアント別の命名規則override（任意）
  utm_source: 小文字スネークケース。媒体正式名（google, yahoo, meta）
  utm_medium: cpc / display / email / social のみ許可
  notes: 全社デフォルトは parameter_management/standards/naming-conventions.md
open_questions:                   # 仮説・未解決課題
  - id: q_001
    question: 資料DL後のリード化率が低い要因は？
    hypothesis: フォーム項目過多の可能性
    status: open                  # open / investigating / resolved
```

`gotchas` は各エージェントが分析前に必ず確認する想定。

---

## stakeholders.yaml — ステークホルダー

```yaml
stakeholders:
  - name: 山田 太郎
    role: マーケ責任者（決裁者）
    org: 株式会社サンプル  # leak-ok: ダミー会社名の統一表記（実在の社名ではない）
    contact: yamada@example.com
    notes: 施策の最終承認者
  - name: 鈴木 一郎
    role: 自社側担当
    org: 自社
```

施策の「実施担当を明記」する際の参照元。

---

## analysis-history.yaml — 分析・アウトプット履歴

各エージェントが完了時に1エントリ追記（findings引き継ぎ）。今回はスキーマ＋手動追記、自動追記はPhase2。

```yaml
entries:
  - date: "2026-04-01"
    agent: parameter_management      # 実行エージェント
    summary: utm監査と基本分析を実施
    findings:                        # 主要な発見（後続エージェントが参照）
      - yahoo広告の utm_medium 未設定で (not set) 流入が15%
      - メルマガ経由のCVRが最も高い
    outputs:
      - outputs/sample-client/2026-04-01_report.html
```

`findings` は次のエージェントへの引き継ぎ情報。降順（新しい順）でも昇順でも可、`date` で判別。

---

## meetings/ — 議事録（Markdown）

ファイル名: `YYYY-MM-DD_<topic>.md`。先頭にメタ情報、本文に要点。

```markdown
---
date: 2026-04-01
attendees: [山田太郎, 鈴木一郎, 佐藤次郎]
type: client            # client / internal
---

# 4月定例MTG

## 決定事項
- ホワイトペーパーLPを継続、5月に2本追加

## 論点・宿題
- リード化率の改善策を次回までに検討（→ open_questions q_001 と連動）
```
