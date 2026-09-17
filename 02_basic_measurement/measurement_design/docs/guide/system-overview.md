# システム概要

## 何をするツールか

**計測設計 CLI** は、GA4/GTM の現状データを API で取得し、Claude AI が KPI・画面導線をもとに計測設計書を自動生成する Python CLI ツール。

手動で作成すると数時間かかる計測設計書の初稿を、コマンド数本で生成する。

---

## アーキテクチャ

```
run.py (CLI エントリーポイント)
    │
    ├── [fetch] scripts/           ← データ取得層
    │   ├── config.py              AuditConfig（クライアント別パス管理）
    │   ├── auth.py                SA 認証（内部にADC/OAuth分岐も残すが利用者へは案内しない）
    │   ├── ga4_admin.py           GA4 Admin API（プロパティ設定・イベント定義）
    │   ├── ga4_data.py            GA4 Data API（実績データ）
    │   ├── gtm.py                 GTM API v2（タグ・トリガー・変数）
    │   └── run_phase.py           Phase 別実行（phase1 / phase2 / phase3）
    │
    └── [review / design] src/measurement_design/   ← AI 設計生成層
        ├── loader.py              inputs/ YAML 読み込み
        ├── review/
        │   ├── normalizer.py      phase JSON → 統一 review_data スキーマ
        │   ├── diagnoser.py       機械検出（GA4 命名・予約語 / GTM 量産・残骸・二重計測・値の使い回し）+ LLM 違反検出
        │   └── renderer.py        check-report.md テンプレート描画
        └── design/
            ├── decomposer.py      KPI → 必要 GA4 イベント分解（Claude Sonnet）
            ├── standardizer.py    イベント命名を規約・既存実装に合わせて標準化（Claude Sonnet）
            ├── selector.py        案件特性から含める章を選定（ルールベース）
            └── generator.py       章ごとの Markdown 生成（Claude Haiku / Sonnet）
```

---

## データフロー

```
【準備】inputs/ に YAML を手動作成
  kpis.yaml           KPI 定義（計測目標）
  screen-flow.yaml    ページ・画面導線定義
  ga4.local.yaml      プロパティID・認証方式（任意）
  gtm.local.yaml      GTM アカウント・コンテナID（任意）
        │
        ▼ validate コマンドで確認
        │
【fetch】GA4 / GTM API からデータ取得
  Phase 1 (Admin API)  →  _data/phase1.json
  Phase 2 (Data API)   →  _data/phase2.json
  Phase 3 (GTM API)    →  _data/phase3.json  ← GTM 指定時のみ
        │
        ▼
【review】チェックレポート生成
  normalizer    phase1.json + phase2.json + phase3.json(任意) → review_data（統一スキーマ）
  diagnoser     機械検出（GA4 命名・予約語 / GTM 量産・残骸・二重計測・値の使い回し） + Claude Sonnet（LLM 検出）
  renderer      テンプレート + 違反リスト → check-report.md
                ※ GTM 検出の解釈・集約案は standards/gtm-tag-consolidation.md（Q1–Q6）を参照
        │
        ▼
【design】計測設計書生成
  decomposer    kpis.yaml + screen-flow.yaml → KPI 別 GA4 イベント分解（Sonnet）
  standardizer  分解されたイベント + review_data → 命名標準化（Sonnet）
  selector      kpi_breakdowns + review_data → 生成する章の選定（ルールベース）
  generator     各章テンプレート + コンテキスト → 章 Markdown（Haiku / Sonnet）
        │
        ▼
【出力】
  {client}/docs/check-report.md
  {client}/docs/design-doc/01-cover.md 〜 最大16章
```

---

## fetch の各フェーズ詳細

### Phase 1 — GA4 Admin API（プロパティ設定取得）

| 取得する情報 | 用途 |
|-------------|------|
| プロパティ詳細（名称・タイムゾーン・通貨） | 設計書の基本情報 |
| データストリーム・測定ID | GTM との整合性チェック |
| 拡張計測設定（フォーム操作・スクロール等の有効/無効） | 二重計測の検出 |
| カスタムディメンション・カスタム指標一覧 | 章7（変数）の生成判断 |
| キーイベント一覧 | review_data に統合。発火ゼロのイベント検出 |
| オーディエンス一覧 | 章15（オーディエンス）の生成 |

所要時間: 約30秒〜1分

### Phase 2 — GA4 Data API（実績データ取得）

| 取得する情報 | 用途 |
|-------------|------|
| 直近30日のイベント一覧（名称・発火数） | 現状把握・命名規則チェック |
| キーイベント別の発火状況 | 発火ゼロのキーイベント検出 |
| チャネルグループ別セッション分布 | review のコンテキスト |

所要時間: 約1〜3分

### Phase 3 — GTM API v2（コンテナ監査）※GTM 指定時のみ

| 取得する情報 | 用途 |
|-------------|------|
| 公開バージョンの全タグ（GA4 タグの特定） | GA4 イベントの送信状況確認 |
| 全トリガー（タイプ分類） | SPA 対応の確認 |
| 全変数（dataLayer 変数・定数） | パラメータのソース特定 |
| GA4 タグ → イベント名のマッピング | phase1 / phase2 との整合性 |

所要時間: 約30秒〜1分

---

## design の処理詳細

### 1. KPI 分解（decomposer.py）

`kpis.yaml` の各 KPI に対して Claude Sonnet が以下を判断:

- このKPIを計測するために必要なGA4イベントは何か
- 各イベントに必要なパラメータ（名称・型・取得元）は何か
- どのページで計測するか（screen-flow.yaml の page_id と対応）

### 2. イベント命名標準化（standardizer.py）

分解されたイベント名を Claude Sonnet が `standards/naming-conventions.md` と `standards/reserved-words.md` および既存のGA4実装（phase2.json）と照合して:

- 既存イベントを再利用できる場合は `use_existing`
- 命名規則に合わせて修正が必要な場合はリネーム提案
- 完全新規の場合は `new` として確定

### 3. 章の選定（selector.py）

ルールベースで出力する章を決定:

| 条件 | 追加される章 |
|------|-------------|
| 常時 | 章1・2・3（カバー・基本設定・アカウント）、章11・12・13（仕様書） |
| KPI が定義されている | 章4（CV・MCV 設定） |
| カスタムイベントがある | 章6（イベント設定） |
| カスタムディメンション・指標がある | 章7（変数定義） |
| EC イベントがある（purchase / view_item 等） | 章8（EC 計測） |

### 4. 章生成（generator.py）

各章テンプレートをもとに Claude が Markdown を生成。章の複雑さに応じてモデルを使い分け:

| モデル | 担当章 | 理由 |
|--------|--------|------|
| claude-haiku-4-5-20251001 | 章1・2・3・5・9・10・14・15・16 | テンプレート埋め込み型の軽量章。コスト削減 |
| claude-sonnet-4-6 | 章4・6・7・8・11・12・13 | 設計上の判断が必要な重量章 |

---

## 認証方式

サービスアカウント（SA）認証が推奨。鍵ファイルはホームフォルダ配下の既定パスに配置する（リポジトリの外）:

```
~/.saa/credentials/google-analytics/sa-key.json（既定。準備手順は docs/setup-ga4.md）
```

鍵を別の場所に置いている場合は、環境変数 `GA4_SA_KEY_PATH` にそのパスを設定すれば動きます。

サービスアカウント認証のみ対応（`--auth sa`。既定でもこの値になる）。認証ファイルは `~/.saa/credentials/google-analytics/sa-key.json`。

> SA キーの内容はログに出力しない。ファイルパスのみを記録する。

---

## セキュリティ方針

- `ANTHROPIC_API_KEY` は `.env` で管理（`.gitignore` 対象）
- SA キーはホームフォルダ配下の `~/.saa/credentials/` に配置（リポジトリの外。docs/setup-ga4.md）
- ログに GA4 キーや個人情報は出力しない
- GTM は JSON ファイルではなく API 経由で取得（パストラバーサル防止）
