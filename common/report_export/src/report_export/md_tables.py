"""Markdown中のテーブル抽出とプレーンテキスト化。

xlsx出力向け。MDテーブルのパイプ`|`区切り・エスケープ済みパイプ`\\|`・
セル内`<br>`改行・空セルを崩さず扱う。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
# 区切り行: |---|:---:|---:|:-:|-| のような行(パイプ・ハイフン・コロン・スペースのみ)
# 各セルは 前後任意のコロン + ハイフン1個以上(:-: / :- / -: / - / --- など)を許容する。
_SEP_LINE_RE = re.compile(r"^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$")
_CODE_FENCE_RE = re.compile(r"^\s*(```|~~~)")


@dataclass
class Table:
    title: str
    headers: list[str]
    rows: list[list[str]]
    start_line: int
    end_line: int  # 排他的(この行は含まない)


@dataclass
class ParsedMarkdown:
    tables: list[Table] = field(default_factory=list)
    prose_lines: list[tuple[str, str]] = field(default_factory=list)
    # prose_lines: (kind, text) kind in {"heading1".."heading6", "text"}


def _split_row(line: str) -> list[str]:
    """テーブル行をセルに分割する。エスケープ済みパイプ`\\|`は分割対象にしない。"""
    line = line.strip()
    # 先頭・末尾のパイプを除去(あれば)。ただしエスケープパイプでないもののみ。
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|") and not line.endswith("\\|"):
        line = line[:-1]
    # (?<!\\)\| で「直前がバックスラッシュでないパイプ」のみ分割点にする
    raw_cells = re.split(r"(?<!\\)\|", line)
    cells = []
    for cell in raw_cells:
        cell = cell.strip()
        cell = cell.replace("\\|", "|")
        cells.append(cell)
    return cells


def _looks_like_table_row(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    # 分割不要のエスケープを考慮した上で、パイプが1つ以上あるか
    unescaped = re.sub(r"\\\|", "", stripped)
    return "|" in unescaped


def _sanitize_cell_for_excel(cell: str) -> str:
    """セル内の<br>系改行をExcelの改行(\\n)に変換し、簡易的にインラインMD記法を除去する。"""
    text = re.sub(r"<br\s*/?>", "\n", cell, flags=re.IGNORECASE)
    # 太字・イタリック・インラインコードの記号だけ外す(内容は残す)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    # [text](url) -> text (url)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", text)
    return text


def _strip_inline_md(text: str) -> str:
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", text)
    return text


def parse_markdown_for_excel(md_text: str) -> ParsedMarkdown:
    """MarkdownをExcel向けに解析する。

    表ブロックを検出して抜き出し、残りは見出し/本文の行リストとして返す。
    """
    lines = md_text.splitlines()
    n = len(lines)
    tables: list[Table] = []
    consumed = [False] * n
    last_heading: str | None = None
    heading_seen_count: dict[str, int] = {}
    untitled_table_count = 0

    i = 0
    in_code_fence = False
    while i < n:
        line = lines[i]

        if _CODE_FENCE_RE.match(line):
            in_code_fence = not in_code_fence
            i += 1
            continue

        if in_code_fence:
            i += 1
            continue

        h = _HEADING_RE.match(line)
        if h:
            last_heading = h.group(2).strip()
            i += 1
            continue

        # テーブル候補: 現在行がテーブル行っぽく、次の非空行が区切り行
        if _looks_like_table_row(line) and i + 1 < n and _SEP_LINE_RE.match(lines[i + 1]):
            header_cells = _split_row(line)
            body_start = i + 2
            j = body_start
            body_rows: list[list[str]] = []
            while j < n and _looks_like_table_row(lines[j]) and not _SEP_LINE_RE.match(lines[j]):
                body_rows.append(_split_row(lines[j]))
                j += 1

            if last_heading is None:
                # 見出しの前に表が出現した場合の既定名。「概要」シート(xlsx側で予約済み)
                # と衝突しないよう、連番の既定名にする。
                untitled_table_count += 1
                title = f"表{untitled_table_count}"
            else:
                title = last_heading
                count = heading_seen_count.get(title, 0)
                heading_seen_count[title] = count + 1
                if count > 0:
                    title = f"{title}_{count + 1}"

            tables.append(
                Table(
                    title=title,
                    headers=[_sanitize_cell_for_excel(c) for c in header_cells],
                    rows=[[_sanitize_cell_for_excel(c) for c in row] for row in body_rows],
                    start_line=i,
                    end_line=j,
                )
            )
            for k in range(i, j):
                consumed[k] = True
            i = j
            continue

        i += 1

    prose_lines: list[tuple[str, str]] = []
    in_code_fence = False
    for idx, line in enumerate(lines):
        if consumed[idx]:
            continue
        if _CODE_FENCE_RE.match(line):
            in_code_fence = not in_code_fence
            continue
        if in_code_fence:
            if line.strip():
                prose_lines.append(("code", line))
            continue
        h = _HEADING_RE.match(line)
        if h:
            level = len(h.group(1))
            prose_lines.append((f"heading{level}", h.group(2).strip()))
            continue
        stripped = line.strip()
        if not stripped:
            continue
        if _SEP_LINE_RE.match(stripped):
            # 表の残骸ではない孤立した区切り行(hr等)はそのまま無視
            continue
        prose_lines.append(("text", _strip_inline_md(stripped)))

    return ParsedMarkdown(tables=tables, prose_lines=prose_lines)
