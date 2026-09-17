"""本文内の目次リンク(手書きのMarkdownアンカー)が、実際に生成された見出しidへ
張り替えられることを確認するテスト。

背景: markdownの"toc"拡張は既定で見出しidをASCII化して振る(日本語は落ちる)。
一方、本文に手書きされる目次は日本語を残す一般的なアンカー規則で書かれるため、
素の状態では一致せずクリックしても飛ばない。サイドバー目次(house_style側)は
実際のidを読んで作るため元々壊れていない。ここでは本文リンク側の張り替え
(html_components.relink_body_toc_links)を対象にする。
"""

from __future__ import annotations

import re
from pathlib import Path

from report_export.html_components import relink_body_toc_links
from report_export.html_export import build_html

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"


def _build(md_name: str) -> str:
    md_path = FIXTURES_DIR / md_name
    md_text = md_path.read_text(encoding="utf-8")
    full_html, _ = build_html(md_text, md_path)
    return full_html


def _heading_ids(html: str) -> set[str]:
    return set(re.findall(r'<h[1-6][^>]*\sid="([^"]+)"', html))


def _internal_link_hrefs(html: str) -> list[str]:
    # サイドバー目次(.report-nav)は対象外。本文内のリンクだけを見る。
    body = html.split('<aside class="report-nav"', 1)[-1]
    body = body.split("</aside>", 1)[-1]
    return re.findall(r'<a\b[^>]*\bhref="#([^"]*)"', body)


def test_japanese_heading_toc_link_resolves_to_actual_id():
    """fixtureの目次は5項目、順序は固定(1.月次推移 2.存在しない項目
    3.絵文字混じり 4.月次まとめ 5.月次(重複見出しへのリンク))。"""
    html = _build("with_toc_links.md")
    ids = _heading_ids(html)
    hrefs = _internal_link_hrefs(html)
    assert len(hrefs) == 5

    # 1. 「月次推移」: 手書きの日本語アンカー(#1-月次推移)のままでは実idと
    # 一致しないが、張り替え後は実在する見出しidを指す。
    assert hrefs[0] != "1-月次推移"
    assert hrefs[0] in ids

    # 4. 「月次まとめ」も同様に実idへ解決される。
    assert hrefs[3] != "4-月次まとめ"
    assert hrefs[3] in ids


def test_dangling_toc_link_is_left_unchanged():
    """対応する見出しが無いリンクは、壊れたまま(誤った場所へ飛ばさず)残す。"""
    html = _build("with_toc_links.md")
    hrefs = _internal_link_hrefs(html)
    assert hrefs[1] == "99-存在しない見出し"


def test_duplicate_heading_toc_link_resolves_without_crash():
    """同名見出し(### 月次 が2つ)があっても例外にならず、実在するidに解決される。

    どちらの"月次"に解決されるか(先頭優先)は固定しない。Markdown自体が
    同じアンカー文字列で2つの見出しを指しており、書き手側でも本来曖昧なため。
    """
    html = _build("with_toc_links.md")
    ids = _heading_ids(html)
    hrefs = _internal_link_hrefs(html)
    matsuji_href = hrefs[4]
    assert matsuji_href != "月次"  # 未変換のまま残っていない
    assert matsuji_href in ids


def test_emoji_and_symbol_heading_does_not_crash_and_resolves():
    """絵文字・記号混じりの見出し("3. 📈 伸びているページ")でも例外にならず、
    手書きの目次リンク(#3-伸びているページ)が実際の見出しidへ解決されること。

    見出しid自体は既定のASCII化で絵文字・日本語ごと落ちて "3" になるため、
    張り替え後のhrefは元の日本語混じりの文字列ではなく "3" になるのが正しい。
    """
    html = _build("with_toc_links.md")
    ids = _heading_ids(html)
    hrefs = _internal_link_hrefs(html)
    assert "3-伸びているページ" not in hrefs  # 未変換のまま残っていない
    assert "3" in hrefs
    assert "3" in ids


def test_sidebar_toc_still_matches_actual_heading_ids():
    """サイドバー目次(.report-nav)の挙動を壊していないことの回帰確認。"""
    html = _build("with_toc_links.md")
    nav_html = html.split('<aside class="report-nav"', 1)[1].split("</aside>", 1)[0]
    nav_hrefs = re.findall(r'href="#([^"]+)"', nav_html)
    ids = _heading_ids(html)
    for href in nav_hrefs:
        if href == "report-top":
            continue  # 先頭へ戻るリンク(見出しではない)
        assert href in ids


def test_no_body_toc_present_does_not_crash():
    """本文内に目次(内部リンク)が無いレポートでも壊れないこと。"""
    html = _build("with_tables.md")
    assert "<html" in html or "<!doctype" in html.lower() or "report-sheet" in html


def test_relink_unit_leaves_already_matching_href_untouched():
    html = (
        '<h2 id="1-kpi" class="section-title">1. KPI</h2>'
        '<p><a href="#1-kpi">KPI</a></p>'
    )
    assert relink_body_toc_links(html) == html


def test_relink_unit_ignores_external_and_empty_hrefs():
    html = (
        '<h2 id="1" class="section-title">1</h2>'
        '<p><a href="https://example.com/#foo">外部</a> <a href="#">空</a></p>'
    )
    assert relink_body_toc_links(html) == html
