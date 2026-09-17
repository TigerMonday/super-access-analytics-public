from report_export.md_tables import parse_markdown_for_excel


def test_escaped_pipe_in_cell_is_unescaped():
    md = """
| a | b |
|---|---|
| x\\|y | z |
"""
    parsed = parse_markdown_for_excel(md)
    assert len(parsed.tables) == 1
    table = parsed.tables[0]
    assert table.headers == ["a", "b"]
    assert table.rows == [["x|y", "z"]]


def test_br_in_cell_becomes_newline():
    md = """
| a | b |
|---|---|
| line1<br>line2 | ok |
"""
    parsed = parse_markdown_for_excel(md)
    table = parsed.tables[0]
    assert table.rows[0][0] == "line1\nline2"


def test_empty_cells_are_preserved_as_empty_string():
    md = """
| a | b | c |
|---|---|---|
| x |  | z |
"""
    parsed = parse_markdown_for_excel(md)
    table = parsed.tables[0]
    assert table.rows[0] == ["x", "", "z"]


def test_multiple_tables_get_distinct_titles_from_headings():
    md = """
## 表1

| a | b |
|---|---|
| 1 | 2 |

## 表2

| c | d |
|---|---|
| 3 | 4 |
"""
    parsed = parse_markdown_for_excel(md)
    assert len(parsed.tables) == 2
    assert parsed.tables[0].title == "表1"
    assert parsed.tables[1].title == "表2"


def test_no_table_returns_empty_list_and_prose_lines():
    md = """
# タイトル

本文だけのMarkdown。

- 箇条書き1
- 箇条書き2
"""
    parsed = parse_markdown_for_excel(md)
    assert parsed.tables == []
    texts = [t for _, t in parsed.prose_lines]
    assert "タイトル" in texts
    assert "本文だけのMarkdown。" in texts


def test_duplicate_heading_titles_get_suffixed():
    md = """
## メモ

| a |
|---|
| 1 |

## メモ

| b |
|---|
| 2 |
"""
    parsed = parse_markdown_for_excel(md)
    titles = [t.title for t in parsed.tables]
    assert titles == ["メモ", "メモ_2"]


def test_inline_markdown_is_stripped_in_cells():
    md = """
| a | b |
|---|---|
| **bold** | `code` |
"""
    parsed = parse_markdown_for_excel(md)
    table = parsed.tables[0]
    assert table.rows[0] == ["bold", "code"]


def test_center_align_separator_single_hyphen_is_recognized():
    md = """
# テスト

| A | B |
|:-:|:-:|
| 1 | 2 |
"""
    parsed = parse_markdown_for_excel(md)
    assert len(parsed.tables) == 1
    table = parsed.tables[0]
    assert table.headers == ["A", "B"]
    assert table.rows == [["1", "2"]]


def test_left_and_right_align_single_hyphen_separators_are_recognized():
    md = """
| A | B |
|:-|-:|
| 1 | 2 |
"""
    parsed = parse_markdown_for_excel(md)
    assert len(parsed.tables) == 1
    assert parsed.tables[0].rows == [["1", "2"]]


def test_bare_single_hyphen_separator_is_recognized():
    md = """
| A | B |
|-|-|
| 1 | 2 |
"""
    parsed = parse_markdown_for_excel(md)
    assert len(parsed.tables) == 1
    assert parsed.tables[0].rows == [["1", "2"]]


def test_mixed_separator_styles_in_same_row_are_recognized():
    md = """
| A | B | C |
|:-:|--:|---|
| 1 | 2 | 3 |
"""
    parsed = parse_markdown_for_excel(md)
    assert len(parsed.tables) == 1
    assert parsed.tables[0].rows == [["1", "2", "3"]]
