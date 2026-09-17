# 運用手順書

**計測設計 CLI** の利用手順。初めて使う場合は上から順に読む。

---

## 前提条件

| 項目 | 確認方法 |
|------|---------|
| Python 3.11 以上 | `python --version` |
| uv インストール済み | `uv --version`（なければ `pip install uv`） |
| LLM バックエンド | 既定 `none`（外部LLMなし）。任意の `anthropic_api` 利用時のみ `.env` に `ANTHROPIC_API_KEY` を設定 |
| Google 認証（サービスアカウント）準備済み | 後述 |
| GA4/GTM の各種ID | 実行時に解決（フラグ→`inputs/*.local.yaml`→01コンテキスト）。一度指定すれば保存・再利用。不明ならサイトのGA4/GTM管理者に確認 |

---

## ステップ 0: セットアップ（初回のみ）

### 依存ライブラリのインストール

```bash
# リポジトリ直下から
cd 02_basic_measurement/measurement_design
uv sync
```

### Anthropic API キーの設定（任意の `--llm-backend anthropic_api` を使う場合のみ）

```bash
cp .env.example .env
# .env を開いて ANTHROPIC_API_KEY=sk-ant-... を記入
```

### Google 認証の設定

サービスアカウントキーファイルを以下のパスに配置する:

```
~/.saa/credentials/google-analytics/sa-key.json（既定。準備手順・なぜサービスアカウントが必要かは docs/setup-ga4.md）
```

鍵を別の場所に置いている場合は、環境変数 `GA4_SA_KEY_PATH` にそのパスを設定すれば動きます。

---

## ステップ 1: クライアントフォルダの準備

### フォルダ構成

```
{クライアント名}/
└── inputs/
    ├── kpis.yaml           ← 必須。KPI を定義する
    ├── screen-flow.yaml    ← 必須。ページ・導線を定義する
    ├── ga4.local.yaml      ← 任意。property_id と認証方式
    └── gtm.local.yaml      ← 任意。GTM account/container ID
```

`sample-client/inputs/` にサンプルがあるので、コピーして編集する:

```bash
mkdir -p my-client/inputs
cp sample-client/inputs/*.yaml my-client/inputs/
```

---

## ステップ 2: inputs/ ファイルの書き方

### kpis.yaml — KPI 定義

このファイルで「何を計測目標とするか」を定義する。

```yaml
kpis:
  - kpi_id: kpi_001                        # 一意のID（英数字・アンダースコア）
    name: 資料ダウンロード数                   # KPI の名称
    target_metric: イベント数
    target_value:
      goal: 200
      unit: 件/月
    description: コーポレートサイト経由の資料ダウンロード完了
    related_pages:
      - page_id: page_download             # screen-flow.yaml の page_id と対応させる

  - kpi_id: kpi_002
    name: お問い合わせ完了数
    target_metric: イベント数
    target_value:
      goal: 50
      unit: 件/月
    description: お問い合わせフォームの送信完了
    related_pages:
      - page_id: page_contact_complete
```

**ポイント:**
- `kpi_id` はユニークであれば自由に設定してよい
- `related_pages` の `page_id` は、必ず `screen-flow.yaml` に存在する `page_id` を指定する

---

### screen-flow.yaml — ページ・画面導線定義

このファイルで「どのページがあり、ユーザーはどう動くか」を定義する。

```yaml
pages:
  - page_id: page_top                      # 一意のID
    name: トップページ
    screen_type: top                       # top / form / thanks / detail / list など
    url_pattern: "^/$"                     # 正規表現でURLパターンを指定

  - page_id: page_download
    name: 資料ダウンロードページ
    screen_type: form
    url_pattern: "^/download"

  - page_id: page_contact
    name: お問い合わせページ
    screen_type: form
    url_pattern: "^/contact$"

  - page_id: page_contact_complete
    name: お問い合わせ完了ページ
    screen_type: thanks
    url_pattern: "^/contact/complete"

flows:
  - flow_id: flow_download                 # 一意のID
    name: 資料ダウンロード導線
    related_kpi: kpi_001                   # kpis.yaml の kpi_id と対応させる
    steps:
      - page_id: page_top
      - page_id: page_download

  - flow_id: flow_contact
    name: お問い合わせ導線
    related_kpi: kpi_002
    steps:
      - page_id: page_top
      - page_id: page_contact
      - page_id: page_contact_complete
```

**ポイント:**
- `flows` の `related_kpi` は `kpis.yaml` の `kpi_id` と一致させる
- `steps` のページは `pages` に存在する `page_id` を指定する

---

### ga4.local.yaml — GA4 設定（任意）

`fetch` コマンドでプロパティIDをコマンドライン引数で渡す場合は不要。

```yaml
ga4:
  property_id: "123456789"    # GA4 プロパティID（管理画面の「プロパティの詳細」で確認）
  auth_method: sa             # sa 固定（利用者向けにはSA認証のみ案内）
```

---

### gtm.local.yaml — GTM 設定（任意）

GTM のデータも取得したい場合に作成する。

```yaml
gtm:
  gtm_account_id: "123456"        # GTM アカウントID
  gtm_container_id: "GTM-XXXXXXX" # 公開IDでも数値containerIdでも可。公開IDはAPI実行時に自動解決
```

---

## ステップ 3: 入力ファイルの検証

```bash
uv run python run.py validate --client {クライアント名}
```

正常時の出力:

```
✓ kpis.yaml: 2 件
✓ screen-flow.yaml: pages=4, flows=2

✓ 検証完了。問題ありません。
```

エラーが出た場合は、メッセージに従って YAML ファイルを修正する。

---

## ステップ 4: データ取得

### GA4 のみ（GTM なし）

```bash
uv run python run.py fetch \
  --client {クライアント名} \
  --property-id {GA4プロパティID} \
  --auth sa
```

### GA4 + GTM

```bash
uv run python run.py fetch \
  --client {クライアント名} \
  --property-id {GA4プロパティID} \
  --auth sa \
  --gtm-account {GTMアカウントID} \
  --gtm-container {GTMコンテナID}
```

**出力ファイル:**

| ファイル | 内容 |
|---------|------|
| `{client}/_data/phase1.json` | GA4 Admin API データ（プロパティ設定・イベント定義） |
| `{client}/_data/phase2.json` | GA4 Data API データ（直近30日のイベント実績） |
| `{client}/_data/phase3.json` | GTM API データ ※GTM 指定時のみ |

---

## ステップ 5: チェックレポート生成

```bash
uv run python run.py review --client {クライアント名}

# LLM なし（機械検出のみ。API コストをかけずに確認したい場合）
uv run python run.py review --client {クライアント名} --no-llm
```

**出力:** `{クライアント名}/docs/check-report.md`（**クライアントが見る唯一のレポート**）

チェックレポートには以下が含まれる:
- ユーザーが判断に使う設定確認表。自動判定できる項目はカテゴリ／確認項目／判定／結果／対応事項の5列とし、APIで取得できない設定は個別の△行にせず「管理画面でまとめて目視確認」へ集約する。
- 受信イベント一覧は載せない。自動収集は通常取得され、拡張計測は設定と操作、推奨イベントはサイト要件に依存するため、一覧だけでは改善判断につながらない。主要イベントの欠落、異常比率、日本語イベント名、二重送信など具体的な異常だけを「要対応・要確認」に出す。
- 取得データから具体的に確認できた異常・要確認と改善順。大文字・ハイフンだけの命名差はLowの参考、日本語イベント名はデータ連携上の要対応として扱う。
- `standards/audit-items.md` の機械37項目・目視19項目は内部監査として全件実行・保持するが、正常・適用外を含む全56行は本文へ転記しない。

配布前にリポジトリルートで `python tools/validate_measurement_report.py outputs/{クライアント名}/02_measurement/docs/check-report.md` を実行する。内部監査の正本と公開設定確認表を別々に検査し、判定を元データと突合する。フォーム通過率・業界平均・問い合わせ減少の分析は計測チェックに含めない。

**`check-report.md` は `review` を実行するたびに毎回まっさらに再生成される。**
計測チェックはこの1回では終わらず、指摘をクライアントに確認し、
回答を書き込み、対応済みを消し込むという往復が発生するが、**このファイルに
直接書き足しても、次に `review` を実行した時点で消える。**

指摘への確認・対応は、初回の `review` 実行時に自動で作られる
`{クライアント名}/docs/check-report-notes.md` に書く。このファイルは
「無ければ作る。あれば絶対に上書きしない」ので、書き足しは何度 `review` を
実行しても消えない。書き方の目安（テンプレートにも同じ内容がある）:

```markdown
## V-P-a1c4e7 パラメータ命名規則違反 `utm_Source`
- 確認日: YYYY-MM-DD
- 状態: 対応済み / 未対応 / 保留
- メモ: クライアントへ確認した内容・回答をここに書く
```

指摘ID（`V-a1c4e7` 等）は指摘の内容（種別・対象など）から決まる固定の符号なので、
データを取り直して `review` を再実行しても、同じ指摘には同じIDが振られる
（対象名が変わった、または指摘そのものが解消された場合は当然IDも変わる・消える）。
読み返すときに探しやすいよう、対象名も一緒に書いておくとよい。

---

## ステップ 5.5: 確定所見を書く（任意・推奨）

計測設計書の生成器は `_data/` の実測データしか見ないため、調査で判明した「原因まで
特定できた事実」を知らない。そのため、似た名前のイベント（`signup` と `sign_up` 等）
を取り違えたり、人が出した結論と逆の推奨を書くことがある。

これを防ぐため、`{クライアント名}/docs/findings.md` に確定済みの事実を書いておくと、
`design`（ステップ6）実行時に読み込まれ、**生成プロンプトの最優先制約**として渡される
（他の情報と矛盾する場合はこの内容が優先される）。

```
{クライアント名}/docs/findings.md
```

```markdown
- signup と sign_up は別イベント。signup が正、sign_up は旧実装の残骸で無視してよい
- お問い合わせ完了の発火は `/contact/complete` 到達時点のみ。フォーム送信ボタンのクリックとは別
```

**書き方のポイント:**

- 「まだ確認中」「たぶんこう」ではなく、**確認が取れた事実だけ**を書く（未確定の推測を書くと、それが最優先の制約として設計書に混入する）
- 箇条書きで短く。1件1行が目安
- ファイルが無い場合は単に「確定所見なし」として扱われ、`design` は根拠データだけから判断する（エラーにはならない）
- `docs/check-report.md` の `## 0.` 節に直接書く運用でも代用できるが、専用ファイルの `findings.md` を優先して探す

---

## ステップ 6: 計測設計書生成

事前に `validate` と `fetch` を完了させることを推奨。既定では外部LLMを呼ばず、任意の `anthropic_api` 利用時のみ `ANTHROPIC_API_KEY` が必要。

```bash
uv run python run.py design --client {クライアント名}
```

**出力:** `{クライアント名}/docs/design-doc/` 以下に最大16章の Markdown ファイル

生成される章は案件特性に応じて自動選定される（詳細は `system-overview.md` 参照）。

### 既定（`--llm-backend none`）のとき: 章はAIエージェント自身が書く

**`design` は「AIエージェントが書いてください」という案内を出すだけで、章ファイルは作らない。**
外部LLMを呼ばない設計（既定）では、文章生成の役割がリポジトリを開いているAIエージェント側に
移っている。**書かずに `doc` を実行しても「章ファイルが見つかりません」で止まる**ため、
このAIエージェント自身が次の手順で章ファイルを書く。

**いつ書くか:** `review`（ステップ5）が終わり、任意で `findings.md`（ステップ5.5）を書いた後。

**何を材料にするか:**

| 材料 | 場所 | 使い方 |
|------|------|--------|
| 章テンプレート | `templates/design-doc/{番号}-{章名}.template.md`（16章） | `{{...}}` プレースホルダを埋める。先頭の `# 章 NN: ...` 見出しはそのまま残す |
| 取得済み実測データ | `{クライアント名}/_data/`（`fetch` の出力） | プロパティ設定・イベント実績・GTM設定など、章の記述内容の根拠にする |
| チェックレポート | `{クライアント名}/docs/check-report.md` | 命名規則違反・設定上の問題点を、該当する章の記述に反映する |
| KPI・画面導線 | `inputs/kpis.yaml`・`inputs/screen-flow.yaml` | CV・MCVや導線に関する章（04章など）の元データ |
| 確定所見（あれば） | `{クライアント名}/docs/findings.md` | 他の材料と矛盾する場合、この内容を最優先で採用する |

上記以外に、**クローンの外にあるファイル**（クライアントから受け取った資料・議事録など）を
章の記述に使った場合は、`01-cover.md` の「クローンの外にあるファイル」節にファイルのパス・
読んだ日・そこから採った内容を書く（`docs/standard-run-order.md` §4 規約5。読むこと自体は
妨げないが黙って使わない）。識別子は振らない。使っていなければこの節ごと書かない。
`kpis.yaml`・`screen-flow.yaml`・`findings.md`・`_data/`・`check-report.md` は上表のとおり
クローン内の定型入力なので対象外。

**どこに書くか:** `{クライアント名}/docs/design-doc/` に、テンプレートと同じファイル名で
`.template.md` を `.md` に変えて保存する（例: `templates/design-doc/01-cover.template.md`
→ `{クライアント名}/docs/design-doc/01-cover.md`）。この命名規則からずれると `doc` が
その章を拾えない（`build_design_doc_html.py` はファイル名先頭2桁の数字で章番号を判定する）。

**どの章を書くか:** 案件特性に応じて選ぶ（全16章を毎回書く必要はない）。目安は
`src/measurement_design/design/selector.py` の選定ルール（01〜03は常に含む、KPIがあれば04、
イベントがあれば06、カスタム定義があれば07、ECイベントがあれば08、11〜13は常に含む）。
05・09・10・14〜16は案件の実態に応じて要否を判断する。

**書いた後どうするか:**

```bash
uv run python run.py doc --client {クライアント名}
```

で `design-doc.html`（1枚の自己完結HTML）にまとめる。章を追加・修正したら `doc` を
再実行すれば反映される（`doc` は既存の章ファイルを毎回読み直す。上書きが必要な操作は無い）。

---

## ステップ 7: スライドレポート化する場合

計測チェックをスライドにする場合も、公開本文は設定確認表・具体的な異常・改善順に絞る。受信イベント一覧は設けない。機械37項目・目視19項目は内部監査として保持し、公開スライドへ全件一覧を戻さない。計測設計書も作る場合は別の目的の成果物として扱う。

### 推奨構成

| 章 | 内容 | 注意点 |
|---|---|---|
| 01 | 目的・確認対象 | GA4・GTM・対象ドメイン・対象期間を明記 |
| 02 | 全体サマリー | 何ができていて、何が分析上の制約かを分ける |
| 03 | 設定確認表 | 自動判定できる設定を5列で示し、APIで取れない設定は別の目視確認ブロックへまとめる |
| 04 | 要対応・改善順 | イベントを含む具体的な異常・要確認だけを集約し、対応優先度を明示 |

### ページ単位の書き方

- タイトル冒頭に `[論点]` を付ける。例: `[チャネルグループ] Unassignedの中身を特定する`
- タイトルは事象だけで終わらせず、問題または望ましい状態まで書く
- リード文は、読み手が「だから何をすればよいか」を理解できる文章にする
- 修正や確認が必要なページだけ、本文下部に `! 修正推奨`、`? 要確認` の注記を置く
- 表と注記は離しすぎない。表の右余白や直下など、読む順番が自然な位置に置く
- 専門用語は無理に置き換えず、必要なら括弧で補足する。例: `Unassigned（GA4が分類できなかった流入）`

### 監査で必ず見る項目

- クロスドメイン設定: メインサイトと予約・申込ドメインでセッションが分断されていないか
- 参照元・メディア: `(direct) / (none)`、`Unassigned`、QR、広告媒体の分類
- UTMルール: `source`、`medium`、`campaign` の実運用と推奨値
- 独自イベント: イベント名だけでなく、同時に送信されるイベントパラメータ
- UI計測: CTAクリック、スクロール、フォーム開始・完了、店舗・プラン選択
- 非ECサイトのEコマース利用: 使う必要があるか、使うなら何を商品・アイテムに見立てるか

サンプル: [`../../samples/ga4-measurement-audit-slide-report.example.md`](../../samples/ga4-measurement-audit-slide-report.example.md)

---

## 一括実行（fetch + review + design）

ステップ 4〜6 をまとめて実行したい場合:

```bash
uv run python run.py run \
  --client {クライアント名} \
  --property-id {GA4プロパティID} \
  --auth sa
```

GTM あり・LLM なし review の場合:

```bash
uv run python run.py run \
  --client {クライアント名} \
  --property-id {GA4プロパティID} \
  --auth sa \
  --gtm-account {GTMアカウントID} \
  --gtm-container {GTMコンテナID} \
  --no-llm
```

---

## 認証方式

サービスアカウント認証のみ対応（`--auth sa`。既定でもこの値になる）。認証ファイルは `~/.saa/credentials/google-analytics/sa-key.json`。準備手順・なぜサービスアカウントが必要かは docs/setup-ga4.md を参照。

サービスアカウント鍵を別の場所に置いている場合は、環境変数 `GA4_SA_KEY_PATH` にそのパスを設定すれば動きます。

---

## エラー対処

| エラーメッセージ | 原因 | 対処 |
|---------------|------|------|
| `ANTHROPIC_API_KEY が設定されていません` | `--llm-backend anthropic_api` 指定かつ `.env` 未設定 | `.env` にキーを記入するか、既定の `none` を使う |
| `FileNotFoundError: Service account key not found` | SA キー未配置 | `~/.saa/credentials/google-analytics/sa-key.json` を配置（docs/setup-ga4.md）。別の場所に置いている場合は環境変数 `GA4_SA_KEY_PATH` にそのパスを設定 |
| `kpis.yaml が見つかりません` | inputs/ 未準備 | `validate` コマンドで確認。sample-client/inputs/ をコピー |
| `screen-flow.yaml が見つかりません` | inputs/ 未準備 | 同上 |
| `403 PERMISSION_DENIED` | GA4 権限不足 | GA4 プロパティに「閲覧者」権限を付与 |
| `phase1.json が見つかりません` | fetch 未実行 | `fetch` コマンドを先に実行する |
| `design-doc の章ファイルが見つかりません`（`doc` 実行時） | 既定（`--llm-backend none`）では `design` が章ファイルを作らないため | AIエージェントが `docs/design-doc/` に章ファイルを書く（本ステップ「既定のとき: 章はAIエージェント自身が書く」参照）。`design` を再実行しても解決しない |

---

## テスト実行

```bash
uv run pytest tests/ -v --cov=src --cov-report=term-missing
```
