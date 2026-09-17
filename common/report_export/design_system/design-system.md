# デザインシステム定義書

このファイルは、HTMLで作るすべての成果物（レポート・提案書・一枚もの・スライド）の見た目を統一するための唯一の定義書です。色・フォント・余白・部品の見た目をここに集約しています。トーンを変えたいときは各成果物を直すのではなく、まずこのファイルを直してください。

## AIエージェント向けの適用ルール

- HTMLの成果物を作るときは、必ずこのファイルの「コアCSS」を `<style>` の先頭に丸ごと埋め込む。
- 配布先で1ファイルで開ける必要があるため、外部CSSをリンク参照する作りにはしない。CSSは各HTMLに埋め込む。
- 色やフォントは下のCSS変数（トークン）を使う。生の色コードを直接書かない。
- 表・カード・コールアウトなどは下の共通部品クラスを使い回す。新しく似た見た目を作らない。
- 配布するレポートの土台は `report-template.html`。提案書・一枚もの・スライドの専用テンプレートは未提供。

## デザインの原則

- ベースは白黒グレー。文字・罫線・背景はすべてグレースケールにする。数値（データ）が主役。表とKPIは等幅数字で桁を揃え、数字を大きく黒く立てる。
- ゴールド（`--gold`）は強調にだけ使う。見出しラベル、選択中の項目、特に見せたいデータ系列に絞り、カードの上辺・左辺を飾る線には使わない。面での塗り分けも常用しない。
- 囲み枠を多用しない。カードやブロックは枠線で囲わず、薄いグレー面（`--gray-50`）と余白・級差で区切る。罫線は構造的に必要な所（表のヘッダ下・区切り）だけに細く使う。
- 角丸は使わない。`border-radius` は原則 0（直角）。丸を使うのはタイムラインのドットやプロットマーカーなど、丸であることに意味がある場合だけ。
- 緑は「良い結果」、赤は「悪い結果・要対応」に限る。分類、工程、確からしさを色分けしない。色だけに依存せず、「良好」「要対応」などの文字も併記する。
- 1面の主張は1つ。独立した情報が並列でない限り、小さなカードを敷き詰めた管理画面風の構成にしない。結論、根拠、次の行動の順に、余白と字の大きさで重みをつける。

---

## 1. デザイントークン（色・フォント）

トークンとは、色やフォントに名前をつけて一括管理する仕組みのこと。「ゴールド」を `--gold` という名前で持っておけば、後で色を変えても名前を使った箇所が全部まとめて変わる。

### 色の役割

- ゴールド（`--gold` #D4AF37）はブランドの差し色。アクセントとしてだけ使い、背景の塗りには使わない。文字に乗せるときは濃いめの `--gold-dark`（#9A7B1F）を使う。
- グレー系が主役。本文は `--gray-900`、本文濃いめは `--gray-700`、補足は `--gray-500`、罫線は `--gray-200`、薄い背景は `--gray-50`。
- 緑（`--green`）は良い数値結果、赤（`--red`）は悪い数値結果または要対応の状態に限る。その他は白・黒・グレーとゴールドで示す。

### 差し色を自社ブランドカラーに変える（利用者向け設定）

**このデザインシステムの既定ゴールドは固定の指定色ではない。** 利用者は、自社のブランドカラーに差し替えられる。変えられるのは差し色（グレースケール主体の3原則はそのまま）。

- 変えるのは `report_export`（`common/report_export`）の実行時オプションで、`design-system.md` や `report-template.html` を直接編集する必要はない。
  - CLI: `uv run python -m report_export input.md --to html --accent-color '#1D4ED8'`
  - 環境変数（CLIフラグが無いときのフォールバック）: `REPORT_EXPORT_ACCENT_COLOR=#1D4ED8`
  - ロゴも同じ場所で差し替えられる: `--logo path/to/logo.svg`（環境変数は `REPORT_EXPORT_LOGO_PATH`）。既定は `logo-placeholder.svg`。
  - **未指定なら何も変わらない**（既定のゴールド `#D4AF37` のまま）。設定した人だけ配色が変わる。
- **1色（基準となるHEX）を渡すだけでよい**。`--gold` / `--gold-dark` / `--gold-bright` / `--gold-soft` の4トークンは `src/report_export/accent_color.py` の `derive_palette()` が自動で導出する（色相・彩度を保ったまま明度だけを調整する方式）。
  - `--gold-dark` は実際に**文字色として**使われるトークン（`.section-label`・`.highlight-box strong` 等）。白背景とのコントラスト比が **4.5:1**（WCAG AA・通常サイズの文字の目安）を満たすまで自動的に暗くする。
    - 明るい色を指定すると読めなくなる実例: `#FFC800` を文字色にそのまま使うと白背景でのコントラスト比は約1.7:1しかなく読めない。`derive_palette()` はこの入力からでも、コントラスト比4.5:1以上を満たす暗い `--gold-dark`（例: `#8f7000` 前後）を自動生成する。利用者が自社カラーに明るい色を選んでも、同じ罠を踏まない。
    - `--gold`（罫線・下線などの非文字用途）も、白地でほぼ見えないほど薄い色（コントラスト比3:1未満）のときだけ少し暗くする。
  - 導出ロジックとコントラスト計算は `common/report_export/src/report_export/accent_color.py`、テストは `common/report_export/tests/test_accent_color.py`。
- 対象は HTML/PDF のみ（`--accent-color` は docx/xlsx には効かない。CSSが効かない形式のため。README参照）。
- **設定場所を `common/report_export` 側のCLI/環境変数にした理由**: このツールは「特定のエージェント専用ではない汎用ツール」（README参照）であり、SAAの01コンテキストストア（`context_store`）に依存させると汎用性が壊れる。SAA側で使うときは、01の `profile.yaml` の `preferences.accent_color` / `preferences.logo_path` に利用者の選択を保存し（`output_formats` と同じ仕組み。`docs/standard-run-order.md` §4-2参照）、各機能を実行しているAIエージェントがその値を読んで `--accent-color` / `--logo` に渡す。`report_export` 自体は `context_store` を一切importしない。

### フォント

游ゴシック系・Noto Sans JP を優先する日本語ゴシック。行間は 1.7。本文で太字装飾を多用しない（CLAUDE.mdの文章ルールに合わせる）。

### コアCSS（全成果物に丸ごと埋め込む）

```css
:root{
  --gold:#D4AF37; --gold-dark:#9A7B1F; --gold-bright:#E3C457; --gold-soft:#FBF6E8;
  --gray-50:#fafafa; --gray-100:#f5f5f5; --gray-200:#e5e5e5; --gray-300:#d4d4d4;
  --gray-400:#a3a3a3; --gray-500:#737373; --gray-700:#404040; --gray-900:#171717; --white:#ffffff;
  --red:#b91c1c; --red-soft:#fef2f2; --green:#15803d; --green-soft:#f0fdf4;
}
*{ margin:0; padding:0; box-sizing:border-box; }
html{ scroll-behavior:smooth; }
body{
  font-family:"Hiragino Kaku Gothic ProN","Noto Sans JP","Yu Gothic","Meiryo",sans-serif;
  color:var(--gray-900); line-height:1.8; -webkit-font-smoothing:antialiased;
  font-feature-settings:"palt" 1;
}

/* 見出し（成果物共通）─ ゴールドの縦罫は付けない。ラベルの短い横罫だけを差し色にする */
.section-label{ font-size:11px; font-weight:700; letter-spacing:.16em; text-transform:uppercase; color:var(--gold-dark); display:flex; align-items:center; gap:8px; margin-bottom:10px; }
.section-label::before{ content:""; width:16px; height:2px; background:var(--gold); flex:none; }
.section-title{ font-size:23px; font-weight:800; line-height:1.4; letter-spacing:-.01em; color:var(--gray-900); margin-bottom:14px; }
.section-summary{ font-size:14px; color:var(--gray-700); line-height:1.95; margin-bottom:20px; }

/* 表（数値が主役。縦罫・外枠なし、等幅数字、ヘッダ下と表尾を黒罫で締める） */
table.s-table{ width:100%; border-collapse:collapse; font-size:13px; margin-top:8px; font-variant-numeric:tabular-nums; font-feature-settings:"tnum" 1; }
table.s-table th{ text-align:left; padding:8px 12px; font-weight:700; font-size:11px; letter-spacing:.04em; color:var(--gray-500); border-bottom:1.5px solid var(--gray-900); white-space:nowrap; }
table.s-table td{ padding:9px 12px; border-bottom:1px solid var(--gray-200); vertical-align:top; color:var(--gray-700); }
table.s-table tbody tr:last-child td{ border-bottom:1.5px solid var(--gray-900); }
table.s-table th.r, table.s-table td.r{ text-align:right; white-space:nowrap; }
table.s-table td.r{ font-weight:700; color:var(--gray-900); }
table.s-table td:first-child code{ white-space:nowrap; }
/* 1列目の下限幅。auto layoutでは3列目以降の説明文が長いほど1列目が圧縮され、
   日本語は文字間で折り返せるため項目名が縦に何行も割れることがある(実データの
   判定表で確認)。10emは長めの項目名でも1〜2行に収める値で、URL等で元から
   幅が広い列(例: 02の集客レポート)には効かない(下限を上回っているため無風)。 */
table.s-table td:first-child{ min-width:10em; }
/* 「対象｜内容｜修正案｜重要度」の指摘表。内容列だけが幅を取り、修正案が
   PDFで1文字ずつ縦に割れるのを防ぐ。見出し構成が一致する表にだけ付与する。 */
table.s-table.action-table{ table-layout:fixed; }
table.s-table.action-table th:nth-child(1){ width:18%; }
table.s-table.action-table th:nth-child(2){ width:48%; }
table.s-table.action-table th:nth-child(3){ width:25%; }
table.s-table.action-table th:nth-child(4){ width:9%; }
table.s-table.action-table td:first-child{ min-width:0; }
table.s-table.action-table td:nth-child(-n+3){ overflow-wrap:anywhere; }
table.s-table.action-table td:nth-child(-n+3) code{ white-space:normal; overflow-wrap:anywhere; }
table.s-table.action-table th:last-child,
table.s-table.action-table td:last-child{ white-space:nowrap; }

/* 表のスクロール枠(列数が多く画面幅に収まらない表を包む)。
   ページ全体ではなく表の中だけを横スクロールさせる。収まる幅の表ではスクロールバーは出ない。
   印刷/PDF時は各テンプレの@media printでoverflow:visibleに戻し、右端が切れないようにする。 */
.table-scroll{ overflow-x:auto; }

/* ハイライト（薄グレー面のみ。ゴールドの縦罫は使わない） */
.highlight-box{ background:var(--gray-50); padding:16px 20px; margin-top:16px; font-size:13.5px; line-height:1.9; color:var(--gray-900); }
.highlight-box strong{ color:var(--gold-dark); font-weight:700; }

/* コールアウト（薄グレー面。記号は黒地に白で、ゴールドを面に塗らない） */
.callout{ display:flex; align-items:flex-start; gap:12px; margin-top:16px; padding:15px 18px; background:var(--gray-50); font-size:13px; line-height:1.9; color:var(--gray-700); }
.callout-icon{ flex-shrink:0; width:24px; height:24px; background:var(--gray-900); color:var(--white); display:flex; align-items:center; justify-content:center; font-size:13px; font-weight:700; }

/* KPI（数値が主役。装飾線を置かず、数字を大きく等幅に） */
.kpi-grid{ display:grid; grid-template-columns:repeat(3,1fr); gap:16px; margin-top:18px; }
.kpi-box{ padding:16px 18px; text-align:left; background:var(--gray-50); }
.kpi-box .kpi-label{ font-size:10px; font-weight:700; letter-spacing:.1em; color:var(--gray-500); margin-bottom:8px; }
.kpi-box .kpi-value{ font-size:38px; font-weight:800; line-height:1; color:var(--gray-900); letter-spacing:-.02em; font-variant-numeric:tabular-nums; font-feature-settings:"tnum" 1; }
.kpi-box .kpi-sub{ font-size:11px; margin-top:8px; color:var(--gray-500); }
.kpi-box .kpi-sub.up,.metric-good{ color:var(--green); }
.kpi-box .kpi-sub.down,.metric-bad{ color:var(--red); }

/* カード（囲まない。薄グレー面で区切る） */
.card{ padding:18px 20px; background:var(--gray-50); border:none; }
.card .card-title{ font-size:14px; font-weight:800; color:var(--gray-900); margin-bottom:7px; letter-spacing:-.005em; }
.card .card-body{ font-size:12.5px; color:var(--gray-700); line-height:1.85; }

/* ファインディングカード（下罫で区切るだけ。ゴールドの縦罫は付けない） */
.finding-card{ padding:15px 0; border-bottom:1px solid var(--gray-200); }
.finding-card:last-child{ border-bottom:none; }
.finding-card .fc-title{ font-size:13px; font-weight:800; margin-bottom:5px; color:var(--gray-900); letter-spacing:-.005em; }
.finding-card .fc-body{ font-size:12.5px; color:var(--gray-700); line-height:1.85; }

/* 考察（データと解釈を明確に分ける。箱の辺を強調しない） */
.insight-box{ background:var(--gray-50); padding:20px 24px; margin:12px 0 22px; font-size:16px; line-height:1.9; color:var(--gray-900); }

/* Markdownの表から生成するグラフ */
.report-chart{ margin:18px 0 20px; padding:12px 8px 4px; background:var(--white); overflow-x:auto; }
.report-chart svg{ width:100%; min-width:620px; height:auto; display:block; }
.chart-title{ font-size:14px; font-weight:800; fill:var(--gray-900); }
.chart-grid{ stroke:var(--gray-200); stroke-width:1; }
.chart-label{ font-size:10px; fill:var(--gray-500); }
.chart-legend{ font-size:10px; font-weight:700; fill:var(--gray-700); }
.chart-legend-rate{ fill:var(--gold-dark); }
.chart-bar{ fill:var(--gray-900); }
.chart-line{ fill:none; stroke:var(--gold-dark); stroke-width:2.5; }
.chart-point{ fill:var(--gold-dark); }
.table-visual-title{ margin:14px 0 8px; font-size:14px; font-weight:800; color:var(--gray-900); }
.table-bar-cell{ position:relative; isolation:isolate; display:block; margin:-9px -12px; padding:9px 12px; }
.table-bar-cell::before{ content:""; position:absolute; inset:0 0 0 auto; width:var(--bar-width); background:var(--gold-soft); z-index:0; }
.table-bar-value{ position:relative; z-index:1; }

/* 定性情報の比較図。分類に色を割り当てず、1つの平らな構成として見せる */
.visual-grid{ display:grid; grid-template-columns:repeat(auto-fit,minmax(210px,1fr)); gap:14px; margin:18px 0 22px; }
.visual-card{ padding:18px 20px; background:var(--gray-50); }
.visual-card.customer,.visual-card.competitor,.visual-card.company{ background:var(--gray-50); }
.visual-card .visual-label{ font-size:11px; font-weight:800; letter-spacing:.08em; color:var(--gray-700); margin-bottom:8px; }
.visual-card .visual-title{ font-size:16px; font-weight:800; line-height:1.5; color:var(--gray-900); margin-bottom:8px; }
.visual-card .visual-copy{ font-size:13px; line-height:1.75; color:var(--gray-700); }
.pictogram-grid{ display:grid; grid-template-columns:repeat(auto-fit,minmax(210px,1fr)); gap:14px; margin:18px 0 22px; }
.pictogram-item{ display:flex; align-items:flex-start; gap:14px; padding:18px 20px; background:var(--gray-50); }
.pictogram-mark{ flex:0 0 48px; width:48px; height:48px; color:var(--gray-900); }
.pictogram-icon{ display:block; width:48px; height:48px; }
.pictogram-text{ min-width:0; }
.pictogram-title{ font-size:14px; font-weight:800; line-height:1.5; color:var(--gray-900); margin-bottom:5px; }
.pictogram-copy{ font-size:12.5px; line-height:1.75; color:var(--gray-700); }
.journey-flow{ display:grid; grid-template-columns:repeat(5,minmax(190px,1fr)); gap:14px; margin:18px 0 22px; overflow-x:auto; padding:2px 2px 12px; }
.journey-step{ position:relative; min-width:190px; padding:16px; background:var(--gray-50); }
.journey-step:not(:last-child)::after{ content:"→"; position:absolute; top:18px; right:-13px; z-index:1; color:var(--gray-500); font-weight:800; }
.journey-stage{ font-size:12px; font-weight:800; color:var(--gray-900); margin-bottom:10px; }
.journey-copy{ font-size:12.5px; line-height:1.7; color:var(--gray-700); margin-bottom:10px; }
.journey-barrier,.journey-stimulus{ padding:9px 10px; margin-top:8px; font-size:11.5px; line-height:1.65; }
.journey-barrier{ background:var(--red-soft); color:var(--red); }
.journey-stimulus{ background:var(--green-soft); color:var(--green); }
.journey-barrier strong,.journey-stimulus strong{ display:block; font-size:10px; letter-spacing:.06em; margin-bottom:2px; }
.evidence-status{ display:inline-block; padding:2px 7px; font-size:10.5px; font-weight:800; white-space:nowrap; }
.evidence-status.confirmed{ color:var(--gray-900); background:var(--gray-100); }
.evidence-status.partial{ color:var(--gold-dark); background:var(--gold-soft); }
.evidence-status.hypothesis{ color:var(--gray-700); background:var(--gray-100); }
.status-card.ok{ background:var(--green-soft); }
.status-card.watch{ background:var(--gray-50); }
.status-card.action{ background:var(--red-soft); }
.status-card.ok .visual-label{ color:var(--green); }
.status-card.action .visual-label{ color:var(--red); }
.priority-flow{ display:grid; grid-template-columns:repeat(auto-fit,minmax(210px,1fr)); gap:14px; margin:18px 0 22px; }
.priority-step{ position:relative; padding:18px 20px; background:var(--gray-50); }
.priority-step.now,.priority-step.next,.priority-step.later{ background:var(--gray-50); }
.priority-step.now .priority-label{ color:var(--gold-dark); }
.priority-step .priority-label{ font-size:10.5px; font-weight:800; letter-spacing:.08em; color:var(--gray-700); margin-bottom:7px; }
.priority-step .priority-title{ font-size:16px; font-weight:800; line-height:1.5; color:var(--gray-900); margin-bottom:7px; }
.priority-step .priority-copy{ font-size:12.5px; line-height:1.75; color:var(--gray-700); }

```

---

## 2. 共通部品の使い方

各部品はそのまま使える。良い結果にだけ `--green`、悪い結果・要対応にだけ `--red` を使う。判定でない強調は `--gold-dark`、その他はグレースケールにする。

### 表（s-table）

数値の列には `class="r"` を付けて右寄せにする。割合は小数第1位、数値はカンマ区切り（CLAUDE.mdの数値ルール）。

列数が多く画面幅に収まらないおそれがある表は、`div.table-scroll` で包む。表の中だけが横スクロールし、ページ全体は横に広がらない（収まる幅の表ではスクロールバーは出ない）。report_export（Markdown→HTML変換）はこの包みを自動で付与する。手書きでHTMLを作るときも、列数が多い表には同様に付けること。

```html
<div class="table-scroll">
<table class="s-table">
  <thead>
    <tr><th>項目</th><th>説明</th><th class="r">数値</th></tr>
  </thead>
  <tbody>
    <tr><td>セッション</td><td>自然検索</td><td class="r">12,345</td></tr>
    <tr><td>CVR</td><td>前月比 +2.1pt</td><td class="r">3.4%</td></tr>
  </tbody>
</table>
</div>
```

印刷・PDF化するテンプレートでは、`@media print` で `.table-scroll{ overflow:visible; }` に戻すこと。印刷はスクロールできないため、`overflow-x:auto` のままだと表の右側が切れて消える。横5段のジャーニー図は `min-width` を解除し、5列を紙面幅へ収める（report-template.htmlの実装を参照）。

### ハイライトボックス（highlight-box）

そのセクションで一番伝えたい結論を、薄いグレー面で示す。ゴールドの左罫線は付けない（線が悪目立ちするため）。強調したい語だけ太字の `--gold-dark` にする。1つのセクションに1つまで。

```html
<div class="highlight-box">自然検索のCVRが<strong>前月比 +2.1pt</strong>。流入数より質の改善が効いている。</div>
```

### コールアウト（callout）

補足・注意点・次アクションを灰色の枠で添える。

```html
<div class="callout"><div class="callout-icon">!</div><div>計測期間にタグの不具合があり、4/3〜4/5のデータは参考値。</div></div>
```

### KPIカード（kpi-grid / kpi-box）

主要指標を横3つで並べる。数字は黒、面は薄いグレーとし、上辺や左辺に飾り線を付けない。良い増減には `up`、悪い増減には `down` を付ける。指標の増減だけで良否が決まらない場合は、無理に色を付けない。

```html
<div class="kpi-grid">
  <div class="kpi-box"><div class="kpi-label">セッション</div><div class="kpi-value">48,210</div><div class="kpi-sub">前月比 +8.3%</div></div>
  <div class="kpi-box"><div class="kpi-label">CV</div><div class="kpi-value">1,642</div><div class="kpi-sub">前月比 +12.1%</div></div>
  <div class="kpi-box"><div class="kpi-label">CVR</div><div class="kpi-value">3.4%</div><div class="kpi-sub">前月比 +0.3pt</div></div>
</div>
```

### カード（card）

同じ軸で並べて比較するときだけ使う見出し付きブロック。連続する説明や因果関係はカードに分割せず、本文と図表で1つの構成にする。

```html
<div style="display:flex; gap:16px;">
  <div class="card"><div class="card-title">課題</div><div class="card-body">本文</div></div>
  <div class="card"><div class="card-title">対応</div><div class="card-body">本文</div></div>
</div>
```

### ピクトグラム要約（pictogram-grid）

「課題・示唆・次の行動」のように2〜5個の要素が並ぶとき、見出しの識別を速くするために使う。
チャート・数値表・単一の主結論には置かず、装飾目的で全セクションへ付けない。ピクトグラムは
グレー系の1色のまま使い、差し色で塗らない。Markdownからの指定方法と利用できる名前は
`visualization-guidelines.md` の「Markdownから生成できるピクトグラム要約」を参照する。
使用時は単体HTMLの末尾へ出典を表示し、NOTICE／Apache License 2.0全文もHTML内へ同梱する。
PDFでは同じ全文を末尾の付録として出力する。

---

## 3. 成果物ごとのレイアウト方針

HTML/PDFの各面は1280×720px（16:9）に固定する。ブラウザでは面そのものを縦横比を保って
縮尺表示し、面の中のレイアウト幅や改ページ位置を画面寸法で変えない。PDFも同じ寸法を使う。

見た目の部品は共通。違うのは「全体の枠」だけ。

| 成果物 | 土台テンプレ | 枠の考え方 |
|---|---|---|
| レポート | `report-template.html` | 追従する目次で現在位置を示す。1280×720の白い面を並べる |
| 提案書・企画書 | 未提供 | 表紙＋セクション構成。各セクションは結論を先に置く |
| 一枚もの | 未提供 | 1ページに要点を凝縮。KPI＋ポイント数枚で完結させる |
| スライド | 未提供 | 1280×720の横スライド。本文は上テキスト→下ビジュアルの2ゾーン構成 |

レポートは左側に独立したナビゲーション面(目次)を置き、現在表示中の章を強調する。
本文は1280×720の固定面へ、**見出し、連続する段落、図表の意味単位**で配置する。
高さだけを見て文章や表の行を途中で切らない。原稿は、表の読み方・解釈・判断・指標定義を
表の前へ置き、表の後には出典・脚注だけを残す。説明と表、表と直後の脚注は同じ意味単位に残し、
その間を改ページ候補にしない。1つの意味単位自体が面へ収まらない場合は、文字を縮小したり
内容を隠したりせず、はみ出しとして明示する。PDF変換はその状態を検出して停止し、原稿側で
行数・文章量・見出し構成を見直す。画面では固定面全体を縮尺表示するため、ウィンドウの高さを
変えても改ページ位置は変わらない。目次は広い画面で左側に表示し、幅1100px以下では面の可読幅を
優先して非表示にする。紙面の角は丸めない。実装は `report-template.html` 先頭コメント参照。

ページ分割後に各面の実使用高を測り、余白が多い面だけ本文・見出し・表の行高を2段階で広げる。
これは内容を増やしたり別の意味単位を移したりする処理ではなく、同じ面の可読性を上げる表示調整と
する。拡大後に収まらない場合は1段階戻し、それでも収まらなければ標準密度へ戻す。密度調整を理由に
文字を縮小したり、内容を隠したり、表と解釈のまとまりを分割したりしない。

各図表は、その数値から読み取れる考察と同じ面に置く。数値セクションは根拠表、ラベルを付けない考察本文、グラフの順に並べる。1つの章に複数のグラフ・表があり、
別の面へ送る場合も、直前の考察を小さな考察欄として引き継ぐ。章名だけの「続き」と図表だけを
載せた面は作らない。章見出しと短い導入だけを1面に残し、最初の小見出し・表・図を次面へ送る構成も
作らない。この場合は章開始面の縦余白を詰め、章見出し・導入・最初の判断材料を同じ面に置く。
複数の表には表ごとの小見出しを付け、「小見出し＋説明＋表」を同じ意味単位にする。
図表ごとに判断が異なる場合は、原稿で各図表の直前へ個別の考察を書く。

狭い画面でも面の内部を組み替えず、1280×720の面全体を縮小する。列数や折り返しが変わって
ページ構成が揺れるのを防ぐためである。詳細を読む場合はブラウザの拡大機能を使う。

---

## 4. ロゴと取扱区分（Confidential）

社外共有する成果物は、各ページのフッターに「CONFIDENTIAL（中央）／ ページ番号（右）」を入れ、ロゴは表紙（1ページ目）のタイトル上にだけ置く。提供元を明示し、取扱注意であることを示す。

- ロゴは `--logo path/to/logo.svg` または環境変数 `REPORT_EXPORT_LOGO_PATH` で指定する。未指定時は表示しない。`logo-placeholder.svg` は見本であり、差し替えて使う場合もそのファイルを明示指定する。base64化・data URI埋め込みは実行時に行う。
- 配布物は1ファイルで開ける必要があるため、ロゴSVGは**base64の data URI 化して埋め込む**（外部参照にしない）。ロゴは**表紙のタイトル上に `height:24px` 程度**で置き、フッターには入れない。
- CONFIDENTIAL は小さく（9〜10px）・字間広め・淡色（`--gray-400`）の大文字。枠で囲わず文字だけで示す。ゴールドは使わない。
- スライドのフッターは `.slide::after`（CONFIDENTIAL）を全ページに自動付与し、ページ番号は `.slide-num` で置く。ロゴはフッターに入れず、表紙の本文先頭に `.cover-logo` をタイトル（`.cover-line`）の上へ置く。

```css
/* フッター（全ページ）：CONFIDENTIAL（中央）＋ページ番号（右）。縦中心を下から22pxに揃える */
.slide-num{ position:absolute; right:56px; bottom:16px; line-height:12px; font-size:11px; color:var(--gray-300); font-weight:600; }
.slide::after{ content:"CONFIDENTIAL"; position:absolute; left:50%; transform:translateX(-50%); bottom:16px; line-height:12px;
  font-size:9px; font-weight:700; letter-spacing:.22em; color:var(--gray-400); }
/* ロゴは表紙のみ：本文先頭、タイトルの上に置く（<div class="cover-logo"></div>）。data URI は上記のロゴSVGを base64 化して差し込む */
.cover-logo{ width:175px; height:24px; margin-bottom:28px;
  background:url("data:image/svg+xml;base64,＜ロゴSVGをbase64化した文字列＞") left center / contain no-repeat; opacity:.9; }
```

レポートは各固定面の下部へCONFIDENTIALとページ番号を置く。ロゴは表紙だけに置く。

---

## 参考にした公的ガイド

- デジタル庁、デジタル・ガバメント推進標準ガイドライン「デザインシステム」: https://design.digital.go.jp/dads/resources/
- デジタル庁、DADS「カラー」: https://design.digital.go.jp/dads/foundations/color/

参照日: 2026-09-12。ニュートラル色を共通UIの主体にすること、アクセントを限定すること、セマンティックカラーの意味を固定すること、色以外の手がかりを併用することを採用した。

---

## 5. 更新メモ（フィードバック反映）

- 2026-09-17　基本分析の当期・前期列へ実際の期間を併記し、クライアント向け本文を月次推移だけに固定した。数値セクションは根拠表→考察本文→グラフの順にし、「考察:」ラベルを非表示にした。本文・表の基準文字を拡大し、グラフ内の指標名・凡例・値ラベルは縮小して主データとのバランスを整えた。
- 2026-09-17　複合グラフの実装契約を強化した。`問い合わせ数` / `問い合わせCVR` や
  `申込完了数` / `申込CVR` を同じKPIとして左右の独立軸へ重ね、3組目以降のCVも省略しない。
  CVRが単独パネルに残る場合、未変換の可視化指定が残る場合は、HTML/PDFを完成扱いにせず
  出力を停止する。図表より前に読み方・考察がない固定面は品質チェックで警告する。計測チェックは
  グラフではなく判定・状態・確認根拠の一覧表を必須とした。
- 2026-09-16　固定面の余白が大きい場合、ページ確定後の実使用高に応じて本文・見出し・表の
  行高を2段階で広げるようにした。拡大で収まらない面は自動的に標準密度へ戻し、意味単位・
  改ページ位置・1280×720の固定サイズは変えない。
- 2026-09-16　レポートを1280×720の固定面へ変更した。画面では面全体を縮尺表示して1面を
  ビューポート内へ収める。ページ分割は見出し・連続段落・図表の意味単位だけで行い、表の行や
  表と直後の説明文の間では分けない。意味単位が収まらない場合は縮小・切り捨てをせず警告し、
  PDF変換を停止する。2026-08-25版の失敗原因だったA4縦の狭い固定幅と表の行分割は復活させない。
- 2026-09-16　考察だけの面・データだけの面を作らず、各グラフ・表に直前の考察を同じ面で
  再掲する。図表ごとに判断が異なる場合は、原稿側で個別の考察を置く。
- 2026-09-12　セル内バーの塗りをCSSグラデーションから幅指定の単色面へ変更した。ChromiumのPDF印刷でグラデーション境界だけが濃い縦線として残る表示崩れを防ぎ、HTMLとPDFの双方で数値と相対量を読めるようにした。
- 2026-09-12　色の意味を固定した。良い数値結果は緑、悪い数値結果・要対応は赤、強調はゴールド、その他は白黒グレーとした。カードの上辺・左辺の装飾線と、分類ごとの多色の面塗りを廃止。DADSの配色・セマンティックカラーの考え方を参考にした。
- 2026-07-03　ゴールドの縦罫を全廃。線として悪目立ちしダサいという指摘を反映し、ハイライトボックスの左縦罫（`border-left`）に加えて、見出し（`.section-title::before`）とファインディングカード見出し（`.fc-title::before`）の左ゴールド縦バーも削除した。当時はKPIの短い上線を残していたが、2026-09-12の更新で廃止した。縦罫はどの部品にも付けない。
- 2026-08-23　差し色（ゴールド）とロゴを利用者が自社ブランドに差し替えられるようにした（`report_export` の `--accent-color` / `--logo`。§1・§4参照）。グレースケール主体・角丸なし・囲み枠なしの3原則とレイアウトは変更対象外で、変えられるのは色とロゴだけ。1色（HEX）を渡すだけで `--gold` 系4トークンを自動導出し、文字色に使う `--gold-dark` は白背景とのコントラスト比4.5:1を割らないよう自動調整する（`accent_color.py`）。未指定なら既定のゴールド `#D4AF37` のまま変わらない。
- 2026-08-25　レポート（`report-template.html`）を縦スクロール1枚物から面送り（スライド）形式に作り替えた。「縦長で分かりにくい」というフィードバックを反映し、1面1表・表は切らず続きの面へ送る、という制約のもとブラウザの実測レイアウトで面を組み立てる（詳細は`report-template.html`先頭のHTMLコメント参照）。面のサイズはPDF出力の印刷可能領域と同じ固定値にし、画面表示とPDF化で同じ結果になるようにした。コアCSS（本節の色・部品）・01/03が使う共通部品クラスは変更していない。
- 2026-08-25（同日差し戻し）面送り（スライド）形式が実データで崩れたため撤回した。182mm幅の固定サイズに横広の表を押し込んだ結果、`V-H-001`のような短いIDが3行に折り返し、説明文の列が1〜2文字で縦に流れ、表の行が面の下端で切れる不具合が実レポートで発生した。ページ送り操作・固定サイズの面・実行時にDOMの高さを測るJSをすべて廃止し、セクション（見出し）の境界だけで白い面を区切る縦スクロール方式に差し戻した。面の高さは中身に合わせて伸縮し、幅も本文カラムの可変幅のまま（A4等に縛らない）。目次の追従・現在地ハイライト（IntersectionObserver）は維持。PDFは面（セクション）の境界で改ページする。
- 2026-09-11　全レポートを1面1表を基本とするスライド風表示へ変更した。以前の固定182mm・固定高・DOM実測による表分割は復活させず、章と表の境界だけを静的に分ける。各面は画面高を下限にしつつ内容量に応じて伸び、横幅も可変のままとするため、長い表の行や横長の列を切らない。
- 2026-09-12　時系列の複合グラフは、セッションを単独パネル、同じKPIのCV数（棒）とCVR（折れ線）を左右の独立軸で重ねたパネルにした。複数KPIでも件数と率の対応を保ち、縦に細かく分かれすぎないようにする。
