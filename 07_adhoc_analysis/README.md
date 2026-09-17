# アドホック分析エージェント

分析依頼から **問い構造化 → データ取得 → 結果解釈 → 追加検証** を4フェーズで段階実行する分析エージェント。各フェーズで承認ゲートが入る。

本ツールの **アドホック分析テーマ**。

---

## 位置づけ: 02・03 の後段として動く

アドホック分析は **基本分析（traffic_analytics）と市場・顧客理解（external_research）が終わった後** に実施する想定。起動時にまず前段の成果物を読み込み（Step 0）、それを踏まえて問いを立てる。

| 前段 | 読み込むもの | 使い方 |
|---|---|---|
| 01 コンテキストストア | `load_context(client_id).summary_markdown()`（GA4 ID・キーイベント・gotchas・過去findings） | 前提の自動補完。ユーザーへの再質問を減らす |
| 03 市場・顧客理解 | `outputs/{client_id}/03_research/`（`00_3c_persona_journey_report.md` が起点） | 3C分析・ペルソナ・態度変容ジャーニー（競合・市場・ユーザーの声から組み立てた仮説）を仮説形成の材料にする |
| 04 基本分析 | `outputs/{client_id}/04_traffic/` | 基本指標（チャネル・デバイス・月次推移）は再取得せず引用。**深掘り差分に集中** |

前段成果物が無い場合はその旨を明示し、従来通りユーザーへの質問から始める。

---

## このエージェントでできること

| フェーズ | 内容 |
|---|---|
| **Phase 0: 前段読み込み** | 基本分析・外部リサーチ・サイトの前提情報の成果物を読み、前提と仮説の材料にする |
| **Phase 1: 問い構造化** | 自由記述の分析依頼を「目的・主要指標・切り口・仮説」に整理 |
| **Phase 2: データ取得** | GA4 Data API で必要なクエリを実行（複数クエリ組み立て） |
| **Phase 3: 結果解釈** | 仮説と照合しつつ、要因分解・前提・限界を明示 |
| **Phase 4: 追加検証** | 次にやるべき分析・確認ポイントの提示 |

各フェーズで人レビュー・承認を挟むため、軌道修正しながら進められる。

---

## 簡易分析スライドを作る場合

計測監査や設計レポートの補助資料として、**別資料のGA4簡易分析レポート**を作る場合は、承認ゲートを軽くし、最初に分析範囲を固定して通しで作成してよい。

推奨する最小セットは以下。

- 対象月の概況: セッション、ユーザー、PV、キーイベント、前年同月比
- 13か月推移: `yearMonth` で月次推移を確認し、季節性と計測定義の変化を分ける
- 流入分析: `sessionDefaultChannelGroup`、`sessionSourceMedium`、`sessionCampaignName`
- デバイス分析: `deviceCategory`。CVR差だけでなく、セッション構成も見る
- ドメイン・ページ分析: `hostName`、`landingPagePlusQueryString`、`pagePath` を使い、**ドメイン → サイト構造 → ページ** の順に読む
- 申込・予約導線の確認（店舗型サイトの例）: `/store/`、`/reserve/` のような申込・予約系パスがLPになっているセッションを確認し、店頭・QR・直接申込の利用を媒体評価から分ける。パスは対象サイトの実際の構造に合わせて読み替える
- ページ別アクセス: `pagePath` を使い、クエリストリングを除いた全件でサイトグループと主要ページを整理する。ページ別表にCV列を無理に入れない
- イベント確認: `eventName` と、必要に応じてイベントパラメータを確認。`gtm.*` が多い場合は行動分析には使いにくいと明記

実物大の手本は [`samples/ga4-simple-analysis.reference.md`](./samples/ga4-simple-analysis.reference.md)（架空データで作った全19ページのMarp原稿）を眺める。<!-- leak-ok: ダミー会社名の統一表記＋宛名敬称（実在の社名・人名ではない） -->

> トーンは仕上げ前に見直し、AIっぽい・スノッブな言い回しがないか確認する。

---

## ディレクトリ構成

```
07_adhoc_analysis/
├── README.md                     ← このファイル
├── spec.md                       ← IO 仕様
├── run.md                        ← AIエージェント共通の実行手順
├── pyproject.toml                ← Python 依存（uv 管理）
├── prompts/
│   └── adhoc-analysis.md         ← メインプロンプト（4フェーズ駆動）
├── scripts/
│   └── fetch_ga4.py              ← GA4 クエリ実行（互換シム。実体は common/ga4_fetch/）
└── samples/
    ├── input.example.md          ← 入力例
    └── ga4-simple-analysis.reference.md            ← 実物大の参考デッキ（架空データ・全19ページ）
```

> レポートの出力先は実行フォルダ（セッション開始時のカレントディレクトリ。通常はリポジトリルート。docs/standard-run-order.md §4）直下の共有 `outputs/{client_id}/07_adhoc/`。出力先はユーザーに尋ねない（明示指定があった場合のみ上書き）。完了時に主要成果物のフルパスを表示する。成果物は指定した形式（既定はMarkdown）でも受け取れる。詳細は `docs/standard-run-order.md` §4-2。HTML テンプレートは Phase 2 で整備予定（当面 Markdown を正とする）。

---

## 使い方

```bash
cd <リポジトリ>/07_adhoc_analysis
uv sync   # 初回のみ
claude
```

AIエージェントのセッション内で:
```
@prompts/adhoc-analysis.md を読み込んで、アドホック分析エージェントを起動して
```

エージェントが順番に:

1. **Step 0**: サイトの前提情報 + 基本分析 + 外部リサーチの成果物を読み込み
2. **分析依頼を質問**（自由記述 + Step 0 で補完できなかった前提のみ）
3. **Phase 1**: 問い構造化を提示（前段成果物の参照一覧つき） → 承認待ち
4. **Phase 2**: GA4 から必要データを自動取得 → 結果提示 → 承認待ち
5. **Phase 3**: 結果解釈を提示 → 承認待ち
6. **Phase 4**: 追加検証アイデアを提示 → 承認待ち
7. **Markdown レポート**を `outputs/{client_id}/07_adhoc/{YYYY-MM-DD}_adhoc_{topic}.md` に保存

入力のイメージは [samples/input.example.md](./samples/input.example.md)、出力のイメージは [samples/ga4-simple-analysis.reference.md](./samples/ga4-simple-analysis.reference.md)（実物大の参考デッキ）を参照。

---

## fetch_ga4.py の単独実行（参考）

エージェントが内部で呼び出す GA4 取得スクリプトは単独でも動く:

自然言語で依頼された分析では、AIが先に取得計画JSONを作る。実行前に対象GA4プロパティの
Metadataで項目名を確認し、Google公式の互換性確認APIでディメンション・指標・フィルタの
組み合わせを検証する。検証に失敗した条件は自動修正せず、依頼者へ確認してから取得し直す。
詳細は [`common/ga4_fetch/README.md`](../common/ga4_fetch/README.md) を参照。

```bash
# モバイル/PC のCVR
uv run python scripts/fetch_ga4.py \
  --property-id <GA4_PROPERTY_ID> \
  --dimensions deviceCategory \
  --metrics sessions,keyEvents \
  --days 28

# 特定キーイベントのチャネル別発火
uv run python scripts/fetch_ga4.py \
  --property-id <GA4_PROPERTY_ID> \
  --dimensions sessionDefaultChannelGroup \
  --metrics eventCount \
  --filter "eventName=<キーイベント名>" \
  --days 90
```

> `--days N` は前日までの完全な N 日間（当日の部分データは含まない）。

ディメンション・メトリクス一覧:
https://developers.google.com/analytics/devguides/reporting/data/v1/api-schema

---

## ステータス

- **Phase 1（プロトタイプ）**: GA4 API 自動取得 + 4フェーズ承認ゲート + Markdown 出力 + 01/03/04 前段読み込み（Step 0） ← **現在ここ**
- **Phase 2（拡張）**: Search Console 連携、BigQuery 連携、HTML レポート（テンプレート整備から）

---
