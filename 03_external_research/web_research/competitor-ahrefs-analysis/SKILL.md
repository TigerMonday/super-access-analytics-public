---
name: competitor-ahrefs-analysis
description: |
  Ahrefs（CSVエクスポート or 公式MCPサーバー経由）を用いて、競合サイトのオーガニック検索順位・キーワードギャップ・被リンク・SERP オーバーラップを分析し、SEO/コンテンツ戦略の打ち手を整理する。「順位」「検索ボリューム」「KD（難易度）」「被リンク強度」を一次根拠で見たい場面で使う。**Ahrefs の契約（API トークン）が必要な任意の機能**。トリガー語: 「Ahrefsで競合キーワードを分析」「SEOキーワードギャップ」「被リンクの差を見たい」「KDで打ち手の優先順位を決めたい」「SERPの被覆を見たい」「Brand Radar で AI 検索の引用状況を見たい」。
---

# 競合 Ahrefs 分析

開始前に `../research-quality-standard.md` を全文読み、比較条件・根拠台帳・成果物へ適用する。

Ahrefs から取得できる SEO データ（順位・KD・検索ボリューム・被リンク・SERP・Brand Radar 等）を使って、
競合との SEO ポジションを分析し、コンテンツ／被リンク戦略の打ち手を整理する。

## 前提（必ず最初に確認）

**このスキルは Ahrefs の契約（API トークン）が無いと使えない任意機能。** Ahrefs を契約していない
案件では、このファイルの手順は読み飛ばして問題ない（統括スキル
`external-research-coordinator` 経由の実行では、トークンが無ければこの子スキルの章を
丸ごとスキップし、他の子スキルだけでレポートを成立させる）。

## いつ使うか

- 競合との**検索順位・検索ボリューム・KD（難易度）・被リンク**の差を一次データで確認し、打ち手の優先順位を決めたい
- 競合の被リンクプロファイルから、自社の獲得余地（参考にできる外部メディア）を割り出したい
- AI 検索（ChatGPT / Perplexity 等）でブランド名がどう引用されているかを Brand Radar で見たい
- 提案資料の「SEO・コンテンツ戦略」章を作る
- 他の市場・顧客理解の子スキルで見えた「自社が取れていない一般語」を、順位・ボリューム・被リンクの一次データで打ち手に落としたい

## 前提

利用形態は 3 通り：

| 形態 | 説明 | 入力 |
|---|---|---|
| **直接API（推奨）** | `scripts/fetch_ahrefs.py` で Ahrefs API v3 を直接叩く。トークン管理・キャッシュ・エンベロープ保存込み | 対象ドメイン / 競合ドメイン / キーワード |
| **Ahrefs MCP** | 本環境で `mcp__claude_ai_Ahrefs__*` ツールが使える場合の代替手段 | 対象ドメイン / 競合ドメイン |
| **CSV エクスポート** | Ahrefs UI から各レポートを CSV ダウンロード（MCP・直接APIどちらも使えない場合の最終手段） | `reference/Ahrefs/*.csv`（Organic Keywords / Top Pages / Backlinks 等） |

**直接APIが使える環境では最優先で使う**（`scripts/fetch_ahrefs.py`。設計の背景は
[analysis-design.md](./analysis-design.md) 参照）。使用例（各サブコマンド1行。`--client` `--own` 等は
サンプル値。実際のクライアントID・ドメインに置き換えて使う）:

```bash
# 残ユニット確認（実行前に必ず。--client 不要）
uv run python scripts/fetch_ahrefs.py limits

# 複数ドメインのDR・被リンク・オーガニックKW数を横並び取得（UC-1）
uv run python scripts/fetch_ahrefs.py overview --client sample-client --targets example.com,example.org,example.net

# 単一ドメインのオーガニックキーワード（UC-2: キーワードギャップの元データ）
uv run python scripts/fetch_ahrefs.py organic-keywords --client sample-client --target example.com --min-volume 100 --max-position 10 --limit 1000

# 単一ドメインの参照ドメイン（UC-3: 被リンクギャップ）
uv run python scripts/fetch_ahrefs.py refdomains --client sample-client --target example.com --min-dr 50 --limit 500

# キーワードのSERP上位10件（UC-4: SERP実勢確認）
uv run python scripts/fetch_ahrefs.py serp --client sample-client --keyword "アクセス解析"

# 複数キーワードのvolume/KD/CPC
uv run python scripts/fetch_ahrefs.py kw-overview --client sample-client --keywords "アクセス解析,GA4,ヒートマップ"

# キーワードギャップ（UC-2）＋被リンクギャップ（UC-3）を決定論的に計算（推奨。手で再実装しない）
uv run python scripts/fetch_ahrefs.py gap --client sample-client --own example.com --competitors example.org,example.net --exclude "サンプル社,サンプルブランド"
```

共通フラグ: `--client`（必須。`outputs/{client}/_data/ahrefs/` に保存）, `--country jp`（既定）,
`--refresh`（キャッシュ無視で再取得）, `--cache-days`（2026-07-14〜 未指定ならエンドポイント別既定値:
overview系[domain-rating/backlinks-stats/metrics]・refdomains=30日、organic-keywords=14日、
serp-overview=7日。明示指定すれば従来通りそれが最優先）。
認証は環境変数 `AHREFS_API_TOKEN` → `~/.saa/credentials/ahrefs/token.txt` の順で解決。
トークン未設定で実行すると、その旨（Ahrefsの契約が必要であること）を明示したエラーで止まり、
生のAPIエラーは出ない。

MCP や CSV しか使えない環境では以下を代替手段として使う。MCP が使える場合はそちらを優先
（パラメータをそのまま渡せる、最新データが取れる）。
**MCP を初めて使うときは `mcp__claude_ai_Ahrefs__doc` を先に呼んでパラメータ仕様を確認すること**
（Ahrefs MCP の利用ルール）。

ユーザーから以下を最初に聞いておく：

- 対象ドメイン（自社）
- 競合ドメイン（3〜5 社）
- 対象地域（country / locations）。日本案件なら `JP`、英語圏なら `US/UK/AU` 等
- 取得期間（順位履歴を見たいなら 12〜24 ヶ月、現状把握なら直近スナップショットでも可）
- Ahrefs サブスクリプションのプラン（Lite / Standard / Advanced / Enterprise）と残クレジット
  （Ahrefs はクエリごとに行数クレジットを消費するため、無駄打ちしない）

## アウトプット

`outputs/{client_id}/03_research/YYYYMMDD_competitor_ahrefs/ahrefs_analysis.md` に以下
（コーディネーター経由の場合は統合フォルダの `07_ahrefs_analysis.md` として。生データ（APIレスポンス）は
fetch_ahrefs.py が `outputs/{client_id}/_data/ahrefs/` に自動保存するので、レポートに転記した数値の
一次根拠はそこに残る）：

1. **オーガニック検索ポジション**（DR・参照ドメイン数・オーガニック流入推計の横並び）
2. **キーワードギャップ**（自社未取得 × 競合上位 × ボリューム × KD）
3. **SERP オーバーラップ**（同じクエリで何社が上位を取り合っているか）
4. **被リンクプロファイル**（DR分布、リンク獲得チャネル、Lost/New の動き）
5. **Brand Radar（任意）**：AI 検索における引用状況・SOV
6. **打ち手の優先順位**（KD と検索ボリュームのマトリクスで 5〜10 個）

## 標準フロー

### Phase 0: スコープ確定

```
- 自社ドメイン:
- 競合ドメイン: ___ x N
- 対象地域: JP / US / etc
- 取得期間: 12ヶ月 / 24ヶ月 / 最新スナップショット
- Ahrefs 利用形態: MCP / CSV / 両方
- Brand Radar を使うか: yes / no
- クレジット制約: 残 X 行 / 無制限
```

### Phase 1: ドメイン全体のオーガニックポジション

MCP の場合：

```
mcp__claude_ai_Ahrefs__site-explorer-domain-rating
  target=<domain>
mcp__claude_ai_Ahrefs__site-explorer-metrics
  target=<domain>, country=<JP|US|...>
```

CSV の場合：Site Explorer > Overview のエクスポートを使う。

5 社の **DR（Domain Rating）/ 参照ドメイン数 / オーガニックキーワード数 / オーガニック流入推計** を表で並べる：

```markdown
| サイト | DR | 参照ドメイン数 | オーガニックKW | 流入推計（月） |
|---|---:|---:|---:|---:|
| 自社 | 52 | 1,200 | 8,500 | 45K |
| 競合A | 68 | 5,400 | 35,000 | 320K |
| 競合B | 61 | 2,800 | 18,000 | 180K |
| ... | | | | |
```

### Phase 2: キーワードギャップ

**直接APIの場合は `gap` サブコマンドを使う**（計算はコードに固定されており、手で再実装しない。
抽出条件・KD閾値・推奨アクション判定は [analysis-design.md](./analysis-design.md) UC-2 を参照）：

```bash
uv run python scripts/fetch_ahrefs.py gap --client sample-client \
  --own example.com --competitors example.org,example.net \
  --exclude "サンプル社,サンプルブランド"
```

**抽出条件**（標準。`gap` のデフォルト値と一致）：
- 検索ボリューム ≥ 100/月
- 競合の順位 ≤ 10（1ページ目）
- 自社の順位 > 20（or 未取得）
- ブランド検索除外（社名・サービス名・URL 片を含むものを除く。`--exclude` で指定）

**KD（Keyword Difficulty）フィルタ**：DR と KD のバランスで「現実的に取れるキーワード」に絞る。
`gap` は自社 DR から自動でKD閾値を選ぶ（`--kd-max auto`。DR〜39→KD<30 / 40〜59→KD<45 / 60〜→KD<60）。
閾値以下は「優先」、超過は「参考（KD高）」として結果JSONに分けて保持される。

MCP：`mcp__claude_ai_Ahrefs__site-explorer-organic-keywords` を競合別に取り、自社の順位と突合。
CSV：`Organic Keywords` エクスポートを競合別に取得。

**CSVエクスポート利用時のみの参考**（MCP・直接APIどちらも使えず、CSVを手作業で突合する場合の実装例。
直接APIが使える場合は上記の `gap` サブコマンドを使うため、このコードは書き写さない）：

```python
import csv

def keyword_gap(ours_csv, theirs_csv, min_volume=100, ours_rank_min=20, theirs_rank_max=10):
    ours = {r['Keyword']: int(r['Position']) for r in csv.DictReader(open(ours_csv))}
    out = []
    for r in csv.DictReader(open(theirs_csv)):
        if int(r['Volume']) < min_volume: continue
        if int(r['Position']) > theirs_rank_max: continue
        our_pos = ours.get(r['Keyword'], 999)
        if our_pos < ours_rank_min: continue
        out.append({'kw': r['Keyword'], 'volume': r['Volume'],
                    'their_pos': r['Position'], 'our_pos': our_pos,
                    'kd': r.get('KD', '')})
    return sorted(out, key=lambda x: -int(x['volume']))
```

### Phase 3: SERP オーバーラップ

`mcp__claude_ai_Ahrefs__serp-overview` で個別キーワードの SERP を見て、誰が上位を取り合っているか。
**自社が想定していない競合**が SERP 上位にいる場合、コンテンツ構造の参考にする。

```markdown
| キーワード | Vol | KD | 1位 | 2位 | 3位 | 5位 | 自社順位 |
|---|---:|---:|---|---|---|---|---:|
| <主要KW> | 8,000 | 35 | 競合A | 競合B | メディアX | 競合C | 28 |
```

### Phase 4: 被リンクプロファイル

直接APIの場合、`gap` サブコマンドが被リンクギャップ（競合だけが持つ参照ドメイン。UC-3）も
同時に計算・保存する（`backlink_gap` 配列。「何社の競合からリンクされているか」降順→DR降順）。
被リンク獲得候補メディアのリストが欲しいだけなら、Phase 2 と同じ `gap` 実行の出力で足りる
（`refdomains` を個別に叩き直して手で突合する必要はない）。

MCP：
- `mcp__claude_ai_Ahrefs__site-explorer-backlinks-stats`：被リンク数・DR 分布
- `mcp__claude_ai_Ahrefs__site-explorer-referring-domains`：参照ドメイン
- `mcp__claude_ai_Ahrefs__site-explorer-refdomains-history`：参照ドメインの時系列推移

```markdown
| サイト | 被リンク数 | 参照ドメイン | DR70+ 比率 | 直近12ヶ月の新規RD |
|---|---:|---:|---:|---:|
| 自社 | 4,500 | 480 | 8% | +60 |
| 競合A | 95,000 | 5,200 | 22% | +850 |
```

**読み解きポイント**：
- 競合の **新規参照ドメインの月次トレンド** を見る。急増中の競合は PR 投資・コンテンツ施策が走っている可能性
- 競合の **DR70+ の被リンク獲得元**（メディア名）を抽出 → 自社の獲得アプローチ候補

### Phase 5: Brand Radar（AI 検索引用、任意）

Ahrefs Brand Radar は AI 検索（ChatGPT / Perplexity / Gemini 等）における引用状況を測れる。
B2B SaaS や知名度勝負の領域では強力。

- `mcp__claude_ai_Ahrefs__brand-radar-mentions-overview`：言及数の概観
- `mcp__claude_ai_Ahrefs__brand-radar-sov-overview`：Share of Voice
- `mcp__claude_ai_Ahrefs__brand-radar-cited-pages`：どのページが AI に引用されたか

```markdown
| 製品 | AI 言及数 | SOV | 主要引用ページ |
|---|---:|---:|---|
| 自社 | 320 | 8% | <記事URL> |
| 競合A | 1,850 | 42% | <記事URL> |
```

### Phase 6: 打ち手の優先順位マトリクス

KD（横軸）× 検索ボリューム（縦軸）で、Phase 2 で抽出したキーワードを散布図化。
**右下（KD 低 × ボリューム高）** が最優先。**左上（KD 高 × ボリューム低）** は捨てる。

```markdown
| 優先度 | キーワード | Vol | KD | 競合上位 | 打ち手 |
|---|---|---:|---:|---|---|
| 高 | <KW1> | 12K | 24 | 競合B | 既存記事のリライト＋関連ページ増設 |
| 高 | <KW2> | 8K | 31 | 競合A, B | 新規ピラーページ作成 |
| 中 | <KW3> | 3K | 18 | 競合C | 既存記事の内部リンク強化のみ |
| ... | | | | | |
```

## やってはいけないこと

- **Ahrefs の Traffic 列を絶対値として断定的に語らない**（推計）。一次根拠は **Volume × CTR**（順位別 CTR 表）で再計算
- **ブランド検索と一般語を混ぜたランキングを出さない**（示唆がぼやける。除外処理を必ず通す）
- **KD だけで打ち手を決めない**（KD が高くても自社の DR / トピカル権威があれば狙える）
- **データ取得日を残さない**（順位は日次で動くため再現性が無くなる）
- **Brand Radar の数値を「SEO 流入の代替」として読まない**（AI 引用は補完指標であって SEO 流入とは別物）
- **クレジットを浪費するクエリを乱発しない**（特に site-explorer-all-backlinks は大量行を返す。フィルタを必ず付ける）
- **Ahrefs未契約なのに他の手段を案内せず作業を止める**（このスキルが使えないだけで、他の市場・顧客理解の子スキルは動く）

## 関連スキル

- `competitor-desk-research` — 競合の Web 表層・コンテンツ設計の質的観点。本スキルで出した「打ち手キーワード」が既存コンテンツのどこに当たるかを照合

## 参考: Ahrefs MCP の使い方

このプロジェクトでは `mcp__claude_ai_Ahrefs__*` の MCP ツールが使える環境を想定している。
利用前に必ず：

1. **`mcp__claude_ai_Ahrefs__doc`** を呼んで該当 API のパラメータ仕様を確認
2. **`mcp__claude_ai_Ahrefs__subscription-info-limits-and-usage`** で残クレジットを確認
3. **金額は USD cents で返ってくる**（`value`, `org_cost` 等）。表示時は 100 で割って USD に
4. レスポンスに `render_with` が含まれる場合は指定された **render-* ツール** を呼ぶ（テーブル / スコアカード / 時系列チャート）
