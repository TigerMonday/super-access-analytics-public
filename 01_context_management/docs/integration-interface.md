# コンテキストストア 連携インターフェース定義

他の全エージェントが、コンテキストストア（`01_context_management/context/<client_id>/`）を
**どう参照するか**の規約。

> **2026-07-13 PR-B 実装済み**: 01 は `uv pip install -e 01_context_management/` で
> `import context_store` が通る installable パッケージになった（`PYTHONPATH=src` 方式も後方互換で
> 動く）。`load_context()` は別名（`profile.yaml` の `aliases`）解決に対応し、`context_store.writeback.append_finding()`
> で各エージェントから `analysis-history.yaml` への書き戻しができる。03/05/06/07 の主要プロンプトへの
> Step 0（読み込み）・末尾（書き戻し）の接続はこの PR で完了済み。

---

## 1. 解決する課題

| 現状の課題 | コンテキストストアでの解決 |
|---|---|
| 各エージェントが毎回 client名 / GA4 ID / KPI / key_events を聞く | `load_context()` で自動補完、無ければ従来の対話にフォールバック |
| findings がエージェント間で引き継がれない | `analysis_history.yaml` の findings を後続が参照 |
| サイト固有のgotchas（CVR分母等）の取りこぼし | `summary_markdown()` が gotchas を先頭で注入 |
| KPI / 命名規則の定義がエージェントごとにブレる | `kpis.yaml` / `constraints.yaml` を単一の正典に |

---

## 2. Python系エージェントの参照方法

`04_traffic_analysis/parameter_management`、`07_adhoc_analysis`、`02_basic_measurement/measurement_design` 等。

### import 設定（2026-07-13〜: installable化）
01 は `uv pip install -e 01_context_management/`（または各エージェントの venv 内で
`pip install -e ../01_context_management`）を実行すれば、どこからでも `import context_store` が
そのまま通る（`pyproject.toml` に `[build-system]` を追加し、`src/context_store` をパッケージとして
ビルドする構成にした）。

```bash
uv pip install -e 01_context_management/     # リポジトリルートで一度実行すればよい
```

```python
from context_store.loader import load_context, list_clients
from context_store.writeback import append_finding
```

#### 後方互換: `PYTHONPATH=src` 方式（installable化前からの既存手順）
インストールしない/できない環境向けに、従来の `sys.path` 追加方式も引き続き動く。

```python
import sys
from pathlib import Path

# 各エージェントから 01_context_management/src への相対パスを追加
CONTEXT_SRC = Path(__file__).resolve().parents[2] / "01_context_management" / "src"
sys.path.insert(0, str(CONTEXT_SRC))

from context_store.loader import load_context, list_clients
```

プロンプト駆動エージェントの `python -c` ワンライナーでは、`cd 01_context_management && uv run python -c ...`
を使う統一形にしている（§3 参照）。

### 起動時のコンテキスト補完パターン
```python
ctx = load_context(client_id)            # 無ければ空コンテキスト（落ちない）

# 1) 各種IDをストアから補完、無ければ従来通り対話で聞く
property_id = ctx.ga4_property_id or ask_user("GA4 property ID は？")
key_events  = ctx.key_events or ask_user("キーイベント名は？")

# 2) gotchas / findings を分析の前提として読み込む
preface = ctx.summary_markdown()         # プロンプト/レポート冒頭に注入

# 3) バリデーション警告があれば提示
for w in ctx.validate():
    log.warning(w)
```

### 利用できる主な API
| API | 返り値 | 用途 |
|---|---|---|
| `load_context(client_id)` | `ClientContext` | 全YAML + 議事録を統合。`client_id` が別名（`aliases`）なら正規IDに解決してから読む |
| `resolve_client_id(client_id)` | `str` | 別名 → 正規ID の解決のみ行う（`load_context` が内部で呼ぶものと同じ関数） |
| `list_clients()` | `list[str]` | 登録済みクライアント一覧 |
| `ClientContext.summary_markdown()` | `str` | 前提情報サマリ（gotchas/KPI/計測ID/findings） |
| `ClientContext.ga4_property_id` | `str \| None` | GA4 プロパティID |
| `ClientContext.key_events` | `list[str]` | CV計算用イベント |
| `ClientContext.profile / .measurement / .kpis / .initiatives / .constraints / .stakeholders / .analysis_history / .meetings` | `dict` / `list` | 各カテゴリ生データ |
| `ClientContext.validate()` | `list[str]` | 整合性警告 |
| `append_finding(client_id, agent, summary, findings, outputs, date=None)`（`context_store.writeback`） | `Path` | `analysis-history.yaml` への書き戻し（§4） |

#### client_id の別名解決（aliases）
`profile.yaml` に `aliases: [旧clientフォルダ名, 略称, 表記ゆれ, ...]` を登録しておくと、
`load_context('旧clientフォルダ名')` のように別名で呼んでも正規の `client_id` に解決される。
解決時は stderr に `別名 X を正規ID Y に解決しました` と1行出る。同じ別名が複数クライアントに
登録されている場合は `ValueError` になる（どちらを使うべきか人が決めて重複を解消する）。

---

## 3. プロンプト系エージェント（Markdownのみ）の参照方法

`03_external_research/web_research` 等、Pythonを持たないエージェント。
起動フローの先頭に以下の**標準スニペット**を追記する（`cd 01_context_management && uv run python -c ...`
の形でプロンプトのワンライナーを統一する）。

```markdown
### Step 0: 01コンテキストストア読み込み（共通）
- 実行: `cd 01_context_management && uv run python -c "from context_store.loader import load_context; print(load_context('{client_id}').summary_markdown())"`
- 出力された「クライアント前提」（クライアント名・GA4プロパティID・キーイベント・命名規則・gotchas）を前提として取り込み、**ユーザーには聞き直さない**。無い項目だけ質問する。
- gotchas（⚠ 分析時の注意）は必ず遵守する。
- client_id が01に未登録（出力が空）の場合は、01登録（`01_context_management/prompts/context-manager.md`）をユーザーに促し、いったん中断する。
```

2026-07-13 PR-B でこの標準スニペットを 03/05/06/07 の主要プロンプトに接続済み（`{client_id}` は各エージェントの起動時にユーザーから受け取った値に置換する）。

---

## 4. 書き戻し規約（findings 引き継ぎ）

各エージェントは **完了時に `analysis_history.yaml` へ 1 エントリ追記** する。これにより
後続エージェントが `summary_markdown()` 経由で直近findingsを受け取れる。

2026-07-13 PR-B で追記ヘルパー `context_store.writeback.append_finding()` を実装済み。
手動でYAMLを編集する必要はない。

```python
from context_store.writeback import append_finding

append_finding(
    "<client_id>",
    agent="04_parameter_management",       # テーマ番号を付けた自エージェント名
    summary="utm監査と基本分析を実施",
    findings=["後続が知るべき発見を箇条書き"],
    outputs=["outputs/<client_id>/2026-06-08_report.html"],
    # date は省略可（省略時は当日）
)
```

プロンプト駆動エージェントからは以下のワンライナー例で呼べる:

```bash
cd 01_context_management
uv run python -c "
from context_store.writeback import append_finding
append_finding('{client_id}', agent='{agent_name}', summary='{summary}',
    findings=['{finding1}'], outputs=['{output_path}'])"
```

`entries` は `context/<client_id>/analysis-history.yaml` に追記される。ファイルや `entries`
キーが無ければ `append_finding()` が新規作成する:

```yaml
entries:
  - date: "2026-06-08"
    agent: parameter_management
    summary: utm監査と基本分析を実施
    findings:
      - 後続が知るべき発見を箇条書き
    outputs:
      - outputs/<client_id>/2026-06-08_report.html
```

> `client_id` は別名解決を通る（§2 参照）。手動追記・context-manager エージェント経由の追記も
> 従来通り可能。

---

## 5. 各エージェントの接続状況

| エージェント | 補完できる入力 | 接続状況 |
|---|---|---|
| parameter_management | client名 / GA4 ID / key_events / 命名規則 / gotchas | 接続済み |
| adhoc_analysis | client名 / GA4 ID / 過去findings / 未解決課題（問いの起点） | 接続済み（読み込み・書き戻しとも） |
| measurement_design | kpis.yaml（既に互換形式） / screen-flow | 接続済み（id_resolver.py / kpi_coverage.py） |
| 06 effect_verification | 施策履歴（initiatives）/ 対象KPI | 接続済み（06 各レビューにStep 0＋書き戻し） |
| 05 campaign_optimization（analysis/creation/page_profile） | client名 / GA4 ID / KPI / ターゲット / gotchas / initiatives | 接続済み |
| 03 external_research | client名 / 01登録状況 | 接続済み（external-research-coordinator） |

このリポジトリには GA4/BigQuery/Search Console を使った監視・アラート機能（monitoring dashboard/alert）は含まれない。
