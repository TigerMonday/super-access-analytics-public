# 実行手順: パラメータ管理エージェント

ユーザーは「監査したい」と言うだけ。エージェントが GA4 データ取得 → 観察 → 質問 → 監査 → MDファイル保存まで自動で駆動する。

> 最終出力はMarkdownを正本とし、利用者がHTMLを選んでいる場合は共通の `report_export` で、目次・考察ボックス・グラフを備えたHTMLへ変換する。

## 自然文で基本分析を依頼されたときの受付

ユーザーから「基本分析して」「GA4とSearch Consoleを見て」などと依頼されたら、現在のAIエージェントが次を行ってから本文の手順へ進む。質問の必須・任意の区別は `docs/standard-run-order.md` §2-1を優先する。

1. 依頼文の client_id、または `list_clients()` の一覧から対象を確定し、`load_context(client_id)` を読む。未登録なら `docs/standard-run-order.md` §2-1 のURL先行受付を使う。最初に対象サイトURLを確認し、サイト表示名と client_id はURL・サイト・GA4情報から候補を作る。候補が曖昧・矛盾・重複する場合だけ利用者へ確認し、`ensure_client_registered()` と `save_business_profile(site_url=...)` で最小登録する。
2. GA4プロパティIDとCVの業務上の意味・完了イベント名を確認する。01に無いものだけを一度に聞き、確認できた値を保存する。CVが分からなければGA4のキーイベント設定を候補として提示し、確定しないまま分析を進めない。
3. 既存クライアントで01にサイトURLが無ければ確認する。URLが得られたら実際のサイトを読み、サイトの役割・toB/toC・事業内容を根拠つきで提示して確認を取る。確認できた内容だけ保存し、推測をそのまま保存しない。
4. Search Consoleは標準で接続確認する。01にプロパティが無ければ、登録済みサイトURLと閲覧可能なプロパティを照合して候補を確認する。接続できなくてもGA4分析は継続し、顧客向けレポートに接続事情の説明や空の章を出さない。
5. 出力先は `outputs/{client_id}/04_traffic/` とし、利用者には聞かない。出力形式は依頼文→01の既定→利用者への確認の順で決める。無人実行で未設定ならMDだけにする。
6. 完了時は最終成果物と `outputs/{client_id}/index.html` の絶対パスを簡潔に示し、`append_finding(..., agent="04_parameter_management")` で履歴を保存する。

## 現行の基本分析契約

BigQueryを実行する前に `docs/bigquery-cost-guardrails.md` に従う。5GiB超の見積もり・上限引き上げは、概算金額と上限を示して利用者の明示同意を得る。`--estimate-only` で事前確認し、同意なしで実行上限を変更しない。

- 全体の実行順は `docs/standard-run-order.md` を正本とする。先に作成した市場・顧客理解を利用し、この基本分析の中では「GA4・Search Consoleの事実取得 → 市場・顧客前提の読み合わせ → 解釈・レポート」の順で進む。Search Consoleは標準の確認対象とし、未登録時は閲覧可能なプロパティを登録済みサイトURLで照合する。候補なし・権限不足でもGA4分析は止めない。
- CV数は確認済み完了イベントの `eventCount`、基本分析のCVRはCVイベント数÷セッション数。
- 月次・週次はセッションを単独パネル、同じKPIのCV数（棒）とCVR（折れ線）を左右の独立軸で重ねて可視化する。チャネルは独立した棒グラフ、ランディングページはセル内バー付き表で比較する。時系列を取得できない場合もチャネルの棒グラフを残し、基本分析HTMLには最低1つの独立したグラフを入れる。全一覧表に合計または表示合計を置く。
- ランディングページはセッション上位とCV上位を分け、`(not set)` は表示・指摘しない。ページ別はPVのみ。
- リードサイトは完了イベント数÷フォームページPVのフォーム通過率。表に確認済みフォームURLを載せ、業種・目的に近い外部基準との差を定義の違いとともに考察する。フォームページ不明時は利用者に聞く。ECサイトは推奨eコマースイベントの取得有無を先に確認する。
- BigQueryがある場合だけ、CVしたセッションの実遷移を具体的なURLで示す。無ければ案内文も出さない。
- 計測監査は実行するが、指摘件数や「計測欠損の可能性」を基本分析レポートへ混ぜない。「流入パラメータの状態」「流入元の表記ゆれ」「計測対象のホスト名」は内部監査項目であり、独立した章・目次項目として追加しない。
- GA4値が不明なら `standards/ga4-analysis-interpretation.md`、可視化は `common/report_export/design_system/visualization-guidelines.md` を正本とする。
- Search Consoleの比較は、日付行が両期間の全日分あること、日数が等しく期間が重複しないことを確認してから使う。未返却日はゼロと判断できないため、条件を満たさない場合は取得処理が増減を「比較不可」と表示する。保持期間外を含む年次比較を強行しない。前期の上位一覧に無いクエリ・ページも0件や新規とは扱わない。
- Search Consoleの`--start-date` / `--end-date`指定時も、前期はその実日数と等しい直前期間とする（暦年の前年同期を保証しない）。`--output`指定時は取得行・取得日時・日付範囲の検査結果を`<出力ファイル名>.json`へ併記する。生データと同じ非公開フォルダに保存し、欠損・上限・期間を再検算する材料にする。

---

## 前提（初回のみ）

- 対応するAIコーディングエージェントが利用可能（AIなしの場合は取得・集計まで実行可能）
- Python 3.11+ と [uv](https://docs.astral.sh/uv/) がインストール済み
- 監査対象 GA4 プロパティに**サービスアカウント**のアクセス権を付与済み
- サービスアカウント鍵が `~/.saa/credentials/google-analytics/sa-key.json`（既定）に配置済み（準備手順は docs/setup-ga4.md）
  - 鍵を別の場所に置いている場合は、環境変数 `GA4_SA_KEY_PATH` にそのパスを設定すれば動きます。
- 基本分析では、GA4用の読み取り用サービスアカウントをSearch Consoleの対象プロパティへ制限付きユーザーとして追加し、Search Console APIを有効にする。既定ではGA4用の鍵を使い、組織の方針で分ける場合だけ `SC_SA_KEY_PATH` を指定する（準備手順は `docs/setup-search-console.md`）。未設定でもGA4分析は止めない
- （任意）BigQueryによるCVセッションのページ遷移を使う場合のみ、次の3点を確認する。未設定でもエラーにはならず、該当セクションを出さずにレポートを完成する。
  - GA4のBigQueryエクスポートが設定済みであること。**エクスポート先はサイト所有者側の別GCPプロジェクトになっていることが多く**、分析する側がサービスアカウントを置いているプロジェクトとは別になりがち。エクスポート先のプロジェクトIDはGA4管理画面のBigQueryリンク設定で確認できる
  - そのプロジェクトに対して、使うサービスアカウントに `roles/bigquery.dataViewer` と `roles/bigquery.jobUser` が付与されていること
  - エクスポートは有効にした時点以降のデータしか入らないので、過去にさかのぼって分析したい場合は、いつから有効になっているかを確認する
  - GA4用とBigQuery用でサービスアカウントを分けている場合は、環境変数 `BQ_SA_KEY_PATH` にBigQuery用の鍵のパスを設定する（未設定時はGA4用の鍵にフォールバックする。詳しくは docs/setup-ga4.md）

### 初回セットアップ

```bash
cd <リポジトリルート>/04_traffic_analysis/parameter_management
uv sync
```

---

## 使い方

AIエージェントでリポジトリルートを開き、「このサイトの基本分析をして」「GA4とSearch Consoleを分析して」などと自然文で依頼する。専用コマンドやプロンプトファイルの指定は不要。AIエージェントは `docs/ai-agent-guide.md` からこの文書へ到達し、必要に応じて `prompts/parameter-audit.md` を読む。

### 対話の流れ

エージェントが順に質問してくるので答えるだけ:

1. **クライアント名 / GA4プロパティID / キーイベント** を聞かれる → 答える（期間を指定しなければ、直近の完了した12か月の月初〜月末。比較期間は前年の同じ暦日範囲）
   - キーイベントは GA4管理画面 > 管理 > イベント > キーイベント で確認できる名前を指定
   - サイトURLが01に未登録なら、続けて**サイトのURL**を聞かれる → 答える（分からなければ「無し」でも進められる）。URLを答えると、エージェントがトップページを実際に読みに行き、サイトの役割・toB/toC・事業内容を根拠つきで推測して確認を求める（「はい」か訂正で1回答えるだけ）。この確認は任意で、既に01に登録済みなら聞かれない
2. エージェントが GA4 データを自動取得
   - `scripts/fetch_ga4_traffic.py`（utm別・パラメータ監査用）
   - `scripts/fetch_ga4_analytics.py`（基本分析の数値: 推移・チャネル・LP・ページ・デバイス・新規/リピーター）
   - `scripts/fetch_search_console.py`（自然検索のクリック・表示回数・CTR・掲載順位・クエリ・ページ。未登録時は`--match-site-url`で閲覧可能な候補を確認し、候補確定後に取得）
   - `scripts/fetch_ga4_analytics.py --hostnames`（ホスト名別セッション数。自己参照・想定外ドメインの棚卸し用。内訳合計と全体セッションの差を自動で注記する。旧版は汎用の `scripts/fetch_ga4.py` を素の絞り込みで叩いていたため、ホスト名別の合計が全体セッションと数千件単位でずれても出力に出なかった）
   - （クライアントの計測環境にBigQueryのGA4エクスポート設定があれば）`scripts/bq_cv_paths.py`（CVパス精度版）
3. エージェントが **観察結果** を提示
   - 全体セッション・前期比
   - 欠損流入の量
   - 観測された媒体識別子と表記ゆれの疑い
   - キーイベント発火が少ない/ゼロの媒体・チャネル
   - 計測対象になっているホスト名の一覧（自社/想定外の切り分け。自己参照があれば発生ページも）
   - ランディングページ別とページ別（PV）で顔ぶれが違うページ、CVの多い流入元とセッションの多い流入元のズレ
   - キーイベントごとに候補を確認し、対応するフォームページを利用者へ提示する
4. **フォームページ / 媒体・施策一覧 / 既存命名規則** を確認する。フォームページが分からなければ通過率を作らない
5. 03市場・顧客理解の成果物を読み込み、その文脈を使って基本分析を解釈する。計測監査の指摘件数や欠損可能性は基本分析レポートへ混ぜない
6. **Markdown レポート** が `<リポジトリルート>/outputs/{client_id}/04_traffic/basic-analysis-report.md` に保存される（`<リポジトリルート>` は `git rev-parse --show-toplevel` で求める。既存ファイルは `_past/` へ退避してから上書きする。docs/standard-run-order.md §4）。保存後に `tools/report_quality_check.py` を通し、HTML指定時は `report_export` で変換して、独立したグラフが最低1つあることと可視化指定コメントが残っていないことを確認する
   - 1ファイルの中に「文章サマリー」「数値表」「基本分析の詳細」が並ぶ構成
7. `outputs/{client_id}/index.html` を再生成する
8. サマリ + 基本分析ハイライト + 優先対応 Top3 が画面に表示される

詳細フロー例は [samples/interaction.example.md](./samples/interaction.example.md) を参照。

---

## 出力

```
<リポジトリルート>/outputs/{client_id}/04_traffic/basic-analysis-report.md
```

基本分析の結論と根拠をMarkdown 1ファイルにまとめ、HTML指定時は共通の `report_export` で変換する。UTM監査の作業記録は `outputs/{client_id}/04_traffic/_data/` に保存する。ファイル名と退避は `docs/standard-run-order.md` の出力規約に従う。
取得した生データ（utm別・基本分析データ・CVパス精度版など）は `outputs/{client_id}/_data/ga4/`（取得日プレフィックス付き）に保存する。
出力先はユーザーに尋ねない（明示指定があった場合のみ上書き）。完了時はこのファイル（変換した場合は変換後のファイル）のパスを**最終成果物**として明示する（docs/standard-run-order.md §4 規約4）。成果物は指定した形式（既定はMarkdown）でも受け取れる。詳細は `docs/standard-run-order.md` §4-2。
完了時に `python common/report_index/build_index.py "outputs/{client_id}"` で `index.html` を再生成する（規約3）。

**構成:**
1. ヘッダ（対象サイト／分析日／対象期間／比較期間／キーイベント）
2. 分析サマリー（主要指標の前期比＋今回確認できたこと3〜5点。監査指摘の一覧を混ぜず、結論の判断に影響するデータ制約だけを該当する数値に短く添える）
3. 📈 基本分析（月次・チャネル・ランディングページのセッション順/CV順・ページPV・デバイス・新規/リピーター・フォーム通過率またはEC購入プロセス。週次はクライアント向け本文へ出さない。BigQuery設定時のみCVセッションのページ遷移）

**キーイベントの表示名**: 01の `kpis.yaml` に業務名があれば、ヘッダとフォーム通過率の見出しに `名前（event_name）` で表示する。未登録イベントはイベント名へフォールバックする。

**複数CVは合算せず内訳を出す**: サマリー・推移・チャネル・ランディングページ・デバイス・新規/リピーターはKPIごとのCV数とCVRを表示し、フォーム通過率はイベントごとに作る。

**優先KPI**: `priority: 1` が一意なら各表の先頭へ★付きで置く。未設定なら全KPIを対等に扱う。基本分析のCV数は確認済み完了イベントの発生回数で統一する。

パラメータ監査（ホスト名棚卸し・utm設定・命名規則違反・欠損流入の4観点チェック）自体は従来どおり実施するが、媒体×項目マトリクスや重大度別の全指摘リストなど詳細な一覧はレポート本文には出力しない（上記2のサマリーへの反映のみ）。

**サイトセグメント別の内訳をサマリーに反映する（01の `site_segments`）**: 役割の違うセクションが全体値をどう動かしているかを判断できるよう、定義がある場合だけセッション・CV・CVRの内訳を出す。分母はサイト全体のまま変えず、CVは確認済み完了イベントの発生回数で集計する。分類外と合計を省かない。

**クエリパラメータの既定をパスのみにする**: ランディングページ・ページ・フォーム候補は既定でクエリ文字列を落とす。`preferences.include_query_params: true` のサイトだけクエリ込みにする。末尾スラッシュ違いは安全に同一と断定できないため自動統合しない。

Markdown ビューアやエディタで閲覧可能。

`outputs/` は `.gitignore` 済み（クライアントデータを含むため）。

---

## トラブルシューティング

| 状況 | 対応 |
|---|---|
| `FileNotFoundError: sa-key.json` | `~/.saa/credentials/google-analytics/sa-key.json`（既定）の配置を確認。鍵を別の場所に置いている場合は、環境変数 `GA4_SA_KEY_PATH` にそのパスを設定すれば動きます。 |
| `PermissionDenied: 403` | GA4 プロパティのアクセス権限にサービスアカウントを追加（閲覧者以上） |
| Search Consoleの対象サイトが候補に出ない | `docs/setup-search-console.md` に従い、GA4用サービスアカウントのメールアドレスと対象プロパティへ追加した制限付きユーザーが一致するか、Search Console APIが有効かを確認する。別の鍵を指定した場合は、その鍵のサービスアカウントを確認する |
| `uv: command not found` | `pip install uv` または `brew install uv` |
| `uv sync` が必要と言われた | 初回は `uv sync` を実行 |
| `(not set)` ばかり出る | プロパティID誤り or 期間に流入なし。GA4 管理画面で同条件の数値を照合 |
| 出力が冗長・的外れ | エージェントに「重大度 High の3件のみに絞って」等と追加指示 |
| フォームページ指定（`--funnel-events`）がWindowsパスに化ける | Git Bashではコマンド前に `MSYS_NO_PATHCONV=1` を付ける |
| `--output` の保存先が `C:\c\dev\...` のような見当違いの場所になる | `WORKDIR` を `$(pwd)` で取得すると `/c/dev/...` 形式のままになり、`MSYS_NO_PATHCONV=1` と組み合わせたときに誤変換される。`WORKDIR=$(pwd -W)` を使うこと（本ファイルのコマンド例は対応済み） |
| `--output` の保存先が `04_traffic_analysis/parameter_management/outputs/...` のようにネストした場所になる | セッション中に一度でも `parameter_management` 配下へ `cd` した後で `WORKDIR` を取得すると、そのときのカレントディレクトリを拾ってしまう。`WORKDIR=$(cd "$(git rev-parse --show-toplevel)" && pwd -W)`（`pwd -W` 単体ではなくリポジトリルートを経由して取得）を使うこと（本ファイルのコマンド例は対応済み） |
| BigQueryのページ遷移が省略される | 設定なし・権限不足・スキャン上限超過のいずれか。基本分析は止めず、本文にも案内用の節を作らない |
| CVパス精度版で `FileNotFoundError: BigQuery用のサービスアカウント鍵が見つかりません` | 環境変数 `BQ_SA_KEY_PATH` の指定先が間違っている。GA4用とBigQuery用でサービスアカウントを分けている場合に出るエラーで、GA4側の鍵（`GA4_SA_KEY_PATH`）とは別に案内される |
| CVパス精度版で `PermissionDenied: 403`（BigQuery） | 使っている鍵のサービスアカウントに、GA4のBigQueryエクスポート先プロジェクト（GA4管理画面のBigQueryリンク設定で確認できる。分析する側のプロジェクトとは別なことが多い）で `roles/bigquery.dataViewer` / `roles/bigquery.jobUser` が付与されているか確認する |

---

## 上級者向け: スクリプト単体実行

エージェントを介さず、データ取得スクリプトだけ単体で動かしたい場合:

```bash
# リポジトリルートの絶対パスを控える（出力をリポジトリルート基準にするため。
# pwd -W で Windows形式のパスを取得する。$(pwd) の /c/dev/... 形式のままだと
# MSYS_NO_PATHCONV=1 と組み合わせたときに誤った場所に書かれることがある）
WORKDIR=$(cd "$(git rev-parse --show-toplevel)" && pwd -W)
cd <リポジトリルート>/04_traffic_analysis/parameter_management

# utm別流入データ（期間省略時は直近の完了した12か月）
uv run python scripts/fetch_ga4_traffic.py \
  --property-id 123456789 --start-date 2025-09-01 --end-date 2026-08-31 \
  --output "$WORKDIR/outputs/sample-client/_data/ga4/20260714_traffic.md"

# 基本分析データ（フォームページ未確認なら --funnel-events を付けず、通過率を作らない）
uv run python scripts/fetch_ga4_analytics.py \
  --property-id 123456789 --start-date 2025-09-01 --end-date 2026-08-31 \
  --key-events "form_submit,file_download" \
  --output "$WORKDIR/outputs/sample-client/_data/ga4/20260714_analytics.md"

# --event-names-json は任意。01の kpis.yaml に業務名が登録されている場合、
# {event_name: KPI名} のJSONを渡すと、ヘッダとフォーム通過率の見出しがイベント名では
# なく業務名になる（省略時は従来どおりイベント名のみで表示され、エラーにはならない）。
# --key-events が2グループ以上に分かれる場合、サマリー・推移・チャネル別等はCVを
# 合算せずKPIごとの列・行に分けて表示する（1グループしか無ければ従来どおり合算1本）
uv run python scripts/fetch_ga4_analytics.py \
  --property-id 123456789 --start-date 2025-09-01 --end-date 2026-08-31 \
  --key-events "form_submit,file_download" \
  --event-names-json '{"form_submit": "お問い合わせ完了数", "file_download": "資料ダウンロード数"}' \
  --output "$WORKDIR/outputs/sample-client/_data/ga4/20260714_analytics.md"

# --primary-kpi-name も任意。01の kpis.yaml で priority:1 が一意に決まっている場合
# （ClientContext.primary_kpi）、その業務名を渡すと各表で先頭に並べ★印を付ける
# （各表でこのKPIを先頭表示する）。
# 省略時、または一致するKPIが無い場合は全KPIを対等に扱う（優先度は未設定のまま進む）
uv run python scripts/fetch_ga4_analytics.py \
  --property-id 123456789 --start-date 2025-09-01 --end-date 2026-08-31 \
  --key-events "form_submit,file_download" \
  --event-names-json '{"form_submit": "お問い合わせ完了数", "file_download": "資料ダウンロード数"}' \
  --primary-kpi-name "お問い合わせ完了数" \
  --output "$WORKDIR/outputs/sample-client/_data/ga4/20260714_analytics.md"

# サイトセグメント（そのセクションが何であるか、の定義）とクエリパラメータの既定を
# 反映する場合は、基本分析データ取得（上記）に以下の2つを追加する:
#   --site-segments-json '[{"segment_id": "seg_001", "name": "本体サイト", "default": true},
#     {"segment_id": "seg_002", "name": "オウンドメディア",
#     "match": {"path_prefix": "/media/"}}]'
#   （01の site-segments.yaml 由来。指定時も基本分析の分母はサイト全体のまま、
#   「0. 全体サマリ数値」にセグメント別のセッション・CV・CVRの内訳表を追加する。
#   どの match にも一致しないページは、default: true のセグメントがあればそこに、
#   無ければ「その他（分類外）」に入る。未指定・空リストならこの内訳自体を出さない）
#   --include-query-params
#   （ランディングページ別・ページ別・中間ページ候補でクエリ文字列を
#   含めるかどうか。既定は付けない＝パスのみで集計する。ECサイト・ブログのように
#   クエリ文字列そのものが別ページを表すサイトだけ明示的に付ける）

# フォームページ候補（キーイベントが発火したセッションでよく見られているページを
# セッション数の多い順に列挙。実際にサイトを読みに行って何のフォームかを判定してから、
# 下の --funnel-events で対にする）
uv run python scripts/fetch_ga4_analytics.py \
  --property-id 123456789 --start-date 2025-09-01 --end-date 2026-08-31 \
  --candidates-for "form_submit,file_download" --candidates-limit 10 \
  --output "$WORKDIR/outputs/sample-client/_data/ga4/20260714_funnel_candidates.md"

# フォーム通過率だけの追加取得（候補確認後。キーイベント1件=フォームページ1件を
# "event:page:match_type:status" の形式で ; 区切りで指定する。ページパスを引数に渡すため
# MSYS_NO_PATHCONV=1 を付ける。Git BashのMSYS2がパス変換を行うため）
MSYS_NO_PATHCONV=1 uv run python scripts/fetch_ga4_analytics.py \
  --property-id 123456789 --start-date 2025-09-01 --end-date 2026-08-31 \
  --key-events "form_submit,file_download" \
  --event-names-json '{"form_submit": "お問い合わせ完了数", "file_download": "資料ダウンロード数"}' \
  --primary-kpi-name "お問い合わせ完了数" \
  --funnel-events "form_submit:/contact/:contains:confirmed;file_download:/lp/whitepaper-download/:contains:confirmed" \
  --funnel-only \
  --output "$WORKDIR/outputs/sample-client/_data/ga4/20260714_funnel.md"

# CVパス精度版（BigQuery設定がある場合のみ。期間はGA4集計期間の当期と合わせる。
# GA4用とBigQuery用でサービスアカウントを分けている場合は、実行前に
# BQ_SA_KEY_PATH=/path/to/bq-sa-key.json を設定する（未設定ならGA4用の鍵にフォールバック）
uv run python scripts/bq_cv_paths.py \
  --project-id my-gcp-project --dataset analytics_123456789 \
  --start-date 2025-07-15 --end-date 2026-07-14 \
  --key-events "form_submit,file_download" \
  --output "$WORKDIR/outputs/sample-client/_data/ga4/20260714_cv_paths_bq.md"
```

### テスト

```bash
cd <リポジトリルート>/04_traffic_analysis/parameter_management
uv run python -m unittest discover -s tests
```

---

## Phase 2 で予定している拡張

- GTM API からタグ・トリガ情報自動取得
- 媒体管理画面側の utm 設定取得（Google広告 / Meta広告 等）
- Notion DB への自動書き込み
