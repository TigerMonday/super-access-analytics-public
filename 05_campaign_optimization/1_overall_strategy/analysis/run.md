# 実行手順: ① 全体施策｜分析エージェント（05）

①全体施策フローの先頭。GA4を取得してボトルネックを出す。

## 前提（初回のみ）
- Python 3.11+ / uv / GA4サービスアカウント鍵 `~/.saa/credentials/google-analytics/sa-key.json`（既定。準備手順は docs/setup-ga4.md）
  - 鍵を別の場所に置いている場合は、環境変数 `GA4_SA_KEY_PATH` にそのパスを設定すれば動きます。

### セットアップ
```bash
cd <リポジトリルート>/05_campaign_optimization/1_overall_strategy/analysis
uv sync
```

## 動作確認（自社サイトのGA4プロパティIDは 01 コンテキストストア参照）
```bash
uv run python scripts/fetch_ga4.py --property-id <GA4_PROPERTY_ID> \
  --dimensions sessionDefaultChannelGroup --metrics sessions \
  --days 90
uv run python scripts/fetch_ga4.py --property-id <GA4_PROPERTY_ID> \
  --dimensions sessionDefaultChannelGroup --metrics sessions,keyEvents \
  --filter "eventName=<USER_CONFIRMED_CV_EVENT>" \
  --days 90
```

## 起動
```bash
claude
# セッション内で:
@prompts/analyze.md を読み込んで、全体施策の分析エージェントを起動して
```

## ①全体施策フロー全体の流れ
1. **05/analysis**（ここ）… GA4→ボトルネック（事実）
2. 06/analysis_review … 数値の検算
3. 05/creation … 方針作成（着手タイプ＋優先順位）
4. 06/creation_review … コンテキスト是正 → 確定方針

各段の途中成果物はリポジトリルート（`git rev-parse --show-toplevel` で求める。docs/standard-run-order.md §4）直下の `outputs/{client_id}/05_cvr/_past/` に `01-analysis → 02-analysis-review → 03-strategy → 04-strategy-final` の順で残る（チェーンの現在地判定もここで行う）。`04-strategy-final` の確定後は、その内容を `outputs/{client_id}/05_cvr/cvr-improvement-plan.md` へ直接反映する。**クライアント向け確定版はこの1本だけで、段ごとの個別確定版は作らない**（docs/standard-run-order.md §4-5）。出力先はユーザーに尋ねない（明示指定があった場合のみ上書き）。完了時は、確定版に反映済みなら `05_cvr/cvr-improvement-plan.md` を**最終成果物**として、それ以外の段（分析・レビュー・作成の途中）なら書き出した `_past/` のファイルを社内用の途中経過として明示してパスを表示し、`outputs/{client_id}/index.html` を再生成する（docs/standard-run-order.md §4 規約4）。成果物は指定した形式（既定はMarkdown）でも受け取れる。詳細は `docs/standard-run-order.md` §4-2。
