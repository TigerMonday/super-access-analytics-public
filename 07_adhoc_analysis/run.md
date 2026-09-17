# 実行手順: アドホック分析エージェント

ユーザーは「分析したいことがある」と伝えるだけ。単純な数値確認なら1回の応答で即答し、深掘りが要る依頼はエージェントが4フェーズで段階的に進行する。

## 自然文で依頼されたときの受付

1. 依頼文の client_id、または `list_clients()` の一覧から対象を確定して `load_context(client_id)` を読む。未登録なら `docs/standard-run-order.md` §2-1 のURL先行受付を使う。最初に対象サイトURLを確認し、サイト表示名と client_id はURL・サイト・GA4情報から候補を作る。曖昧・矛盾・重複がある場合だけ確認し、最小登録して続ける。
2. GA4プロパティIDが無ければ確認し、確認できた値を01へ保存する。CVは分析テーマに関係するときだけ確認する。
3. サイトの前提、基本分析、市場・顧客理解の既存成果物を先に読む。無ければその旨を伝えて続行する。
4. 自然文をGA4の取得計画JSONへ変換する。`common/ga4_fetch/README.md` の曖昧語を確認し、意味が分かれる場合は利用者へ確認する。AIが考えた項目名を直接APIへ渡さない。
5. 通常フローでレポートを保存する場合だけ出力形式を、依頼文→01の既定→利用者への確認の順で決める。即答モードでは聞かない。無人実行で未設定ならMDだけにする。
6. 出力先は `outputs/{client_id}/07_adhoc/` とし、利用者には聞かない。通常フローの完了時は成果物の絶対パスを示し、`append_finding(..., agent="07_adhoc_analysis")` で履歴を保存する。即答モードではファイル保存と履歴保存は不要。

---

## 前提（初回のみ）

- 対応するAIコーディングエージェントが利用可能
- Python 3.11+ と [uv](https://docs.astral.sh/uv/) がインストール済み
- 監査対象 GA4 プロパティにサービスアカウントのアクセス権を付与済み
- サービスアカウント鍵が `~/.saa/credentials/google-analytics/sa-key.json`（既定）に配置済み（準備手順は docs/setup-ga4.md）
  - 鍵を別の場所に置いている場合は、環境変数 `GA4_SA_KEY_PATH` にそのパスを設定すれば動きます。

### 初回セットアップ

```bash
cd <リポジトリ>/07_adhoc_analysis
uv sync
```

---

## 使い方

AIエージェントでリポジトリルートを開き、「先月のセッション数を教えて」「この流入減少を深掘りして」などと自然文で依頼する。専用コマンドやプロンプトファイルの指定は不要。AIエージェントは `docs/ai-agent-guide.md` からこの文書へ到達し、必要に応じて `prompts/adhoc-analysis.md` を読む。

### 対話の流れ（Step 0 + 4フェーズ + 承認ゲート）

| Step | エージェントがやること | ユーザーが答えること |
|---|---|---|
| 0 | **前段読み込み**: サイトの前提情報 + 基本分析 + 外部リサーチの成果物を読む | （自動。無ければその旨の報告のみ） |
| 1 | 分析依頼・Step 0 で補完できなかった前提を質問 | 自由記述で分析したいことを答える |
| 1.5 | **即答モード or 通常フローを判定**（単純な数値確認・比較なら即答モードへ） | （判定に迷う場合のみ一言確認） |
| 2 | **Phase 1: 問い構造化**を提示（前段成果物の参照一覧つき） | 「OK」「ここを変えて」等 |
| 3 | **Phase 2: GA4からデータ取得**して提示 | 「OK」「追加でこれも見て」等 |
| 4 | **Phase 3: 結果解釈**を提示 | 「OK」「この視点も追加」等 |
| 5 | **Phase 4: 追加検証**を提示 | 「OK」 |
| 6 | Markdown レポートを `outputs/{client_id}/07_adhoc/...` に保存 | 完成 |

> **即答モード**（Step 1.5判定）: 「先月のセッション数」「モバイル/PCのCVR差だけ」のような単純な数値確認・比較は、Step 2〜5の個別承認ゲートを省略し、データ取得→提示→一言解釈を1回の応答で返す。深掘りが必要になった時点で通常フロー（Step 2〜）に切り替わる。原因分析・複数仮説の検証が必要な依頼は従来どおり4フェーズで進む。

---

## 出力

```
outputs/{client_id}/07_adhoc/{YYYY-MM-DD}_adhoc_{topic-slug}.md
```

中身は4フェーズ統合の Markdown（「参照した前段成果物」セクションを含む）。
出力先は実行フォルダ（セッション開始時のカレントディレクトリ。通常はリポジトリルート。docs/standard-run-order.md §4）直下の共有 `outputs/`（`.gitignore` 済みのため git には乗らない）。出力先はユーザーに尋ねない（明示指定があった場合のみ上書き）。完了時に主要成果物のフルパスを表示する。成果物は指定した形式（既定はMarkdown）でも受け取れる。詳細は `docs/standard-run-order.md` §4-2。

### HTML 版

Phase 2 拡張（テンプレート未整備）。当面は Markdown を正とする。

---

## 簡易分析スライドとして使う場合

計測設計・設定監査の後続資料として使う場合は、以下のように依頼する。

```
2026年5月単月と、2025年5月から2026年5月までのデータで、
GA4の簡易分析を実施し、スライド用Markdownとしてレポート化して。
クライアント名は提出用の表記に合わせて。
```

推奨クエリ:

| 目的 | dimension | metrics |
|---|---|---|
| 月次推移 | `yearMonth` | `sessions,totalUsers,newUsers,screenPageViews,eventCount,keyEvents` |
| チャネル | `sessionDefaultChannelGroup` | `sessions,keyEvents,totalUsers` |
| 参照元/メディア | `sessionSourceMedium` | `sessions,keyEvents,totalUsers` |
| キャンペーン | `sessionCampaignName` | `sessions,keyEvents,totalUsers` |
| デバイス | `deviceCategory` | `sessions,keyEvents,totalUsers` |
| ドメイン | `hostName` | `sessions,screenPageViews,keyEvents` |
| LP全件 | `landingPagePlusQueryString` | `sessions,totalUsers,newUsers,screenPageViews,keyEvents` |
| LP × 参照元 | `landingPagePlusQueryString,sessionSourceMedium` | `sessions,totalUsers,newUsers,keyEvents` |
| ページパス全件 | `pagePath` | `sessions,totalUsers,screenPageViews,keyEvents` |
| ドメイン × LP | `hostName,landingPagePlusQueryString` | `sessions,totalUsers,newUsers,screenPageViews,keyEvents` |
| イベント | `eventName` | `eventCount,totalUsers` |

> `LP全件` / `ページパス全件` は `--all-rows` で取得し、未取得行警告が0であることを確認する。CVRは、ユーザー確認済みの完了イベントで絞った同条件の `sessions` ÷ 全 `sessions` で計算し、`keyEvents` を分子にしない。

スライド化の注意:

- 成果数が急増している場合は、計測定義の変更・過剰発火の可能性を先に注記する
- `Direct`、`Unassigned`、QR流入は、UTMとクロスドメインの論点に接続する
- 予約・申込ドメインがある場合は、`/store/`、`/reserve/`、`/booking/` などがLPになっているセッションを全件で確認する
- ページ関連は `ドメイン → サイト構造 → ページ` の順に並べ、ページ別アクセスは `pagePath` でクエリストリングを除外して見る
- ページ別表ではCV列を無理に入れず、PV・セッション・ページの役割を中心に整理する
- タイトルは `[全体像] ...`、`[流入元] ...` のように論点ラベルを付ける
- 表が大きくなる場合は、行を削るよりも2分割して可読性を保つ

---

## トラブルシューティング

| 状況 | 対応 |
|---|---|
| `FileNotFoundError: sa-key.json` | `~/.saa/credentials/google-analytics/sa-key.json`（既定）の配置を確認。鍵を別の場所に置いている場合は、環境変数 `GA4_SA_KEY_PATH` にそのパスを設定すれば動きます。 |
| `PermissionDenied: 403` | GA4 プロパティのアクセス権限にSAを追加 |
| `uv: command not found` | `pip install uv` または `brew install uv` |
| 期間にデータがない | プロパティID・期間を確認 |
| 各フェーズの出力が長すぎる | 「Phase 1 は3行で要約して」等の指示を追加 |

---

## 上級者向け: scripts/fetch_ga4.py 単独実行

エージェント経由でなく、データだけ欲しい場合:

```bash
# モバイル vs PC の全セッション（CVRの分母）
uv run python scripts/fetch_ga4.py \
  --property-id <GA4_PROPERTY_ID> \
  --dimensions deviceCategory \
  --metrics sessions \
  --days 28

# 同じ切り口のCVしたセッション（CVRの分子）
uv run python scripts/fetch_ga4.py \
  --property-id <GA4_PROPERTY_ID> \
  --dimensions deviceCategory \
  --metrics sessions,keyEvents \
  --filter "eventName=<USER_CONFIRMED_CV_EVENT>" \
  --days 28

# 特定キャンペーン × チャネル
uv run python scripts/fetch_ga4.py \
  --property-id <GA4_PROPERTY_ID> \
  --dimensions sessionDefaultChannelGroup \
  --metrics sessions,keyEvents \
  --filter "sessionCampaignName=202605_spring_seminar" \
  --days 28

# キーイベント発火回数（日次）
uv run python scripts/fetch_ga4.py \
  --property-id <GA4_PROPERTY_ID> \
  --dimensions date \
  --metrics eventCount \
  --filter "eventName=complete_seminar" \
  --days 90
```

> `--days N` は前日までの完全な N 日間（当日の部分データは含まない）。

利用可能な dimensions / metrics の候補:
https://developers.google.com/analytics/devguides/reporting/data/v1/api-schema

実行時は対象プロパティのMetadataと `checkCompatibility` で最終判定する。静的な一覧だけを正としない。自然文から取得する場合は `common/ga4_fetch/query-plan.example.json` と同じ取得計画を作り、`--query-plan` と `--write-query-plan` を使う。検証済み取得計画が保存されなかった結果は分析に使わない。

---

## Phase 2 で予定している拡張

- Search Console API 連携（検索クエリ起点の分析）
- BigQuery 接続（GA4 生データの SQL 分析）
- HTML レポートのチャート対応
- Notion 連携（分析履歴の蓄積）
