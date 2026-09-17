# コンテキスト管理エージェント

本ツールの **全エージェント共通の前提情報ストア**。
クライアントの基本情報・計測環境・KPI・施策履歴・議事録・gotchas を一元的に入力しておき、
他の全エージェントがそこを参照して、毎回同じことを聞かれずに一貫した前提で分析・アウトプットする。

本ツールの **コンテキスト管理テーマ** 構成エージェント。

---

## このエージェントでできること

### 📥 コンテキストの一元入力（対話型）
クライアントごとに以下を対話で登録・更新する。

| カテゴリ | ファイル | 中身 |
|---|---|---|
| クライアント基本情報 | `profile.yaml` | 業種 / 事業 / URL / toC・toB / ターゲット |
| 計測環境レジストリ | `measurement.yaml` | GA4 / GTM / Search Console / BQ / 広告アカウントID |
| KPI・ゴール・主要イベント | `kpis.yaml` | KGI / KPI（kpi_id 形式）/ key_events |
| 施策履歴 | `initiatives.yaml` | initiative_id / 期間 / 内容 / 対象KPI / 結果 |
| 前提・制約(gotchas) | `constraints.yaml` | 誤分析防止の注意点 / 命名規則 / 未解決課題 |
| ステークホルダー | `stakeholders.yaml` | 決裁者 / 担当 / 連絡先 |
| 分析・アウトプット履歴 | `analysis-history.yaml` | 各エージェントのfindings蓄積（引き継ぎ） |
| 議事録 | `meetings/*.md` | クライアント / 社内MTG |

### 📤 全エージェントへの前提情報提供（共通ローダー）
`context_store` パッケージを他エージェントが import し、`load_context(client_id)` で
クライアント前提を取得。`summary_markdown()` で gotchas / KPI / 計測ID / 直近findings を
プロンプトに注入できる。→ 連携仕様は [docs/integration-interface.md](./docs/integration-interface.md)。

---

## 構成

```
01_context_management/
├── README.md / spec.md / run.md
├── pyproject.toml            # 依存: pyyaml
├── prompts/context-manager.md   # 対話駆動の入力/更新プロンプト
├── src/context_store/
│   ├── loader.py             # load_context() / list_clients() / ClientContext
│   └── schema.py             # ファイル定義 + 軽量バリデーション
├── schema/context-schema.md  # 各YAMLの正典スキーマ
├── templates/                # 新規クライアント雛形
├── samples/sample-client/    # フル記入例（commit対象）
├── docs/integration-interface.md   # 他エージェントの参照IF定義
└── context/<client_id>/      # ★クライアント実データ（.gitignore対象）
```

> `context/` 配下はクライアント実データのため `.gitignore` 済み。commit されるのは
> スキーマ・テンプレート・サンプルのみ。

---

## クイックスタート

```bash
cd 01_context_management
uv sync

# どこからでも import できるようにする（他エージェントから使う場合。リポジトリルートで一度実行）
cd .. && uv pip install -e 01_context_management/

# 既存クライアント一覧
cd 01_context_management && uv run python -c "from context_store.loader import list_clients; print(list_clients())"

# サンプルを試す（samples を context にコピー）
cp -r 01_context_management/samples/sample-client 01_context_management/context/sample-client
cd 01_context_management && uv run python -c "from context_store.loader import load_context; print(load_context('sample-client').summary_markdown())"

# 分析完了時の書き戻し
cd 01_context_management && uv run python -c "from context_store.writeback import append_finding; append_finding('sample-client', agent='demo', summary='...', findings=['...'], outputs=['...'])"
```

> installable化前からの `PYTHONPATH=01_context_management/src python -c "..."` 方式も後方互換で動く（[docs/integration-interface.md](./docs/integration-interface.md) §2）。

> **Windows + Git Bashで日本語が文字化けする場合**: ファイル自体はUTF-8で正しく書かれており、
> 画面表示だけの問題。コマンドの先頭に `PYTHONIOENCODING=utf-8` を付けて実行すると直る（例:
> `PYTHONIOENCODING=utf-8 uv run python -c "..."`）。

対話で新規登録する場合は `prompts/context-manager.md` を起動する（→ [run.md](./run.md)）。

---

## ステータス
- Phase 1 (W4): ストア + スキーマ + 共通ローダー + 対話プロンプト + 連携IF定義
- Phase 2 / PR-B (2026-07-13): 02/05/06/07 の主要プロンプトへの接続（Step 0 読み込み＋完了時書き戻し）、
  `aliases` によるclient_id別名解決、`append_finding()` 書き戻しヘルパー、pip installable化 ← 本実装
  （詳細: [docs/integration-interface.md](./docs/integration-interface.md)）
