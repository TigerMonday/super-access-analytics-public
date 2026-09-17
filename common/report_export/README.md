# report_export

Markdownで書いたレポートを、HTML・PDF・Word（docx）・Excel（xlsx）の4形式に変換するCLI。加えて、既存のGoogleドキュメント／Googleスプレッドシートへ書き出すこともできる（gdoc/gsheet。後述）。特定のエージェント専用ではなく、Markdown1ファイルを渡せばどのプロジェクトでも使える汎用ツールとして作っている。

対応形式にPowerPointは含めない。デザイン崩れが起きやすいため対応しない方針。

## デザイン

HTML/PDF出力の見た目（色・フォント・余白・部品）の正本は `design_system/design-system.md`。
デザインのトーンを変えたいときはこのツールのコードではなく、まず `design_system/design-system.md`
（と土台テンプレート `design_system/report-template.html`）を直す。
表・グラフ・図解の選び方は `design_system/visualization-guidelines.md` を正本とする。伝えたい結論と
データの種類から見せ方を選び、定性情報に疑似的な数値グラフを付けない。
定性サマリーでは、同ガイドの `<!-- pictograms: ... -->` 指定から、同梱した線画ピクトグラムを
HTMLへ埋め込める。数値グラフや表の装飾には使わない。使用したHTMLには出典表示と
Apache License 2.0／NOTICE全文も自動で同梱され、PDFでは末尾の付録として出力される。
HTML/PDFの各ページは1280×720（16:9）固定。画面ではページ全体を縮尺表示して1ページを
ビューポート内へ収める。内容は見出し・連続段落・図表の意味単位だけでページ分割し、表の行や
表と直後の説明文の間では分けない。意味単位自体が1ページへ収まらない場合、PDF変換は内容を
切らずに停止するため、原稿側の文章量・表の行数・構成を見直す。
考察は対応するグラフ・表と同じページに置く。同じ章の図表が複数ページに分かれる場合は、
直前の `> **考察:**` を各図表ページへ引き継ぎ、データだけのページを作らない。このMarkdown記号は
関連付けのために使い、HTML/PDFでは「考察:」を表示しない。数値セクションは根拠表、文章、グラフの順に見せる。
章見出しと短い導入だけが1ページに残る場合は、章開始面の余白を詰め、直後の小見出し・表・図と同じページへ再配置する。
SAAの主要レポートを `outputs/{client_id}/` 配下からHTML/PDFへ変換する場合は、03・04・05について同ガイドの
可視化完成条件を描画後に検査する。必要なグラフ・ピクトグラムが無ければ変換を失敗させ、
担当者が変わっても可視化なしの確定版を配布できないようにする。計測チェックは項目・判定・根拠を表で確認する
レポートのため、グラフやピクトグラムを必須にしない。任意名のレポートやSAA外での単体利用には強制しない。
色はグレースケール基調＋ゴールド（`--gold`）を差し色にのみ使う設計で、旧デザインで使っていた
青系トークン（`#1f6feb` 等）は廃止済み。docx/xlsxはHTMLのCSSが効かないため構造重視のまま
（配色を使う箇所は grayscale寄りの色に留めている）。

### 差し色・ロゴを自社ブランドに差し替える

既定のゴールド（`#D4AF37`）とプレースホルダロゴは、実行時オプションで自社ブランドに差し替えられる（HTML/PDFのみ。docx/xlsxはCSSが効かないため対象外）。**未指定なら何も変わらない。**

```bash
# 差し色を1色(HEX)指定するだけでよい。--gold-dark等の3〜4値は自動で導出する
uv run python -m report_export path/to/report.md --to html --accent-color "#1D4ED8"

# ロゴも同じように差し替えられる（既定は design_system/logo-placeholder.svg）
uv run python -m report_export path/to/report.md --to html --logo path/to/logo.svg

# CLIフラグの代わりに環境変数でも指定できる(フラグの方が優先)
REPORT_EXPORT_ACCENT_COLOR="#1D4ED8" REPORT_EXPORT_LOGO_PATH="path/to/logo.svg" \
  uv run python -m report_export path/to/report.md --to html
```

- `--accent-color` は基準色1つ（6桁HEX）を渡すだけでよい。文字色として使う `--gold-dark` は白背景とのコントラスト比4.5:1（WCAG AA相当）を満たすまで自動的に暗く調整される。導出ロジックは `src/report_export/accent_color.py`。
- 詳しい設計判断（3原則は変えない・01コンテキストストアに依存させない理由 等）は `design_system/design-system.md` の「差し色を自社ブランドカラーに変える」を参照。

## 背景

本ツールのレポートは当面Markdownを正として作り、そこから見せ方に応じて形式を選べるようにする。文章での説明や図解が欲しい場面ではHTML・PDF、Wordで納品したい場面、集計データをExcelで受け渡したい場面がそれぞれあるので、変換元は1つに保ちつつ出力だけ選べる形にした。

## 自然文で変換を依頼されたとき

「このレポートをPDFにして」「HTMLとWordで出して」などと依頼されたら、現在のAIエージェントが変換元Markdownと希望形式を依頼文から確定する。不明なものだけをまとめて確認し、既定では変換元と同じフォルダへ出力する。client_idが分かり、01コンテキストにブランドカラーやロゴが登録されていればHTML/PDFへ渡す。未登録の場合は聞き直さず既定デザインを使う。完了時は生成したファイルの絶対パスを示す。

## 使い方

リポジトリの `common/report_export/` で実行する。

```bash
cd common/report_export

# 初回のみ: 依存パッケージを揃える
uv sync

# 初回のみ: PDF変換に使うChromiumを取得する（PlaywrightがOS別に管理する専用キャッシュに入る）
uv run playwright install chromium

# 1形式だけ変換
uv run python -m report_export path/to/report.md --to html

# 複数形式をまとめて変換（カンマ区切り）
uv run python -m report_export path/to/report.md --to html,pdf,docx,xlsx

# 対応する全形式（PowerPointは含まない）
uv run python -m report_export path/to/report.md --to all

# 出力先を変える（既定は入力Markdownと同じディレクトリ、同名で拡張子違い）
uv run python -m report_export path/to/report.md --to html --output-dir ./out
```

変換が終わると、生成したファイルの絶対パスを毎回標準出力に表示する（gdoc/gsheetは書き込み先のURLを表示する）。

### HTML・PDF出力時の閲覧入口

このリポジトリの `outputs/{client_id}/` 配下へHTMLまたはPDFを書き出した場合は、変換成功後に
`outputs/{client_id}/index.html`（全レポートの閲覧入口）も自動で再生成する。CLIの出力には
`[report_export] 閲覧入口:` としてパスを表示する。HTMLを主リンクとし、同じフォルダ・同じbasenameの
PDFがあれば「PDFを開く」副リンクも表示する。Word・Excel・Google形式だけの変換や、Markdownだけを
更新した場合は自動再生成しない。HTMLを直接作成して `report_export` を通さない場合や、
入口を修復したい場合は `common/report_index` を手動実行する。

`report_export` を別プロジェクトで単体利用する場合や、`outputs/{client_id}/` 外へ書き出す場合は
対象外で、入口ページを勝手に作らない。

## Googleドキュメント／Googleスプレッドシートへの書き出し（gdoc/gsheet）

```bash
# 事前に: uv sync --extra google（後述「依存パッケージ」参照）

# 既存のGoogleドキュメントの、指定した見出し1の区画だけを書き換える
uv run python -m report_export path/to/report.md --to gdoc \
  --gdoc "https://docs.google.com/document/d/xxxx/edit"

# 既存のGoogleスプレッドシートに、新しいシート(タブ)を1枚追加する
uv run python -m report_export path/to/report.md --to gsheet \
  --gsheet "https://docs.google.com/spreadsheets/d/xxxx/edit"
```

**新規ファイルの自動作成はしない。** サービスアカウントは自分でファイルを作れない制約が
あるため（Drive APIの公式ドキュメントに明記。共有ドライブでの回避策はWorkspace有償
エディション前提で無償アカウント利用者では成立しない）、`--gdoc`/`--gsheet` に既存ファイルの
URL（またはID）を渡す必要がある。未指定だと「何を用意すればよいか」を書いたエラーで止まる。
書き込み先には、認証ファイルの `client_email` の値を編集者として共有しておくこと（ドメイン
全体の委任は不要。委任が要るのは人になりすます場合のみ）。

`--to all` にはgdoc/gsheetを含めない（書き込み先URLを都度指定する必要があり、`all`では
補完しようがないため。個別に `--to gdoc,gsheet` のように指定する）。

### 上書き事故を避ける設計

このプロジェクトでは「機械が人の書いたものを上書きする」不具合を過去に2回直している。
gdoc/gsheetは同じ事故を繰り返さない設計にしている。

- **スプレッドシート**: 既存のシート（タブ）には一切触れず、毎回新しいシートを追加する。
  シート名は `{レポート名}_{YYYY-MM-DD}`。同名が既にあれば `_2` のように連番を足す（既存を
  上書きしない）
- **ドキュメント**: そのレポート用の区画（見出し1で区切られた範囲）だけを差し替え、それ以外は
  一切触らない。対象の見出し1が見つからなければ末尾に追記する（既存の内容を消さない）。文書内に
  `メモ` という見出し1があれば、そこから先は絶対に書き換えない（利用者が書き込む場所として
  空けておく。01の計測チェックレポートが使っている `ensure_check_report_notes()` と同じ考え方）。
  **`メモ` そのものを対象見出しに指定することはできない**（`--gdoc-heading メモ` や、Markdown
  先頭のH1がたまたま`メモ`だった場合に保護対象を書き換えてしまう抜け道になるため、エラーで止める）

### 表はDocs APIのネイティブな表（insertTable）で挿入する

行き先は人が読んでコメントを付ける文書のため、表が読める形で入ることを優先する。パイプ区切り
のテキストでは監査マトリクスのような表中心のレポート（01の計測チェック、02の基本分析など）が
読めなくなるため採用しない。

Docs APIでは、挿入したセルの実際の書き込み位置は`insertTable`実行後にドキュメントを再取得
しないと分からない（Google公式のテーブル操作ガイドが推奨する手順）。そのため書き込みは
3段階のAPI往復になる（表が無ければ1回のまま）。

1. `batchUpdate`: 区画の削除（置換時）＋ 表以外のテキスト・書式 ＋ 表シェル（罫線と空セルのみ。
   表が複数あってもまとめて1回に積む）
2. `documents().get()`: 再取得し、表シェルの実際のセル位置を特定する
3. `batchUpdate`: 各表の各セルへ、見出し行の太字も含めて値をまとめて書き込む（これも表・セルの
   数だけ分割せず1回にまとめる）

実行時間が数秒延びることより、表が読めないことの方が問題という判断による。太字（`**text**`）
以外の装飾（イタリック・インラインコード）は記号だけ外してプレーンテキストにする。詳しい理由は
`src/report_export/gdoc_export.py` のモジュールdocstringを参照。

## 対応形式と特性

| 形式 | 方針 | 備考 |
|---|---|---|
| HTML | 正であり最もリッチな形式。単体のHTMLファイル1枚で完結する | 見出し・表・箇条書き・コードブロック・引用・リンクを整形し、画像はbase64で埋め込む。デザイン（配色・フォント・部品の見た目）は `design_system/design-system.md` に準拠する。見出しは `.section-title`、表は `table.s-table`（数値列は右寄せ）、引用は `.callout` に整形し、`design_system/report-template.html` を土台にロゴ（data URI埋め込み。未指定時は非表示、指定したロゴを使用）と生成日時・CONFIDENTIALフッターを添える |
| PDF | 上記HTMLをChromium（Playwright経由）でそのまま印刷してPDF化する | HTMLと見た目を一致させるための選択。base64埋め込み済みのHTMLを渡すため、PDF生成時に外部への通信は発生しない。1280×720相当の16:9。ページごとのCONFIDENTIAL＋ページ番号はHTMLと同じCSSで付与する。収まらない意味単位があれば切れたPDFを作らず停止する |
| Word（docx） | pandocが使える環境ではpandocに変換を任せる。無ければpython-docxで簡易変換する | 見出し・段落・太字・イタリック・箇条書き・表を保持する。pandoc経由の方が表・日本語の再現度が高い |
| Excel（xlsx） | MD中の表を1つずつ別シートに展開し、文章部分は「概要」シートにまとめる | Excelは表計算向けのツールで、文章主体のレポートをそのまま流し込むのには向かないという前提の割り切り。表が1つも無いMarkdownなら「概要」シートのみになる |
| Googleドキュメント（gdoc） | 既存ドキュメントの、見出し1で区切った区画だけを差し替える | 新規ファイルは作らない（`--gdoc` 必須）。`メモ` 見出し以下は絶対に触らない（`メモ`自体を対象見出しに指定するのも不可）。表は罫線付きのネイティブな表（insertTable）として挿入する（詳細は上記「Googleドキュメント／Googleスプレッドシートへの書き出し」参照） |
| Googleスプレッドシート（gsheet） | 既存スプレッドシートに新しいシート（タブ）を1枚追加する | 新規ファイルは作らない（`--gsheet` 必須）。既存シートは一切変更しない。シート名は `{レポート名}_{YYYY-MM-DD}`（連番で重複回避） |

## 依存パッケージ

`pyproject.toml` に明記済み。`uv sync` で `common/report_export/.venv` にまとめて入る。

- markdown（MD→HTML変換。tables/fenced_code拡張を使用）
- openpyxl（xlsx生成）
- python-docx（docxのpandoc代替経路）
- playwright（HTML→PDF。Chromiumでの印刷に使用。初回セットアップは上記「使い方」の `uv run playwright install chromium` を参照）
- pandoc（任意。無ければpython-docx経路にフォールバックする）
- google-api-python-client / google-auth（gdoc/gsheet出力を使う場合のみ。`uv sync --extra google` で導入する。使わない利用者には強制しない任意依存で、未インストールのままgdoc/gsheetを使おうとすると導入方法を書いたエラーで止まる）

### テストを実行する場合

`pytest` は開発用の依存（`[project.optional-dependencies].dev`）にあるため、`uv sync` だけでは入らない。テストを実行する前に以下を実行する。

```bash
uv sync --extra dev
uv run pytest
```

### pandocの入手先（OS別）

pandocは無くても動く（python-docx経路に自動フォールバック）が、入れると docx の表・日本語の再現度が上がる。

| OS | 入手方法 |
|---|---|
| macOS | `brew install pandoc`（Homebrew） |
| Windows | `winget install --id JohnMacFarlane.Pandoc` または [公式インストーラー](https://pandoc.org/installing.html) |
| Linux | ディストリのパッケージマネージャー（例: `apt install pandoc`）または[公式バイナリ](https://pandoc.org/installing.html) |

## 表のパース（xlsx向け）で気をつけていること

MDテーブルのパイプ区切りを素直に `split("|")` すると、以下で崩れる。

- セル内にパイプ文字そのものを入れたい場合のエスケープ `\|`
- セル内改行を表す `<br>`
- 値が空のセル
- 同じ見出し名の下に複数の表がある場合のシート名重複

`md_tables.py` でこれらを個別に処理している。エスケープされたパイプはセル内容の `|` として復元し、`<br>` はExcelのセル内改行に変換し、空セルは空文字列のまま残し、シート名は見出しテキストから作って重複時は連番を振る。

## 制限・既知の注意点

- Excel出力は表の抽出が中心で、文章の書式（太字・箇条書きの階層など）は概要シート内で簡略化される
- Word出力はpandocの有無で仕上がりが変わる。pandoc環境ではより高い再現度になる
- 画像はHTML/PDFのみbase64で埋め込む。Excel・Wordには画像を含めない（表とテキストの再現を優先する設計のため）
- 見出しレベルはExcel概要シートでは文字サイズの違いとしてのみ表現する（Wordはpandoc/python-docxそれぞれの見出しスタイルに従う）
- gdoc/gsheetは新規ファイルを作らない（既存ファイルへの書き込みのみ）。画像・番号付きリストの書式は非対応（番号付きリストはプレーンテキストとしてそのまま入る）
