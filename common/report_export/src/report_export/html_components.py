"""Markdown由来のraw HTMLを、design-system.mdの共通部品クラスへ整形する後処理。

markdownライブラリ(markdown_utils.render_html_body)の出力は素の<table>/<blockquote>/
<h1>-<h6>のため、ここでclass付与や構造の組み替えを行い、report-template.htmlの
コアCSS(table.s-table / .callout / .section-title 等)に乗るようにする。

対応するマッピング(design-system.md 準拠):
- 表         -> table.s-table。数値列(カンマ区切り数字・%・pt・小数など)の th/td に
                class="r" を付けて右寄せにする。列数が多く画面幅に収まらない表は
                div.table-scroll で包み、表の中だけが横スクロールするようにする
                (ページ全体が横に広がるのを防ぐ)。
- 引用       -> .callout(.callout-iconは黒地に白の "!")
- 見出し     -> h1(本文中に残るもの)/h2 は .section-title、h3以降は .sub-title
"""

from __future__ import annotations

import calendar
import html as html_lib
import re
import urllib.parse
from datetime import date

from markdown.extensions.toc import slugify_unicode

from .pictograms import inline_pictogram

# ---------------------------------------------------------------------------
# 表 -> table.s-table + 数値列の右寄せ判定
# ---------------------------------------------------------------------------

_TABLE_RE = re.compile(r"<table>(.*?)</table>", re.DOTALL)
_THEAD_RE = re.compile(r"<thead>(.*?)</thead>", re.DOTALL)
_TBODY_RE = re.compile(r"<tbody>(.*?)</tbody>", re.DOTALL)
_TR_RE = re.compile(r"<tr>(.*?)</tr>", re.DOTALL)
_TH_RE = re.compile(r"<th(?P<attrs>[^>]*)>(?P<content>.*?)</th>", re.DOTALL)
_TD_RE = re.compile(r"<td(?P<attrs>[^>]*)>(?P<content>.*?)</td>", re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")

# 数値セル: 符号(+/-/全角マイナス) + 桁区切り数字 + 小数 + 単位(%/pt/ポイント)。
# 「(前期比)」のような末尾の注記付き数値も許容する。
_NUMERIC_CELL_RE = re.compile(
    r"^[+\-−]?\d{1,3}(,\d{3})*(\.\d+)?\s*(%|pt|ポイント)?"
    r"(\s*[（(][^）)]*[）)])?$"
)
# 「該当なし」を表す記号だけのセル(ハイフン各種・ダッシュ・長音記号・n/a)。
# 数値列の中に単独で混ざっていても、列全体としては数値列の判定を崩さない。
_PLACEHOLDER_CELL_RE = re.compile(r"^(?:[-‐-―ー]+|[Nn]/[Aa])$")


def _cell_text(inner_html: str) -> str:
    """セルの内側HTMLからタグを除いたプレーンテキストを取り出す(判定専用)。"""
    return _TAG_RE.sub("", inner_html).strip()


def _column_is_numeric(values: list[str]) -> bool:
    """列を右寄せ(数値列)にすべきか判定する。

    空セルは無視。残りが全て「数値 or 該当なしプレースホルダ」で、かつ
    実際の数値セルが1つ以上あれば数値列とみなす。
    """
    non_empty = [v for v in values if v]
    if not non_empty:
        return False
    has_numeric = False
    for v in non_empty:
        if _NUMERIC_CELL_RE.match(v):
            has_numeric = True
            continue
        if _PLACEHOLDER_CELL_RE.match(v):
            continue
        return False
    return has_numeric


def _add_class(attrs: str, cls: str) -> str:
    if re.search(r'class\s*=\s*"', attrs):
        return re.sub(r'class\s*=\s*"([^"]*)"', rf'class="\1 {cls}"', attrs, count=1)
    return f'{attrs} class="{cls}"'


def _extract_cells(row_html: str, cell_re: re.Pattern[str]) -> list[tuple[str, str]]:
    return [(m.group("attrs"), m.group("content")) for m in cell_re.finditer(row_html)]


def _rebuild_row(cells: list[tuple[str, str]], tag: str, numeric_cols: list[bool]) -> str:
    parts = ["<tr>"]
    for idx, (attrs, content) in enumerate(cells):
        if idx < len(numeric_cols) and numeric_cols[idx]:
            attrs = _add_class(attrs, "r")
        parts.append(f"<{tag}{attrs}>{content}</{tag}>")
    parts.append("</tr>")
    return "".join(parts)


def style_tables(html: str) -> str:
    """<table>にs-tableクラスを付け、数値列と判定した th/td に class="r" を付ける。

    表本体は div.table-scroll で包む。列数が多く画面幅に収まらない場合でも、
    横スクロールするのは表の中だけにして、ページ全体が押し広げられるのを防ぐ
    (収まる幅の表ではスクロールバーは出ない。overflow-x:autoの挙動)。
    """

    def _replace(m: re.Match[str]) -> str:
        inner = m.group(1)
        thead_m = _THEAD_RE.search(inner)
        tbody_m = _TBODY_RE.search(inner)
        if not thead_m or not tbody_m:
            # 見出し行の無い変則的な表は壊さずクラスだけ付ける
            return f'<div class="table-scroll"><table class="s-table">{inner}</table></div>'

        header_tr_m = _TR_RE.search(thead_m.group(1))
        header_cells = _extract_cells(header_tr_m.group(1), _TH_RE) if header_tr_m else []
        n_cols = len(header_cells)
        header_labels = [_cell_text(content) for _, content in header_cells]
        table_class = "s-table"
        # 指摘表は「内容」が長い一方、「修正案」も文章になる。通常のauto layoutでは
        # 内容列に幅を取られ、PDFで修正案が1文字ずつ折り返されることがあるため、
        # この見出しの組み合わせだけ専用の列幅を与える。
        if n_cols == 4 and header_labels[-2:] == ["修正案", "重要度"]:
            table_class += " action-table"

        body_rows_html = [tr_m.group(1) for tr_m in _TR_RE.finditer(tbody_m.group(1))]
        body_rows_cells = [_extract_cells(row, _TD_RE) for row in body_rows_html]

        numeric_cols: list[bool] = []
        for c in range(n_cols):
            col_values = [
                _cell_text(row[c][1]) for row in body_rows_cells if c < len(row)
            ]
            numeric_cols.append(_column_is_numeric(col_values))

        new_thead = "<thead>" + _rebuild_row(header_cells, "th", numeric_cols) + "</thead>"
        new_rows = "".join(_rebuild_row(row, "td", numeric_cols) for row in body_rows_cells)
        new_tbody = f"<tbody>{new_rows}</tbody>"
        return f'<div class="table-scroll"><table class="{table_class}">{new_thead}{new_tbody}</table></div>'

    return _TABLE_RE.sub(_replace, html)


# ---------------------------------------------------------------------------
# 引用 -> .callout
# ---------------------------------------------------------------------------

_BLOCKQUOTE_RE = re.compile(r"<blockquote>(.*?)</blockquote>", re.DOTALL)
_P_RE = re.compile(r"<p>(.*?)</p>", re.DOTALL)


def style_blockquotes(html: str) -> str:
    """<blockquote>を考察ボックスまたは注意書きへ変換する。"""

    def _replace(m: re.Match[str]) -> str:
        inner = m.group(1).strip()
        paragraphs = _P_RE.findall(inner)
        content = "<br><br>".join(p.strip() for p in paragraphs) if paragraphs else inner
        plain = _TAG_RE.sub("", content).strip()
        if plain.startswith(("考察:", "考察：", "ポイント:", "ポイント：")) or re.match(
            r"^<strong>(考察|ポイント)[：:]</strong>", content
        ):
            # 「考察：」はMarkdown上で意味を識別するためだけに使い、表示では文章だけを読ませる。
            content = re.sub(
                r"^(?:<strong>(?:考察|ポイント)[：:]</strong>|(?:考察|ポイント)[：:])\s*",
                "",
                content,
                count=1,
            )
            return f'<div class="insight-box">{content}</div>'
        return (
            '<div class="callout"><div class="callout-icon">!</div>'
            f"<div>{content}</div></div>"
        )

    return _BLOCKQUOTE_RE.sub(_replace, html)


# ---------------------------------------------------------------------------
# グラフ指定コメント + 表 -> インラインSVG（表は根拠データとして残す）
# ---------------------------------------------------------------------------

_CHART_BLOCK_RE = re.compile(
    r"<!--\s*chart:\s*(line|bar|combo|search|table-bars)(?:\s*;\s*title:\s*([^>]*?))?\s*-->\s*"
    r'(<div class="table-scroll"><table class="s-table">.*?</table></div>)',
    re.DOTALL | re.IGNORECASE,
)
_INSIGHT_CHART_BLOCK_RE = re.compile(
    r'(<div class="insight-box">.*?</div>)\s*'
    r"<!--\s*chart:\s*(line|bar|combo|search|table-bars)(?:\s*;\s*title:\s*([^>]*?))?\s*-->\s*"
    r'(<div class="table-scroll"><table class="s-table">.*?</table></div>)',
    re.DOTALL | re.IGNORECASE,
)


def _table_with_bars(title: str, table_html: str, headers: list[str], rows: list[list[str]]) -> str:
    """比較表の数値セルへ列内相対バーを重ねる。数値自体は消さずアクセシビリティを保つ。"""
    numeric_cols = [
        c for c in range(1, len(headers))
        if any(c < len(row) and _number(row[c]) is not None for row in rows)
    ]
    maxima = {
        c: max(
            (_number(row[c]) or 0 for row in rows if c < len(row) and "合計" not in row[0]),
            default=0,
        )
        for c in numeric_cols
    }

    body = _TBODY_RE.search(table_html)
    if not body:
        return table_html

    def _row(match: re.Match[str]) -> str:
        cells = _extract_cells(match.group(1), _TD_RE)
        is_total = bool(cells) and "合計" in _cell_text(cells[0][1])
        rebuilt: list[str] = []
        for idx, (attrs, inner) in enumerate(cells):
            if idx in maxima and maxima[idx] > 0 and not is_total:
                value = abs(_number(_cell_text(inner)) or 0)
                width = min(100.0, value / maxima[idx] * 100)
                inner = (
                    f'<span class="table-bar-cell" style="--bar-width:{width:.1f}%">'
                    f'<span class="table-bar-value">{inner}</span></span>'
                )
            rebuilt.append(f"<td{attrs}>{inner}</td>")
        return "<tr>" + "".join(rebuilt) + "</tr>"

    new_body = _TR_RE.sub(_row, body.group(1))
    enhanced = table_html[:body.start(1)] + new_body + table_html[body.end(1):]
    return (
        f'<div class="table-visual-title">{html_lib.escape(title)}</div>'
        + enhanced
    )


def _combo_chart_svg(title: str, headers: list[str], rows: list[list[str]]) -> str:
    """共有横軸で描き、同じCVの件数とCVRは同一パネルへ重ねる。"""
    usable = [row for row in rows[:24] if row and "合計" not in row[0] and "表示合計" not in row[0]]
    if not usable:
        return ""

    def find_col(predicate) -> int | None:
        return next((i for i, h in enumerate(headers[1:], 1) if predicate(h)), None)

    session_col = find_col(lambda h: "セッション" in h and "CV" not in h)

    def cv_key(label: str) -> str | None:
        """CV件数とCVRの業務名を、表記差を吸収して同じキーへ寄せる。"""
        normalized = re.sub(r"[\s:：・_-]+", "", label).strip()
        if not normalized:
            return None
        if "CVR" in normalized:
            normalized = normalized.replace("CVR", "")
        elif "コンバージョン率" in normalized:
            normalized = normalized.replace("コンバージョン率", "")
        elif "CV率" in normalized:
            normalized = normalized.replace("CV率", "")
        elif "CV件数" in normalized:
            normalized = normalized.replace("CV件数", "")
        elif "CV数" in normalized:
            normalized = normalized.replace("CV数", "")
        elif "コンバージョン数" in normalized:
            normalized = normalized.replace("コンバージョン数", "")
        elif normalized == "CV":
            normalized = ""
        elif normalized.endswith("件数"):
            normalized = normalized[:-2]
        elif normalized.endswith("数"):
            normalized = normalized[:-1]
        else:
            return None
        # 「問い合わせ完了数」と「問い合わせCVR」のような実務上同じKPIも対応させる。
        if normalized.endswith("完了"):
            normalized = normalized[:-2]
        return normalized

    def is_cv_count(label: str) -> bool:
        normalized = label.strip()
        if any(token in normalized for token in ("CVR", "コンバージョン率", "CV率")):
            return False
        if any(token in normalized for token in ("CV数", "CV件数", "コンバージョン数")) or normalized == "CV":
            return True
        # 実レポートでは「問い合わせ数」「資料DL数」のように業務名＋数になる。
        # セッション数・ユーザー数・表示回数などの一般指標はCV件数として扱わない。
        excluded = ("セッション", "ユーザー", "PV", "表示回数", "クリック", "閲覧", "回遊")
        return normalized.endswith("数") and not any(token in normalized for token in excluded)

    numeric_cols = [
        c for c in range(1, len(headers))
        if any(c < len(row) and _number(row[c]) is not None for row in usable)
    ]
    selected: list[int] = []

    # セッションの次に、表にある全KPIの「件数→CVR」を対で選ぶ。以前の最大5系列
    # という打ち切りでは3つ目以降のKPIが消えたため、成立した対は上限対象にしない。
    if session_col is not None:
        selected.append(session_col)
    count_cols = [col for col in numeric_cols if is_cv_count(headers[col])]
    rate_cols = [col for col in numeric_cols if any(token in headers[col] for token in ("CVR", "コンバージョン率", "CV率"))]
    paired: set[int] = set()
    for count_col in count_cols:
        key = cv_key(headers[count_col])
        rate_match = next(
            (col for col in rate_cols if col not in paired and cv_key(headers[col]) == key),
            None,
        )
        if rate_match is None:
            continue
        selected.extend(col for col in (count_col, rate_match) if col not in selected)
        paired.update((count_col, rate_match))

    # CV対以外の複合グラフにも使えるよう、残りは従来どおり最大5系列まで補う。
    for col in numeric_cols:
        if col is not None and col not in selected:
            selected.append(col)
        if len(selected) >= max(5, 1 + len(paired)):
            break
    series = [
        (headers[col], col, "line" if any(token in headers[col] for token in ("CVR", "CTR", "率")) else "bar")
        for col in selected
    ]
    if len(series) < 2:
        return _chart_svg("line", title, headers, rows)

    # セッションは単独、同じKPIのCV数（棒）とCVR（折れ線）は左右の独立軸で重ねる。
    # 単位差を保ちながら、件数と率が同じ方向へ動いたかを一目で比較できる。
    panels: list[list[tuple[str, int, str]]] = []
    consumed: set[int] = set()
    for idx, item in enumerate(series):
        if idx in consumed:
            continue
        label, _, kind = item
        key = cv_key(label)
        if kind == "bar" and key is not None:
            rate_idx = next(
                (
                    j for j, candidate in enumerate(series[idx + 1:], idx + 1)
                    if j not in consumed
                    and candidate[2] == "line"
                    and cv_key(candidate[0]) == key
                ),
                None,
            )
            if rate_idx is not None:
                panels.append([item, series[rate_idx]])
                consumed.update((idx, rate_idx))
                continue
        panels.append([item])
        consumed.add(idx)

    axis_labels = [_fit_axis_label(row[0]) for row in usable]
    multiline = any(second is not None for _, second in axis_labels)
    left, right, top, panel_h = 100, 100, 82, 170
    label_slot = max(
        (max(_label_width_px(a), _label_width_px(b or "")) for a, b in axis_labels),
        default=0,
    ) + 30
    width = max(760, round(left + right + label_slot * len(usable)))
    plot_w = width - left - right
    bottom = 62 + (12 if multiline else 0)
    height = top + panel_h + bottom
    gap = plot_w / len(usable)
    charts: list[str] = []

    for panel in panels:
        y0 = top
        left_series = panel[0]
        left_label, left_col, left_kind = left_series
        left_values = [max(0, _number(row[left_col]) or 0) for row in usable]
        left_max = (max(left_values) or 1) * 1.2
        panel_title = f"{title} — {left_label}"
        parts = [
            f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{html_lib.escape(panel_title)}">',
            '<style>.report-chart-combo .chart-label{font-size:8.5px;fill:var(--gray-700)}.report-chart-combo .chart-legend{font-size:9.5px}.report-chart-combo .panel-title{font-size:10.5px;font-weight:700;fill:var(--gray-900)}.report-chart-combo .bar-value{font-size:9px;fill:var(--gray-900)}</style>',
            f'<text x="{left}" y="22" class="chart-title">{html_lib.escape(title)}</text>',
            f'<text x="{left}" y="56" class="panel-title">{html_lib.escape(left_label)}</text>',
        ]
        parts.append(f'<text x="{left-10}" y="{y0+panel_h}" text-anchor="end" class="chart-label">0</text>')
        left_top_label = (
            f"{left_max:.1f}%"
            if any(token in headers[left_col] for token in ("CVR", "CTR", "率"))
            else f"{left_max:,.0f}"
        )
        parts.append(f'<text x="{left-10}" y="{y0+4}" text-anchor="end" class="chart-label">{left_top_label}</text>')

        right_series = panel[1] if len(panel) == 2 else None
        if right_series:
            right_label, right_col, _ = right_series
            right_values = [max(0, _number(row[right_col]) or 0) for row in usable]
            right_max = (max(right_values) or 1) * 1.2
            parts.append(f'<text x="{width-right}" y="56" text-anchor="end" class="chart-legend chart-legend-rate">{html_lib.escape(right_label)}</text>')
            parts.append(f'<text x="{width-right+10}" y="{y0+panel_h}" class="chart-label">0</text>')
            parts.append(f'<text x="{width-right+10}" y="{y0+4}" class="chart-label">{right_max:.2f}%</text>')

        for grid_idx in range(3):
            y = y0 + panel_h * grid_idx / 2
            parts.append(f'<line x1="{left}" y1="{y:.1f}" x2="{width-right}" y2="{y:.1f}" class="chart-grid"/>')
            if grid_idx == 1:
                parts.append(f'<text x="{left-10}" y="{y+4:.1f}" text-anchor="end" class="chart-label">{left_max/2:,.0f}</text>')
                if right_series:
                    parts.append(f'<text x="{width-right+10}" y="{y+4:.1f}" class="chart-label">{right_max/2:.2f}%</text>')

        if left_kind == "bar":
            bar_w = min(34, gap * .58)
            for i, value in enumerate(left_values):
                h = panel_h * value / left_max
                x = left + gap * i + (gap - bar_w) / 2
                parts.append(f'<rect x="{x:.1f}" y="{y0+panel_h-h:.1f}" width="{bar_w:.1f}" height="{h:.1f}" class="chart-bar"/>')
                parts.append(f'<text x="{x+bar_w/2:.1f}" y="{y0+panel_h-h-8:.1f}" text-anchor="middle" class="bar-value">{value:,.0f}</text>')
        else:
            points = []
            for i, value in enumerate(left_values):
                x = left + gap * (i + .5)
                y = y0 + panel_h - panel_h * value / left_max
                points.append(f"{x:.1f},{y:.1f}")
                parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" class="chart-point"/>')
            parts.append(f'<polyline points="{" ".join(points)}" class="chart-line"/>')

        if right_series:
            points = []
            for i, value in enumerate(right_values):
                x = left + gap * (i + .5)
                y = y0 + panel_h - panel_h * value / right_max
                points.append(f"{x:.1f},{y:.1f}")
                parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" class="chart-point"/>')
            parts.append(f'<polyline points="{" ".join(points)}" class="chart-line"/>')

        label_y = y0 + panel_h + 24
        for i, (a, b) in enumerate(axis_labels):
            x = left + gap * (i + .5)
            parts.append(f'<text x="{x:.1f}" y="{label_y}" text-anchor="middle" class="chart-label">{html_lib.escape(a)}</text>')
            if b:
                parts.append(f'<text x="{x:.1f}" y="{label_y+14}" text-anchor="middle" class="chart-label">{html_lib.escape(b)}</text>')
        parts.append(f'<text x="{width-right}" y="{label_y+30}" text-anchor="end" class="chart-label">{html_lib.escape(headers[0])}</text>')
        parts.append("</svg>")
        charts.append('<div class="report-chart report-chart-combo">' + "".join(parts) + "</div>")
    return "".join(charts)


def _number(text: str) -> float | None:
    cleaned = _TAG_RE.sub("", text).strip().replace(",", "").replace("%", "").replace("pt", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _table_data(table_html: str) -> tuple[list[str], list[list[str]]]:
    head = _THEAD_RE.search(table_html)
    body = _TBODY_RE.search(table_html)
    if not head or not body:
        return [], []
    head_row = _TR_RE.search(head.group(1))
    headers = [_cell_text(v[1]) for v in _extract_cells(head_row.group(1), _TH_RE)] if head_row else []
    rows = [
        [_cell_text(v[1]) for v in _extract_cells(m.group(1), _TD_RE)]
        for m in _TR_RE.finditer(body.group(1))
    ]
    return headers, rows


# ---------------------------------------------------------------------------
# ピクトグラム指定コメント + 2行テーブル -> 定性サマリー
# ---------------------------------------------------------------------------

_PICTOGRAM_BLOCK_RE = re.compile(
    r"<!--\s*pictograms:\s*([a-z0-9_-]+(?:\s*,\s*[a-z0-9_-]+){1,4})\s*-->\s*"
    r'(<div class="table-scroll"><table class="s-table">.*?</table></div>)',
    re.DOTALL | re.IGNORECASE,
)


def style_pictograms(html: str) -> str:
    """Turn an annotated one-row table into a 2–5 item pictogram summary.

    Markdown remains readable as a normal table.  HTML uses pictograms only
    where parallel qualitative items benefit from quick visual scanning; the
    component is not used for charts, numeric tables, or decoration.
    """

    def _replace(match: re.Match[str]) -> str:
        names = [name.strip().lower() for name in match.group(1).split(",")]
        table_html = match.group(2)
        headers, rows = _table_data(table_html)
        if len(rows) != 1 or len(names) != len(headers) or len(rows[0]) != len(headers):
            return table_html
        icons = [inline_pictogram(name) for name in names]
        if any(icon is None for icon in icons):
            return table_html
        cards = []
        for icon, title, copy in zip(icons, headers, rows[0]):
            cards.append(
                '<article class="pictogram-item">'
                f'<div class="pictogram-mark">{icon}</div>'
                '<div class="pictogram-text">'
                f'<div class="pictogram-title">{html_lib.escape(title)}</div>'
                f'<div class="pictogram-copy">{html_lib.escape(copy)}</div>'
                "</div></article>"
            )
        return '<div class="pictogram-grid">' + "".join(cards) + "</div>"

    return _PICTOGRAM_BLOCK_RE.sub(_replace, html)


def _label_width_px(text: str) -> float:
    """横軸ラベルのフォントサイズ10px前提での概算幅(px)。全角文字は約10px、半角は約5.8px。
    実測フォントメトリクスではなく概算(ラベルが重ならないための余白計算専用)。
    """
    return sum(10.0 if ord(ch) > 0x2000 else 5.8 for ch in text)


def _fit_axis_label(text: str) -> tuple[str, str | None]:
    """横軸ラベルを、必要なら区切り文字(〜・半角スペース・ハイフン)の位置で2行に折り返す。

    以前は12文字で機械的に切って"…"にしていたため、週次の日付レンジ表記
    (例: "2026/08/02〜08/08")やチャネル名(例: "Organic Search")が切れて重なる不具合が
    あった。**切って捨てるのではなく折り返す**ことで、年をまたぐ週(例: 12/29〜1/4)でも
    開始日の年がそのまま1行目に残る(常に開始日をフルで表示するため、圧縮ロジック無しで
    年またぎが自明にわかる)。区切りが無い/短い場合はそのまま1行で返す。
    """
    if len(text) <= 8:
        return text, None
    for sep, keep_sep_on_second_line in (("〜", True), (" ", False), ("-", False)):
        idx = text.find(sep, 1)
        if 0 < idx < len(text) - 1:
            first = text[:idx]
            second = (sep + text[idx + 1:]) if keep_sep_on_second_line else text[idx + 1:]
            return first, second
    return text, None


def _chart_svg(kind: str, title: str, headers: list[str], rows: list[list[str]]) -> str:
    if kind == "search":
        from .search_chart import search_chart
        return search_chart(title, headers, rows)
    if kind == "combo":
        return _combo_chart_svg(title, headers, rows)
    # 単位や桁が違う指標を同じ軸へ重ねると誤読を招くため、既定では
    # 表の最初の数値列だけを可視化する。表自体は直下に残す。
    numeric_cols = [
        c for c in range(1, len(headers))
        if any(c < len(row) and _number(row[c]) is not None for row in rows)
    ][:1]
    # 折れ線は月次推移の最大13点を想定する。棒グラフはカテゴリ比較なので、
    # 行を黙って切ると「全カテゴリの比較」に見える図から一部が欠落してしまう。
    # そのため棒グラフだけは全カテゴリを描画し、横幅不足はスクロールで受け止める。
    chart_rows = rows if kind == "bar" else rows[:13]
    usable = [
        row for row in chart_rows
        if row and "合計" not in row[0] and numeric_cols
        and any(c < len(row) and _number(row[c]) is not None for c in numeric_cols)
    ]
    if not usable or not numeric_cols:
        return ""
    axis_labels = [_fit_axis_label(row[0]) for row in usable]
    multiline = any(second is not None for _, second in axis_labels)
    left, right, top, plot_h = 72, 24, 50, 206
    # 横軸ラベル(折り返した1〜2行のうち幅の広い方)が重ならない最小の項目幅を求め、
    # 既定幅(760px)で足りない分だけグラフ全体を広げる。.report-chart は横スクロール可能
    # (table-scrollと同じ考え方)なので、画面幅が足りなければ図の中だけがスクロールする
    # (12文字で切って"…"にしていた以前の実装をやめた代わりの余白確保)。
    label_slot = max(
        (max(_label_width_px(l1), _label_width_px(l2 or "")) for l1, l2 in axis_labels),
        default=0,
    ) + 14
    width = max(760, round(left + right + label_slot * len(usable)))
    # ラベルが2行になる場合だけ下の余白を1行分(12px)広げる。プロット領域(plot_h)自体の
    # 高さは変えない(折り返しの有無でグラフ本体の縦横比が変わらないようにするため)。
    extra_bottom = 12 if multiline else 0
    bottom = 54 + extra_bottom
    height = top + plot_h + bottom
    label_y1 = top + plot_h + 26
    label_y2 = label_y1 + 12
    plot_w = width - left - right
    values = [_number(row[c]) or 0 for row in usable for c in numeric_cols if c < len(row)]
    vmax = max(values) or 1
    is_percent = any('%' in row[numeric_cols[0]] for row in usable if numeric_cols[0] < len(row))
    colors = ["#171717", "#9A7B1F", "#737373"]
    parts = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{html_lib.escape(title)}">']
    parts.append(f'<text x="{left}" y="24" class="chart-title">{html_lib.escape(title)}</text>')
    for i in range(5):
        y = top + plot_h * i / 4
        val = vmax * (1 - i / 4)
        parts.append(f'<line x1="{left}" y1="{y:.1f}" x2="{width-right}" y2="{y:.1f}" class="chart-grid"/>')
        tick = f"{val:.2f}%" if is_percent else (f"{val:.2f}" if vmax < 4 else f"{val:,.0f}")
        parts.append(f'<text x="{left-9}" y="{y+4:.1f}" text-anchor="end" class="chart-label">{tick}</text>')

    def _axis_label_tags(cx: float, l1: str, l2: str | None) -> str:
        tag = f'<text x="{cx:.1f}" y="{label_y1}" text-anchor="middle" class="chart-label">{html_lib.escape(l1)}</text>'
        if l2:
            tag += f'<text x="{cx:.1f}" y="{label_y2}" text-anchor="middle" class="chart-label">{html_lib.escape(l2)}</text>'
        return tag

    if kind == "bar":
        gap = plot_w / len(usable)
        bar_w = min(42, gap * .62)
        c = numeric_cols[0]
        for i, row in enumerate(usable):
            value = _number(row[c]) or 0
            h = plot_h * value / vmax
            x = left + gap * i + (gap - bar_w) / 2
            y = top + plot_h - h
            parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{h:.1f}" class="chart-bar"/>')
            l1, l2 = axis_labels[i]
            parts.append(_axis_label_tags(x + bar_w / 2, l1, l2))
        parts.append(f'<text x="{width-right}" y="24" text-anchor="end" class="chart-legend">{html_lib.escape(headers[c])}</text>')
    else:
        x_gap = plot_w / max(1, len(usable) - 1)
        for series_idx, c in enumerate(numeric_cols):
            points = []
            for i, row in enumerate(usable):
                value = _number(row[c]) or 0
                x = left + x_gap * i
                y = top + plot_h - plot_h * value / vmax
                points.append(f"{x:.1f},{y:.1f}")
                parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="{colors[series_idx]}"/>')
            parts.append(f'<polyline points="{" ".join(points)}" fill="none" stroke="{colors[series_idx]}" stroke-width="2.5"/>')
            parts.append(f'<text x="{width-right}" y="{24+series_idx*16}" text-anchor="end" fill="{colors[series_idx]}" class="chart-legend">{html_lib.escape(headers[c])}</text>')
        for i, row in enumerate(usable):
            x = left + x_gap * i
            l1, l2 = axis_labels[i]
            parts.append(_axis_label_tags(x, l1, l2))
    parts.append("</svg>")
    return '<div class="report-chart">' + "".join(parts) + "</div>"


def style_charts(html: str) -> str:
    def _render(kind: str, title_text: str | None, table_html: str) -> tuple[str, str]:
        headers, rows = _table_data(table_html)
        default_title = f"{headers[0]}別 {headers[1]}" if len(headers) > 1 else "データ比較"
        title = (title_text or default_title).strip()
        if kind == "table-bars":
            return _table_with_bars(title, table_html, headers, rows), ""
        return table_html, _chart_svg(kind, title, headers, rows)

    def _replace_with_insight(match: re.Match[str]) -> str:
        insight_html = match.group(1)
        table_html, chart_html = _render(match.group(2).lower(), match.group(3), match.group(4))
        if not chart_html:
            return insight_html + table_html
        return table_html + insight_html + chart_html

    def _replace(match: re.Match[str]) -> str:
        table_html, chart_html = _render(match.group(1).lower(), match.group(2), match.group(3))
        return table_html + chart_html

    html = _INSIGHT_CHART_BLOCK_RE.sub(_replace_with_insight, html)
    return _CHART_BLOCK_RE.sub(_replace, html)


_METADATA_PERIOD_ROW_RE = re.compile(
    r'<tr><td(?:\s[^>]*)?>(分析期間|比較期間)</td><td(?:\s[^>]*)?>(.*?)</td></tr>',
    re.DOTALL,
)
_JA_DATE_RANGE_RE = re.compile(
    r"(\d{4})年(\d{1,2})月(\d{1,2})日\s*[〜～~]\s*"
    r"(\d{4})年(\d{1,2})月(\d{1,2})日"
)
_STYLED_TABLE_BLOCK_RE = re.compile(
    r'<div class="table-scroll"><table class="s-table(?: [^"]*)?">.*?</table></div>',
    re.DOTALL,
)


def _compact_date_range(value: str) -> str | None:
    match = _JA_DATE_RANGE_RE.search(value)
    if not match:
        return None
    sy, sm, sd, ey, em, ed = map(int, match.groups())
    start = date(sy, sm, sd)
    end = date(ey, em, ed)
    if start.day == 1 and end.day == calendar.monthrange(end.year, end.month)[1]:
        return f"{start.year}/{start.month}〜{end.year}/{end.month}"
    return f"{start.year}/{start.month}/{start.day}〜{end.year}/{end.month}/{end.day}"


def annotate_period_headers(html: str) -> str:
    """サマリー表の当期・比較期へ、前置きに書かれた実日付範囲を付ける。"""
    periods: dict[str, str] = {}
    for label, raw_value in _METADATA_PERIOD_ROW_RE.findall(html):
        compact = _compact_date_range(html_lib.unescape(_TAG_RE.sub("", raw_value)).strip())
        if compact:
            periods[label] = compact
    current = periods.get("分析期間")
    previous = periods.get("比較期間")
    if not current or not previous:
        return html

    def _replace_table(match: re.Match[str]) -> str:
        table_html = match.group(0)
        headers, _ = _table_data(table_html)
        if not headers or headers[0].strip() != "指標":
            return table_html
        for old, new in {
            "当期": f"当期（{current}）",
            "前期": f"前期（{previous}）",
            "前年同期": f"前年同期（{previous}）",
        }.items():
            table_html = re.sub(
                rf"(<th(?:\s[^>]*)?>){old}(</th>)",
                rf"\1{new}\2",
                table_html,
            )
        return table_html

    return _STYLED_TABLE_BLOCK_RE.sub(_replace_table, html)


# ---------------------------------------------------------------------------
# 見出し -> .section-title / .sub-title
# ---------------------------------------------------------------------------

_HEADING_OPEN_RE = re.compile(r'<h([1-6])((?:\s+[a-zA-Z-]+="[^"]*")*)>')

# 先頭H1は表紙タイトルとして既に抜き出し済み(markdown_utils.extract_title_and_strip)。
# 本文中に残るh1/h2は.section-title、h3以降は.sub-titleとして扱う。
_HEADING_CLASS = {1: "section-title", 2: "section-title", 3: "sub-title", 4: "sub-title", 5: "sub-title", 6: "sub-title"}


def style_headings(html: str) -> str:
    def _replace(m: re.Match[str]) -> str:
        level = int(m.group(1))
        attrs = m.group(2)
        return f'<h{level}{attrs} class="{_HEADING_CLASS[level]}">'

    return _HEADING_OPEN_RE.sub(_replace, html)


# ---------------------------------------------------------------------------
# 本文内の目次リンク -> 実際に振られた見出しidへ張り替え
# ---------------------------------------------------------------------------
#
# markdownの"toc"拡張は既定のslugify(ASCII化。日本語は丸ごと落ちる)でidを振るため、
# 見出し「3. ランディングページ別（セッション上位10件）」のidは "3-10" のような
# 断片になる。一方、本文に手書きされる目次は
# `[ランディングページ別](#3-ランディングページ別セッション上位10件)` のように、
# 日本語を残す一般的なMarkdownアンカー規則(GitHub等のスラッグ化と同じ考え方)で
# 書かれている。両者は一致しないためクリックしても飛ばない。
#
# サイドバー目次(house_style._build_toc)は実際に振られたidをそのまま読んで
# リンクを作るので元々壊れていない。壊れているのは本文に書かれたリンクだけ。
#
# 直し方: 見出しidそのものの採番規則(ASCII化)は変えない。既存のidに依存する
# 挙動(サイドバー目次・重複時の連番など)を変えないための判断。代わりに、
# 「見出しテキストを一般的なアンカー規則でスラッグ化した値」→「実際のid」の
# 対応表を作り、本文内リンクの遷移先がその対応表のキーと一致する場合だけ
# 実際のidへ張り替える。対応する見出しが無いリンク(誤記・見出し削除など)は
# 安全側で元のまま残す(違う場所へ飛ばすより、何も起きない方がまし)。
_HEADING_WITH_ID_RE = re.compile(
    r'<h[1-6][^>]*\sid="(?P<id>[^"]+)"[^>]*>(?P<text>.*?)</h[1-6]>',
    re.DOTALL,
)
_INTERNAL_LINK_RE = re.compile(r'(<a\b[^>]*\bhref="#)([^"]*)(")')


def _anchor_slug(heading_text: str) -> str:
    """見出しの表示テキストを、本文リンクが前提にしている規則でスラッグ化する。

    markdown.extensions.toc.slugify_unicode と同じ関数を使う。id採番自体には
    使わない(id採番は既定のASCII化のまま)が、「本文リンクの書き手が期待する
    アンカー」を逆算するのに使う。
    """
    return slugify_unicode(html_lib.unescape(heading_text), "-")


def relink_body_toc_links(html: str) -> str:
    """本文内の目次リンクのhrefを、実際に生成された見出しidへ張り替える。"""
    actual_ids: set[str] = set()
    slug_to_id: dict[str, str] = {}
    for m in _HEADING_WITH_ID_RE.finditer(html):
        heading_id = m.group("id")
        actual_ids.add(heading_id)
        heading_text = _TAG_RE.sub("", m.group("text")).strip()
        if not heading_text:
            continue
        slug = _anchor_slug(heading_text)
        # 同名見出しが複数ある場合は最初の1つに解決する(元のMarkdown自体が
        # 同じアンカー文字列で複数見出しを指しており、書き手側でも曖昧なため)。
        slug_to_id.setdefault(slug, heading_id)

    if not slug_to_id:
        return html

    def _replace(m: re.Match[str]) -> str:
        prefix, fragment, suffix = m.group(1), m.group(2), m.group(3)
        if not fragment or fragment in actual_ids:
            return m.group(0)
        target = slug_to_id.get(fragment) or slug_to_id.get(urllib.parse.unquote(fragment))
        if target is None:
            return m.group(0)
        return f"{prefix}{target}{suffix}"

    return _INTERNAL_LINK_RE.sub(_replace, html)


def designify_body(html: str) -> str:
    """Markdown変換直後の本文HTMLを、design-system.mdの部品クラスへ整形する。"""
    html = style_tables(html)
    html = annotate_period_headers(html)
    html = style_pictograms(html)
    html = style_blockquotes(html)
    html = style_charts(html)
    html = style_headings(html)
    html = relink_body_toc_links(html)
    return html
