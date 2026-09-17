# spec: コンテキスト管理エージェント

| 項目 | 内容 |
|---|---|
| **概要** | 全エージェント共通のクライアント前提情報ストア。基本情報・計測環境・KPI・施策履歴・議事録・gotchas を一元管理し、共通ローダー経由で他エージェントへ提供する |
| **データソース** | ユーザー対話（前提情報の入力）／ 議事録テキスト ／ 各エージェントの分析findings（書き戻し） |
| **インプット** | ・クライアント基本情報（業種/事業/URL/toC・toB/ターゲット）<br>・計測環境（GA4 property / GTM / Search Console / BQ / 広告アカウントID）<br>・KPI・ゴール・主要イベント（kpi_id 形式）<br>・施策履歴（initiative_id / 期間 / 内容 / 対象KPI / 結果）<br>・前提・制約(gotchas) / 命名規則 / 未解決課題<br>・ステークホルダー<br>・議事録（Markdown 貼り付け） |
| **アウトプット** | `context/<client_id>/` 配下の構造化ファイル群（YAML + meetings/*.md）<br>＋ 共通ローダー `context_store`（他エージェントが import）<br>＋ `summary_markdown()`（プロンプト注入用の前提サマリ） |
| **トリガ** | 案件キックオフ時 / 定例MTG後（議事録反映）/ 新規施策・KPI追加時 / 前提情報の更新時 |
| **人レビュー観点** | 前提情報の正確性、gotchas の妥当性、id 相互リンクの整合 |
| **成果物** | クライアント前提情報ストア（全エージェントの参照元） |

---

## 提供 API（src/context_store/loader.py）

| API | 返り値 | 説明 |
|---|---|---|
| `load_context(client_id)` | `ClientContext` | 全YAML + 議事録を統合。欠損は空で返し落ちない |
| `list_clients()` | `list[str]` | `context/` 配下のクライアントID一覧 |
| `ClientContext.summary_markdown()` | `str` | gotchas / KPI / 計測ID / 直近findings の前提サマリ |
| `ClientContext.validate()` | `list[str]` | 整合性警告（kpi_id 重複・related_kpi 未参照など） |
| `ClientContext.ga4_property_id` / `.key_events` / `.name` | — | よく使う値のショートカット |

連携仕様の詳細は [docs/integration-interface.md](./docs/integration-interface.md)。

---

## エラー・補完ルール

- `context/<client_id>/` や個別ファイルが無くても **例外で落とさず空で返す**（運用初期の未記入を許容）
- 壊れた YAML はパース失敗を警告ログに出し `{}` で続行
- 不正な `client_id`（英数字・ハイフン・アンダースコア以外）は `ValueError`
- 入力時は **憶測で埋めない**。不明項目は空にしてユーザーに確認
- `related_kpi` は `kpis.yaml` の `kpi_id` と一致必須（`validate()` で検出）

---

## スコープ境界

- 本エージェントは **ストア + ローダー + 対話入力 + 連携IF定義** まで（Phase 1 / W4）
- 既存17エージェントを実際に参照対応させる改修は **Phase 2（6/16〜）**
- findings の自動書き戻しヘルパーも Phase 2（今回は手動 or context-manager 経由で追記）
