# ① 全体施策｜フロー（05側）

CVR改善ループの起点。GA4＋外部データを分析し、**着手すべき改善タイプ＋優先順位の全体方針**を出す。
**05が分析と施策作成（する側）、06がそのレビュー（検証する側）**。作る人と検証する人を分けてバイアスを避ける。

## フロー（4エージェント・順番に動く）

| 順 | エージェント | 場所 | 出力 |
|---|---|---|---|
| 1 | **分析** | `analysis/`（05） | 01-analysis（ボトルネックの事実） |
| 2 | 分析レビュー | `../../06_effect_verification/1_overall_strategy/analysis_review/` | 02-analysis-review（妥当性チェック） |
| 3 | **施策作成** | `creation/`（05） | 03-strategy（着手タイプ＋優先順位） |
| 4 | 施策レビュー | `../../06_effect_verification/1_overall_strategy/creation_review/` | 04-strategy-final（確定方針） |

- 起動とデータ取得は **05/analysis** から（`analysis/run.md` あり）
- 06側（analysis_review / creation_review）は、05の出力ファイルを読んでレビューする
- 途中成果物（`01〜04`）は `outputs/{client}/05_cvr/_past/` に `01-analysis → 02-analysis-review → 03-strategy → 04-strategy-final` の順で残る（チェーンの現在地判定もここで行う）。`04-strategy-final` が確定したら、その内容は `outputs/{client}/05_cvr/cvr-improvement-plan.md` へ直接反映する。**クライアント向け確定版はこの1本だけで、段ごとの個別確定版は作らない**（docs/standard-run-order.md §4-5）

## スコープ
出すのは**方針まで**（どの改善タイプを・どの優先で）。
- 「どのページを、どう変えるか」→ ② 施策
