"""クライアント向けレポートの文章を読み直す候補を出す。

このツールは自動修正をしない。警告は誤検出を含むため、人またはAIエージェントが文脈を読んで判断する。
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from pathlib import Path


EMPTY_PHRASES = (
    "本レポートでは",
    "本稿では",
    "以下にまとめます",
    "以下では",
    "重要なのは",
    "このように",
    "と言えるでしょう",
    "包括的に",
    "多角的に",
)
GENERIC_HEADINGS = {"背景", "分析", "考察", "課題", "提案", "まとめ"}
UNPROMPTED_SECTION_HEADINGS = ("次の打ち合わせ", "MTGで", "付録")
BASIC_ANALYSIS_INTERNAL_HEADINGS = (
    "流入パラメータの状態",
    "流入元の表記ゆれ",
    "計測対象のホスト名",
)
BASIC_ANALYSIS_ALLOWED_H2 = tuple(re.compile(pattern) for pattern in (
    r"^分析サマリー$",
    r"^1[.．]\s*月次推移$",
    r"^2[.．]\s*チャネル別パフォーマンス(?:（[^）]+）)?$",
    r"^3[.．]\s*ランディングページ別(?:（[^）]+）)?$",
    r"^4[.．]\s*ページ別(?:（[^）]+）)?$",
    r"^5[.．]\s*デバイス別(?:（[^）]+）)?$",
    r"^6[.．]\s*新規/リピーター別$",
    r"^7[.．]\s*(?:フォーム通過率|ECサイト購入プロセス)$",
    r"^8[.．]\s*自然検索（Search Console）$",
    r"^9[.．]\s*成果に至るページ遷移$",
    r"^分析の前提・制約$",
    r"^付録:\s*クローンの外にあるファイル$",
))
SENTENCE_RE = re.compile(r"[^\n。！？!?]+[。！？!?]")
PROCESS_PATTERNS = tuple(re.compile(pattern) for pattern in (
    r"(?:保存済みファイル|APIから返った行|接続済みです)",
    r"(?:分析の根拠から外します|前年比は撤回|確定値とは扱いません)",
    r"(?:ご指摘|ご要望|指摘|フィードバック)を(?:受け|踏まえ|反映)",
    r"(?:チャット|会話)(?:内|で|のやり取り)",
    r"(?:旧版|前回のレポート|以前のレポート|旧レポート).{0,30}(?:修正|変更|訂正|反省|寄せ|限定)",
    r"(?:だけ|のみ)に限定しません",
    r"(?:掲載|評価|作成|生成)(?:方針|手順)(?:として|に従い|を変更)",
    r"(?:ユーザー|利用者)(?:の回答|から確認|指定|に確認)",
))
INTERNAL_CLIENT_LABEL_PATTERNS = tuple(re.compile(pattern) for pattern in (
    r"会社側仮説",
    r"(?:利用者|ユーザー)未確認",
    r"\b(?:barrier_id|stimulus_id|persona_basis)\b",
    r"\b(?:service_derived|desk_research|customer_voice(?:_confirmed)?|competitor_customer_voice(?:_confirmed)?)\b",
    r"(?:内部用|社内用)(?:の)?(?:識別子|分類|ラベル|メモ)",
))
MARKET_PLAIN_STYLE_RE = re.compile(
    r"(?:である|だ|なっている|できる|できない|し得る|がある|必要がある|"
    r"分けている|整理する|検証する|掲げる|当てはまる|つなげやすい|示す)\。"
)
TABLE_FOOTNOTE_PREFIXES = (
    "※", "注:", "注：", "出典:", "出典：", "Source:", "SOURCE:", "<small", "[^",
)

VISUAL_CONTRACTS: dict[str, tuple[str, ...]] = {
    "check-report": (),
    "00_3c_persona_journey_report": ("pictogram",),
    "basic-analysis-report": ("chart", "pictogram"),
    "cvr-improvement-plan": ("pictogram",),
}
BLOCKING_RULES = {
    "missing-plot-chart", "missing-pictogram-summary", "unresolved-visual-marker",
    "internal-audit-section-in-basic-analysis", "nonstandard-section-in-basic-analysis",
    "basic-analysis-section-order", "missing-required-basic-analysis-section",
    "missing-insight-in-basic-analysis-section",
    "missing-period-range-in-basic-analysis",
    "internal-label-in-client-report",
    "market-report-non-polite-style",
}


def _basic_analysis_section_rank(heading: str) -> int | None:
    if heading == "分析サマリー":
        return 0
    numbered = re.match(r"^(\d+)[.．]", heading)
    if numbered:
        return int(numbered.group(1))
    if heading == "分析の前提・制約":
        return 10
    if heading == "付録: クローンの外にあるファイル":
        return 11
    return None


@dataclass(frozen=True)
class Finding:
    line: int
    rule: str
    message: str
    snippet: str


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.skip_depth = 0
        self.parts: list[tuple[int, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        classes = set(dict(attrs).get("class", "").split())
        if self.skip_depth:
            self.skip_depth += 1
        elif tag in {"style", "script"} or classes & {"asset-license-print", "pictogram-title"}:
            self.skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if self.skip_depth:
            self.skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self.skip_depth and data.strip():
            self.parts.append((self.getpos()[0], data.strip()))


def _markdown_parts(text: str) -> list[tuple[int, str]]:
    parts: list[tuple[int, str]] = []
    in_fence = False
    for number, raw in enumerate(text.splitlines(), 1):
        if raw.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or raw.lstrip().startswith("<!--"):
            continue
        line = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", raw)
        line = unescape(re.sub(r"<[^>]+>", " ", line))
        line = re.sub(r"^[#>*+\-\d.\s]+", "", line)
        line = line.replace("`", "").replace("**", "").strip()
        if line:
            parts.append((number, line))
    return parts


def _parts(path: Path, text: str) -> list[tuple[int, str]]:
    if path.suffix.lower() in {".html", ".htm"}:
        parser = _VisibleTextParser()
        parser.feed(text)
        return parser.parts
    return _markdown_parts(text)


def table_following_narratives(text: str) -> list[tuple[int, str]]:
    """Markdown表の直後にある通常段落を返す。

    表後に許す出典・脚注とHTMLコメントは読み飛ばし、次の見出しまたは表までに
    通常段落・箇条書きがあれば返す。コードフェンス内の表記例は対象外にする。
    次の表を説明する文章にも小見出しが必要なので、見出しなしの文章は検査対象とする。
    意味を推測して自動移動せず、原稿を読み直す候補だけを示す。
    """
    lines = text.splitlines()
    in_fence = False
    fenced_lines: list[bool] = []
    for line in lines:
        is_marker = line.lstrip().startswith("```")
        fenced_lines.append(in_fence or is_marker)
        if is_marker:
            in_fence = not in_fence

    def is_table_start(position: int) -> bool:
        return (
            position + 1 < len(lines)
            and not fenced_lines[position]
            and not fenced_lines[position + 1]
            and lines[position].lstrip().startswith("|")
            and lines[position + 1].lstrip().startswith("|")
            and bool(re.match(r"^\|?\s*:?-{3,}", lines[position + 1].lstrip()))
        )

    findings: list[tuple[int, str]] = []
    index = 0
    while index + 1 < len(lines):
        if not is_table_start(index):
            index += 1
            continue
        index += 2
        while index < len(lines) and lines[index].lstrip().startswith("|"):
            index += 1
        while index < len(lines):
            candidate = lines[index].strip()
            if not candidate or fenced_lines[index]:
                index += 1
                continue
            if candidate.startswith("<!--"):
                while index < len(lines) and "-->" not in lines[index]:
                    index += 1
                index += 1
                continue
            if candidate.startswith("#") or is_table_start(index):
                break
            if candidate.startswith(TABLE_FOOTNOTE_PREFIXES):
                index += 1
                while index < len(lines) and lines[index].strip():
                    index += 1
                continue
            findings.append((index + 1, candidate))
            break
    return findings


def tables_without_intro(text: str) -> list[tuple[int, str]]:
    """直前の見出しまたは表以降に、読み方・考察がないMarkdown表を返す。"""
    lines = text.splitlines()
    findings: list[tuple[int, str]] = []
    in_fence = False
    has_intro = False
    visual_marker_pending = False
    index = 0
    while index < len(lines):
        stripped = lines[index].strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            index += 1
            continue
        if in_fence or not stripped:
            index += 1
            continue
        if stripped.startswith("<!--"):
            comment_lines = [stripped]
            while index < len(lines) and "-->" not in lines[index]:
                index += 1
                if index < len(lines):
                    comment_lines.append(lines[index].strip())
            if re.search(r"<!--\s*(?:chart|pictograms):", " ".join(comment_lines), re.IGNORECASE):
                visual_marker_pending = True
            index += 1
            continue
        if stripped.startswith("#"):
            has_intro = False
            visual_marker_pending = False
            index += 1
            continue
        is_table = (
            stripped.startswith("|")
            and index + 1 < len(lines)
            and lines[index + 1].lstrip().startswith("|")
            and bool(re.match(r"^\|?\s*:?-{3,}", lines[index + 1].lstrip()))
        )
        if is_table:
            if not has_intro and not visual_marker_pending:
                findings.append((index + 1, stripped))
            index += 2
            while index < len(lines) and lines[index].lstrip().startswith("|"):
                index += 1
            has_intro = False
            visual_marker_pending = False
            continue
        if not stripped.startswith(TABLE_FOOTNOTE_PREFIXES):
            has_intro = True
            visual_marker_pending = False
        index += 1
    return findings


def check_file(path: Path) -> list[Finding]:
    text = path.read_text(encoding="utf-8")
    findings: list[Finding] = []
    is_html = path.suffix.lower() in {".html", ".htm"}
    is_internal_artifact = any(part.casefold() in {"data", "_data", "_past"} for part in path.parts)
    requirements = VISUAL_CONTRACTS.get(path.stem.casefold(), ())
    if path.stem.casefold() == "basic-analysis-report":
        if is_html:
            period_header_missing = bool(re.search(
                r'<th(?:\s[^>]*)?>指標</th>\s*<th(?:\s[^>]*)?>当期</th>',
                text,
                re.IGNORECASE,
            ))
        else:
            period_header_missing = any(
                re.match(r"^\s*\|\s*指標\s*\|", line)
                and re.search(r"\|\s*当期\s*\|", line)
                for line in text.splitlines()
            )
        if period_header_missing:
            findings.append(Finding(
                1,
                "missing-period-range-in-basic-analysis",
                "サマリー表の当期・前期見出しには、実際の対象年月を括弧書きします",
                "例: 当期（2025/9〜2026/8）",
            ))
        if is_html:
            headings = [
                (int(match.group(1)), text.count("\n", 0, match.start()) + 1,
                 unescape(re.sub(r"<[^>]+>", " ", match.group(2))))
                for match in re.finditer(r"<h([1-6])\b[^>]*>(.*?)</h\1>", text, re.IGNORECASE | re.DOTALL)
            ]
        else:
            headings = [
                (len(match.group(1)), line_no, match.group(2))
                for line_no, line in enumerate(text.splitlines(), 1)
                if (match := re.match(r"^\s{0,3}(#{1,6})\s+(.+?)\s*$", line))
            ]
        ordered_sections: list[tuple[int, int, str]] = []
        for level, line_no, heading in headings:
            compact_heading = re.sub(r"\s+", " ", heading).strip()
            if any(label in compact_heading for label in BASIC_ANALYSIS_INTERNAL_HEADINGS):
                findings.append(Finding(
                    line_no,
                    "internal-audit-section-in-basic-analysis",
                    "パラメータ監査の内部項目は基本分析本文へ出さず、非公開の作業記録で扱います",
                    compact_heading[:100],
                ))
                continue
            if level == 2 and not any(
                pattern.fullmatch(compact_heading) for pattern in BASIC_ANALYSIS_ALLOWED_H2
            ):
                findings.append(Finding(
                    line_no,
                    "nonstandard-section-in-basic-analysis",
                    "基本分析の章は固定一覧から選び、施策提案や内部監査の章を追加しません",
                    compact_heading[:100],
                ))
            elif level == 2:
                rank = _basic_analysis_section_rank(compact_heading)
                if rank is not None:
                    ordered_sections.append((rank, line_no, compact_heading))
        for previous, current in zip(ordered_sections, ordered_sections[1:]):
            if current[0] < previous[0]:
                findings.append(Finding(
                    current[1],
                    "basic-analysis-section-order",
                    "基本分析の章は固定順（分析サマリー、1〜9、前提・制約、付録）で並べます",
                    current[2][:100],
                ))
        present_ranks = {rank for rank, _, _ in ordered_sections}
        missing_ranks = [rank for rank in range(8) if rank not in present_ranks]
        if missing_ranks:
            labels = ["分析サマリー" if rank == 0 else str(rank) for rank in missing_ranks]
            findings.append(Finding(
                1,
                "missing-required-basic-analysis-section",
                "基本分析には分析サマリーと固定項目1〜7が必要です",
                "不足: " + "、".join(labels),
            ))
        if is_html:
            section_matches = list(re.finditer(
                r"<h2\b[^>]*>(.*?)</h2>", text, re.IGNORECASE | re.DOTALL
            ))
            for index, match in enumerate(section_matches):
                heading = re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", match.group(1)))).strip()
                rank = _basic_analysis_section_rank(heading)
                if rank is None or not 1 <= rank <= 9:
                    continue
                end = section_matches[index + 1].start() if index + 1 < len(section_matches) else len(text)
                if 'class="insight-box' not in text[match.end():end]:
                    findings.append(Finding(
                        text.count("\n", 0, match.start()) + 1,
                        "missing-insight-in-basic-analysis-section",
                        "基本分析の各数値項目には、対応する図表と同じ面へ載せる考察が必要です",
                        heading[:100],
                    ))
        else:
            h2_matches = list(re.finditer(r"^\s{0,3}##\s+(.+?)\s*$", text, re.MULTILINE))
            for index, match in enumerate(h2_matches):
                heading = re.sub(r"\s+", " ", match.group(1)).strip()
                rank = _basic_analysis_section_rank(heading)
                if rank is None or not 1 <= rank <= 9:
                    continue
                end = h2_matches[index + 1].start() if index + 1 < len(h2_matches) else len(text)
                section = text[match.end():end]
                if not re.search(r"^\s*>\s*\*\*(?:考察|ポイント)[：:]\*\*", section, re.MULTILINE):
                    findings.append(Finding(
                        text.count("\n", 0, match.start()) + 1,
                        "missing-insight-in-basic-analysis-section",
                        "基本分析の各数値項目には `> **考察:**` を置き、図表と同じ面へ載せます",
                        heading[:100],
                    ))
    if "chart" in requirements:
        has_chart = (
            'class="report-chart' in text
            if is_html
            else bool(re.search(r"<!--\s*chart:\s*(?:line|bar|combo|search)\b", text, re.IGNORECASE))
        )
        if not has_chart:
            findings.append(Finding(1, "missing-plot-chart", "数値グラフが必要なレポートですが、独立したグラフがありません", path.name))
    if "pictogram" in requirements:
        has_pictogram = (
            'class="pictogram-grid' in text
            if is_html
            else bool(re.search(r"<!--\s*pictograms:\s*", text, re.IGNORECASE))
        )
        if not has_pictogram:
            findings.append(Finding(1, "missing-pictogram-summary", "要点ピクトグラムが必要なレポートですが、指定または描画結果がありません", path.name))
    if is_html and re.search(r"<!--\s*(?:chart|pictograms):", text, re.IGNORECASE):
        findings.append(Finding(1, "unresolved-visual-marker", "HTMLに未変換の可視化指定が残っています。指定と直後の表を確認", path.name))
    if not is_html:
        if path.stem.casefold() in VISUAL_CONTRACTS:
            for line_no, table_header in tables_without_intro(text):
                findings.append(Finding(
                    line_no,
                    "table-without-intro",
                    "表だけの面を避けるため、表の前へ読み方・考察を1〜3文で置くか確認します",
                    table_header[:100],
                ))
        for line_no, paragraph in table_following_narratives(text):
            findings.append(Finding(
                line_no,
                "narrative-after-table",
                "結論・判断・表の読み方・指標定義は表の前へ移し、表の後は出典・脚注だけにします",
                paragraph[:100],
            ))
    for line_no, part in _parts(path, text):
        compact = re.sub(r"\s+", " ", part).strip()
        if path.stem.casefold() == "00_3c_persona_journey_report" and MARKET_PLAIN_STYLE_RE.search(compact):
            findings.append(Finding(
                line_no,
                "market-report-non-polite-style",
                "市場・顧客理解レポートの本文は、です・ます調へ統一します",
                compact[:100],
            ))
        if not is_internal_artifact and any(pattern.search(compact) for pattern in INTERNAL_CLIENT_LABEL_PATTERNS):
            findings.append(Finding(
                line_no,
                "internal-label-in-client-report",
                "内部の根拠分類・確認状態を利用者向け本文や見出しへ出さず、普通の顧客表現へ直します",
                compact[:100],
            ))
        if any(pattern.search(compact) for pattern in PROCESS_PATTERNS):
            findings.append(Finding(line_no, "production-context", "チャット・制作経緯が本文に混入していないか確認。判断に必要な出所・制約は残す", compact[:100]))
        if compact in GENERIC_HEADINGS:
            findings.append(Finding(line_no, "generic-heading", "対象と読み取りが分かる見出しか確認", compact))
        if any(compact.startswith(heading) for heading in UNPROMPTED_SECTION_HEADINGS):
            findings.append(Finding(line_no, "unprompted-section", "利用者が求めた会議項目または付録か確認", compact))
        for phrase in EMPTY_PHRASES:
            if phrase in compact:
                findings.append(Finding(line_no, "stock-phrase", "削っても意味が変わらない定型句か確認", compact[:100]))
        for sentence in SENTENCE_RE.findall(compact):
            if len(sentence) > 80:
                findings.append(Finding(line_no, "long-sentence", f"1文が{len(sentence)}文字。分けられないか確認", sentence[:100]))
    return findings


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="レポート文章の読み直し候補を表示する")
    parser.add_argument("paths", nargs="+", type=Path, help="対象のMarkdownまたはHTML")
    args = parser.parse_args(argv)

    missing = [path for path in args.paths if not path.is_file()]
    if missing:
        for path in missing:
            print(f"ERROR {path}: ファイルがありません")
        return 2

    count = 0
    blocking_count = 0
    for path in args.paths:
        findings = check_file(path)
        count += len(findings)
        blocking_count += sum(item.rule in BLOCKING_RULES for item in findings)
        for item in findings:
            level = "ERROR" if item.rule in BLOCKING_RULES else "WARN"
            print(f"{level} {path}:{item.line} [{item.rule}] {item.message}: {item.snippet}")
    print(f"確認候補: {count}件（自動修正はしません）")
    return 1 if blocking_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
