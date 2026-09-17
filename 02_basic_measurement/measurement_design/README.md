# 計測設計 CLI

GA4/GTM の現状データから **計測チェックレポート** を生成し、KPI・画面導線情報をもとに **計測設計書（最大16章）** も作成する Python CLI ツール。機械監査は外部AIなしで実行できる。

---

## このツールでできること

| 機能 | 説明 |
|------|------|
| **validate** | inputs/ フォルダの YAML ファイルを検証する |
| **fetch** | GA4 Admin API・Data API・GTM API からデータを取得する |
| **review** | 命名規則違反・設計上の問題をチェックレポートとして出力する |
| **design** | KPI・画面導線・GA4 実態をもとに計測設計書（Markdown）を生成する |
| **run** | fetch → review → design を一括実行する |

---

## レポート化するときの運用メモ

**計測チェックレポートは `docs/check-report.md` 1本で独立して読めるようにする。**
機械37項目・目視19項目は内部監査として全件実行するが、本文へ56行をそのまま転記しない。
本文は自動判定の5列表、APIで取得できない設定をまとめた目視確認ブロック、要対応・要確認となった具体的な異常、改善順に絞る。受信イベント一覧は掲載しない。
内部監査の網羅性とクライアント本文の最小公開契約は別々に検証する。計測チェックではGA4・GTMの
計測の正確性を扱い、フォーム通過率・業界平均・問い合わせ減少の分析は含めない。

実務上の見せ方は以下を標準にする。

- 見出しは `[チャネルグループ] ...`、`[イベント計測] ...` のように、論点が一目でわかるラベルを先頭につける
- タイトルとリード文は「So what?」が残らないように、問題・望ましい状態・判断を明示する
- 修正が必要な箇所には `! 修正推奨`、`? 要確認` の目立つ注記を置く
- 直訳調・意味が取りにくい表現は禁止し、`GA4/GTM管理画面で実際の設定を確認する` のように書く
- **日本語はAIっぽい・スノッブな言い回しを避け、平易な業務文書調にする**（読み手が意味を取りづらくなるため）。手元にトーンチェック用のリンタがあれば仕上げ前にかけるとよい（無ければこの確認はスキップしてよい）。主役/牽引/突出/資産/土台/「に効く」/可視化の連発/抽象メタファーは使わない
- 大文字・ハイフンだけの表記差は Low の参考情報とし、既存イベント名の修正を必須にしない。新しく作るイベントは命名を揃える
- 日本語のイベント名は、GA4で受信できるかどうかとは別に、外部データ連携でエラーになる可能性を明記して修正対象とする
- **`scroll` / `page_view` / `session_start` / `click` / `share` / `video_*` / `file_download` 等は GA4 の自動収集・拡張計測・推奨イベントであり、予約語衝突ではない。違反扱いしない**（`review` の機械検出はこれらを除外済み。詳細は [`standards/reserved-words.md`](./standards/reserved-words.md)）
- 非ECサイトでEコマースイベントを扱う場合は、必要性を先に判断し、使う場合だけ `view_item=店舗詳細閲覧`、`select_item=店舗・プラン選択` のように対応表を示す
- UI計測は、CTAクリック、スクロール、フォーム開始・完了、店舗・プラン選択など、分析に使うイベントパラメータまで確認する
- GA4のみで取得した場合、GTM・UTM・クロスドメイン・ページ計測検証は「追加取得」として明示する
- Google シグナルは状態を示すが、無効であることだけを一律の不備にしない。利用目的・同意管理・プライバシー方針を踏まえて判断する
- 不要な参照元の除外は外部サービスから戻った流入の扱い、クロスドメイン計測はドメイン間で利用者・セッションを継続する設定であり、同じ項目としてまとめない
- Search Console連携はGA4 Admin APIから自動判定せず、GA4管理画面で手動確認する。Search Console APIを読めることをリンク済みの根拠にしない
- GTMタグの本数だけを根拠に一本化を勧めない。同じイベント名と発火条件が重なる場合に重複リスクを示し、イベント名が変数なら静的に特定できないことを前提として書く
- ○・△・×の件数だけを独立したグラフにしない。計測チェックでは件数よりも、各項目の判定・状態・確認根拠を一覧表で読めることを優先する

関連するサンプルは [`samples/ga4-measurement-audit-slide-report.example.md`](./samples/ga4-measurement-audit-slide-report.example.md)（構成アウトライン）を参照。

---

## ディレクトリ構成

```
measurement_design/              ← このディレクトリで実行する
├── run.py                        ← CLI エントリーポイント（ここを実行する）
├── pyproject.toml                ← 依存ライブラリ管理（uv）
├── .env                          ← ANTHROPIC_API_KEY を記載（任意の `--llm-backend anthropic_api` 利用時のみ）
├── .env.example                  ← .env のテンプレート
│
├── scripts/                      ← GA4/GTM データ取得スクリプト
│   ├── config.py                 ← AuditConfig（クライアント別パス）
│   ├── auth.py                   ← Google 認証（SA。内部にADC/OAuth分岐も残すが利用者へは案内しない）
│   ├── ga4_admin.py              ← GA4 Admin API（プロパティ・イベント設定）
│   ├── ga4_data.py               ← GA4 Data API（実績データ）
│   ├── gtm.py                    ← GTM API v2（タグ・トリガー・変数）
│   ├── gtm_export.py             ← GTMコンテナ エクスポートJSON の解析（API取得できない案件用）
│   ├── gtm_public.py             ← 公開 gtag.js からのGTM構成の推測（GTM閲覧権限が無い案件用）
│   ├── run_phase.py              ← Phase 別実行ロジック
│   ├── dataset.py                ← `_data/` を観点別ファイルへ読み書き（旧phase*.jsonへの互換あり）
│   ├── pii.py                    ← 取得データの個人情報らしい値を伏せる
│   ├── list_properties.py        ← アカウント配下のGA4プロパティ一覧化（複数プロパティ案件の見取り図）
│   ├── har_ga4.py                ← ブラウザのHARから実際に送信されたGA4イベントを確認
│   ├── landing_funnel.py         ← ランディングページ別のCTR/CVRファネル集計
│   ├── summarize.py              ← 取得データの人間可読サマリー生成
│   ├── questions.py              ← 確認事項の骨組み生成
│   ├── verify_numbers.py         ← 成果物中の数値を実データと突合
│   └── build_design_doc_html.py  ← 計測設計書（章01〜16）を1枚のHTMLにまとめる
│
├── src/measurement_design/       ← AI 設計生成モジュール
│   ├── loader.py                 ← inputs/ YAML 読み込み
│   ├── review/
│   │   ├── normalizer.py         ← phase JSON → 統一スキーマ変換
│   │   ├── diagnoser.py          ← 機械検出 + 実測ベースの健全性検出 + LLM による違反検出
│   │   ├── health_checks.py      ← 実測値の形から不備を逆算する検出（session_start比など）
│   │   ├── audit_matrix.py       ← 計測領域ごとの監査項目と判定（ok/warn/ng）
│   │   ├── kpi_coverage.py       ← KPIと計測イベントの対応判定
│   │   └── renderer.py           ← check-report.md 生成
│   └── design/
│       ├── decomposer.py         ← KPI → 必要 GA4 イベント分解（Sonnet）
│       ├── standardizer.py       ← イベント命名標準化（Sonnet）
│       ├── selector.py           ← 含める章の選定（ルールベース）
│       └── generator.py          ← 章ごとの Markdown 生成（Sonnet / Haiku）
│
├── templates/                    ← 設計書テンプレート（16章 + チェックレポート）
│   ├── check-report.template.md
│   └── design-doc/
│       ├── 01-cover.template.md
│       └── ... (02〜16)
│
├── standards/                    ← 命名規則・予約語リスト
│   ├── naming-conventions.md
│   └── reserved-words.md
│
├── sample-client/                ← サンプルクライアント（動作確認用）
│   └── inputs/
│       ├── kpis.yaml
│       ├── screen-flow.yaml
│       ├── ga4.local.yaml
│       └── gtm.local.yaml
│
├── docs/guide/                   ← 運用ドキュメント
│   ├── work-procedure.md         ← 利用手順（詳細）
│   ├── system-overview.md        ← システム概要・データフロー
│   └── output-mapping.md         ← 出力ファイル一覧
│
└── tests/                        ← ユニットテスト（pytest）
    ├── fixtures/                 ← テスト用サンプルデータ
    └── unit/
        └── test_*.py
```

実行時に自動作成されるフォルダ（`scripts/config.py` の `resolve_client_paths` が解決する。inputs/ と成果物で置き場所が異なる点に注意）:

```
{クライアント名}/inputs/                              ← 事前に手動で準備する（kpis.yaml, screen-flow.yaml）。
                                                        `sample-client/` は動作確認用の共通サンプルのためリポジトリ管理対象。
                                                        実クライアントの入力は、実際の目標値・KPIなど各社固有の情報を含むため
                                                        git管理外とし、各自の環境で個別に管理する（.gitignore 参照）

<repo_root>/outputs/{クライアント名}/02_measurement/   ← 成果物（git管理外。docs/standard-run-order.md §4）
├── _data/           ← fetch で取得した GA4/GTM データ（JSON。phase1/2/3.json と
│                       観点別ファイル 01-property.json 等の両方を持つ）
├── docs/            ← 生成された成果物（Markdown・HTML）
│   ├── check-report.md         ← クライアントが見る唯一のレポート。review で毎回
│   │                             再生成される（上書き前提。設定確認表＋具体的な異常＋
│   │                             要対応・要確認となった異常＋改善順）
│   ├── check-report-notes.md   ← 指摘への確認・対応を書く場所。review を再実行しても
│   │                             上書きされない（無ければ作る。あれば絶対に触らない）
│   ├── questions.draft.md       ← questions で毎回まっさらに再生成される骨組み
│   ├── questions.md             ← 「なぜ確認が必要か」を書く場所。questions を再実行
│   │                               しても上書きされない（無ければ作る。あれば絶対に触らない）
│   ├── design-doc.html
│   └── design-doc/
│       ├── 01-cover.md
│       └── ...
└── report/          ← 納品用に人が手で仕上げた原稿の置き場所（verify の突合対象）。
                        docs/ ではなく output_dir 直下。review 等は自動作成しないため、
                        実際に何か置くまで存在しない
```

---

## 自然文で計測チェックを依頼されたときの受付

ユーザーから「GA4・GTMが正しく計測できているか確認して」「計測設計書を作って」などと依頼されたら、現在のAIエージェントが次を行ってから、このREADMEの実行手順へ進む。質問の必須・任意の区別とまとめ方は `docs/standard-run-order.md` §2-1を優先する。

1. 依頼文の client_id、または `list_clients()` の一覧から対象を確定し、`load_context(client_id)` を読む。未登録なら `docs/standard-run-order.md` §2-1 のURL先行受付を使う。最初に対象サイトURLを確認し、サイト表示名と client_id はURL・サイト・GA4情報から候補を作る。候補が曖昧・矛盾・重複する場合だけ利用者へ確認し、`ensure_client_registered()` と `save_business_profile(site_url=...)` で最小登録する。フル登録には進まない。
2. GA4プロパティIDを「依頼時の指定→`inputs/ga4.local.yaml`→01コンテキスト」の順で解決する。候補を自動取得できても、利用者の確認なしに確定しない。確認できたIDは `save_measurement_ids()` で保存する。
3. GTMも点検するときだけ、GTMアカウントID・コンテナIDを確認して保存する。GTMを点検しない依頼では聞かない。
4. CVは `inputs/kpis.yaml` または01の登録値を使う。無ければ「サイト上で成果とみなす完了地点（予約完了・購入完了・問い合わせ完了等）は何か」を一度だけ確認する。GA4イベント名まで分かればあわせて保存し、不明なら受信イベント名・GTMタグから候補を示して利用者の確認後に `save_kpi_info()` で保存する。候補を自動確定せず、分からないという回答でも計測チェック自体は止めない。
5. GA4の閲覧権限と、GTM点検時はGTMの閲覧権限を確認する。外部LLMは利用者が明示指定しない限り使わない。
6. 出力先は `outputs/{client_id}/02_measurement/` とし、利用者には聞かない。出力形式は依頼文→01の既定→利用者への確認の順で決める。今回だけの指定は保存せず、`review` / `run` に `--output-formats html pdf` 等を渡す。MDのみは `--output-formats md`。指定なしは引数を省略し、確認できた既定だけ保存する。無人実行で未設定ならMDだけにする。
7. 完了時はcheck-reportと必要に応じてdesign-docの絶対パスを示し、`append_finding(..., agent="02_measurement_design")` で履歴を保存する。`check-report.md`への追記は再生成で消えるため、利用者確認や対応状況は`docs/check-report-notes.md`へ記録する。

## 前提条件

### 必要なもの

| 項目 | 内容 |
|------|------|
| Python | 3.11 以上。未導入ならuvが実行時に用意する |
| uv | 分析用プログラムを動かすツール。導入は[ルートREADMEの「必要なツールをインストールする」](../../README.md#install-tools)を参照 |
| AI | **既定は外部LLMを呼ばない**。分析・考察は現在利用中のAIエージェントが行う。任意バックエンド利用時のみ追加設定が必要 |
| Google 認証 | サービスアカウントキー（後述） |
| GA4/GTM の各種ID | **ハードコードせず実行時に解決**。フラグ → `inputs/*.local.yaml` → 01コンテキストの順。一度指定すれば保存され次回以降は省略可（不明な場合はサイトのGA4/GTM管理者に確認） |

### Google 権限

| 対象 | 必要な権限 |
|------|-----------|
| GA4 プロパティ | 閲覧者以上 |
| GTM コンテナ | 閲覧者以上（GTM 使用時のみ） |

---

## セットアップ

### 1. 依存ライブラリのインストール

```bash
# リポジトリ直下から
cd 02_basic_measurement/measurement_design
uv sync
```

### 2. LLM バックエンド（任意）

Python CLIは外部LLMを呼ばないのが既定。必要な場合だけ `--llm-backend` で切り替える:

| backend | 説明 | APIキー |
|---|---|---|
| `none`（**既定**） | 外部LLMを呼ばず機械診断を行う | **不要** |
| `claude_cli` | 明示指定時だけ `claude -p` を使う | 不要（Claude Code契約が必要） |
| `anthropic_api` | Anthropic SDK を使う | 必要（下記） |

`anthropic_api` を使う場合のみ APIキーを設定:

```bash
cp .env.example .env
# .env を開いて ANTHROPIC_API_KEY=sk-ant-... を記入
```

### 3. Google 認証の準備

サービスアカウントキーを以下のパスに配置する（ホームフォルダ配下。準備手順・なぜサービスアカウントが必要かは docs/setup-ga4.md）:

```
~/.saa/credentials/google-analytics/sa-key.json
```

鍵を別の場所に置いている場合は、環境変数 `GA4_SA_KEY_PATH` にそのパスを設定すれば動きます。

---

## クイックスタート

ここはコマンドを自分で実行する人向けの手順。AIに任せる場合は、[ルートREADMEの導入手順](../../README.md#導入手順)に沿って依頼すればよい。

### 1. sample-client でファイル構成だけ確認する（GA4に接続しない）

PowerShell／ターミナルで、このリポジトリの一番上（`README.md`があるフォルダ）を開いてから、次の2行を順に実行する。すでに`02_basic_measurement/measurement_design`へ移動済みなら、2行目だけでよい。

```bash
cd 02_basic_measurement/measurement_design
uv run python run.py validate --client sample-client
```

初回はuvが必要なライブラリをダウンロードする。検証そのものはGA4や外部AIに接続せず、`kpis.yaml`と`screen-flow.yaml`が正しく読めるかだけを確認する。両方に`[OK]`が表示され、検証に成功すれば完了。この操作ではレポートは生成されない。
**`sample-client` はそのまま `fetch`/`run` に使わないこと。** `sample-client/inputs/*.local.yaml`
はこのリポジトリのバージョン管理対象（サンプル値を配布するため）なので、ここで実際のGA4/GTMのIDを
取得すると、気づかずコミット・公開してしまう恐れがある（`fetch --client sample-client` はこの事故を
防ぐため実行時にエラーで止まる）。実データで試すときは次の手順で自分用のクライアント名を使う。

### 2. 自分のクライアントで実データを取得する

先に[GA4の初回セットアップ](../../docs/setup-ga4.md)を済ませる。ここからは前の手順で移動した`02_basic_measurement/measurement_design`で実行する。`my-site`は保存用の名前の例で、登録済みならその名前に置き換える。次のファイル準備は計測設計書も作る場合に必要。計測チェックだけなら、AIに依頼して必要な情報を会話で登録できる。

**Windows（PowerShell）でファイルを準備する場合**

```powershell
New-Item -ItemType Directory -Force my-site/inputs
Copy-Item sample-client/inputs/*.yaml my-site/inputs/
```

**Mac（ターミナル）でファイルを準備する場合**

```bash
mkdir -p my-site/inputs
cp sample-client/inputs/*.yaml my-site/inputs/
```

コピーした`my-site/inputs/kpis.yaml`（成果や目標）と`screen-flow.yaml`（ページと導線）を自社サイトに合わせて編集する。書き方が分からなければ、AIにこの2ファイルの作成を依頼する。以下のコマンドはWindows／Mac共通。

```bash
uv run python run.py validate --client my-site
```

検証に成功したら実行する。`{GA4プロパティID}`は、波括弧ごと自分のGA4プロパティID（数字）に置き換える。IDの指定は初回のみで、以後は省略できる。

```bash
uv run python run.py run --client my-site --property-id {GA4プロパティID} --auth sa
```

`my-site/inputs/*.local.yaml` はコピー元と違ってバージョン管理対象外なので、実データで
上書きしても問題ない（`.gitignore` 参照）。GTMも点検したい場合は `--gtm-account`/`--gtm-container`
を追加で指定する（未指定ならGTM取得はスキップされ、GA4の実データだけで判断できる範囲の
点検結果になる）。

計測チェックレポートは、リポジトリの一番上にある`outputs/my-site/02_measurement/docs/check-report.md`へ保存される。

**既定では、計測設計書の文章生成は現在使っているAIエージェントが担当する。** 上のコマンドだけで設計書まで完成するわけではない。設計書も必要なら、実行後にAIへ「取得したデータと入力ファイルを使い、計測設計書を作って」と依頼する。AIは画面に表示された案内に従い、`outputs/my-site/02_measurement/docs/design-doc/`へ章ごとの文書を保存する。

---

## コマンド一覧

### validate — 入力ファイルの検証

```bash
uv run python run.py validate --client {クライアント名}
```

`inputs/kpis.yaml` と `inputs/screen-flow.yaml` が正しく読み込めるか確認する。データ取得の前に必ず実行。

### fetch — GA4/GTM データ取得

```bash
# GA4 のみ（--property-id は初回のみ。指定後は inputs/ga4.local.yaml に保存され省略可）
uv run python run.py fetch \
  --client {クライアント名} \
  --property-id {GA4プロパティID} \
  --auth sa

# 2回目以降は ID 省略可（保存済み or 01コンテキストから自動解決）
uv run python run.py fetch --client {クライアント名}

# GA4 + GTM（GTM ID も初回のみ。以降は inputs/gtm.local.yaml に保存）
uv run python run.py fetch \
  --client {クライアント名} \
  --property-id {GA4プロパティID} \
  --gtm-account {GTMアカウントID} \
  --gtm-container {GTMコンテナID}
```

> ID は **フラグ → `inputs/*.local.yaml` → 01コンテキスト** の順で解決し、見つからなければ実行を止めて指定を促す。一度指定すれば保存され次回以降は省略できる（不明な場合はサイトのGA4/GTM管理者に確認）。

取得内容:

| Phase | API | 出力ファイル |
|-------|-----|-------------|
| Phase 1 | GA4 Admin API | `outputs/{クライアント名}/02_measurement/_data/phase1.json`（プロパティ設定・イベント・カスタム定義・**イベント作成ルール**） |
| Phase 2 | GA4 Data API | `outputs/{クライアント名}/02_measurement/_data/phase2.json`（直近30日イベント実績・チャネル別データ） |
| Phase 3 | GTM API v2 | `outputs/{クライアント名}/02_measurement/_data/phase3.json`（タグ・トリガー・変数）※GTM指定時のみ |
| 公開実装 | 対象URLのHTML・公開 `gtm.js` | `outputs/{クライアント名}/02_measurement/_data/09-site-implementation.json`（直接設置のGA4/UA ID・公開中タグ。サイトURL登録時はGTM APIの有無にかかわらず取得） |

UA経由の計測継続性はGTM APIだけでなく、対象URLの公開HTMLに残る `UA-*` / `G-*` と公開 `gtm.js` のタグ種別も根拠にする。GTM APIが無いという理由だけで判定不能とはしない。ただし公開情報で分かるのは配信中の実装に限られるため、UA削除後もGA4が継続するかは実機で確認する。

### review — チェックレポート生成

```bash
uv run python run.py review --client {クライアント名}

# 任意でClaude CLIまたはAnthropic APIを明示指定
uv run python run.py review --client {クライアント名} --llm-backend claude_cli
uv run python run.py review --client {クライアント名} --llm-backend anthropic_api

# LLM なし（機械検出のみ。最速）
uv run python run.py review --client {クライアント名} --no-llm
```

出力: `outputs/{クライアント名}/02_measurement/docs/check-report.md`（全体サマリー / 設定確認表 / 要対応・要確認 / 改善順）。**利用者が見る計測チェックレポートはこの1本だけ。** 内部では機械37項目・目視19項目を維持するが、正常・適用外を含む全56行を本文へ掲載しない。自動判定できる項目はカテゴリ／確認項目／判定／結果／対応事項の5列とし、APIで取得できない設定は「管理画面でまとめて目視確認」へ集約する。KPIとイベントの対応表、受信イベント一覧、パラメータの独立章、カスタム計測の独立章、その他推奨設定の独立章も設けない。1件の指摘はどこか1つにだけ出し、**管理ID・指摘IDはレポートに出さない。** 工程間の受け渡しや内部処理では保持し、読者は対象名・カテゴリで各行を特定する。

設定確認表の項目・分類・判定方法は `standards/audit-items.md` を正本とする。予約・決済・オンラインサービス等の外部ドメインは事前質問で登録せず、GA4で受信した主要 `hostName` と `source / medium` を使って、自己参照に加えAmazon Pay・PayPal等の外部サービス由来の `referral` を確認候補にする。ただし、別々の集計だけでは実際のホスト間遷移やセッション分断を確定できないため、該当時も△の確認候補とする。対象間の導線、同じWebストリーム・タグID、実ブラウザ遷移時のセッション継続を確認し、分断を再現できた場合だけ設定変更を提案する。Search Console連携はAdmin APIで取得していないため、必要時に手動確認として「要対応・要確認」へ出す。自動収集・拡張計測・推奨・カスタムの各イベント一覧は公開本文へ出さない。ただし拡張計測の有効・無効は設定確認表で要約し、主要イベントの欠落、異常比率、日本語イベント名、二重送信など具体的な異常がある場合は「要対応・要確認」に掲載する。利用者へ確認済みのコンバージョンイベントは、上位100件ではなく直近30日の全イベント名・件数で受信有無を確認してサマリーに示す。全件取得が成功した場合だけ未掲載を0件と判定し、旧データ・取得不足は未確認とする。0件または類似名で受信している場合だけ詳細指摘を出し、KPIとイベントの対応表は復活させない。

**`check-report.md` は `review` を実行するたびに毎回まっさらに再生成される。** 計測チェックは1回で終わらず、指摘をクライアントに確認し回答を書き込み、対応済みを消し込む往復が発生するが、このファイルに直接書き足すと次回の `review` で消える。指摘への確認・対応は `docs/check-report-notes.md` に書くこと。**このファイルは `review` が「無ければ作る。あれば絶対に上書きしない」** ので、書き足しは何度 `review` を実行しても消えない（`docs/findings.md` と同じ「人専用ファイル」の扱い。§0所見用の findings.md とは役割が別）。HTML等への自動変換の対象にもしていない（人が編集途中のファイルのため、`questions.draft.md` と同じ扱い）。

**`--output-formats` があれば今回の指定を優先する（`md` は変換なし）。引数を省略し、01に既定の出力形式（`profile.yaml` の `preferences.output_formats`）が設定されている場合、check-report はこの時点で `common/report_export` により自動的にHTML等へ変換され、変換後のファイルの絶対パスも標準出力に表示される。** 設定が無い・MDのみの場合は変換せず、従来どおりMDのパスだけが出る（`run.py` を直接叩いても、AIエージェント経由の実行と同じ挙動になる）。単発で別形式が要るときは「このレポートをPDFにして」などと自然文で依頼し、`common/report_export` を使う（詳細は docs/standard-run-order.md §4-2）。design-doc（後述の `doc` の出力）はこの自動変換の対象外。

**配布前の必須検査:** リポジトリルートで `python tools/validate_measurement_report.py outputs/{クライアント名}/02_measurement/docs/check-report.md` を実行する。この検査は、内部監査の正本が機械37項目・目視19項目を保っていることと、公開本文に5列の設定確認表・異常のみの指摘・改善順があることを別々に確認する。受信イベント一覧と全56項目の本文掲載は要求しない。自動変換済みでも検査通過前に配布せず、通過後も各判定と元データの一致、未確認範囲、HTML/PDFの表示を確認する。

### design — 計測設計書生成

```bash
uv run python run.py design --client {クライアント名}
```

出力: `outputs/{クライアント名}/02_measurement/docs/design-doc/01-cover.md` 〜 最大16章

`design` は文章生成を伴うため、現在利用中のAIエージェントへ依頼するか、任意バックエンドを明示指定する。`_data/` がなくても動くが、fetch済みデータがあると精度が上がる。

**既定（`--llm-backend none`）では、`design` は案内を出すだけで章ファイルを作らない。** 章ファイルは、いま実行しているAIエージェント自身が `docs/design-doc/` に書く（材料・命名規則・書く章の選び方は `docs/guide/work-procedure.md` ステップ6を参照）。書かずに `doc` を実行すると「章ファイルが見つかりません」で止まる。

**所要時間の目安: 章ごとにLLMを1回呼ぶ仕様のため、1章あたり40〜70秒かかる。** 章数は案件によって変わるが、最大16章では10〜15分程度。実行中は画面に進捗（`章を選定中...`等）が出るので、しばらく反応が無くても中断せずに待つ。

### summarize — 取得データのサマリーレポート

```bash
uv run python run.py summarize --client {クライアント名}
```

出力: `outputs/{クライアント名}/02_measurement/_data/summary.md`。`fetch` 済みの `_data/` を人間が読めるサマリーにする（外部LLM不要）。

### questions — 確認事項の骨組み

```bash
uv run python run.py questions --client {クライアント名}
```

出力: `outputs/{クライアント名}/02_measurement/docs/questions.draft.md`（`_data/` から「確認が必要そうな点」の骨組みを作る。**毎回まっさらに作り直される**）。
書き込む先は同時に作られる `outputs/{クライアント名}/02_measurement/docs/questions.md`（無ければ draft の骨組みを複製して作る。**あれば絶対に上書きしない**。`check-report.md` に対する `check-report-notes.md` と同じ作法）。**「なぜ確認が必要か」は人がこちらに書く**（外部LLM不要）。仕上がったらこのファイルをクライアントへの確認事項として使う。

### verify — 成果物の数値突合

```bash
uv run python run.py verify --client {クライアント名}
```

`docs/` と `report/`（納品用に人が手で仕上げた原稿の置き場所。output_dir 直下、docs/ の外）の Markdown・HTML 原稿に書かれた数値を `_data/` の実データと突き合わせ、食い違い（stale な数値）や他案件名の混入を検出する（外部LLM不要）。不一致があれば終了コード1。

### doc — 計測設計書のHTML化

```bash
uv run python run.py doc --client {クライアント名}
```

出力: `outputs/{クライアント名}/02_measurement/docs/design-doc.html`。`design` で生成した章（01〜16）を1つの自己完結HTML（外部ファイル参照なし）にまとめる。先に `design` を実行しておくこと。

### run — 一括実行

```bash
uv run python run.py run --client {クライアント名} --property-id {GA4プロパティID}
# 2回目以降は ID 省略可:  uv run python run.py run --client {クライアント名}
```

既定では `fetch → review` を実行し、外部LLMを呼ばず終了する。計測設計書は現在利用中のAIエージェントへ依頼する。任意バックエンドを明示指定した場合のみ `design → summarize` まで実行する。

---

## 認証方式

サービスアカウント認証のみ対応（`--auth sa`。既定でもこの値になる）。認証ファイルは `~/.saa/credentials/google-analytics/sa-key.json`。準備手順・なぜサービスアカウントが必要かは docs/setup-ga4.md を参照。

サービスアカウント鍵を別の場所に置いている場合は、環境変数 `GA4_SA_KEY_PATH` にそのパスを設定すれば動きます。

---

## 出力ファイル一覧

| ファイル | 説明 |
|---------|------|
| `outputs/{client}/02_measurement/docs/check-report.md` | クライアントが見る唯一の計測チェックレポート。5列の設定確認表、要対応・要確認となった具体的な異常、改善順を1本にまとめたもの。受信イベント一覧と内部の機械37項目・目視19項目は全文転記しない |
| `outputs/{client}/02_measurement/docs/design-doc/01-cover.md` | カバーページ |
| `outputs/{client}/02_measurement/docs/design-doc/02-basic-settings.md` | 基本設定 |
| `outputs/{client}/02_measurement/docs/design-doc/03-account-property.md` | アカウント・プロパティ設定 |
| `outputs/{client}/02_measurement/docs/design-doc/04-cv-mcv.md` | CV・MCV 設定 |
| `outputs/{client}/02_measurement/docs/design-doc/06-event-config.md` | カスタムイベント設定 |
| `outputs/{client}/02_measurement/docs/design-doc/07-variables.md` | カスタムディメンション・指標 |
| `outputs/{client}/02_measurement/docs/design-doc/08-ecommerce-main.md` | EC イベント設定 |
| `outputs/{client}/02_measurement/docs/design-doc/11-event-tracking-cta.md` 〜 `13-event-tracking-spec.md` | イベントトラッキング仕様書 |
| `outputs/{client}/02_measurement/_data/summary.md` | `summarize` の出力。取得データの人間可読サマリー |
| `outputs/{client}/02_measurement/docs/questions.draft.md` | `questions` の出力。確認事項の骨組み（本文は人が書く） |
| `outputs/{client}/02_measurement/docs/design-doc.html` | `doc` の出力。章01〜16を1枚のHTMLにまとめたもの |
| `outputs/{client}/02_measurement/report/` | 納品用に人が手で仕上げた原稿（Markdown・HTML）の置き場所。`docs/` の外（output_dir 直下）。自動作成はせず、`verify` の突合対象になるだけ |

章は案件特性（KPI・ECイベントの有無・カスタム定義の有無）に応じて自動選定される。

成果物は指定した形式（既定はMarkdown）でも受け取れる。詳細は `docs/standard-run-order.md` §4-2。

---

## エラー対処

| エラー | 原因 | 対処 |
|--------|------|------|
| `ANTHROPIC_API_KEY が設定されていません` | `--llm-backend anthropic_api` 指定かつ `.env` 未設定 | `.env` にキーを記入するか、既定の `none` を使う |
| `GA4プロパティIDが見つかりません` | フラグ・`inputs/ga4.local.yaml`・01コンテキストのどこにも無い | `--property-id` で指定（保存され次回省略可）。不明ならサイトのGA4/GTM管理者に確認 |
| `FileNotFoundError: Service account key not found` | SA キー未配置 | `~/.saa/credentials/google-analytics/sa-key.json` を配置（docs/setup-ga4.md）。別の場所に置いている場合は環境変数 `GA4_SA_KEY_PATH` にそのパスを設定 |
| `kpis.yaml が見つかりません` | inputs/ 未準備 | `validate` コマンドで確認。sample-client/inputs/ をコピーして編集 |
| `403 PERMISSION_DENIED` | GA4 権限不足 | GA4 プロパティに「閲覧者」権限を付与 |
| `phase1.json が見つかりません` | fetch 未実行 | `fetch` コマンドを先に実行する |
| `design-doc の章ファイルが見つかりません`（`doc` 実行時） | 既定（`--llm-backend none`）では `design` が章ファイルを作らないため | AIエージェントが `docs/design-doc/` に章ファイルを書く（`docs/guide/work-procedure.md` ステップ6）。`design` を再実行しても解決しない |
| `sample-client は配布用のサンプルのため、実データの取得には使えません` | `--client sample-client` で `fetch`/`run` を実行した | 自分用のクライアント名（例: `my-site`）を作ってそちらで実行する（上記クイックスタート参照） |

---

## テスト実行

```bash
uv run pytest tests/ -v --cov=src --cov-report=term-missing
```

---

## 詳細ドキュメント

| ドキュメント | 内容 |
|-------------|------|
| `docs/guide/work-procedure.md` | 利用手順（詳細・inputs/ ファイルの書き方） |
| `docs/guide/system-overview.md` | システム概要・フェーズ詳細・データフロー |
| `docs/guide/output-mapping.md` | 出力ファイル一覧 |
