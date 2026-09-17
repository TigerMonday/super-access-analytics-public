"""MarkdownからGoogleドキュメント(既存ファイル)への部分書き込み。

## サービスアカウントの制約と、そこから来る設計

サービスアカウントは自分でファイルを作れない(Drive APIの公式ドキュメントに明記されている
制約。共有ドライブでの回避策はWorkspace有償エディション前提で、無償アカウント利用者では
成立しない)。そのため、このモジュールは**新規ドキュメントの自動作成を行わない**。
書き込み先は必ず既存ドキュメントのURL(またはID)で指定し、無ければエラーで止めて
何を用意すればよいかを案内する(黙って別形式にフォールバックしない)。

## 上書き事故を避ける設計(このプロジェクトで過去2回踏んだ地雷)

ドキュメント全体を書き換えるのではなく、**そのレポート用の見出し1(H1)区画だけ**を
差し替える。区画は「次の見出し1が現れるところ」までとし、`メモ` という見出し1が
あれば、そこから先(それ以降の全て)は絶対に触らない
(`02_basic_measurement/measurement_design/src/measurement_design/review/renderer.py`の
`ensure_check_report_notes()` と同じ「人が書き込む場所は機械が触らない」という考え方)。

- 対象の見出し1が既にあれば、その区画だけを削除して新しい内容に差し替える
- 対象の見出し1が無ければ、`メモ`見出しの手前に新規追記する(`メモ`が無ければ文末に追記)
- これにより、無関係な区画・`メモ`以下の利用者の書き込みは何度実行しても消えない
- **`メモ`そのものを対象見出しに指定することは許さない**(`--gdoc-heading メモ` や、
  Markdown先頭のH1がたまたま`メモ`だった場合に、指定の仕方次第で保護対象が差し替え対象に
  化けてしまう抜け道になるため)。`find_doc_region`・`export_gdoc`の両方でエラーにする

## 表: Docs APIのネイティブな表(insertTable)を使う

このツールの行き先は「人が読んでコメントを付ける文書」であるため、表が読める形で入る
ことを最優先する。パイプ区切りのテキストでは読めないため採用しない。

Docs APIでは、表に挿入したセルの実インデックス(どこにテキストを入れればそのセルに入るか)は
`insertTable`実行後にドキュメントを再取得しないと分からない(Google公式のテーブル操作ガイドが
推奨する手順どおり)。そのため書き込みは3段階のAPI往復になる。

1. `batchUpdate`: 区画の削除(置換時)+ 表以外のテキスト・見出し/太字/箇条書きの書式 +
   表シェル(罫線と空セルだけの`insertTable`。中身は空)をまとめて1回で送る
   (表が複数あっても、シェルの`insertTable`はまとめて同じbatchUpdateに積む)
2. `documents().get()`: 再取得し、挿入した表シェルの実際のセル位置を特定する
3. `batchUpdate`: 各表の各セルへ、見出し行の太字も含めて値をまとめて書き込む
   (これも表・セルの数だけ分割せず、1回のbatchUpdateにまとめる)

往復は3回になるが(表が無ければ1回のまま)、実行時間が数秒延びることより表が読めない
ことの方が問題という判断による。1回のbatchUpdate内で複数の挿入(insertText/insertTable)を
安全に混ぜるには、書式(update*Style系)は同じテキストへの挿入の直後に置き(挿入後は書式は
その内容に残り続けるため、後続の別位置への挿入で無効化されない)、表シェルの挿入は
オフセットが大きい(文書の後ろにある)ものから先に処理する(先に挿入すると、後ろにある
未処理の挿入位置がそのぶん前方にずれてしまうため)。同じ理由で、手順3のセル埋めも
セル開始インデックスの大きい方から処理する。

## 表現力の簡略化(意図的な割り切り)

太字は`**text**`のみ対応し、イタリック・インラインコードは記号だけ外してプレーンテキストに
する(docx出力のpython-docx経路と同じ簡略化)。番号付きリストは特別扱いせず、プレーン
テキストとしてそのまま入る(README「制限・既知の注意点」に明記)。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from . import google_auth
from .markdown_utils import extract_title_and_strip
from .md_tables import _HEADING_RE, _SEP_LINE_RE, parse_markdown_for_excel

NOTES_HEADING_TEXT = "メモ"

_BULLET_RE_LOCAL = re.compile(r"^(\s*)[-*+]\s+(.*)$")
_INLINE_TOKEN_RE = re.compile(r"(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)")


class ReservedHeadingError(ValueError):
    """`メモ`見出しを対象見出しに指定しようとしたときに送出する(ValueErrorのサブクラス)。"""


@dataclass
class DocRegion:
    """ドキュメント内の「そのレポート用の区画」の位置。"""

    start_index: int | None  # 既存区画の開始(見出し1行の先頭)。見つからなければNone
    end_index: int | None  # 既存区画の終了(次の見出し1の直前、または文末)。startがNoneなら無意味
    insert_index: int  # 新しい内容を挿入する開始位置(置換時はstart_indexと同じ)
    notes_index: int | None  # `メモ`見出しの開始位置。無ければNone


@dataclass
class TableOp:
    """挿入すべき表1つぶんのデータ。offsetはtext中の(表を幅0として数えた)挿入位置。"""

    offset: int
    headers: list[str]
    rows: list[list[str]]


@dataclass
class RegionContent:
    """Docs APIのbatchUpdateに変換する前の、挿入テキスト・書式範囲・表(すべて相対オフセット)。"""

    text: str
    heading_ranges: list[tuple[int, int, int]] = field(default_factory=list)  # (start, end, level)
    bold_ranges: list[tuple[int, int]] = field(default_factory=list)
    bullet_ranges: list[tuple[int, int]] = field(default_factory=list)
    tables: list[TableOp] = field(default_factory=list)


def _paragraph_text(paragraph: dict) -> str:
    return "".join(
        el.get("textRun", {}).get("content", "") for el in paragraph.get("elements", [])
    ).strip()


def _is_heading1(paragraph: dict) -> bool:
    return paragraph.get("paragraphStyle", {}).get("namedStyleType") == "HEADING_1"


def _reject_notes_heading(heading_text: str) -> None:
    if heading_text == NOTES_HEADING_TEXT:
        raise ReservedHeadingError(
            f"見出し「{NOTES_HEADING_TEXT}」は利用者が書き込む専用の区画のため、レポートの"
            f"対象見出しに指定できません。--gdoc-heading、またはMarkdown先頭のH1を確認して"
            f"ください。"
        )


def find_doc_region(document: dict, heading_text: str) -> DocRegion:
    """ドキュメントのJSON構造(documents().get()の戻り値)から対象区画を特定する。

    純粋関数(Docs APIクライアントを呼ばない)。テスト容易性のため実際のAPI呼び出しと分離している。
    `heading_text`が`メモ`の場合は、ドキュメントの状態に関係なく常にエラーにする
    (保護対象そのものを差し替え対象にする抜け道を塞ぐため。モジュールdocstring参照)。
    """
    _reject_notes_heading(heading_text)

    content = document.get("body", {}).get("content", [])
    body_end_index = content[-1].get("endIndex", 1) if content else 1

    h1_entries: list[tuple[int, str]] = []  # (startIndex, text) 見出し1のみ
    for el in content:
        para = el.get("paragraph")
        if not para or not _is_heading1(para):
            continue
        h1_entries.append((el["startIndex"], _paragraph_text(para)))

    notes_index = next((s for s, t in h1_entries if t == NOTES_HEADING_TEXT), None)
    # 「メモ」から後ろは利用者専用の保護区画。そこに同名見出しがあっても、
    # 更新対象として扱わない。
    editable_h1_entries = [
        entry for entry in h1_entries
        if notes_index is None or entry[0] < notes_index
    ]
    target = next(((s, t) for s, t in editable_h1_entries if t == heading_text), None)

    if target is None:
        # 対象見出しが無い: メモの手前に追記(メモが無ければ文末)
        insert_index = notes_index if notes_index is not None else max(body_end_index - 1, 1)
        return DocRegion(start_index=None, end_index=None, insert_index=insert_index, notes_index=notes_index)

    start_index, _ = target
    later_starts = sorted(s for s, _ in h1_entries if s > start_index)
    end_index = later_starts[0] if later_starts else max(body_end_index - 1, start_index)
    return DocRegion(start_index=start_index, end_index=end_index, insert_index=start_index, notes_index=notes_index)


def _append_inline(buffer: list[str], bold_ranges: list[tuple[int, int]], text: str) -> None:
    """`**bold**`の記号を外して太字範囲を記録し、bufferに追記する。

    イタリック(`*text*`)・インラインコード(`` `code` ``)は記号だけ外し、書式は付けない
    (docx出力のpython-docx経路と同じ簡略化。モジュールdocstring参照)。
    """
    for part in _INLINE_TOKEN_RE.split(text):
        if not part:
            continue
        if part.startswith("**") and part.endswith("**") and len(part) > 4:
            content = part[2:-2]
            start = sum(len(s) for s in buffer)
            buffer.append(content)
            bold_ranges.append((start, start + len(content)))
        elif part.startswith("`") and part.endswith("`") and len(part) > 2:
            buffer.append(part[1:-1])
        elif part.startswith("*") and part.endswith("*") and len(part) > 2:
            buffer.append(part[1:-1])
        else:
            buffer.append(part)


def build_region_content(md_text: str) -> RegionContent:
    """Markdown本文を、Docs APIのinsertText用テキスト+書式範囲+表データに変換する。

    表は本文テキストには含めない(幅0のTableOpとして別扱いにする)。実際の罫線付き表として
    Docs API側で組み立てるため(モジュールdocstring参照)。
    """
    parsed = parse_markdown_for_excel(md_text)
    table_by_start = {t.start_line: t for t in parsed.tables}
    lines = md_text.splitlines()
    n = len(lines)

    buffer: list[str] = []
    heading_ranges: list[tuple[int, int, int]] = []
    bold_ranges: list[tuple[int, int]] = []
    bullet_ranges: list[tuple[int, int]] = []
    tables: list[TableOp] = []

    def cur_pos() -> int:
        return sum(len(s) for s in buffer)

    i = 0
    in_code_fence = False
    while i < n:
        line = lines[i]

        if i in table_by_start:
            table = table_by_start[i]
            tables.append(
                TableOp(
                    offset=cur_pos(),
                    headers=list(table.headers),
                    rows=[list(row) for row in table.rows],
                )
            )
            i = table.end_line
            continue

        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_code_fence = not in_code_fence
            i += 1
            continue
        if in_code_fence:
            buffer.append(line + "\n")
            i += 1
            continue

        h = _HEADING_RE.match(line)
        if h:
            level = min(len(h.group(1)), 6)
            start = cur_pos()
            _append_inline(buffer, bold_ranges, h.group(2).strip())
            end = cur_pos()
            buffer.append("\n")
            heading_ranges.append((start, end, level))
            i += 1
            continue

        if _SEP_LINE_RE.match(stripped) and stripped:
            i += 1
            continue

        bullet = _BULLET_RE_LOCAL.match(line)
        if bullet:
            start = cur_pos()
            _append_inline(buffer, bold_ranges, bullet.group(2))
            end = cur_pos()
            buffer.append("\n")
            bullet_ranges.append((start, end))
            i += 1
            continue

        if not stripped:
            i += 1
            continue

        _append_inline(buffer, bold_ranges, stripped)
        buffer.append("\n")
        i += 1

    return RegionContent(
        text="".join(buffer),
        heading_ranges=heading_ranges,
        bold_ranges=bold_ranges,
        bullet_ranges=bullet_ranges,
        tables=tables,
    )


def _table_dimensions(table: TableOp) -> tuple[int, int]:
    rows = len(table.rows) + (1 if table.headers else 0)
    cols = max(len(table.headers), max((len(r) for r in table.rows), default=0)) or 1
    return max(rows, 1), cols


def build_batch_requests(
    *,
    insert_index: int,
    delete_start: int | None,
    delete_end: int | None,
    content: RegionContent,
) -> list[dict]:
    """Docs API batchUpdate(1回目)用のrequests配列を組み立てる(純粋関数)。

    表があれば、罫線・空セルだけの表シェル(insertTable)もこの1回に含める(中身は空のまま。
    セルへの書き込みはRound2でdocuments().get()による再取得後に行う。モジュールdocstring参照)。

    Docs APIはbatchUpdate内のrequestsを配列順に、直前までの結果を反映した状態に対して
    適用する。そのため「削除→挿入→書式→表シェル」の順で並べる:
    - 削除→挿入の順で並べれば、削除後の挿入位置(insert_index)はそのまま有効
      (置換時はinsert_index == delete_start)
    - 書式(見出し/太字/箇条書き)はテキスト挿入直後に適用すれば、その後の表シェル挿入で
      対象範囲がずれても書式自体は挿入済みの内容に残り続けるため安全
    - 表シェルの挿入は、オフセットが大きい(文書の後ろにある)ものから先に処理する。
      先に処理した挿入が、まだ未処理の(より手前の)挿入位置を前方にずらしてしまうのを防ぐため
    """
    requests: list[dict] = []
    if delete_start is not None and delete_end is not None and delete_end > delete_start:
        requests.append(
            {"deleteContentRange": {"range": {"startIndex": delete_start, "endIndex": delete_end}}}
        )

    if content.text:
        requests.append({"insertText": {"location": {"index": insert_index}, "text": content.text}})

    for start, end, level in content.heading_ranges:
        requests.append(
            {
                "updateParagraphStyle": {
                    "range": {"startIndex": insert_index + start, "endIndex": insert_index + end},
                    "paragraphStyle": {"namedStyleType": f"HEADING_{level}"},
                    "fields": "namedStyleType",
                }
            }
        )

    for start, end in content.bold_ranges:
        if end > start:
            requests.append(
                {
                    "updateTextStyle": {
                        "range": {"startIndex": insert_index + start, "endIndex": insert_index + end},
                        "textStyle": {"bold": True},
                        "fields": "bold",
                    }
                }
            )

    for start, end in content.bullet_ranges:
        if end > start:
            requests.append(
                {
                    "createParagraphBullets": {
                        "range": {"startIndex": insert_index + start, "endIndex": insert_index + end},
                        "bulletPreset": "BULLET_DISC_CIRCLE_SQUARE",
                    }
                }
            )

    # 表シェル: オフセット降順(文書の後ろにあるものから先)に積む
    for table in sorted(content.tables, key=lambda t: t.offset, reverse=True):
        rows, cols = _table_dimensions(table)
        requests.append(
            {
                "insertTable": {
                    "rows": rows,
                    "columns": cols,
                    "location": {"index": insert_index + table.offset},
                }
            }
        )

    return requests


def find_tables_after(
    document: dict,
    insert_index: int,
    end_index: int | None = None,
) -> list[dict]:
    """対象区画内の表構造要素を、出現順(昇順)で返す(純粋関数)。

    Round1(insertTable)実行後にdocuments().get()で再取得したdocumentに対して使う。
    Round1内で複数の表を挿入すると、先に挿入した表の実インデックスは後から挿入した表の
    ぶんだけ前後にずれるため、絶対インデックスの一致では特定できない。`insert_index`より
    手前はRound1で一切変更していない(区画の削除・挿入は常にinsert_index以降にしか及ばない)
    ため安定した開始境界として使える。`end_index`を指定した場合は、次の見出し1や
    「メモ」より前に限定する。後続区画の既存表を、今回挿入した表と取り違えないためである。
    """
    content = document.get("body", {}).get("content", [])
    return [
        el for el in content
        if "table" in el
        and el.get("startIndex", -1) >= insert_index
        and (end_index is None or el.get("startIndex", -1) < end_index)
    ]


def _cell_paragraph_start_index(cell: dict) -> int:
    # 新規insertTableで作られたセルは、中身が単一の空段落(content[0])のみのはず
    # (Google公式のテーブル操作ガイドの前提)。
    return cell["content"][0]["startIndex"]


def build_cell_fill_requests(table_elements: list[dict], table_ops: list[TableOp]) -> list[dict]:
    """Round1で作った表シェルへ、ヘッダー/データ行の値を書き込むrequests(Round2)を組み立てる。

    純粋関数。table_elements(find_tables_afterの戻り値=出現順)とtable_ops
    (build_region_contentが返したTableOp=出現順)は同じ順番で対応すると仮定する。

    セルへのinsertTextは、セル開始インデックスが大きい方から先に適用する。先に埋めたセルの
    位置が、後から埋める(より手前の)セルへのinsertTextでずれるのを防ぐため。ヘッダー行の
    太字化は、そのセルへのinsertTextの直後に置く(挿入直後の書式は後続の他セルへの挿入の
    影響を受けない。モジュールdocstring参照)。
    """
    if len(table_elements) != len(table_ops):
        raise RuntimeError(
            "Googleドキュメントへの表の書き込みに失敗しました"
            "(挿入したはずの表の数と、ドキュメント側で見つかった表の数が一致しません)。"
            "再実行するか、対象ドキュメントの状態を確認してください。"
        )

    fills: list[tuple[int, str, bool]] = []  # (セル開始インデックス, 値, ヘッダー行か)
    for element, table_op in zip(table_elements, table_ops):
        rows_data = element["table"]["tableRows"]
        has_header = bool(table_op.headers)
        for row_index, row in enumerate(rows_data):
            is_header_row = has_header and row_index == 0
            if is_header_row:
                values = table_op.headers
            else:
                data_row_index = row_index - (1 if has_header else 0)
                values = table_op.rows[data_row_index] if data_row_index < len(table_op.rows) else []
            for col_index, cell in enumerate(row["tableCells"]):
                value = values[col_index] if col_index < len(values) else ""
                if not value:
                    continue
                cell_start = _cell_paragraph_start_index(cell)
                fills.append((cell_start, value, is_header_row))

    fills.sort(key=lambda f: f[0], reverse=True)

    requests: list[dict] = []
    for cell_start, value, is_header_row in fills:
        requests.append({"insertText": {"location": {"index": cell_start}, "text": value}})
        if is_header_row:
            requests.append(
                {
                    "updateTextStyle": {
                        "range": {"startIndex": cell_start, "endIndex": cell_start + len(value)},
                        "textStyle": {"bold": True},
                        "fields": "bold",
                    }
                }
            )
    return requests


def export_gdoc(
    md_path: Path,
    target: str | None,
    md_text: str,
    *,
    heading: str | None = None,
    service=None,
) -> str:
    """Markdownの内容を、既存のGoogleドキュメントの対象区画へ書き込む。GoogleドキュメントのURLを返す。

    target: 書き込み先ドキュメントのURL、またはID。未指定ならエラーで止める
    (サービスアカウントは新規ファイルを作れないため。モジュールdocstring参照)。
    heading: 区画を区切る見出し1のテキスト。未指定ならMarkdown先頭のH1(無ければファイル名)を使う。
    `メモ`は指定できない(ReservedHeadingError)。
    service: Docs APIクライアント。テスト用の差し替え口(未指定なら認証して実クライアントを作る)。
    """
    if not target:
        raise ValueError(
            "書き込み先のGoogleドキュメントが指定されていません。--gdoc に既存ドキュメントの"
            "URL(またはID)を指定してください。サービスアカウントは新規ファイルを作成できないため、"
            "事前に対象ドキュメントを用意し、認証ファイルの client_email の値を編集者として共有して"
            "おいてください。"
        )

    doc_id = google_auth.extract_doc_id(target)
    title, body_md = extract_title_and_strip(md_text, fallback=md_path.stem)
    heading_text = heading or title
    # ここで早期に弾く(APIを1回も呼ばずに済ませる)。find_doc_region側にも同じガードがあり、
    # find_doc_regionを直接呼ぶ利用者(テスト等)も保護される(二重防御)。
    _reject_notes_heading(heading_text)

    if service is None:
        creds = google_auth.get_credentials()
        service = google_auth.build_docs_service(creds)

    document = service.documents().get(documentId=doc_id).execute()
    region = find_doc_region(document, heading_text)

    # 区画の先頭は常に対象heading_textちょうどの見出し1にする(元のMarkdownのH1テキストが
    # 違う/無い場合でも、次回実行時に同じ見出しで区画を再特定できるようにするため)。
    region_source_md = f"# {heading_text}\n\n{body_md}"
    content = build_region_content(region_source_md)

    requests = build_batch_requests(
        insert_index=region.insert_index,
        delete_start=region.start_index,
        delete_end=region.end_index,
        content=content,
    )
    if requests:
        service.documents().batchUpdate(documentId=doc_id, body={"requests": requests}).execute()

    if content.tables:
        # Round2: 表シェルの実セル位置を再取得してから中身を埋める(モジュールdocstring参照)。
        refreshed = service.documents().get(documentId=doc_id).execute()
        refreshed_region = find_doc_region(refreshed, heading_text)
        if refreshed_region.start_index is None:
            raise RuntimeError(
                "Googleドキュメントへの表の書き込みに失敗しました"
                "(挿入したレポートの見出しを再取得できません)。再実行するか、"
                "対象ドキュメントの状態を確認してください。"
            )
        table_elements = find_tables_after(
            refreshed,
            refreshed_region.start_index,
            refreshed_region.end_index,
        )
        fill_requests = build_cell_fill_requests(table_elements, content.tables)
        if fill_requests:
            service.documents().batchUpdate(documentId=doc_id, body={"requests": fill_requests}).execute()

    return f"https://docs.google.com/document/d/{doc_id}/edit"
