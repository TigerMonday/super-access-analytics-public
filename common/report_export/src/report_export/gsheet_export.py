"""MarkdownからGoogleスプレッドシート(既存ファイル)への追加書き込み。

## サービスアカウントの制約と、そこから来る設計

gdoc_export.pyと同じ理由(サービスアカウントは新規ファイルを作れない)で、新規スプレッドシート
の自動作成は行わない。書き込み先は既存スプレッドシートのURL(またはID)で指定し、無ければ
エラーで止めて何を用意すればよいかを案内する。

## 上書き事故を避ける設計

**既存のシート(タブ)には一切触らず、毎回新しいシートを追加する。**
シート名は `{レポート名}_{YYYY-MM-DD}` とし、同名タブが既にあれば `_2` のように連番を足す
(既存を上書き・削除しない。docx/xlsxの `check-report-notes.md` と同じ「機械が人の書いた
ものを上書きする」事故を避ける設計)。

## 表以外の本文の扱い(方針)

このツールは「毎回1枚のシートを追加する」設計(複数タブを増やさない)なので、xlsx出力
(表ごとに別シート)とは異なり、見出し・本文・表を**1枚のシートの中に縦に並べて**書き込む。
表が読める形になっていることを最優先し、見出しは太字1行、表はヘッダー行を太字にした
セルの並びとして展開する。本文の段落は1セル1行のプレーンテキストとして流し込む
(装飾はしない。Excel出力の「概要シート」と同様、表計算ツールでの見た目は簡略化する前提)。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from . import google_auth
from .markdown_utils import extract_title_and_strip
from .md_tables import _HEADING_RE, _SEP_LINE_RE, parse_markdown_for_excel

_BULLET_RE = re.compile(r"^(\s*)[-*+]\s+(.*)$")
_INVALID_SHEET_CHARS = re.compile(r"[\\/?*\[\]:]")
# Sheets API自体の制約はxlsxより緩いが、後でExcelへエクスポートされても壊れないよう
# xlsx側(xlsx_export.py)と同じ禁止文字・長さ制約を踏襲しておく。
MAX_SHEET_NAME_LEN = 100


@dataclass
class SheetContent:
    """新しいシートに書き込む行データと書式範囲(すべて0始まりの行インデックス)。"""

    rows: list[list[str]] = field(default_factory=list)
    heading_rows: list[tuple[int, int]] = field(default_factory=list)  # (row_index, level)
    table_header_rows: list[int] = field(default_factory=list)


def generate_new_sheet_title(base_name: str, existing_titles: list[str]) -> str:
    """既存タブ名と衝突しない新しいシート名を作る(純粋関数)。既存名は変更しない。"""
    cleaned = _INVALID_SHEET_CHARS.sub("_", base_name).strip() or "Sheet"
    cleaned = cleaned[:MAX_SHEET_NAME_LEN]
    used = {t.lower() for t in existing_titles}

    if cleaned.lower() not in used:
        return cleaned

    n = 2
    while True:
        candidate = f"{cleaned}_{n}"[:MAX_SHEET_NAME_LEN]
        if candidate.lower() not in used:
            return candidate
        n += 1


def build_sheet_rows(md_text: str) -> SheetContent:
    """Markdown本文を、1枚のシートに書き込む行データへ変換する。"""
    parsed = parse_markdown_for_excel(md_text)
    table_by_start = {t.start_line: t for t in parsed.tables}
    lines = md_text.splitlines()
    n = len(lines)

    rows: list[list[str]] = []
    heading_rows: list[tuple[int, int]] = []
    table_header_rows: list[int] = []

    i = 0
    in_code_fence = False
    while i < n:
        line = lines[i]

        if i in table_by_start:
            table = table_by_start[i]
            if table.headers:
                table_header_rows.append(len(rows))
                rows.append(list(table.headers))
            for row in table.rows:
                rows.append(list(row))
            rows.append([])
            i = table.end_line
            continue

        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_code_fence = not in_code_fence
            i += 1
            continue
        if in_code_fence:
            rows.append([line])
            i += 1
            continue

        h = _HEADING_RE.match(line)
        if h:
            heading_rows.append((len(rows), min(len(h.group(1)), 6)))
            rows.append([h.group(2).strip()])
            i += 1
            continue

        if _SEP_LINE_RE.match(stripped) and stripped:
            i += 1
            continue

        bullet = _BULLET_RE.match(line)
        if bullet:
            rows.append([f"・{bullet.group(2)}"])
            i += 1
            continue

        if not stripped:
            i += 1
            continue

        rows.append([stripped])
        i += 1

    return SheetContent(rows=rows, heading_rows=heading_rows, table_header_rows=table_header_rows)


def build_format_requests(sheet_id: int, content: SheetContent) -> list[dict]:
    """見出し・表ヘッダー行を太字にするbatchUpdate用requestsを組み立てる(純粋関数)。"""
    requests: list[dict] = []
    bold_rows = [r for r, _level in content.heading_rows] + content.table_header_rows
    for row_index in bold_rows:
        requests.append(
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": row_index,
                        "endRowIndex": row_index + 1,
                    },
                    "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                    "fields": "userEnteredFormat.textFormat.bold",
                }
            }
        )
    return requests


def export_gsheet(
    md_path: Path,
    target: str | None,
    md_text: str,
    *,
    service=None,
    today: date | None = None,
) -> str:
    """Markdownの内容を、既存のGoogleスプレッドシートへ新しいシートとして追加する。

    書き込んだシートのURL(gid付き)を返す。既存シートは一切変更しない。

    target: 書き込み先スプレッドシートのURL、またはID。未指定ならエラーで止める。
    service: Sheets APIクライアント。テスト用の差し替え口(未指定なら認証して実クライアントを作る)。
    today: シート名の日付部分に使う日付。未指定なら実行時点の日付。
    """
    if not target:
        raise ValueError(
            "書き込み先のGoogleスプレッドシートが指定されていません。--gsheet に既存スプレッド"
            "シートのURL(またはID)を指定してください。サービスアカウントは新規ファイルを作成でき"
            "ないため、事前に対象スプレッドシートを用意し、認証ファイルの client_email の値を"
            "編集者として共有しておいてください。"
        )

    spreadsheet_id = google_auth.extract_sheet_id(target)
    title, _ = extract_title_and_strip(md_text, fallback=md_path.stem)
    date_str = (today or date.today()).isoformat()

    if service is None:
        creds = google_auth.get_credentials()
        service = google_auth.build_sheets_service(creds)

    spreadsheet = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    existing_titles = [s["properties"]["title"] for s in spreadsheet.get("sheets", [])]
    new_title = generate_new_sheet_title(f"{title}_{date_str}", existing_titles)

    add_response = (
        service.spreadsheets()
        .batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": [{"addSheet": {"properties": {"title": new_title}}}]},
        )
        .execute()
    )
    new_sheet_id = add_response["replies"][0]["addSheet"]["properties"]["sheetId"]

    content = build_sheet_rows(md_text)
    if content.rows:
        service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f"'{new_title}'!A1",
            valueInputOption="RAW",
            body={"values": content.rows},
        ).execute()

    format_requests = build_format_requests(new_sheet_id, content)
    if format_requests:
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id, body={"requests": format_requests}
        ).execute()

    return f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit#gid={new_sheet_id}"
