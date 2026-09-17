# 実行手順: ② 施策｜施策作成エージェント（06、対象ページ選定＋改善案）

①の方針の中で対象ページを決め、選んだページの改善案（どこを・どう変えるか）まで出す。
選定は `05/2_target_page_plan/analysis`（検算済み）と page_profile の入力だけで進められるが、
改善案づくりは対象ページの**HTML/モバイルFVを実際に見て**改善箇所を特定するため、Playwrightが要る。

## 前提（初回のみ）
- Node.js / npm（Playwright 用）と、現在このリポジトリを操作するAIエージェント。

### セットアップ（モバイルFV撮影用）
```bash
cd <リポジトリルート>/05_campaign_optimization/2_target_page_plan/creation
npm install                      # playwright
npx playwright install chromium  # ブラウザ未取得の場合
```

## モバイルFVの撮影（対象ページが決まった後、改善案づくりの起点）
```bash
node scripts/fv-capture.mjs "https://{対象ページURL}" "iPhone 14 Pro"
```
出力（`scripts/screenshots/<URL識別子>-<取得時刻>/`、gitignore対象）:
- `report.json` … FV内の見出し/CTA・`ctaInFold`（FVにCTAがあるか）・`foldsToScroll`（全体が何画面分か）・status/redirect
- `iphone-14-pro-fv.png` … モバイルFV画像 / `iphone-14-pro-full.png` … 全体

URLと取得時刻ごとに別フォルダへ保存されるため、複数ページ・再撮影でも既存証跡を上書きしない。

> 例（sample-client セミナーLP）: `ctaInFold: false`（モバイルFVに申込CTAなし）/ `foldsToScroll: 12.4` → FVに行動導線が無いのが改善候補、と判明。

## 起動
```bash
claude
# セッション内で:
@prompts/create-page-plan.md を読み込んで、施策作成エージェントを起動して
```

## フロー
1. 対象候補ページの精査（CV直結度×規模×改善余地で選定。生CV率ワーストで選ばない）
2. 選んだページのHTML＋モバイルFV取得
3. 改善候補箇所の洗い出し → 4. 仮説 → 5. 変更要素1つ → 5.5. 検出力判定 → 6. 実行可能なパターン案 → 7. テスト／単一リリース設計

→ 次は 06/2_target_page_plan/creation_review（選定と改善案を別々に判定）。途中成果物はリポジトリルート（`git rev-parse --show-toplevel` で求める。docs/standard-run-order.md §4）直下の共有 `outputs/{client_id}/05_cvr/_past/` に `07-target-page-plan → 08-target-page-plan-final` の順で残る（チェーンの現在地判定もここで行う）。`08-target-page-plan-final` の確定後は、その内容を `outputs/{client_id}/05_cvr/cvr-improvement-plan.md` へ直接反映する。**クライアント向け確定版はこの1本だけで、段ごとの個別確定版は作らない**（docs/standard-run-order.md §4-5）。出力先はユーザーに尋ねない（明示指定があった場合のみ上書き）。完了時は、確定版に反映済みなら `05_cvr/cvr-improvement-plan.md` を**最終成果物**として、それ以外の段（作成・レビューの途中）なら書き出した `_past/` のファイルを社内用の途中経過として明示してパスを表示し、`outputs/{client_id}/index.html` を再生成する（docs/standard-run-order.md §4 規約4）。成果物は指定した形式（既定はMarkdown）でも受け取れる。詳細は `docs/standard-run-order.md` §4-2。
