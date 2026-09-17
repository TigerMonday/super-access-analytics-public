# 実行手順: ② 施策｜分析エージェント（05）

②施策フロー（対象ページ選定＋改善案）の先頭。①の方針を受けて、該当ページ群を分析する。

## 前提（初回のみ）
- Python 3.11+ / uv / GA4サービスアカウント鍵 `~/.saa/credentials/google-analytics/sa-key.json`（既定。準備手順は docs/setup-ga4.md）
  - 鍵を別の場所に置いている場合は、環境変数 `GA4_SA_KEY_PATH` にそのパスを設定すれば動きます。

### セットアップ
```bash
cd <リポジトリルート>/05_campaign_optimization/2_target_page_plan/analysis
uv sync
```

## 動作確認（自社サイトのGA4プロパティIDは 01 コンテキストストア参照）
```bash
uv run python scripts/fetch_ga4.py --property-id <GA4_PROPERTY_ID> \
  --dimensions landingPagePlusQueryString --metrics sessions \
  --days 90 --all-rows --output /tmp/ga4_smoke_lp.md
uv run python scripts/fetch_ga4.py --property-id <GA4_PROPERTY_ID> \
  --dimensions landingPagePlusQueryString --metrics sessions,keyEvents \
  --filter "eventName=<USER_CONFIRMED_CV_EVENT>" \
  --days 90 --all-rows --output /tmp/ga4_smoke_lp_cv_sessions.md
```

## 起動
```bash
claude
# セッション内で:
@prompts/analyze.md を読み込んで、個別施策の分析エージェントを起動して
```

## ②施策フロー全体（対象ページ選定＋改善案）
1. （前提）①全体施策の確定方針 + `06/page_profile`（ページ目的判定）
2. **05/2_target_page_plan/analysis**（ここ）… ページ別分析（事実）
3. 05/2_target_page_plan/analysis_review … 数値の検算
4. 05/2_target_page_plan/creation … 対象ページ選定＋改善案の作成（旧②選定と旧③ABテスト案を統合。CV直結度×規模×改善余地で選び、選んだページのHTML/モバイルFVを見て改善案まで出す）
5. 06/2_target_page_plan/creation_review … 選定と改善案を別々に判定し、コンテキスト是正 → 確定

途中成果物はリポジトリルート（`git rev-parse --show-toplevel` で求める。docs/standard-run-order.md §4）直下の `outputs/{client}/05_cvr/_past/` に `05-page-analysis → 06-page-analysis-review → 07-target-page-plan → 08-target-page-plan-final` の順で残る（チェーンの現在地判定もここで行う）。`08-target-page-plan-final` の確定後は、その内容を `outputs/{client}/05_cvr/cvr-improvement-plan.md` へ直接反映する。**クライアント向け確定版はこの1本だけで、段ごとの個別確定版は作らない**（docs/standard-run-order.md §4-5）。出力先はユーザーに尋ねない（明示指定があった場合のみ上書き）。完了時は、確定版に反映済みなら `05_cvr/cvr-improvement-plan.md` を**最終成果物**として、それ以外の段（分析・レビュー・作成の途中）なら書き出した `_past/` のファイルを社内用の途中経過として明示してパスを表示し、`outputs/{client}/index.html` を再生成する（docs/standard-run-order.md §4 規約4）。成果物は指定した形式（既定はMarkdown）でも受け取れる。詳細は `docs/standard-run-order.md` §4-2。
