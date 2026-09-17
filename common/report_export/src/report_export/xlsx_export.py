"""MarkdownからExcel(xlsx)への変換。

方針: MD中の表を1シートずつに展開し、文章セクションは「概要」シートへまとめる。
Excelは表計算向きで文章主体レポートには不向きという前提の割り切り。
"""

from __future__ import annotations

import math
import re
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from .md_tables import ParsedMarkdown, parse_markdown_for_excel

# design_system/design-system.md のグレースケーストークンに合わせた配色
# (--gray-50 / --gray-900 / --gray-500 相当。xlsxはCSSが効かないため直書き)。
_HEADER_FILL = PatternFill(start_color="FAFAFA", end_color="FAFAFA", fill_type="solid")
_HEADER_FONT = Font(bold=True, color="171717")
_INVALID_SHEET_CHARS = re.compile(r"[\\/?*\[\]:]")

MAX_SHEET_NAME_LEN = 31

_ELLIPSIS = "…"
# 見出し先頭の番号プレフィックス(「3. 」「10) 」等)。短縮しても意味が分かるよう保持する。
_LEADING_NUM_RE = re.compile(r"^\d+[.)]\s*")
# md_tables側で同一見出しの重複に付く連番サフィックス(「_2」「_3」等)。
# 単純な前方一致truncateだとこれが真っ先に削れて2枚の表が区別できなくなるため、
# 短縮時は最優先で末尾に残す。
_DUP_SUFFIX_RE = re.compile(r"_(\d+)$")


def _write_text_cell(ws: Worksheet, row: int, column: int, value: str):
    """レポート由来の文字列をExcel数式として評価させない。"""
    cell = ws.cell(row=row, column=column, value=value)
    if isinstance(value, str):
        # = は openpyxl が数式に変換する。明示的に文字列へ戻す。
        # + / - / @ も引用済みテキストとして保存し、表示値は保持する。
        cell.data_type = "s"
        if value.lstrip().startswith(("=", "+", "-", "@")):
            cell.quotePrefix = True
    return cell


def _split_trailing_dup_suffix(name: str) -> tuple[str, str]:
    """末尾の重複連番サフィックス(_2 等)を切り出す。戻り値は (残り, サフィックス)。"""
    m = _DUP_SUFFIX_RE.search(name)
    if m:
        return name[: m.start()], name[m.start() :]
    return name, ""


def _shorten_to_fit(name: str, max_len: int) -> str:
    """name を max_len 文字に短縮する。

    先頭の番号プレフィックスと末尾の重複連番サフィックスは可能な限りそのまま残し、
    中間の説明部分(括弧書きなど)だけを省略記号で圧縮する。これにより、
    同じ見出しに由来する別表同士が単純truncateで見分けられなくなるのを避ける。
    """
    if len(name) <= max_len:
        return name

    core, dup_suffix = _split_trailing_dup_suffix(name)
    head_match = _LEADING_NUM_RE.match(core)
    prefix = head_match.group(0) if head_match else ""
    body = core[len(prefix) :]

    available = max_len - len(prefix) - len(dup_suffix)
    if available <= 0:
        # 番号プレフィックスと連番サフィックスだけで上限を超える極端なケース。
        # 単純truncateにフォールバックする。
        return (prefix + dup_suffix)[:max_len]

    if len(body) <= available:
        return prefix + body + dup_suffix

    if available <= len(_ELLIPSIS):
        return prefix + body[:available] + dup_suffix

    # 中間を省略記号で圧縮する。前方(見出しの主題)をやや多めに残しつつ、
    # 後方(区別に効く末尾)も一定量残す。
    content_budget = available - len(_ELLIPSIS)
    head_len = min(math.ceil(content_budget * 0.6), content_budget)
    tail_len = content_budget - head_len
    shortened_body = body[:head_len] + _ELLIPSIS + (body[-tail_len:] if tail_len else "")
    return prefix + shortened_body + dup_suffix


def generate_sheet_name(name: str, used: set[str]) -> str:
    """Excelシート名として妥当・一意な名前を生成する(純粋関数)。

    - 禁止文字(\\ / ? * [ ] :)を除去する。
    - 31文字上限に収める。超える場合は先頭からの単純truncateではなく、
      番号プレフィックスと末尾の差分(重複連番等)を残す形で中間を短縮する。
    - それでも既存の名前(used、小文字比較)と衝突する場合、最後の手段として
      末尾に (2), (3)... を付与する。
    - `used` は変更しない(呼び出し側で管理する)。
    """
    cleaned = _INVALID_SHEET_CHARS.sub("_", name).strip().strip("'")
    if not cleaned:
        cleaned = "Sheet"

    candidate = _shorten_to_fit(cleaned, MAX_SHEET_NAME_LEN)
    if candidate.lower() not in used:
        return candidate

    n = 2
    while True:
        suffix = f"({n})"
        base_budget = MAX_SHEET_NAME_LEN - len(suffix)
        base = _shorten_to_fit(cleaned, base_budget)
        candidate = base + suffix
        if candidate.lower() not in used:
            return candidate
        n += 1


def _sanitize_sheet_name(name: str, used: set[str]) -> str:
    candidate = generate_sheet_name(name, used)
    used.add(candidate.lower())
    return candidate


def _autosize_columns(ws: Worksheet, n_cols: int, sample_rows: list[list[str]]) -> None:
    widths = [8] * n_cols
    for row in sample_rows:
        for idx, cell in enumerate(row):
            if idx >= n_cols:
                continue
            # マルチバイト文字は幅を広めに見積もる
            longest_line = max((len(line) for line in str(cell).split("\n")), default=0)
            widths[idx] = max(widths[idx], min(longest_line + 2, 60))
    for idx, width in enumerate(widths):
        ws.column_dimensions[get_column_letter(idx + 1)].width = width


def _write_overview_sheet(wb: Workbook, parsed: ParsedMarkdown, source_name: str) -> None:
    ws = wb.active
    ws.title = "概要"
    ws.append([f"出典: {source_name}"])
    ws["A1"].font = Font(italic=True, color="737373", size=10)
    row_idx = 3

    if not parsed.prose_lines:
        ws.cell(row=row_idx, column=1, value="(本文セクションはありません。表はテーブル名のシートを参照)")
        _autosize_columns(ws, 1, [])
        return

    heading_sizes = {
        "heading1": 15,
        "heading2": 13,
        "heading3": 12,
        "heading4": 11,
    }
    for kind, text in parsed.prose_lines:
        cell = _write_text_cell(ws, row_idx, 1, text)
        if kind in heading_sizes:
            cell.font = Font(bold=True, size=heading_sizes[kind])
        elif kind == "code":
            cell.font = Font(name="Menlo", size=10)
        else:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
        row_idx += 1

    ws.column_dimensions["A"].width = 100


def _write_table_sheet(wb: Workbook, used_names: set[str], table) -> None:
    name = _sanitize_sheet_name(table.title, used_names)
    ws = wb.create_sheet(title=name)

    n_cols = max(len(table.headers), max((len(r) for r in table.rows), default=0))
    for col_idx, header in enumerate(table.headers, start=1):
        cell = _write_text_cell(ws, 1, col_idx, header)
        cell.font = _HEADER_FONT
        cell.fill = _HEADER_FILL
        cell.alignment = Alignment(wrap_text=True, vertical="center")
    # ヘッダーがrows中の最大列数より少ない場合、残りの列も塗りだけ揃える
    for col_idx in range(len(table.headers) + 1, n_cols + 1):
        cell = ws.cell(row=1, column=col_idx, value="")
        cell.font = _HEADER_FONT
        cell.fill = _HEADER_FILL

    for r_offset, row in enumerate(table.rows, start=2):
        for c_offset, value in enumerate(row, start=1):
            cell = _write_text_cell(ws, r_offset, c_offset, value)
            if "\n" in value:
                cell.alignment = Alignment(wrap_text=True, vertical="top")

    if n_cols > 0:
        ws.freeze_panes = "A2"
        _autosize_columns(ws, n_cols, [table.headers] + table.rows)


def export_xlsx(md_path: Path, output_path: Path, md_text: str) -> Path:
    """MarkdownをxlsxへエクスポートしてPathを返す。"""
    parsed = parse_markdown_for_excel(md_text)

    wb = Workbook()
    _write_overview_sheet(wb, parsed, md_path.name)

    used_names = {"概要".lower()}
    for table in parsed.tables:
        _write_table_sheet(wb, used_names, table)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(output_path)
    return output_path
