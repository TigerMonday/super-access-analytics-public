# 出力ファイルマッピング

各コマンドが生成するファイルの一覧。

---

## fetch コマンド

| ファイル | 説明 |
|---------|------|
| `{client}/_data/phase1.json` | GA4 Admin API 結果（プロパティ、ストリーム、カスタム定義、KPIイベント、イベント作成ルール `event_create_rules_{streamId}`） |
| `{client}/_data/phase2.json` | GA4 Data API 結果（過去30日イベント、KPIイベント発火数、チャネル別実績） |
| `{client}/_data/phase3.json` | GTM API 結果（タグ、トリガー、変数、GA4タグ分析）※GTM指定時のみ |

## review コマンド

| ファイル | 説明 |
|---------|------|
| `{client}/docs/check-report.md` | **クライアントが見る唯一の計測チェックレポート。** 自動判定の5列表、APIで取得できない設定を集約した目視確認ブロック、要対応・要確認となった具体的な異常、改善順をまとめる。受信イベント一覧は載せない。内部では機械37項目・目視19項目を全件監査するが、全56行は本文へ転記しない。Search Console連携も目視確認ブロックで扱う。**実行するたびに再生成される** |
| `{client}/docs/check-report-notes.md` | 指摘への確認・対応を書く場所。**「無ければ作る。あれば絶対に上書きしない」ファイル**（初回のみ雛形を作成し、以後は review を何度実行しても内容が変わらない）。指摘IDは指摘の内容から決まる固定の符号で、データを取り直しても同じ指摘には同じIDが振られる。読み返すときに探しやすいよう対象名も一緒に書いておくとよい |

## design コマンド

| ファイル | 説明 |
|---------|------|
| `{client}/docs/design-doc/01-cover.md` | カバーページ |
| `{client}/docs/design-doc/02-basic-settings.md` | 基本設定 |
| `{client}/docs/design-doc/03-account-property.md` | アカウント・プロパティ設定 |
| `{client}/docs/design-doc/04-cv-mcv.md` | CV・MCV 設定（KPI あり時） |
| `{client}/docs/design-doc/05-internal-traffic.md` | 内部トラフィック除外 |
| `{client}/docs/design-doc/06-event-config.md` | カスタムイベント設定（カスタムイベントあり時） |
| `{client}/docs/design-doc/07-variables.md` | カスタムディメンション・指標（定義あり時） |
| `{client}/docs/design-doc/08-ecommerce-main.md` | ECイベント設定（EC イベントあり時） |
| `{client}/docs/design-doc/09-ecommerce-lp.md` | EC LP 計測 |
| `{client}/docs/design-doc/10-content-groups.md` | コンテンツグループ |
| `{client}/docs/design-doc/11-event-tracking-cta.md` | CTA イベントトラッキング仕様 |
| `{client}/docs/design-doc/12-event-tracking-general.md` | 汎用イベントトラッキング仕様 |
| `{client}/docs/design-doc/13-event-tracking-spec.md` | イベントトラッキング仕様書 |
| `{client}/docs/design-doc/14-data-import.md` | データインポート |
| `{client}/docs/design-doc/15-audiences.md` | オーディエンス設定 |
| `{client}/docs/design-doc/16-linked-tools.md` | 連携ツール設定 |

章は案件特性に応じて自動選定されるため、すべての章が生成されるとは限りません。

## summarize コマンド

| ファイル | 説明 |
|---------|------|
| `{client}/_data/summary.md` | 取得データ（phase1〜3）の人間可読サマリー |

## questions コマンド

| ファイル | 説明 |
|---------|------|
| `{client}/docs/questions.draft.md` | 確認事項の骨組み（毎回作り直される。編集しても消える） |
| `{client}/docs/questions.md` | 確認事項の書き込み先。無ければ draft を複製して作る。**あれば絶対に上書きしない**。「なぜ確認が必要か」はここに書く |

## doc コマンド

| ファイル | 説明 |
|---------|------|
| `{client}/docs/design-doc.html` | design で生成した章（01〜16）を1枚の自己完結HTMLにまとめたもの |

## verify コマンド

成果物ファイルを書き換えない（`docs/` と `report/`（output_dir 直下。docs/ の外。納品用に
人が手で仕上げた原稿の置き場所で、自動作成はしない）の Markdown・HTML 原稿を読み、`_data/` の
実データと数値を突合した所見を標準出力に表示するだけ）。
