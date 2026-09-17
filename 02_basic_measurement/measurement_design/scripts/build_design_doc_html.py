"""計測設計書（docs/design-doc/ の章01〜16）を1枚のHTMLにする。

Markdown のままだと章ファイルを1つずつ開く必要があり、通し読みしづらい。
章を並べて1つのスクロールできるHTMLにする。

- 外部ファイルを一切参照しない自己完結HTML（CSS・JSインライン、CDN不使用）。
  クライアントの計測データを含むため、オフラインで開ける単一ファイルにする
- 配色は common/report_export の既定色に合わせたプレースホルダ
  （自社ブランドカラーに差し替える場合はこのファイルの CSS 変数を書き換える）

Usage:
    python run.py doc --client <client_id>
"""

from __future__ import annotations

import html
import re
from datetime import date
from pathlib import Path

from config import AuditConfig

# markdown-it-py は必須依存（pyproject.toml）。
# ImportError を握って <pre> でそのまま出すフォールバックにすると、表が1つも
# 描画されない壊れたHTMLが静かに生成され、気づくのが遅れる。落とすほうがよい。
from markdown_it import MarkdownIt

# 設計書の章はクライアント情報を含む入力であり、その中の生HTMLを信頼しない。
# markdown-it の HTML パスを無効にすると、script / iframe / イベント属性を含むタグは
# 文字列としてエスケープされ、生成したHTMLを開いたときに実行されない。
_MD = MarkdownIt("commonmark", {"html": False}).enable("table").enable("strikethrough")


def _render_md(text: str) -> str:
    return _MD.render(text)


def _split_title(md: str) -> tuple[str, str]:
    """先頭の H1 をタイトルとして取り出し、本文と分ける。"""
    lines = md.split("\n")
    title = ""
    start = 0
    for i, ln in enumerate(lines):
        if ln.startswith("# "):
            title = ln[2:].strip()
            start = i + 1
            break
    return title, "\n".join(lines[start:]).strip()


def _chapter_number(path: Path) -> str:
    m = re.match(r"^(\d{2})[-_]", path.name)
    return m.group(1) if m else "--"


def _collect(base: Path) -> dict[str, tuple[str, str]]:
    """章番号 -> (タイトル, HTML本文)."""
    out: dict[str, tuple[str, str]] = {}
    seen: dict[str, Path] = {}
    if not base.is_dir():
        return out
    for p in sorted(base.glob("*.md")):
        if p.name == "README.md":
            continue
        # テンプレートのコピー（`NN-....template.md`）は成果物ではない。
        if p.name.endswith(".template.md"):
            continue
        number = _chapter_number(p)
        if number in seen:
            # 番号が衝突すると後に来たファイルで上書きされ、前のファイルは HTML から消える。
            # 黙って落とすと「書いたはずの内容が出ていない」ことに気づけない
            print(
                f"警告: 章 {number} に複数のファイルがある"
                f"（{seen[number].name} / {p.name}）。{p.name} を採用し {seen[number].name} は HTML に含めない。"
                "1つに統合すること。"
            )
        seen[number] = p
        title, body = _split_title(p.read_text(encoding="utf-8"))
        # 「章 06: ...」のような接頭辞を落とす（見出しは番号バッジで表す）
        title = re.sub(r"^章?\s*\d+\s*[:：]\s*", "", title)
        out[number] = (title, _render_md(body))
    return out


# 配色は common/report_export/design_system/design-system.md の既定値
# （グレースケール基調＋ゴールドを差し色に、のみ使う設計）に合わせたプレースホルダ。
# 自社ブランドカラーに差し替える場合はここを書き換える。
CSS = """
:root{
  --bg:#ffffff; --fg:#1f2328; --muted:#6b7280; --line:#e5e7eb;
  --accent:#D4AF37; --chip:#f3f4f6; --code:#f6f8fa;
}
@media (prefers-color-scheme: dark){
  :root{ --bg:#14161a; --fg:#e8eaed; --muted:#9aa0a6; --line:#2c3038;
         --chip:#1f2329; --code:#1b1f24; }
}
:root[data-theme="light"]{ --bg:#ffffff; --fg:#1f2328; --muted:#6b7280; --line:#e5e7eb;
  --chip:#f3f4f6; --code:#f6f8fa; }
:root[data-theme="dark"]{ --bg:#14161a; --fg:#e8eaed; --muted:#9aa0a6; --line:#2c3038;
  --chip:#1f2329; --code:#1b1f24; }

*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Hiragino Sans","Noto Sans JP",sans-serif;
  line-height:1.75;font-size:15px;}
header.top{padding:28px 32px 20px;border-bottom:4px solid var(--accent);}
header.top h1{margin:0 0 6px;font-size:24px;letter-spacing:.02em}
header.top .sub{color:var(--muted);font-size:13px}
.wrap{display:grid;grid-template-columns:250px minmax(0,1fr);gap:0;align-items:start}
@media (max-width:900px){ .wrap{grid-template-columns:1fr} nav.toc{position:static!important;border-right:0;border-bottom:1px solid var(--line)} }

nav.toc{position:sticky;top:0;max-height:100vh;overflow:auto;padding:20px 16px;
  border-right:1px solid var(--line);}
nav.toc h2{font-size:11px;letter-spacing:.14em;color:var(--muted);margin:0 0 10px;text-transform:uppercase}
nav.toc a{display:block;padding:7px 10px;border-radius:6px;color:var(--fg);text-decoration:none;font-size:13px}
nav.toc a:hover{background:var(--chip)}
nav.toc a .n{display:inline-block;width:26px;color:var(--muted);font-variant-numeric:tabular-nums}

main{padding:24px 32px 80px;min-width:0}
section.chapter{margin:0 0 40px;scroll-margin-top:16px}
section.chapter > h2{font-size:19px;margin:0 0 4px;padding-bottom:8px;border-bottom:1px solid var(--line)}
section.chapter > h2 .n{color:var(--muted);font-variant-numeric:tabular-nums;margin-right:10px}

main h2,main h3,main h4{line-height:1.5}
main h2{font-size:17px;margin:26px 0 8px}
main h3{font-size:15px;margin:20px 0 6px}
main h4{font-size:14px;margin:16px 0 6px;color:var(--muted)}
main p{margin:8px 0}
main ul,main ol{margin:8px 0;padding-left:22px}
main li{margin:3px 0}
main blockquote{margin:12px 0;padding:10px 14px;border-left:3px solid var(--accent);
  background:var(--chip);border-radius:0 6px 6px 0;color:var(--fg)}
main blockquote p{margin:4px 0}
main code{background:var(--code);padding:1px 5px;border-radius:4px;font-size:.9em;
  font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
main pre{background:var(--code);padding:12px 14px;border-radius:8px;overflow-x:auto}
main pre code{background:none;padding:0}
.tablewrap{overflow-x:auto;margin:12px 0}
main table{border-collapse:collapse;font-size:13px;min-width:100%}
main th,main td{border:1px solid var(--line);padding:6px 10px;text-align:left;vertical-align:top}
main th{background:var(--chip);font-weight:700;white-space:nowrap}

.theme{position:fixed;right:16px;bottom:16px;border:1px solid var(--line);background:var(--bg);
  color:var(--fg);border-radius:999px;padding:8px 14px;cursor:pointer;font-size:12px;font-family:inherit}

@media print{
  nav.toc,.theme{display:none!important}
  .wrap{grid-template-columns:1fr}
  section.chapter{break-inside:avoid-page;page-break-inside:avoid}
  body{font-size:11px}
  main{padding:0}
}
"""

JS = """
var root = document.documentElement;
document.querySelector('.theme').addEventListener('click', function(){
  var now = root.dataset.theme
    || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
  root.dataset.theme = (now === 'dark') ? 'light' : 'dark';
});
"""


def build(config: AuditConfig, client_label: str = "") -> Path:
    docs = config.docs_dir
    design_doc_dir = docs / "design-doc"
    chapters = _collect(design_doc_dir)
    if not chapters:
        # 「先に design を実行してください」は誤り: 既定（--llm-backend none）の design は
        # 案内を出すだけで章ファイルを作らないため、これだけでは design→doc→design の
        # 堂々巡りになる。実際に必要な行動（AIエージェントが章ファイルを書く）を明示する。
        raise FileNotFoundError(
            f"design-doc の章ファイルが見つかりません: {design_doc_dir}\n"
            "外部LLM未使用（--llm-backend none、既定）の場合、`design` はAIエージェントへの"
            "案内を出すだけで章ファイルは作らない。\n"
            f"AIエージェントが {design_doc_dir} に "
            "`01-cover.md` 等（templates/design-doc/*.template.md と同じファイル名、"
            "`# 章 NN: ...` 見出し付き）を1つ以上書いてから再実行すること。\n"
            "詳細は docs/guide/work-procedure.md ステップ6、テンプレートは templates/design-doc/ を参照。"
        )

    numbers = sorted(chapters)
    label = client_label or config.client_name

    toc, body = [], []
    for n in numbers:
        title, body_html = chapters[n]
        toc.append(
            f'<a href="#chapter-{n}"><span class="n">{n}</span>{html.escape(title)}</a>'
        )
        body.append(f"""
<section class="chapter" id="chapter-{n}">
  <h2><span class="n">{n}</span>{html.escape(title)}</h2>
  {body_html}
</section>""")

    doc = f"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>GA4計測設計書 — {html.escape(label)}</title>
<style>{CSS}</style>
</head>
<body>
<header class="top">
  <h1>GA4 計測設計書 — {html.escape(label)}</h1>
  <div class="sub">章ごとに計測設計をまとめたもの。&nbsp;/&nbsp;生成日 {date.today().isoformat()}</div>
</header>
<div class="wrap">
  <nav class="toc">
    <h2>章</h2>
    {"".join(toc)}
  </nav>
  <main>
    {"".join(body)}
  </main>
</div>
<button class="theme" type="button">テーマ切替</button>
<script>{JS}</script>
</body>
</html>
"""
    # 表を横スクロールできるように包む
    doc = doc.replace("<table>", '<div class="tablewrap"><table>').replace(
        "</table>", "</table></div>"
    )

    out = docs / "design-doc.html"
    out.write_text(doc, encoding="utf-8")
    return out
