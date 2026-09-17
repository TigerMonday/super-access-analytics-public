# 対話実行例: パラメータ管理エージェント

ユーザーは「監査したい」「基本分析をしたい」と言うだけ、あとは質問に答えるだけ。
GA4 データ取得・パラメータ監査・基本分析のレポート組み立てすべてエージェントが自動駆動。

**最終出力**: `<リポジトリルート>/outputs/{client_id}/04_traffic/basic-analysis-report.md`（`<リポジトリルート>` は `git rev-parse --show-toplevel` で求める。ファイル名に日付は入れない。docs/standard-run-order.md §4。Markdown 1ファイル。HTML版はデザインシステム統一時に再開予定）
- 分析サマリー（主要指標の前年同期比＋今回確認できたこと。パラメータ監査で見つかった重大な指摘があればここに反映）
- 📈 基本分析（項目1〜9）

パラメータ監査（utm設定・命名規則・欠損流入・媒体目的の4観点チェック）自体は従来どおり実施するが、詳細な一覧はレポート本文には出力しない（重大なものだけをサマリーに反映）。

---

## Step 1: Claude Code 起動 → エージェント起動依頼

```bash
$ cd <リポジトリルート>/04_traffic_analysis/parameter_management
$ claude
```

**ユーザー入力:**
```
@prompts/parameter-audit.md を読み込んで、パラメータ管理エージェントを起動して
```

---

## Step 2: エージェントが初期情報を質問

**エージェント:**
```
パラメータ管理エージェントを起動します。集客計測の監査と基本分析を行います。
以下を教えてください:

1. クライアント名（出力ファイル名に使用。例: sample-client）
2. GA4プロパティID（数値のみ）
3. キーイベント名（CV計算用、複数可。例: form_submit, file_download）
   - GA4管理画面 > 管理 > イベント > キーイベント で確認できます

期間を指定しない場合は、直近の完了した12か月（今回は2025年8月1日〜2026年7月31日）で進めます。
```

**ユーザー:**
```
sample-client / 123456789 / form_submit, file_download
```

---

## Step 3: エージェントが GA4 データを自動取得

**エージェント（裏で Bash 実行）:**
```bash
$ uv run python scripts/fetch_ga4_traffic.py \
    --property-id 123456789 --start-date 2025-08-01 --end-date 2026-07-31 \
    --output outputs/sample-client/_data/ga4/20260824_traffic.md
Written 4,231 bytes to outputs/sample-client/_data/ga4/20260824_traffic.md

$ uv run python scripts/fetch_ga4_analytics.py \
    --property-id 123456789 --start-date 2025-08-01 --end-date 2026-07-31 \
    --key-events "form_submit,file_download" \
    --output outputs/sample-client/_data/ga4/20260824_analytics.md
Written 42,880 bytes to outputs/sample-client/_data/ga4/20260824_analytics.md

$ uv run python scripts/fetch_ga4.py \
    --property-id 123456789 --dimensions hostName --metrics sessions,conversions \
    --start-date 2025-08-01 --end-date 2026-07-31 --limit 50 \
    --output outputs/sample-client/_data/ga4/20260824_hostname.md
Written 612 bytes to outputs/sample-client/_data/ga4/20260824_hostname.md

$ uv run python scripts/fetch_ga4_analytics.py \
    --property-id 123456789 --start-date 2025-08-01 --end-date 2026-07-31 \
    --candidates-for "form_submit,file_download" --candidates-limit 10 \
    --output outputs/sample-client/_data/ga4/20260824_funnel_candidates.md
Written 890 bytes to outputs/sample-client/_data/ga4/20260824_funnel_candidates.md
```

（01の `measurement.yaml` に BigQuery のGA4エクスポート設定が無いクライアントのため、CVパス精度版の取得は行わない。レポートには「CVがどのページを経て起きたかは、BigQuery連携を設定すると分かる」旨を一言添えて進める）

CVファネルの中間ページ候補（`20260824_funnel_candidates.md`）の上位ページを、外部通信が発生する旨を伝えたうえで実際に読みに行き、何のフォームかを判定した（下記Step 4で使う）。

---

## Step 4: エージェントが観察結果を提示

**エージェント:**
```
GA4データを取得しました（2025-08-25 ～ 2026-08-24、365日間＝直近1年）。

【全体】
- セッション: 152,400（前年同期比 +8.6%）
- ユーザー: 118,600
- 主要チャネル: Organic Search 43%, Paid Search 18%, Email 12%, Paid Social 8%

【欠損流入】
- (not set): 12,600セッション (8.3%) ← 要対応
- (direct): 14,780セッション (9.7%)

【観測された媒体識別子】(utm_source / utm_medium)
- google / organic, cpc
- Google / cpc          ← 表記ゆれ ⚠
- yahoo / cpc
- yss / cpc             ← 表記ゆれ ⚠
- facebook / paid_social
- meta_ads / cpc        ← 同一媒体疑い ⚠
- linkedin / social
- mailmag / email
- newsletter / mail     ← medium=mail は非標準 ⚠
- line / (not set)      ← medium 未設定 ⚠
- nikkei_xtech / referral

【ランディングページ別とページ別の顔ぶれの違い】
- ランディングページ上位は「/」「/lp/spring-seminar/」「/media/knowledge/xxx/」
- ページ別（PV）上位には上記に加えて「/pricing/」「/case/」が入る
  → 料金・事例ページは入口としてよりも、回遊先として見られている

【CVの由来（量と質のズレ）】
- セッション最多は「/」（1位）だがCVは0件
- 「/lp/spring-seminar/」はセッション7位だがCVは1位 → 効率が高い

【キーイベント発火状況】
- form_submit: 全体548件、Paid Search 234件、Organic 156件、Email 104件、Paid Social 52件、Direct 2件
- file_download: 全体938件、Paid Social 302件、Email 206件、Organic 198件、Paid Search 128件、Direct 104件

【CVファネルの中間ページ候補（キーイベント発火セッションでよく見られているページ）】
- form_submit: 1位 /contact/（390セッション）、2位 /pricing/（210セッション）
- file_download: 1位 /lp/spring-seminar/（720セッション）、2位 /pricing/（180セッション）

上記の候補ページを実際に読みに行って確認しました（外部通信が発生する旨は事前に伝達済み）。
- /contact/: 問い合わせフォーム（氏名・会社名・お問い合わせ内容の入力欄、送信ボタン「送信する」）
- /lp/spring-seminar/: セミナー申込ページ（日程選択・参加者情報の入力欄）

監査と基本分析を進めるため、以下3点だけ教えてください:

【質問1】CVファネルの入口の確認
CVごとの入口はこれで合っていますか。
- `form_submit` ← `/contact/`（問い合わせフォーム）
- `file_download` ← `/lp/spring-seminar/`（セミナー申込ページ）

このまま進めてよければ「はい」、違う点があれば教えてください。

【質問2】媒体・施策一覧
GA4から推測される運用中媒体は上記です。
それぞれの種別 / 目的 / 施策内容を教えてください。
GA4に出ていないが運用中の媒体があれば追加で。

【質問3】既存命名規則
社内のutm命名規則ドキュメントはありますか?
無ければ standards/naming-conventions.md のデフォルトを適用します。
```

---

## Step 5: ユーザーが文章で答える

**ユーザー:**
```
CVファネルの入口はそれで合っています。

媒体は以下です:
- Google広告(検索)/広告/獲得: ブランド指名キャンペーン
- Yahoo広告/広告/獲得: 検索広告
- Meta広告/広告/獲得: WPダウンロード誘導
- LinkedIn広告/広告/認知: スポンサードコンテンツ
- メルマガ/メール/既存接点維持: 月2回お役立ちコンテンツ
- LINE公式/メッセージ/獲得: 月2配信、セミナー案内
- Nikkei xTech/タイアップ/認知: 月1本タイアップ記事

命名規則はデフォルトでお願いします。
```

**エージェント（裏で追加のBash実行、全量は再取得しない）:**
```bash
$ MSYS_NO_PATHCONV=1 uv run python scripts/fetch_ga4_analytics.py \
    --property-id 123456789 --start-date 2025-08-01 --end-date 2026-07-31 \
    --key-events "form_submit,file_download" \
    --funnel-events "form_submit:/contact/:contains:confirmed;file_download:/lp/spring-seminar/:contains:confirmed" \
    --funnel-max 5 \
    --funnel-only \
    --output outputs/sample-client/_data/ga4/20260824_funnel.md
```

---

## Step 6: エージェントがパラメータ監査 + 基本分析の解釈 → 保存

**エージェント（バックグラウンド処理）:**
```
[パラメータ監査: 4観点A〜Dで分析]
[基本分析: 項目1〜8（+ CVファネルは項目7として反映）の表を確認し、解釈の文章を追加]
[パラメータ監査で見つかった重大な指摘は、レポート本文の独立セクションではなくサマリーの「今回確認できたこと」に反映する]
[Markdown を直接組み立て（サマリ→基本分析の順）]
[既存ファイルがあれば outputs/sample-client/04_traffic/_past/ へ退避]
[Write tool で <リポジトリルート>/outputs/sample-client/04_traffic/basic-analysis-report.md に保存]
[python common/report_index/build_index.py "outputs/sample-client" で index.html を再生成]
```

---

## Step 7: エージェントが完了報告

**エージェント:**
```
✅ レポート生成完了しました。

📄 保存先: outputs/sample-client/04_traffic/basic-analysis-report.md
   （Markdown 1ファイルにサマリ＋基本分析を集約）

──────────────────────────────
📊 サマリ
──────────────────────────────
- 全体セッション 152,400（前年同期比 +8.6%）／CV合計 1,486件（前年同期比 +11.2%、内訳: form_submit 548件・file_download 938件。CVが2件あるため合算ではなくキーイベントごとに表示）
- 今回確認できたこと:
  1. 資料DLページはセッション7位だがCV1位。効率の高い導線
  2. CVファネル（form_submit）は中間ページ（/contact/）への到達率が低く、到達後の転換率は高い
     → ボトルネックは「呼び込み」側（到達率の低さ）
  3. (not set) 流入 12,600セッション（8.3%）の参照元が未特定
  4. LinkedIn広告にutm未設定（2,500セッション全件がキャンペーン識別不能）

──────────────────────────────
📋 パラメータ監査の要点
──────────────────────────────
- 指摘総数: 9件 (High: 3 / Mid: 3 / Low: 3)（詳細一覧はレポート本文には出力せず、重大なものだけを上記サマリーに反映）
- 欠損流入率: 18.0%

優先対応 Top 3:
1. 🔴 LinkedIn広告に utm 未設定
2. 🔴 (not set) 流入 12,600セッション の参照元特定
3. 🔴 媒体名の表記ゆれ（google/Google、yahoo/yss、facebook/meta_ads）

💡 次のアクション
1. LinkedIn広告のutm付与
2. CVファネル（form_submit）の到達率が低いため、/contact/ への導線（内部リンク・CTA）を強化
3. (not set) 12,600セッションを特定し、Paid Search への振り分けで CVR 寄与を測定

詳細はファイルを開いてご確認ください。
```

---

## 補足: ファイル準備モード（対話省略）

媒体・施策一覧と命名規則を事前準備すれば、対話を省略できる:

```bash
$ cat prompts/parameter-audit.md samples/sample-client.input.md | claude
```

ただし キーイベントとプロパティIDは必須なので、入力ファイル内で明示するか、
セッション内で追加質問される。CVファネルの中間ページは任意項目のため、
指定が無ければ省略して進む。無人実行で応答を待てない場合は、候補一覧のうち除外候補
（自イベント発火ページ＝サンクスページ等と推定）ではない最上位をそのまま採用し、
レポートに「中間ページ未確認」と明記する（勝手に確定させない）。除外候補しか無い場合は
中間ページ無し（2段構成）のまま進める。
