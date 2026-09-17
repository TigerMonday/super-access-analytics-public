"""Googleドキュメント書き出しのテスト。

実際のGoogle Docs APIは叩かない。documents().get()/batchUpdate()の代わりに、
簡易的な「インメモリDocs文書モデル」を持つフェイクサービスを使い、
- 対象の見出し1区画だけが置き換わること
- `メモ`見出し以下が一切変更されないこと
- 対象の見出しが無ければ末尾(または`メモ`の手前)に追記されること
- 書き込み先URL未指定でエラーになること
を、batchUpdateのrequestsを実際に適用した結果(最終的な段落テキストの並び)で検証する。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from report_export.gdoc_export import (
    NOTES_HEADING_TEXT,
    ReservedHeadingError,
    TableOp,
    build_batch_requests,
    build_cell_fill_requests,
    build_region_content,
    export_gdoc,
    find_doc_region,
    find_tables_after,
)


def _paragraph(text: str, *, heading1: bool = False, start: int, end: int) -> dict:
    style = {"namedStyleType": "HEADING_1"} if heading1 else {"namedStyleType": "NORMAL_TEXT"}
    return {
        "startIndex": start,
        "endIndex": end,
        "paragraph": {
            "paragraphStyle": style,
            "elements": [{"textRun": {"content": text}}],
        },
    }


def _doc_from_paragraphs(texts_and_flags: list[tuple[str, bool]]) -> dict:
    """(テキスト, 見出し1か)のリストから、インデックス計算済みのdocument JSONを組み立てる。"""
    content = []
    pos = 1
    for text, is_h1 in texts_and_flags:
        body = text + "\n"
        start = pos
        end = pos + len(body)
        content.append(_paragraph(body, heading1=is_h1, start=start, end=end))
        pos = end
    return {"body": {"content": content}}


class FakeDocsModel:
    """段落のリストとして文書を表現し、batchUpdateのrequestsを実際に適用するフェイク。"""

    def __init__(self, texts_and_flags: list[tuple[str, bool]]):
        # 各要素: [text(改行含まない), is_heading1, is_bold, is_bullet]
        self.paragraphs = [[t, h1, False, False] for t, h1 in texts_and_flags]
        self.batch_calls: list[list[dict]] = []

    def _to_document(self) -> dict:
        pairs = [(t, h1) for t, h1, _bold, _bullet in self.paragraphs]
        return _doc_from_paragraphs(pairs)

    def _flat_offsets(self) -> list[tuple[int, int]]:
        doc = self._to_document()
        return [(el["startIndex"], el["endIndex"]) for el in doc["body"]["content"]]

    def documents(self):
        return self

    def get(self, documentId: str):  # noqa: N803 (Docs APIの引数名に合わせる)
        return _Executable(self._to_document())

    def batchUpdate(self, documentId: str, body: dict):  # noqa: N802,N803
        requests = body["requests"]
        self.batch_calls.append(requests)
        self._apply(requests)
        return _Executable({})

    def _apply(self, requests: list[dict]) -> None:
        for req in requests:
            if "deleteContentRange" in req:
                self._delete(req["deleteContentRange"]["range"])
            elif "insertText" in req:
                self._insert(req["insertText"]["location"]["index"], req["insertText"]["text"])
            elif "updateParagraphStyle" in req:
                pass  # このフェイクでは段落分割済みテキストの内容一致だけ見る(見出しレベルは別テストで検証)
            elif "updateTextStyle" in req:
                pass
            elif "createParagraphBullets" in req:
                pass

    def _delete(self, rng: dict) -> None:
        start, end = rng["startIndex"], rng["endIndex"]
        offsets = self._flat_offsets()
        keep = [
            self.paragraphs[i]
            for i, (s, e) in enumerate(offsets)
            if not (s >= start and e <= end)
        ]
        self.paragraphs = keep

    def _insert(self, index: int, text: str) -> None:
        offsets = self._flat_offsets()
        # 挿入位置を含む段落を特定し、その手前で新規段落群に分割する。
        insert_at_para = len(self.paragraphs)
        for i, (s, e) in enumerate(offsets):
            if s <= index <= e:
                insert_at_para = i
                break
        new_paragraphs = [[line, False, False, False] for line in text.split("\n") if line != ""]
        # 挿入テキストの先頭行はHEADING_1指定が別リクエストで来る想定だが、このフェイクでは
        # 「新規に増えた段落はすべて見出し1として扱う」という単純化はせず、テスト側は
        # テキストの並び・メモ以下の残存のみを検証する(見出しレベルの正確さは別テストで検証)。
        self.paragraphs[insert_at_para:insert_at_para] = new_paragraphs

    def texts(self) -> list[str]:
        return [p[0] for p in self.paragraphs]


class _Executable:
    def __init__(self, payload):
        self._payload = payload

    def execute(self):
        return self._payload


# --- find_doc_region: 純粋関数のテスト ---


def test_find_doc_region_replaces_existing_heading_and_stops_before_next_h1():
    doc = _doc_from_paragraphs(
        [
            ("前置きの本文", False),
            ("対象レポート", True),
            ("本文1", False),
            ("本文2", False),
            ("次のセクション", True),
            ("次の本文", False),
        ]
    )
    region = find_doc_region(doc, "対象レポート")
    assert region.start_index is not None
    assert region.notes_index is None
    # 開始位置は「対象レポート」段落の先頭、終了位置は「次のセクション」段落の先頭
    h1_starts = [el["startIndex"] for el in doc["body"]["content"] if el["paragraph"]["paragraphStyle"]["namedStyleType"] == "HEADING_1"]
    assert region.start_index == h1_starts[0]
    assert region.end_index == h1_starts[1]


def test_find_doc_region_never_extends_past_notes_heading():
    doc = _doc_from_paragraphs(
        [
            ("対象レポート", True),
            ("本文", False),
            (NOTES_HEADING_TEXT, True),
            ("利用者が書いたメモ", False),
        ]
    )
    region = find_doc_region(doc, "対象レポート")
    notes_start = next(
        el["startIndex"]
        for el in doc["body"]["content"]
        if "".join(e["textRun"]["content"] for e in el["paragraph"]["elements"]).strip() == NOTES_HEADING_TEXT
    )
    assert region.end_index == notes_start
    assert region.notes_index == notes_start


def test_find_doc_region_missing_heading_inserts_before_notes():
    doc = _doc_from_paragraphs(
        [
            ("無関係のセクション", True),
            ("本文", False),
            (NOTES_HEADING_TEXT, True),
            ("利用者が書いたメモ", False),
        ]
    )
    region = find_doc_region(doc, "見つからない見出し")
    assert region.start_index is None
    assert region.insert_index == region.notes_index


def test_find_doc_region_ignores_matching_heading_after_notes():
    doc = _doc_from_paragraphs(
        [
            (NOTES_HEADING_TEXT, True),
            ("利用者が書いたメモ", False),
            ("対象レポート", True),
            ("保護される本文", False),
        ]
    )

    region = find_doc_region(doc, "対象レポート")

    assert region.start_index is None
    assert region.insert_index == region.notes_index


def test_find_doc_region_missing_heading_and_no_notes_appends_at_end():
    doc = _doc_from_paragraphs([("無関係のセクション", True), ("本文", False)])
    region = find_doc_region(doc, "見つからない見出し")
    assert region.start_index is None
    assert region.notes_index is None
    body_end = doc["body"]["content"][-1]["endIndex"]
    assert region.insert_index == body_end - 1


# --- build_region_content: 純粋関数のテスト ---


def test_build_region_content_extracts_heading_and_bold_ranges():
    md = "# タイトル\n\n本文に**強調**あり\n"
    content = build_region_content(md)
    assert "タイトル" in content.text
    assert "本文に強調あり" in content.text  # **は外れて中身だけ残る
    assert len(content.heading_ranges) == 1
    start, end, level = content.heading_ranges[0]
    assert content.text[start:end] == "タイトル"
    assert level == 1
    assert len(content.bold_ranges) == 1
    bstart, bend = content.bold_ranges[0]
    assert content.text[bstart:bend] == "強調"


def test_build_region_content_keeps_table_out_of_plain_text():
    """表はテキストに埋め込まず、TableOp(実表用のデータ)として別に持つ(パイプ区切りテキストにはしない)。"""
    md = "# タイトル\n\n前置き\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n後書き\n"
    content = build_region_content(md)
    assert "a | b" not in content.text
    assert "1 | 2" not in content.text
    assert "前置き" in content.text
    assert "後書き" in content.text
    assert len(content.tables) == 1
    table = content.tables[0]
    assert table.headers == ["a", "b"]
    assert table.rows == [["1", "2"]]


# --- export_gdoc: end-to-endに近い、フェイクサービス経由のテスト ---


def test_export_gdoc_requires_target():
    with pytest.raises(ValueError):
        export_gdoc(Path("dummy.md"), None, "# タイトル\n本文\n")


def test_export_gdoc_replaces_only_target_region_and_preserves_notes(tmp_path: Path):
    model = FakeDocsModel(
        [
            ("前置き", True),
            ("前置き本文(無関係、残るべき)", False),
            ("計測チェック", True),
            ("古い本文1(消えるべき)", False),
            ("古い本文2(消えるべき)", False),
            (NOTES_HEADING_TEXT, True),
            ("利用者が書いた対応メモ", False),
        ]
    )
    md_path = tmp_path / "report.md"
    md_text = "# 計測チェック\n\n新しい本文1\n\n新しい本文2\n"

    export_gdoc(md_path, "https://docs.google.com/document/d/abc123/edit", md_text, service=model)

    texts = model.texts()
    # 無関係の前置きセクションは丸ごと残る
    assert "前置き" in texts
    assert "前置き本文(無関係、残るべき)" in texts
    # 対象区画は新しい内容に置き換わっている
    assert "新しい本文1" in texts
    assert "新しい本文2" in texts
    assert "古い本文1(消えるべき)" not in texts
    assert "古い本文2(消えるべき)" not in texts
    # メモ以下は一切変更されていない
    assert NOTES_HEADING_TEXT in texts
    assert "利用者が書いた対応メモ" in texts
    notes_idx = texts.index(NOTES_HEADING_TEXT)
    assert texts[notes_idx + 1] == "利用者が書いた対応メモ"


def test_export_gdoc_appends_before_notes_when_heading_not_found(tmp_path: Path):
    model = FakeDocsModel(
        [
            ("無関係のセクション", True),
            ("本文", False),
            (NOTES_HEADING_TEXT, True),
            ("利用者が書いた対応メモ", False),
        ]
    )
    md_path = tmp_path / "report.md"
    md_text = "# 新しいレポート\n\nはじめての本文\n"

    export_gdoc(md_path, "abc123", md_text, service=model)

    texts = model.texts()
    assert "無関係のセクション" in texts
    assert "はじめての本文" in texts
    assert NOTES_HEADING_TEXT in texts
    assert "利用者が書いた対応メモ" in texts
    # 追記した内容はメモより前にある
    assert texts.index("はじめての本文") < texts.index(NOTES_HEADING_TEXT)


def test_build_batch_requests_orders_delete_before_insert():
    requests = build_batch_requests(
        insert_index=10,
        delete_start=10,
        delete_end=20,
        content=build_region_content("# 見出し\n本文\n"),
    )
    assert "deleteContentRange" in requests[0]
    assert "insertText" in requests[1]


# --- 「メモ」を対象見出しに指定できてしまう問題の回帰テスト ---


def test_find_doc_region_rejects_notes_as_target_when_notes_exists():
    doc = _doc_from_paragraphs(
        [
            ("計測チェック", True),
            ("本文", False),
            (NOTES_HEADING_TEXT, True),
            ("利用者が書いた対応メモ", False),
        ]
    )
    with pytest.raises(ReservedHeadingError):
        find_doc_region(doc, NOTES_HEADING_TEXT)


def test_find_doc_region_rejects_notes_as_target_even_when_notes_absent():
    """`メモ`は指定の仕方に関わらず常に予約語として拒否する(ドキュメントに`メモ`が無くても)。"""
    doc = _doc_from_paragraphs([("計測チェック", True), ("本文", False)])
    with pytest.raises(ReservedHeadingError):
        find_doc_region(doc, NOTES_HEADING_TEXT)


def test_export_gdoc_rejects_explicit_notes_heading_and_does_not_touch_document(tmp_path: Path):
    model = FakeDocsModel(
        [
            ("計測チェック", True),
            ("本文", False),
            (NOTES_HEADING_TEXT, True),
            ("利用者が書いた対応メモ", False),
        ]
    )
    md_path = tmp_path / "report.md"
    md_text = "# 計測チェック\n\n新しい本文\n"

    with pytest.raises(ReservedHeadingError):
        export_gdoc(md_path, "abc123", md_text, heading=NOTES_HEADING_TEXT, service=model)

    # ドキュメントには一切書き込まれていない(batchUpdateが呼ばれていない)
    assert model.batch_calls == []
    assert "利用者が書いた対応メモ" in model.texts()


def test_export_gdoc_rejects_when_markdown_title_itself_is_notes(tmp_path: Path):
    """--gdoc-heading未指定でも、Markdown先頭のH1が`メモ`ならガードが効く。"""
    model = FakeDocsModel(
        [
            ("計測チェック", True),
            ("本文", False),
            (NOTES_HEADING_TEXT, True),
            ("利用者が書いた対応メモ", False),
        ]
    )
    md_path = tmp_path / "report.md"
    md_text = f"# {NOTES_HEADING_TEXT}\n\n新しい本文\n"

    with pytest.raises(ReservedHeadingError):
        export_gdoc(md_path, "abc123", md_text, service=model)

    assert model.batch_calls == []


# --- 表: insertTableでの実表挿入(往復を挟むセル埋め込み)のテスト ---


def test_build_batch_requests_includes_insert_table_shell():
    md = "# タイトル\n\n| a | b | c |\n|---|---|---|\n| 1 | 2 | 3 |\n| 4 | 5 | 6 |\n"
    content = build_region_content(md)
    requests = build_batch_requests(insert_index=1, delete_start=None, delete_end=None, content=content)

    insert_table_reqs = [r["insertTable"] for r in requests if "insertTable" in r]
    assert len(insert_table_reqs) == 1
    assert insert_table_reqs[0]["rows"] == 3  # ヘッダー1行 + データ2行
    assert insert_table_reqs[0]["columns"] == 3


def test_build_batch_requests_orders_multiple_table_shells_by_descending_offset():
    md = (
        "# タイトル\n\n"
        "| a | b |\n|---|---|\n| 1 | 2 |\n\n"
        "本文\n\n"
        "| c | d |\n|---|---|\n| 3 | 4 |\n"
    )
    content = build_region_content(md)
    assert len(content.tables) == 2
    requests = build_batch_requests(insert_index=100, delete_start=None, delete_end=None, content=content)

    insert_table_indices = [r["insertTable"]["location"]["index"] for r in requests if "insertTable" in r]
    assert len(insert_table_indices) == 2
    # 後ろ(オフセットが大きい)側の表から先に積まれている
    assert insert_table_indices == sorted(insert_table_indices, reverse=True)
    assert insert_table_indices[0] > insert_table_indices[1]


def _fake_table_element(start_index: int, rows: list[list[int]]) -> dict:
    """documents().get()再取得後の表構造要素をテスト用に組み立てる。

    rowsは各行のセル開始インデックスのリスト(例: [[10, 20], [40, 50]]は2行2列)。
    """
    return {
        "startIndex": start_index,
        "table": {
            "tableRows": [
                {
                    "tableCells": [
                        {"content": [{"startIndex": cell_start}]} for cell_start in row
                    ]
                }
                for row in rows
            ]
        },
    }


def test_build_cell_fill_requests_matches_original_markdown_values():
    table_op = TableOp(offset=0, headers=["チャネル", "CVR"], rows=[["Organic", "3.2%"], ["Paid", "1.8%"]])
    # ヘッダー行 + データ2行、2列ぶんのセル開始インデックス(架空の値、昇順)
    table_element = _fake_table_element(
        start_index=5,
        rows=[[10, 20], [30, 40], [50, 60]],
    )

    requests = build_cell_fill_requests([table_element], [table_op])

    insert_texts = {r["insertText"]["location"]["index"]: r["insertText"]["text"] for r in requests if "insertText" in r}
    assert insert_texts[10] == "チャネル"
    assert insert_texts[20] == "CVR"
    assert insert_texts[30] == "Organic"
    assert insert_texts[40] == "3.2%"
    assert insert_texts[50] == "Paid"
    assert insert_texts[60] == "1.8%"

    # ヘッダー行のセルだけ太字書式が付いている
    bold_ranges = {
        r["updateTextStyle"]["range"]["startIndex"] for r in requests if "updateTextStyle" in r
    }
    assert bold_ranges == {10, 20}


def test_build_cell_fill_requests_processes_in_descending_index_order():
    """セル開始インデックスが大きい方から先にinsertTextが並ぶ(手前の挿入で後ろがずれるのを防ぐ)。"""
    table_op = TableOp(offset=0, headers=["a"], rows=[["1"], ["2"]])
    table_element = _fake_table_element(start_index=5, rows=[[100], [50], [10]])

    requests = build_cell_fill_requests([table_element], [table_op])
    insert_indices = [r["insertText"]["location"]["index"] for r in requests if "insertText" in r]
    assert insert_indices == sorted(insert_indices, reverse=True)


def test_build_cell_fill_requests_raises_when_table_count_mismatches():
    table_op = TableOp(offset=0, headers=["a"], rows=[])
    with pytest.raises(RuntimeError):
        build_cell_fill_requests([], [table_op])


def test_find_tables_after_returns_only_tables_at_or_after_insert_index_in_order():
    doc = {
        "body": {
            "content": [
                {"startIndex": 1, "paragraph": {"paragraphStyle": {"namedStyleType": "NORMAL_TEXT"}, "elements": []}},
                {"startIndex": 5, "table": {"tableRows": []}},  # insert_index未満(既存の無関係な表): 対象外
                {"startIndex": 50, "table": {"tableRows": []}},
                {"startIndex": 80, "table": {"tableRows": []}},
            ]
        }
    }
    result = find_tables_after(doc, insert_index=10)
    assert [el["startIndex"] for el in result] == [50, 80]


def test_find_tables_after_stops_at_target_region_end():
    doc = {
        "body": {
            "content": [
                {"startIndex": 20, "table": {"tableRows": []}},
                {"startIndex": 70, "table": {"tableRows": []}},
            ]
        }
    }

    result = find_tables_after(doc, insert_index=10, end_index=50)

    assert [el["startIndex"] for el in result] == [20]


def test_export_gdoc_writes_table_cells_via_second_batch_update(tmp_path: Path):
    """3段階往復の結合テスト: Round1でシェルを積み、再取得後にRound2でセルへ実データを書く。"""

    class FakeDocsServiceWithTables:
        def __init__(self, initial_document: dict, post_round1_document: dict):
            self._get_payloads = [initial_document, post_round1_document]
            self.batch_calls: list[list[dict]] = []

        def documents(self):
            return self

        def get(self, documentId: str):  # noqa: N803
            return _Executable(self._get_payloads.pop(0))

        def batchUpdate(self, documentId: str, body: dict):  # noqa: N802,N803
            self.batch_calls.append(body["requests"])
            return _Executable({})

    initial_doc = _doc_from_paragraphs([("計測チェック", True)])
    # Round1後の対象区画に新規表が1つあり、その後の別区画にも既存表がある状態。
    # 対象区画の表だけをセル埋めの対象にする。
    post_round1_doc = {
        "body": {
            "content": [
                _paragraph("計測チェック\n", heading1=True, start=1, end=10),
                _fake_table_element(start_index=12, rows=[[20, 30], [40, 50]]),
                _paragraph("別レポート\n", heading1=True, start=70, end=80),
                _fake_table_element(start_index=82, rows=[[90], [100]]),
                _paragraph("別レポートの本文\n", start=110, end=130),
            ]
        }
    }

    service = FakeDocsServiceWithTables(initial_doc, post_round1_doc)
    md_path = tmp_path / "report.md"
    md_text = "# 計測チェック\n\n| チャネル | CVR |\n|---|---|\n| Organic | 3.2% |\n"

    export_gdoc(md_path, "abc123", md_text, service=service)

    assert len(service.batch_calls) == 2  # Round1(シェル) + Round2(セル埋め)
    round1_requests, round2_requests = service.batch_calls
    assert any("insertTable" in r for r in round1_requests)

    round2_texts = {
        r["insertText"]["location"]["index"]: r["insertText"]["text"]
        for r in round2_requests
        if "insertText" in r
    }
    assert round2_texts == {20: "チャネル", 30: "CVR", 40: "Organic", 50: "3.2%"}
