# report_export_bridge

今回だけの形式指定は `export_if_configured(..., output_formats=["html"])` のように渡す。`None`（省略）は保存済み設定、`[]` は今回だけMDのみ。保存済み設定は書き換えない。計測のCLIでは `review --output-formats html` / `review --output-formats md`（`run`も同様）を使う。

01（`context_store`）の `preferences.output_formats`（成果物の既定変換形式）を読み、
指定があれば成果物のMarkdownを `common/report_export` で自動変換する橋渡し。
特定のエージェント専用ではない（`common/ga4_fetch`・`common/report_index` と同じ、
テーマ横断の共通実装）。

外部依存パッケージは無い（標準ライブラリのみ）。`report_export` 本体は `subprocess` で
別プロセスとして呼ぶため、呼び出し元パッケージの仮想環境に依存を追加しない。

## 使い方

呼び出し元（`run.py` を持つエージェント）の起動時に、自分の `sys.path` へこのフォルダを
足してから import する（02の `run.py` を参照）。

```python
import sys
from pathlib import Path

sys.path.insert(0, str(REPO_ROOT / "common" / "report_export_bridge"))
from report_export_bridge import export_if_configured

outcome = export_if_configured([md_path], client_id)
for path in outcome.generated:   # 実際に書き出せた先（ローカルファイルのPath、またはGoogle document/sheetのURL文字列）
    print(path)
for warning in outcome.warnings:  # 設定はあったが一部/全部書き出せなかった理由（日本語）
    print(warning)
```

- `output_formats` が未設定（一度も聞いていない）または空リスト（MDのみを明示済み）なら
  何もしない。
- `gdoc`/`gsheet` は書き込み先URL（`google_doc_url`/`google_sheet_url`）が01に無いと
  成立しない（サービスアカウントは自分でファイルを作れないため）。無ければその形式だけ
  諦め、`warnings` に理由を積む（他の形式の変換は続ける）。
- 変換・書き込みに失敗しても例外は投げない。成果物のMarkdown自体は生成済みという前提を
  守り、失敗の理由は `warnings` に積んで呼び出し元へ返す（黙って無かったことにはしない）。

## テスト

```bash
cd common/report_export_bridge
uv sync --extra dev
uv run pytest
```

## 現状（2026-09時点）でこれを呼んでいるエージェント

- 02（計測設計）の `run.py review`

03・04・05・06・07 はAIエージェントが `run.md`/プロンプトに従ってMarkdownを書く形で、
Pythonの `run.py` を持たない。そちらの成果物変換は各機能の正本と
`common/report_export/README.md` に従い、現在のAIエージェントが実行する。今後 `run.py` を持つ
エージェントが増えたときは、02と同じ形（`sys.path` にこのフォルダを足して import）で使える。
