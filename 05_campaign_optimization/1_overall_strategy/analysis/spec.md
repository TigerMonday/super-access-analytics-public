# spec: ① 全体施策｜分析エージェント（05）

| 項目 | 内容 |
|---|---|
| 概要 | GA4からサイト全体のボトルネックを事実ベースで特定する（方針は出さない） |
| レイヤー | ① 全体施策 / 分析（05） |
| データソース | GA4 Data API のみ（BigQueryはV2） |
| 入力 | client_id / GA4プロパティID / 期間 / KPI・キーイベント / toC・toB（09から補完） |
| 出力 | 全体分析レポート（事実＋ボトルネック候補）`outputs/{client}/05_cvr/_past/01-analysis.md` |
| 次段 | 06/analysis_review（検算）→ 05/creation（方針作成） |

## このフォルダが持つもの
- `prompts/analyze.md`（分析プロンプト）
- `scripts/{auth,fetch_ga4}.py`（GA4取得。①全体施策フローのデータ取得はここが担う）
- `pyproject.toml` / `uv.lock`

## 注意
- 方針・優先順位は出さない（事実とボトルネックまで）
- CVR分母を最初に固定（toC/toB混在は B2B 入口に landingPage で絞る）
- `gtm.*`・過剰発火を成果に数えない／`hostName` の予約・開発ドメイン混入を注記
