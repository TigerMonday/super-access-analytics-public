"""Googleスプレッドシート書き出しのテスト。

実際のGoogle Sheets APIは叩かない。spreadsheets().get()/batchUpdate()/values().update()を
呼び出し内容の記録だけ行うフェイクサービスに差し替え、
- 既存シートを一切変更せず、新しいシートが追加されること
- 同名シートがあれば連番になること
- 書き込み先URL未指定でエラーになること
を検証する。
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from report_export.gsheet_export import (
    build_sheet_rows,
    export_gsheet,
    generate_new_sheet_title,
)


class _Executable:
    def __init__(self, payload):
        self._payload = payload

    def execute(self):
        return self._payload


class FakeSheetsService:
    """既存シート名の一覧を保持し、addSheet/values.update/format をそのまま記録するフェイク。"""

    def __init__(self, existing_titles: list[str]):
        self.existing_titles = list(existing_titles)
        self._next_sheet_id = 1000
        self.added_titles: list[str] = []
        self.values_calls: list[dict] = []
        self.format_calls: list[dict] = []
        self.new_sheet_ids: set[int] = set()

    def spreadsheets(self):
        return self

    def get(self, spreadsheetId: str):  # noqa: N803
        return _Executable(
            {"sheets": [{"properties": {"title": t}} for t in self.existing_titles]}
        )

    def batchUpdate(self, spreadsheetId: str, body: dict):  # noqa: N802,N803
        requests = body["requests"]
        if any("addSheet" in r for r in requests):
            assert len(requests) == 1, "作成リクエストに他の操作が混入"
            assert set(requests[0]) == {"addSheet"}
            title = requests[0]["addSheet"]["properties"]["title"]
            assert title not in self.existing_titles, "既存シートと同名を作ろうとした"
            sheet_id = self._next_sheet_id
            self._next_sheet_id += 1
            self.new_sheet_ids.add(sheet_id)
            self.added_titles.append(title)
            self.existing_titles.append(title)  # 実際のSheetsも追加後は既存扱いになる
            return _Executable({"replies": [{"addSheet": {"properties": {"sheetId": sheet_id, "title": title}}}]})
        for request in requests:
            assert set(request) == {"repeatCell"}, "既存シートの削除・変更につながる操作"
            assert request["repeatCell"]["range"]["sheetId"] in self.new_sheet_ids
            assert request["repeatCell"]["fields"] == "userEnteredFormat.textFormat.bold"
        self.format_calls.append(requests)
        return _Executable({"replies": []})

    def values(self):
        return self

    def update(self, spreadsheetId: str, range: str, valueInputOption: str, body: dict):  # noqa: N803,A002
        assert range in {f"'{title}'!A1" for title in self.added_titles}, "既存タブへの書き込み"
        assert valueInputOption == "RAW", "本文を数式として実行しない"
        self.values_calls.append({"range": range, "values": body["values"]})
        return _Executable({})


# --- generate_new_sheet_title: 純粋関数のテスト ---


def test_generate_new_sheet_title_unique_name_unchanged():
    assert generate_new_sheet_title("計測チェック_2026-09-06", []) == "計測チェック_2026-09-06"


def test_generate_new_sheet_title_collision_gets_numbered_suffix():
    existing = ["計測チェック_2026-09-06"]
    name = generate_new_sheet_title("計測チェック_2026-09-06", existing)
    assert name == "計測チェック_2026-09-06_2"


def test_generate_new_sheet_title_multiple_collisions_increment():
    existing = ["レポート_2026-09-06", "レポート_2026-09-06_2"]
    name = generate_new_sheet_title("レポート_2026-09-06", existing)
    assert name == "レポート_2026-09-06_3"


def test_generate_new_sheet_title_strips_forbidden_characters():
    name = generate_new_sheet_title("5:流入/質[参考]_2026-09-06", [])
    for ch in "\\/?*[]:":
        assert ch not in name


# --- build_sheet_rows: 純粋関数のテスト ---


def test_build_sheet_rows_expands_table_with_bold_header():
    md = "# タイトル\n\n| a | b |\n|---|---|\n| 1 | 2 |\n"
    content = build_sheet_rows(md)
    assert ["a", "b"] in content.rows
    assert ["1", "2"] in content.rows
    header_row_index = content.rows.index(["a", "b"])
    assert header_row_index in content.table_header_rows


def test_build_sheet_rows_includes_heading_as_row():
    md = "# 見出し1\n\n本文\n"
    content = build_sheet_rows(md)
    assert ["見出し1"] in content.rows
    assert ["本文"] in content.rows


# --- export_gsheet: フェイクサービス経由のテスト ---


def test_export_gsheet_requires_target():
    with pytest.raises(ValueError):
        export_gsheet(Path("dummy.md"), None, "# タイトル\n本文\n")


def test_export_gsheet_adds_new_sheet_without_touching_existing(tmp_path: Path):
    service = FakeSheetsService(existing_titles=["既存タブ1", "既存タブ2"])
    md_path = tmp_path / "report.md"
    md_text = "# 集客レポート\n\n| a | b |\n|---|---|\n| 1 | 2 |\n"

    url = export_gsheet(
        md_path,
        "https://docs.google.com/spreadsheets/d/xyz789/edit",
        md_text,
        service=service,
        today=date(2026, 9, 6),
    )

    # 既存シートは変更されない(削除も上書きもされない)
    assert "既存タブ1" in service.existing_titles
    assert "既存タブ2" in service.existing_titles
    # 新しいシートが1枚追加される
    assert service.added_titles == ["集客レポート_2026-09-06"]
    assert "xyz789" in url
    assert len(service.values_calls) == 1
    written = service.values_calls[0]
    assert written["range"] == "'集客レポート_2026-09-06'!A1"
    # 表の間の空行はレイアウトの自由度として許容する。
    assert [row for row in written["values"] if row] == [["集客レポート"], ["a", "b"], ["1", "2"]]


def test_export_gsheet_dedupes_when_same_name_exists_same_day(tmp_path: Path):
    service = FakeSheetsService(existing_titles=["集客レポート_2026-09-06"])
    md_path = tmp_path / "report.md"
    md_text = "# 集客レポート\n\n本文\n"

    export_gsheet(md_path, "xyz789", md_text, service=service, today=date(2026, 9, 6))

    assert service.added_titles == ["集客レポート_2026-09-06_2"]
    # 元のシート名はそのまま残っている(上書きされていない)
    assert "集客レポート_2026-09-06" in service.existing_titles


def test_export_gsheet_writes_table_values_to_new_sheet(tmp_path: Path):
    service = FakeSheetsService(existing_titles=[])
    md_path = tmp_path / "report.md"
    md_text = "# レポート\n\n| チャネル | CVR |\n|---|---|\n| Organic | 3.2% |\n"

    export_gsheet(md_path, "xyz789", md_text, service=service, today=date(2026, 9, 6))

    assert len(service.values_calls) == 1
    values = service.values_calls[0]["values"]
    assert ["チャネル", "CVR"] in values
    assert ["Organic", "3.2%"] in values
