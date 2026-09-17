# run: コンテキスト管理エージェント 実行手順

ユーザーから「サイト情報を登録して」「分析対象を登録して」などと自然文で依頼されたら、この文書を入口にする。

## 自然文で依頼されたときの受付

1. `list_clients()` で登録済み一覧を確認する。依頼文に client_id があれば既登録か照合し、既登録なら更新、未登録なら新規登録へ進む。指定が無ければ、既存更新か新規登録かを利用者に確認する。
2. client_id は `^[A-Za-z0-9_-]+$` に合わせ、自社サイトも含めて以後同じ表記を使う。表記揺れは `aliases` で吸収する。
3. 新規登録では、対話を始める前にセッション開始時のフォルダ直下にある `CLAUDE.md`、議事録、資料、`docs`、`notes` 等を必要な範囲で読む。得られた情報は質問の下敷きにするが、「資料にはこうありますが合っていますか」と確認し、勝手に確定しない。何も無ければ通常の対話へ進む。
4. KPI・CVと対応するGA4イベント名を確認する。利用者が分からなければGA4のキーイベント設定・イベント一覧から候補を示して確認する。
5. `prompts/context-manager.md` の対話を実行し、保存後に `summary_markdown()` で確認する。
6. 完了時は保存先の絶対パス、確定した client_id、CVとGA4イベント名を示す。

## 0. セットアップ

```bash
cd 01_context_management
uv sync          # pyyaml を解決
```

他エージェントから import する場合は `uv pip install -e 01_context_management/`（リポジトリルートで一度実行）で
`import context_store` がそのまま通る。未インストールの環境向けに、従来の `PYTHONPATH=src` /
`sys.path.insert` 方式も後方互換で動くが、下記コマンド例は `uv run`（01_context_management配下で実行）で統一する。

---

## 1. 対話で前提情報を入力／更新する（メインの使い方）

`prompts/context-manager.md` を起動し、エージェントの誘導に従う。

1. 既存クライアント一覧の確認 → 既存更新 or 新規登録を選ぶ
2. カテゴリ別に対話入力（基本情報 → 計測環境 → KPI → 施策 → gotchas → ステークホルダー）
3. 議事録を貼り付けると `context/<client_id>/meetings/YYYY-MM-DD_<topic>.md` に保存
4. `summary_markdown()` で内容レビュー → 完了

雛形は `templates/*.template.yaml`、スキーマは `schema/context-schema.md` を参照。

---

## 2. ローダーを直接使う（他エージェント／確認用）

```bash
# 登録済みクライアント一覧
uv run python -c "from context_store.loader import list_clients; print(list_clients())"

# 特定クライアントの前提サマリ
uv run python -c "from context_store.loader import load_context; print(load_context('sample-client').summary_markdown())"

# 整合性チェック
uv run python -c "from context_store.loader import load_context; print(load_context('sample-client').validate())"
```

---

## 3. サンプルで動作確認

```bash
cp -r samples/sample-client context/sample-client
uv run python -c "from context_store.loader import load_context; print(load_context('sample-client').summary_markdown())"
```

`context/` は `.gitignore` 済みなので、コピーしたサンプルは commit されない。

---

## トラブルシュート

| 症状 | 対処 |
|---|---|
| `ModuleNotFoundError: context_store` | `python` を単体で呼んでいないか確認し、`uv run python` に切り替える（01_context_management配下で実行） |
| `list_clients()` が空 | `context/` 配下にクライアントフォルダが無い。対話入力 or サンプルをコピー |
| `summary_markdown()` が空に近い | 該当 YAML が未記入。`templates/` を雛形に埋める |
| YAML パース警告 | インデント崩れ。`schema/context-schema.md` の形式に合わせる |
| `ValueError: 不正な client_id` | client_id は英数字・ハイフン・アンダースコアのみ |
| Windows + Git Bashで日本語が文字化けする | ファイルはUTF-8で正しく書かれており画面表示だけの問題。`PYTHONIOENCODING=utf-8 uv run python -c "..."` のように先頭に付けて実行する |

---

## 他エージェントからの参照

連携方法（import パス設定、起動時の補完パターン、findings 書き戻し規約）は
[docs/integration-interface.md](./docs/integration-interface.md) を参照。
