"""基本分析レポート（Markdown）の構成ルールを検証するユニットテスト。

このエージェントはレポート本文をコード生成せず、プロンプト
（prompts/parameter-audit.md）に従ってLLMが直接Markdownを組み立てる。
そのため「目次の番号」も「ヘッダ項目」もコード側のテンプレートエンジンが
存在しない。検証対象は、LLMが実際に見本として参照する
samples/output.example.md（出力例）とし、以下2点のバグ再発を防ぐ:

- 目次の番号が本文の見出し番号（## 1. 〜）とずれる
  （「分析サマリー」を1番として数えてしまい、以降が1つずつずれる）
- ヘッダに社内向けの「管理ID」が残る
  （読み手に意味の無い内部識別子はヘッダ仕様から外す）
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

SAMPLE_PATH = Path(__file__).resolve().parents[1] / "samples" / "output.example.md"

NUMBERED_HEADING_RE = re.compile(r"^##\s+(\d+)\.\s+(.+)$", re.MULTILINE)
NUMBERED_TOC_RE = re.compile(r"^(\d+)\.\s+\[(.+?)\]\(#.+?\)\s*$", re.MULTILINE)


def extract_toc_block(text: str) -> str:
    """`## 目次` の見出しから次の `---` 区切りまでを取り出す。"""
    match = re.search(r"^## 目次\s*$(.*?)^---\s*$", text, re.MULTILINE | re.DOTALL)
    if not match:
        raise AssertionError("`## 目次` セクションが見つからない")
    return match.group(1)


def extract_header_block(text: str) -> str:
    """ファイル冒頭から最初の `---` 区切りまで（ヘッダ部分）を取り出す。"""
    match = re.search(r"^(.*?)^---\s*$", text, re.MULTILINE | re.DOTALL)
    if not match:
        raise AssertionError("ヘッダ区切り（最初の `---`）が見つからない")
    return match.group(1)


def numbered_toc_entries(toc_block: str) -> list[tuple[int, str]]:
    """目次内の番号付きリスト項目を (番号, タイトル) の並びで返す。"""
    return [(int(n), title) for n, title in NUMBERED_TOC_RE.findall(toc_block)]


def numbered_body_headings(text: str) -> list[tuple[int, str]]:
    """本文の `## N. タイトル` 見出しを (番号, タイトル) の並びで返す。"""
    return [(int(n), title) for n, title in NUMBERED_HEADING_RE.findall(text)]


class ReportTemplateStructureTest(unittest.TestCase):
    """samples/output.example.md（LLMが参照する出力例）の構成ルールを検証する。"""

    @classmethod
    def setUpClass(cls):
        cls.text = SAMPLE_PATH.read_text(encoding="utf-8")

    def test_header_has_no_internal_management_id(self):
        """ヘッダに社内の「管理ID」を含めない（読み手に意味が無いため標準仕様から除外）。"""
        header = extract_header_block(self.text)
        self.assertNotIn("管理ID", header)
        # ファイル全体にも残っていないことを確認する
        self.assertNotIn("管理ID", self.text)

    def test_header_has_required_fields(self):
        """ヘッダに残すのは対象サイト・分析日・対象期間・比較期間・キーイベントの5項目。"""
        header = extract_header_block(self.text)
        for field in ["対象サイト", "分析日", "対象期間", "比較期間", "キーイベント"]:
            self.assertIn(field, header, f"ヘッダに {field} が無い")

    def test_toc_summary_entry_is_unnumbered(self):
        """「分析サマリー」は番号を持たない見出しなので、目次でも連番に含めない。"""
        toc_block = extract_toc_block(self.text)
        self.assertIn("[分析サマリー](#分析サマリー)", toc_block)
        # 番号付きリストとして拾われていないことを確認する
        numbered_titles = [title for _, title in numbered_toc_entries(toc_block)]
        self.assertNotIn("分析サマリー", numbered_titles)

    def test_toc_numbers_match_body_heading_numbers(self):
        """目次の番号付き項目数と番号は、本文の `## N.` 見出しと1つのずれもなく一致する。"""
        toc_block = extract_toc_block(self.text)
        toc_numbers = [n for n, _ in numbered_toc_entries(toc_block)]
        body_numbers = [n for n, _ in numbered_body_headings(self.text)]

        self.assertTrue(body_numbers, "本文に番号付き見出し（## N. ...）が無い")
        # 1から始まる連番であること（歯抜け・重複が無いこと）
        self.assertEqual(body_numbers, list(range(1, len(body_numbers) + 1)))
        # 目次と本文の番号列が完全一致すること（今回のバグの再発防止）
        self.assertEqual(
            toc_numbers,
            body_numbers,
            "目次の番号が本文の見出し番号とずれている",
        )


if __name__ == "__main__":
    unittest.main()
