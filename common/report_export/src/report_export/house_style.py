"""design_system/report-template.html を土台にしたレポートHTML生成。

配色・フォント・部品の見た目の正本は `design_system/design-system.md`。
このモジュールは design-system.md の方針に沿って作った
`design_system/report-template.html`（コアCSS＋レポート枠）を読み込み、
プレースホルダ文字列を置換して本文を差し込むだけの役割に徹する。
トーンを変えたいときはこのファイルではなく design-system.md / report-template.html を直す。
"""

from __future__ import annotations

import base64
import html as html_lib
import re
from pathlib import Path

from . import accent_color

# このファイル: <repo>/common/report_export/src/report_export/house_style.py
# design_system/ : <repo>/common/report_export/design_system/
_DESIGN_SYSTEM_DIR = Path(__file__).resolve().parents[2] / "design_system"
_TEMPLATE_PATH = _DESIGN_SYSTEM_DIR / "report-template.html"
_LOGO_PATH = _DESIGN_SYSTEM_DIR / "logo-placeholder.svg"
_HEADING_RE = re.compile(
    r'<h(?P<level>[23])[^>]*\sid="(?P<id>[^"]+)"[^>]*>(?P<text>.*?)</h[23]>',
    re.DOTALL,
)
# セクション(白い面)の境界に使う見出し。h1/h2はstyle_headings()で
# class="section-title"を付与済み(h3以降は"sub-title"なので対象外＝面を割らない)。
_SECTION_HEADING_RE = re.compile(r'<h[12]\b[^>]*\bclass="section-title"[^>]*>')
_TABLE_BLOCK_RE = re.compile(
    r'<div class="table-scroll"><table\b.*?</table></div>',
    re.DOTALL,
)
_DIV_CLASS_RE = re.compile(r'<div class="(?P<classes>[^"]*)"')
_INSIGHT_BLOCK_RE = re.compile(r'<div class="insight-box">.*?</div>', re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
# ファイル先頭(\A)から最初の "-->" までの1個だけにマッチする。
# 本文(__BODY__)や<style>内など、他の場所にあるコメントを巻き込まない安全側の指定。
_LEADING_COMMENT_RE = re.compile(r"\A\s*<!--.*?-->\s*", re.DOTALL)
# <style>〜</style>の中身だけを取り出すためのブロック検出。中身はグループ2。
# 開始/終了タグ自体は書き換えないので、属性付き(<style type="text/css">等)や
# 複数のstyleブロックがあっても壊れない。
_STYLE_BLOCK_RE = re.compile(r"(<style[^>]*>)(.*?)(</style>)", re.DOTALL)
# CSSコメント/* ... */。<style>ブロックの中身だけに適用する前提(下記_strip_style_comments参照)。
# report-template.htmlの<style>内には content:"" や url("data:...") はあるが、
# "/*"や"*/"に見える文字列リテラルは存在しないことを確認済み(誤爆しない)。
_CSS_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)


def _build_toc(body_html: str) -> str:
    """本文の章見出しから、画面追従型の目次を作る。"""
    items = []
    for match in _HEADING_RE.finditer(body_html):
        level = match.group("level")
        heading_id = html_lib.escape(match.group("id"), quote=True)
        label = html_lib.escape(_TAG_RE.sub("", match.group("text")).strip())
        if not label:
            continue
        items.append(
            f'<li class="toc-level-{level}"><a href="#{heading_id}" data-section="{heading_id}">{label}</a></li>'
        )
    if not items:
        return ""
    return (
        '<aside class="report-nav" aria-label="目次">'
        '<div class="toc-title">目次</div><ol>'
        + "".join(items)
        + '</ol><a class="back-to-top" href="#report-top">先頭へ戻る</a></aside>'
    )


def _split_section_at_tables(section_html: str) -> list[str]:
    """1セクションに複数の表があれば、1シート1表になるよう表の手前で分ける。

    表の行数やブラウザ上の高さは測らず、表そのものは分割しない。固定スライドへの
    最終配置はテンプレート側が意味単位の境界だけで行い、表の行は分割しない。
    2枚目以降には元の章名を小さく再掲し、何の続きか分かるようにする。
    原稿では説明を表の前へ置く。旧原稿の説明文や表後に残る脚注はその表と同じ面へ残す。
    次の表に小見出しがある場合は、
    その小見出しから次の面へ送る。小見出しがなくても次の表に対応するグラフや
    表内バーのタイトルがあれば、その可視化から次の面へ送る。
    """
    tables = list(_TABLE_BLOCK_RE.finditer(section_html))
    if len(tables) <= 1:
        return [section_html]

    heading_match = re.search(
        r'<h[12]\b[^>]*\bclass="section-title"[^>]*>(?P<text>.*?)</h[12]>',
        section_html,
        re.DOTALL,
    )
    heading = (
        html_lib.unescape(_TAG_RE.sub("", heading_match.group("text"))).strip()
        if heading_match else "続き"
    )
    context = f'<div class="slide-context">{html_lib.escape(heading)}（続き）</div>'

    boundaries: list[int] = []
    for previous, current in zip(tables, tables[1:]):
        between = section_html[previous.end() : current.start()]
        subheadings = list(re.finditer(r'<h[3-6]\b[^>]*class="sub-title"[^>]*>', between))
        insight_prefixes = list(_INSIGHT_BLOCK_RE.finditer(between))
        visual_prefixes = [
            match
            for match in _DIV_CLASS_RE.finditer(between)
            if {"report-chart", "table-visual-title"}
            & set(match.group("classes").split())
        ]
        if subheadings:
            boundary = previous.end() + subheadings[-1].start()
        elif insight_prefixes:
            boundary = previous.end() + insight_prefixes[-1].start()
        elif visual_prefixes:
            boundary = previous.end() + visual_prefixes[-1].start()
        else:
            boundary = current.start()
        boundaries.append(boundary)

    def _carried_insight(start: int, end: int) -> str:
        """分割後の図表にも、直前の考察を同じ面へ引き継ぐ。"""
        chunk = section_html[start:end]
        first_visual = re.search(
            r'<div class="(?:[^"]*\b(?:report-chart|table-scroll|table-visual-title)\b[^"]*)"',
            chunk,
        )
        before_visual = chunk[:first_visual.start()] if first_visual else chunk
        if _INSIGHT_BLOCK_RE.search(before_visual):
            return ""
        previous = list(_INSIGHT_BLOCK_RE.finditer(section_html[:start]))
        if not previous:
            return ""
        return previous[-1].group(0)

    chunks = [section_html[: boundaries[0]]]
    for start, end in zip(boundaries, boundaries[1:]):
        chunks.append(context + _carried_insight(start, end) + section_html[start:end])
    final_start = boundaries[-1]
    chunks.append(context + _carried_insight(final_start, len(section_html)) + section_html[final_start:])
    return [chunk for chunk in chunks if chunk.strip()]


def _split_into_sheets(body_html: str) -> tuple[str, list[str]]:
    """本文HTMLを章と表の境界で分割し、スライド風シートの材料を作る。

    戻り値は (先頭見出しより前のプリアンブル, セクションごとのHTMLのリスト)。
    プリアンブルは「実行日」「対象URL」等、最初の見出しより前に置かれた本文
    (レポートの前置き)で、表紙の面にまとめて表示する(__COVER_EXTRA__)。
    見出しが1つも無い場合は分割しようがないので、本文全体を1つのセクション
    として返す(プリアンブル扱いにはしない＝本文が消えない安全側)。
    """
    matches = list(_SECTION_HEADING_RE.finditer(body_html))
    if not matches:
        return "", _split_section_at_tables(body_html) if body_html.strip() else []
    preamble = body_html[: matches[0].start()]
    sections = []
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body_html)
        section = body_html[match.start() : end]
        sections.extend(_split_section_at_tables(section))
    return preamble, sections


def _strip_style_comments(text: str) -> str:
    """<style>ブロック内のCSSコメントだけを落とす。

    report-template.html の<style>内には design-system.md への参照・Playwright等の
    実装手段・デザイン判断の理由といった開発者向けコメントが入っており、先頭コメントと
    同じ理由で生成HTMLに出したくない(テンプレートファイル自体には残す)。
    <style>〜</style>の外(本文・<script>等)には一切触れないよう、まずブロックの中身
    だけを取り出してからコメントを除去する安全側の実装。
    """

    def _strip(match: re.Match[str]) -> str:
        open_tag, body, close_tag = match.group(1), match.group(2), match.group(3)
        return open_tag + _CSS_COMMENT_RE.sub("", body) + close_tag

    return _STYLE_BLOCK_RE.sub(_strip, text)


def _load_template() -> str:
    """テンプレートを読み込み、開発者向けコメントを落として返す。

    report-template.html の先頭には __TITLE__ 等のプレースホルダ仕様を説明する
    HTMLコメントがある(開発者向けの説明としてテンプレートファイル自体には残す)。
    これをそのまま出力すると生成HTMLの1行目から内部仕様が読めてしまうため、
    読み込み時にここで落とす。ファイル先頭から最初の "-->" までの1個だけを
    対象にし、本文(__BODY__ に差し込まれるMarkdown由来のHTML)や<style>内の
    コメントなど、他の場所にあるコメントは巻き込まない。
    続けて、<style>ブロック内のCSSコメント(design-system.mdへの参照や実装上の
    判断理由など)も同じ理由で落とす(_strip_style_comments参照)。
    """
    text = _TEMPLATE_PATH.read_text(encoding="utf-8")
    text = _LEADING_COMMENT_RE.sub("", text, count=1)
    return _strip_style_comments(text)


def _logo_base64(logo_path: Path | None = None) -> str:
    """ロゴSVGを実行時にbase64化する。

    事前生成の `logo-placeholder.svg.b64` には依存しない。クライアントごとにロゴを
    差し替えるときは `logo-placeholder.svg` を自社のロゴファイルで置き換えるだけで済む
    ようにするため、実行のたびにこのSVGファイルを読み込んでbase64化する。
    `logo_path` を渡した場合はそちらを優先する（CLIの `--logo` / 環境変数からの差し替え用）。

    `wrap_html` は `logo_path` が None のとき、この関数自体を呼ばない
    (表紙にロゴを何も出さない。既定のプレースホルダーへのフォールバックは
    ここでは行わない＝呼び出し側の`_cover_logo_css`/`_cover_logo_html`が制御する)。
    このデフォルト引数(`_LOGO_PATH`)は、この関数を直接 `--logo` 未指定相当で
    呼びたい場合(テスト等)のために残す。
    """
    target = logo_path if logo_path is not None else _LOGO_PATH
    return base64.b64encode(target.read_bytes()).decode("ascii")


def _cover_logo_css(logo_b64: str | None) -> str:
    """表紙ロゴの `.cover-logo` CSSルールを組み立てる。

    `logo_b64` が None（`--logo` 未指定）なら空文字列を返し、ルールごと出さない。
    指定時だけ、固定サイズの箱にdata URIを背景として持つルールを返す。
    """
    if logo_b64 is None:
        return ""
    return (
        ".cover-logo{\n"
        "  width:175px; height:24px; margin-bottom:28px;\n"
        f'  background:url("data:image/svg+xml;base64,{logo_b64}") left center / contain no-repeat;\n'
        "  opacity:.9;\n"
        "}\n"
    )


def _cover_logo_html(logo_b64: str | None) -> str:
    """表紙ロゴのHTML要素を組み立てる。

    `logo_b64` が None（`--logo` 未指定）なら空文字列を返し、要素自体を出さない
    (`.cover-logo` は固定サイズのため、背景を空にするだけでは箱と余白が残る)。
    """
    if logo_b64 is None:
        return ""
    return '<div class="cover-logo"></div>'


def _accent_override_css(accent_hex: str | None) -> str:
    """差し色の上書きCSSを組み立てる。

    `accent_hex` が None（未指定）なら空文字列を返し、コアCSSの既定ゴールドのまま変わらない。
    指定時は `accent_color.derive_palette()` で1色から4トークンを導出し、
    :root{ --gold:...; ... } として後勝ちで上書きする（コアCSS自体は書き換えない）。
    """
    if not accent_hex:
        return ""
    palette = accent_color.derive_palette(accent_hex)
    declarations = "\n".join(f"  --{name}:{value};" for name, value in palette.items())
    return f":root{{\n{declarations}\n}}\n"


def _asset_credit(body_html: str) -> str:
    """ピクトグラム使用時だけ、配布物へ出典表示とライセンス本文を同梱する。"""
    if 'class="pictogram-grid"' not in body_html:
        return ""
    asset_dir = Path(__file__).resolve().parent / "assets" / "pictograms"
    license_text = (asset_dir / "LICENSE").read_text(encoding="utf-8")
    notice_text = (asset_dir / "NOTICE").read_text(encoding="utf-8")
    bundled_terms = html_lib.escape(f"{notice_text}\n\n{license_text}")
    return (
        '<div class="asset-credit">Pictograms: Material Symbols Rounded (Google) — '
        '<a href="https://www.apache.org/licenses/LICENSE-2.0">Apache License 2.0</a></div>'
        '<div class="asset-license-print" aria-label="ピクトグラムのライセンス"><pre>'
        + bundled_terms
        + "</pre></div>"
    )


def wrap_html(
    title: str,
    body_html: str,
    generated_at: str,
    *,
    accent_hex: str | None = None,
    logo_path: Path | None = None,
) -> str:
    """design_system/report-template.html に本文を差し込み、単体完結HTMLにする。

    body_html は事前に html_components.designify_body() で
    表(.s-table)・引用(.callout)・見出し(.section-title等) へ整形済みのものを渡す。

    本文はセクション(h1/h2)境界で分割し、1セクションに複数の表がある場合はさらに
    表の手前で分割する。それぞれを白い面(.report-sheet)の材料にし、テンプレート側で
    見出し・連続段落・図表の意味単位だけを候補に1280x720の面へ配置する。表の行や、
    表と直後の説明文の間では分割しない。最初の見出しより前のプリアンブルは表紙の面に
    まとめる(__COVER_EXTRA__)。

    accent_hex: 差し色(ゴールド)を自社ブランドカラーに置き換えたいときの基準色(6桁HEX)。
      未指定(None)なら既定のゴールドのまま変わらない。
    logo_path: ロゴSVGを差し替えたいときのファイルパス。未指定(None)なら表紙にロゴを
      何も出さない(CSSルール・HTML要素とも出力しない)。01の `logo_path` 登録から
      `--logo` 経由で渡された場合だけ、そのファイルをbase64化して表示する。
    """
    template = _load_template()
    safe_title = html_lib.escape(title)
    safe_generated = html_lib.escape(generated_at)
    cover_extra, sections = _split_into_sheets(body_html)
    sheets_html = "".join(
        f'<section class="report-sheet report-body">{section}</section>' for section in sections
    )
    # logo_path が None（--logo未指定）のときは base64化そのものを行わず、
    # CSS/HTMLの両プレースホルダーを空文字列にして要素ごと出さない。
    logo_b64 = _logo_base64(logo_path) if logo_path is not None else None
    return (
        template.replace("__TITLE__", safe_title)
        .replace("__GENERATED_AT__", safe_generated)
        .replace("__COVER_LOGO_CSS__", _cover_logo_css(logo_b64))
        .replace("__COVER_LOGO_HTML__", _cover_logo_html(logo_b64))
        .replace("__ACCENT_OVERRIDE__", _accent_override_css(accent_hex))
        .replace("__TOC__", _build_toc(body_html))
        .replace("__COVER_EXTRA__", cover_extra)
        .replace("__BODY__", sheets_html)
        .replace("__ASSET_CREDIT__", _asset_credit(body_html))
    )
