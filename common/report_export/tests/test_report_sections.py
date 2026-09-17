"""1280x720固定レポートを実ブラウザ(Playwright)で検証するテスト。

ページ分割は高さだけで文章や表の行を切らず、見出し・連続段落・図表の意味単位の
境界だけで行う。表と直後の説明は同じ単位に残す。単位そのものが収まらない場合は
縮小や切り捨てをせず、HTMLで明示してPDF変換を止める。

- すべての面が論理サイズ1280x720で、画面では1面全体がビューポート内に収まること
- 表の行が欠落・重複せず、巨大表は行分割されずにはみ出しとして検出されること
- 通常の原稿では意味単位が面内へ収まり、PDFの1面と1ページが一致すること
- ウィンドウ寸法を変えても改ページ位置と面数が変わらないこと
- 目次と「次の面」操作が固定面のフレームへ移動すること
"""

from __future__ import annotations

import base64
import re
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

from report_export.html_export import build_html
from report_export.house_style import _split_section_at_tables

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"


def _build(md_name: str) -> str:
    md_path = FIXTURES_DIR / md_name
    md_text = md_path.read_text(encoding="utf-8")
    full_html, _ = build_html(md_text, md_path)
    return full_html


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def _load(browser, html: str, *, viewport=None):
    page = browser.new_page(viewport=viewport or {"width": 1400, "height": 900})
    page.set_content(html, wait_until="load")
    # wait_for_function は文字列を eval するため、生成HTMLの厳格なCSPで拒否される。
    # evaluate は Playwright の分離実行環境から参照できるので、短いポーリングで待つ。
    for _ in range(100):
        if page.evaluate("() => document.body.dataset.slidesReady === 'true'"):
            break
        page.wait_for_timeout(50)
    else:
        raise AssertionError("report slide layout did not finish")
    return page


def _sheet_info(page):
    return page.evaluate(
        """
        () => {
          const sheets = [...document.querySelectorAll('.report-sheet')];
          const overflowing = sheets.filter(s => s.classList.contains('has-overflow')).length;
          const totalRows = [...document.querySelectorAll('table.s-table tbody')]
            .reduce((a, t) => a + t.children.length, 0);
          const tablesOutsideSheet = [...document.querySelectorAll('table.s-table')]
            .filter(t => !t.closest('.report-sheet')).length;
          const maxTablesPerSheet = Math.max(0, ...sheets.map(s => s.querySelectorAll('table.s-table').length));
          return {
            sheetCount: sheets.length,
            frameCount: document.querySelectorAll('.report-sheet-frame').length,
            overflowing,
            totalRows,
            tablesOutsideSheet,
            maxTablesPerSheet,
            ellipsis: document.body.innerText.includes('…'),
          };
        }
        """
    )


def _source_row_count(md_name: str) -> int:
    md_text = (FIXTURES_DIR / md_name).read_text(encoding="utf-8")
    lines = [ln for ln in md_text.splitlines() if ln.strip().startswith("|")]
    # ヘッダ行+区切り行(|---|のような行)を除いた実データ行数
    return len(lines) - 2


def _source_h1_h2_count(md_name: str) -> int:
    md_text = (FIXTURES_DIR / md_name).read_text(encoding="utf-8")
    # 先頭のH1(表紙タイトルとして抜き出され本文には残らない)を除いた見出し数
    lines = [ln for ln in md_text.splitlines() if re.match(r"^#{1,2}\s", ln)]
    return max(len(lines) - 1, 0)


# ---------------------------------------------------------------------------
# 面の数: セクション境界どおりに分かれ、表の行が欠落・重複せず、切られないこと
# ---------------------------------------------------------------------------


def test_sections_become_at_least_one_slide_each_plus_cover(browser):
    html = _build("big_table.md")
    page = _load(browser, html)
    info = _sheet_info(page)
    page.close()

    # 表紙(.report-cover)+ セクション数ぶんの面
    assert info["sheetCount"] >= _source_h1_h2_count("big_table.md") + 1
    assert info["frameCount"] == info["sheetCount"]


def test_big_table_stays_atomic_and_is_reported_as_overflow(browser):
    html = _build("big_table.md")
    page = _load(browser, html)
    info = _sheet_info(page)
    page.close()

    assert info["totalRows"] == _source_row_count("big_table.md")
    assert info["tablesOutsideSheet"] == 0
    assert info["maxTablesPerSheet"] <= 1
    assert not info["ellipsis"]
    assert info["overflowing"] == 1


def test_wide_table_is_reported_instead_of_clipped_in_pdf(browser):
    headers = [f"列{i}" for i in range(1, 31)]
    md = (
        "# 横長表テスト\n\n## 横長表\n\n"
        + "| " + " | ".join(headers) + " |\n"
        + "| " + " | ".join(["---"] * len(headers)) + " |\n"
        + "| " + " | ".join([f"長い値{i}" for i in range(1, 31)]) + " |\n"
    )
    html, _ = build_html(md, Path("wide-table.md"))
    page = _load(browser, html)
    measurements = page.evaluate(
        """
        () => {
          const frame = document.querySelector('.table-scroll');
          return {
            clientWidth: frame.clientWidth,
            scrollWidth: frame.scrollWidth,
            overflowLabels: window.__reportSlideState.overflowLabels,
          };
        }
        """
    )
    page.close()
    assert measurements["scrollWidth"] > measurements["clientWidth"]
    assert measurements["overflowLabels"] == ["横長表"]


def test_tall_data_image_is_measured_after_decode(browser):
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="900" '
        'viewBox="0 0 800 900"><rect width="800" height="900" fill="white"/>'
        '<text x="40" y="80" font-size="42">tall image</text></svg>'
    )
    encoded = base64.b64encode(svg.encode()).decode()
    md = (
        "# 画像テスト\n\n## 縦長画像\n\n"
        f'<img src="data:image/svg+xml;base64,{encoded}" alt="縦長画像">\n'
    )
    html, _ = build_html(md, Path("tall-image.md"))
    page = _load(browser, html)
    state = page.evaluate(
        """
        () => {
          const image = document.querySelector('.report-body img');
          const content = image.closest('.report-slide-content');
          return {
            imageComplete: image.complete,
            imageHeight: image.getBoundingClientRect().height,
            contentHeight: content.clientHeight,
            overflowLabels: window.__reportSlideState.overflowLabels,
          };
        }
        """
    )
    page.close()
    assert state["imageComplete"]
    assert state["imageHeight"] > state["contentHeight"]
    assert state["overflowLabels"] == ["縦長画像"]


def test_small_fixture_keeps_every_row(browser):
    html = _build("with_tables.md")
    page = _load(browser, html)
    info = _sheet_info(page)
    page.close()

    # with_tables.mdは表が2つ(チャネル別サマリー4行・施策別メモ3行)ある
    assert info["totalRows"] == 7
    assert info["maxTablesPerSheet"] <= 1
    assert not info["ellipsis"]
    assert info["overflowing"] == 0


def test_multiple_tables_in_one_section_become_separate_sheets():
    section = (
        '<h2 id="summary" class="section-title">まとめ</h2><p>導入</p>'
        '<div class="table-scroll"><table class="s-table"><tbody><tr><td>A</td></tr></tbody></table></div>'
        '<h3 class="sub-title">詳細</h3><p>説明</p>'
        '<div class="table-scroll"><table class="s-table"><tbody><tr><td>B</td></tr></tbody></table></div>'
        '<p>結論</p>'
    )

    sheets = _split_section_at_tables(section)

    assert len(sheets) == 2
    assert all(sheet.count('<table class="s-table">') == 1 for sheet in sheets)
    assert "まとめ（続き）" in sheets[1]
    assert "詳細" in sheets[1]
    assert "説明" in sheets[1]
    assert "結論" in sheets[1]


def test_explanation_after_first_table_stays_with_that_table():
    section = (
        '<h2 id="device" class="section-title">デバイス・ユーザー種別</h2>'
        '<div class="table-scroll"><table class="s-table"><tbody><tr><td>mobile</td></tr></tbody></table></div>'
        '<p>モバイル比率から読み取れること。</p>'
        '<div class="table-scroll"><table class="s-table"><tbody><tr><td>new</td></tr></tbody></table></div>'
    )

    sheets = _split_section_at_tables(section)

    assert len(sheets) == 2
    assert "モバイル比率から読み取れること。" in sheets[0]
    assert "モバイル比率から読み取れること。" not in sheets[1]


def test_chart_immediately_before_next_table_moves_with_that_table():
    section = (
        '<h2 id="summary" class="section-title">まとめ</h2>'
        '<div class="report-chart"><svg aria-label="A"></svg></div>'
        '<div class="table-scroll"><table class="s-table"><tbody><tr><td>A</td></tr></tbody></table></div>'
        '<p>最初の表の説明。</p>'
        '<div class="report-chart"><svg aria-label="B"></svg></div>'
        '<div class="table-scroll"><table class="s-table"><tbody><tr><td>B</td></tr></tbody></table></div>'
    )

    sheets = _split_section_at_tables(section)

    assert len(sheets) == 2
    assert all(sheet.count('class="report-chart"') == 1 for sheet in sheets)
    assert all(sheet.count('<table class="s-table">') == 1 for sheet in sheets)
    assert "最初の表の説明。" in sheets[0]
    assert 'aria-label="B"' not in sheets[0]
    assert 'aria-label="B"' in sheets[1]


def test_combo_chart_with_multiple_classes_moves_with_its_table():
    section = (
        '<h2 id="trend" class="section-title">推移</h2>'
        '<div class="report-chart report-chart-combo"><svg aria-label="月次"></svg></div>'
        '<div class="table-scroll"><table class="s-table"><tbody><tr><td>月次</td></tr></tbody></table></div>'
        '<p>月次の説明。</p>'
        '<div class="report-chart report-chart-combo"><svg aria-label="週次"></svg></div>'
        '<div class="table-scroll"><table class="s-table"><tbody><tr><td>週次</td></tr></tbody></table></div>'
    )

    sheets = _split_section_at_tables(section)

    assert len(sheets) == 2
    assert all(sheet.count('class="report-chart report-chart-combo"') == 1 for sheet in sheets)
    assert 'aria-label="週次"' not in sheets[0]
    assert 'aria-label="週次"' in sheets[1]


def test_insight_is_carried_to_later_table_sheet():
    insight = '<div class="insight-box"><strong>考察:</strong> 数値の主因です。</div>'
    section = (
        '<h2 id="search" class="section-title">自然検索</h2>'
        + insight
        + '<div class="report-chart"><svg aria-label="推移"></svg></div>'
        + '<div class="table-scroll"><table class="s-table"><tbody><tr><td>A</td></tr></tbody></table></div>'
        + '<div class="table-visual-title">ページ別</div>'
        + '<div class="table-scroll"><table class="s-table"><tbody><tr><td>B</td></tr></tbody></table></div>'
    )

    sheets = _split_section_at_tables(section)

    assert len(sheets) == 2
    assert "数値の主因です。" in sheets[0]
    assert "数値の主因です。" in sheets[1]


def test_individual_insight_moves_only_with_its_table():
    section = (
        '<h2 id="detail" class="section-title">詳細</h2>'
        '<div class="insight-box"><strong>考察:</strong> 表Aの考察です。</div>'
        '<div class="table-scroll"><table class="s-table"><tbody><tr><td>A</td></tr></tbody></table></div>'
        '<div class="insight-box"><strong>考察:</strong> 表Bの考察です。</div>'
        '<div class="table-scroll"><table class="s-table"><tbody><tr><td>B</td></tr></tbody></table></div>'
    )

    sheets = _split_section_at_tables(section)

    assert len(sheets) == 2
    assert "表Aの考察です。" in sheets[0]
    assert "表Bの考察です。" not in sheets[0]
    assert "表Bの考察です。" in sheets[1]
    assert "表Aの考察です。" not in sheets[1]


def test_table_and_following_explanation_stay_in_same_semantic_block(browser):
    md = (
        "# 意味単位テスト\n\n## 結果\n\n"
        "| 指標 | 値 |\n|---|---:|\n| セッション | 100 |\n\n"
        "この表から、流入量は前期より増えていると読める。\n\n"
        "## 次の章\n\n別の内容。\n"
    )
    html, _ = build_html(md, Path("semantic-table.md"))
    page = _load(browser, html)
    same_block = page.evaluate(
        """
        () => {
          const table = document.querySelector('table.s-table');
          const paragraph = [...document.querySelectorAll('p')]
            .find(p => p.textContent.includes('この表から'));
          return table.closest('.semantic-block') === paragraph.closest('.semantic-block') &&
            table.closest('.report-sheet') === paragraph.closest('.report-sheet');
        }
        """
    )
    page.close()
    assert same_block


def test_chapter_heading_and_short_intro_are_not_left_on_an_orphan_sheet(browser):
    rows = "\n".join(
        f"| 項目{i} | 長い説明文を含む確認結果です。設定値と実装状態を照合します。 |"
        for i in range(1, 9)
    )
    md = (
        "# 改ページテスト\n\n"
        "## 1. 計測設定の確認結果\n\n"
        "現在の設定と取得できた範囲を一覧にしています。追加確認が必要な項目も含みます。\n\n"
        "### データ収集・保持\n\n"
        "受信範囲、データの収集方法、保持期間を確認した結果です。\n\n"
        "| 確認項目 | 結果 |\n|---|---|\n" + rows + "\n"
    )
    html, _ = build_html(md, Path("no-orphan-heading.md"))
    page = _load(browser, html)
    result = page.evaluate(
        """
        () => {
          const title = [...document.querySelectorAll('.report-body h2')]
            .find(node => node.textContent.includes('計測設定の確認結果'));
          const sheet = title.closest('.report-sheet');
          return {
            hasDecisionMaterial: Boolean(sheet.querySelector('h3,table,.report-chart,.pictogram-grid,.kpi-grid')),
            overflowLabels: window.__reportSlideState.overflowLabels,
          };
        }
        """
    )
    page.close()

    assert result["hasDecisionMaterial"]
    assert result["overflowLabels"] == []


def test_each_data_visual_keeps_the_section_insight(browser):
    md = (
        "# 考察セットテスト\n\n## 1. 推移\n\n"
        "> **考察:** 流入減が成果減の主因であり、CVRは横ばいです。\n\n"
        "<!-- chart: combo; title: 月次 -->\n"
        "| 月 | セッション | 資料DL CV数 | 資料DL CVR | 相談 CV数 | 相談 CVR |\n"
        "|---|---:|---:|---:|---:|---:|\n"
        "| 2026-01 | 1,000 | 10 | 1.00% | 20 | 2.00% |\n"
        "| 2026-02 | 800 | 8 | 1.00% | 16 | 2.00% |\n\n"
        "表の注記です。\n"
    )
    html, _ = build_html(md, Path("insight-with-visuals.md"))
    page = _load(browser, html)
    result = page.evaluate(
        """
        () => [...document.querySelectorAll('.report-chart,.table-scroll')]
          .map(visual => {
            const sheet = visual.closest('.report-sheet');
            return {
            insight: sheet.textContent.includes('流入減が成果減の主因'),
            kind: visual.classList.contains('report-chart') ? 'chart' : 'table',
            overflow: sheet.classList.contains('has-overflow'),
            };
          })
        """
    )
    page.close()
    assert len(result) == 4  # セッション、2つのCV、根拠表
    assert all(item["insight"] for item in result)
    assert all(not item["overflow"] for item in result)
    assert [item["kind"] for item in result].count("chart") == 3
    assert [item["kind"] for item in result].count("table") == 1


def test_section_insight_survives_subheading_before_combo_visuals(browser):
    introduction = "\n\n".join(
        f"導入文 {index}: この段落は、図表より前の説明を十分な長さにするための文章です。"
        for index in range(1, 13)
    )
    md = (
        "# 小見出し考察セットテスト\n\n## 1. 推移\n\n"
        "> **考察:** 章全体に共通する判断です。\n\n"
        f"{introduction}\n\n"
        "### 月次の内訳\n\n"
        "<!-- chart: combo; title: 月次 -->\n"
        "| 月 | セッション | 資料DL CV数 | 資料DL CVR | 相談 CV数 | 相談 CVR |\n"
        "|---|---:|---:|---:|---:|---:|\n"
        "| 2026-01 | 1,000 | 10 | 1.00% | 20 | 2.00% |\n"
        "| 2026-02 | 800 | 8 | 1.00% | 16 | 2.00% |\n"
    )
    html, _ = build_html(md, Path("insight-after-subheading.md"))
    page = _load(browser, html)
    result = page.evaluate(
        """
        () => [...document.querySelectorAll('.report-chart,.table-scroll')]
          .map(visual => {
            const sheet = visual.closest('.report-sheet');
            return {
              insight: sheet.textContent.includes('章全体に共通する判断'),
              overflow: sheet.classList.contains('has-overflow'),
            };
          })
        """
    )
    page.close()
    assert len(result) == 4
    assert all(item["insight"] for item in result)
    assert all(not item["overflow"] for item in result)


def test_repeated_context_is_shown_once_when_visual_groups_share_a_slide(browser):
    md = (
        "# 重複考察テスト\n\n## 1. 概要\n\n"
        "> **考察:** 同じ面では一度だけ表示する判断です。\n\n"
        '<div class="pictogram-grid"><div>課題</div></div>\n\n'
        '<div class="kpi-grid"><div>100</div></div>\n'
    )
    html, _ = build_html(md, Path("deduplicate-insight.md"))
    page = _load(browser, html)
    result = page.evaluate(
        """
        () => {
          const sheets = [...document.querySelectorAll('.report-sheet')]
            .filter(sheet => sheet.textContent.includes('同じ面では一度だけ'));
          return sheets.map(sheet => ({
            visibleContexts: [...sheet.querySelectorAll('.insight-box,.visual-context')]
              .filter(node => getComputedStyle(node).display !== 'none').length,
            pictogram: Boolean(sheet.querySelector('.pictogram-grid')),
            kpi: Boolean(sheet.querySelector('.kpi-grid')),
          }));
        }
        """
    )
    page.close()
    assert result == [{"visibleContexts": 1, "pictogram": True, "kpi": True}]


def test_no_tables_fixture_still_renders_sections(browser):
    html = _build("no_tables.md")
    page = _load(browser, html)
    count = page.evaluate("() => document.querySelectorAll('.report-sheet').length")
    page.close()
    assert count == _source_h1_h2_count("no_tables.md") + 1


# ---------------------------------------------------------------------------
# 固定面と画面縮尺
# ---------------------------------------------------------------------------


def test_logical_slide_is_1280_by_720_and_frame_fits_viewport(browser):
    html = _build("big_table.md")
    page = _load(browser, html, viewport={"width": 1400, "height": 900})
    sizes = page.evaluate(
        """
        () => {
          const slide = document.querySelector('.report-sheet');
          const frame = document.querySelector('.report-sheet-frame');
          return {
            slideWidth: slide.offsetWidth,
            slideHeight: slide.offsetHeight,
            frameWidth: frame.getBoundingClientRect().width,
            frameHeight: frame.getBoundingClientRect().height,
            viewportWidth: innerWidth,
            viewportHeight: innerHeight,
          };
        }
        """
    )
    page.close()
    assert sizes["slideWidth"] == 1280
    assert sizes["slideHeight"] == 720
    assert sizes["frameWidth"] <= sizes["viewportWidth"]
    assert sizes["frameHeight"] <= sizes["viewportHeight"] - 40


def test_sparse_slide_uses_roomy_density_without_changing_semantic_group(browser):
    md = """# 密度テスト

## 優先順位

短い説明です。

| 施策 | ICE | 理由 |
|---|---:|---|
| 施策A | 240 | 最優先 |
| 施策B | 180 | 次点 |

この表を受けた判断です。
"""
    html, _ = build_html(md, Path("density-sparse.md"))
    page = _load(browser, html)
    result = page.evaluate(
        """
        () => {
          const sheet = [...document.querySelectorAll('.report-sheet')]
            .find(item => item.querySelector('table.s-table'));
          const table = sheet.querySelector('table.s-table');
          const explanation = [...sheet.querySelectorAll('p')]
            .find(item => item.textContent.includes('この表を受けた判断'));
          return {
            density: sheet.dataset.density,
            overflow: sheet.classList.contains('has-overflow'),
            tableFont: parseFloat(getComputedStyle(table).fontSize),
            sameBlock: table.closest('.semantic-block') === explanation.closest('.semantic-block'),
          };
        }
        """
    )
    page.close()
    assert result["density"] == "roomy"
    assert not result["overflow"]
    assert result["tableFont"] == 14
    assert result["sameBlock"]


def test_medium_slide_uses_comfortable_density_without_overflow(browser):
    paragraphs = "\n\n".join(
        f"段落{i}です。判断に必要な説明をここに置き、読み手が意味を確認できる長さにします。"
        for i in range(8)
    )
    md = f"# 密度テスト\n\n## 中密度\n\n{paragraphs}\n"
    html, _ = build_html(md, Path("density-comfortable.md"))
    page = _load(browser, html)
    result = page.evaluate(
        """
        () => {
          const sheet = [...document.querySelectorAll('.report-sheet')]
            .find(item => item.querySelector('#_1'));
          const content = sheet.querySelector('.report-slide-content');
          return {
            density: sheet.dataset.density,
            roomy: sheet.classList.contains('density-roomy'),
            comfortable: sheet.classList.contains('density-comfortable'),
            overflow: sheet.classList.contains('has-overflow'),
            verticalFits: content.scrollHeight <= content.clientHeight + 1,
            horizontalFits: content.scrollWidth <= content.clientWidth + 1,
          };
        }
        """
    )
    page.close()
    assert result["density"] == "comfortable"
    assert not result["roomy"]
    assert result["comfortable"]
    assert not result["overflow"]
    assert result["verticalFits"]
    assert result["horizontalFits"]


def test_roomy_density_falls_back_when_expansion_overflows_vertically(browser):
    rows = "\n".join(
        f"| 施策{i} | {300 - i} | 説明文を入れて表の高さを調整します {i} |"
        for i in range(7)
    )
    md = f"""# 密度テスト

## 表の密度

短い説明です。

| 施策 | ICE | 理由 |
|---|---:|---|
{rows}

表を受けた判断です。
"""
    html, _ = build_html(md, Path("density-fallback-vertical.md"))
    page = _load(browser, html)
    result = page.evaluate(
        """
        () => {
          const sheet = [...document.querySelectorAll('.report-sheet')]
            .find(item => item.querySelector('table.s-table'));
          const content = sheet.querySelector('.report-slide-content');
          return {
            density: sheet.dataset.density,
            roomy: sheet.classList.contains('density-roomy'),
            comfortable: sheet.classList.contains('density-comfortable'),
            overflow: sheet.classList.contains('has-overflow'),
            verticalFits: content.scrollHeight <= content.clientHeight + 1,
          };
        }
        """
    )
    page.close()
    assert result["density"] == "comfortable"
    assert not result["roomy"]
    assert result["comfortable"]
    assert not result["overflow"]
    assert result["verticalFits"]


def test_roomy_density_falls_back_when_expansion_overflows_horizontally(browser):
    md = """# 密度テスト

## 横幅の復帰

短い説明です。

| 施策 | ICE | 理由 |
|---|---:|---|
| 施策A | 240 | 最優先 |
| 施策B | 180 | 次点 |

表を受けた判断です。
"""
    html, _ = build_html(md, Path("density-fallback-horizontal.md"))
    html = html.replace(
        "</head>",
        "<style>.report-sheet.density-roomy table.s-table{min-width:1300px}</style></head>",
    )
    page = _load(browser, html)
    result = page.evaluate(
        """
        () => {
          const sheet = [...document.querySelectorAll('.report-sheet')]
            .find(item => item.querySelector('table.s-table'));
          const content = sheet.querySelector('.report-slide-content');
          const tableFrame = sheet.querySelector('.table-scroll');
          return {
            density: sheet.dataset.density,
            roomy: sheet.classList.contains('density-roomy'),
            comfortable: sheet.classList.contains('density-comfortable'),
            overflow: sheet.classList.contains('has-overflow'),
            contentFits: content.scrollWidth <= content.clientWidth + 1,
            tableFits: tableFrame.scrollWidth <= tableFrame.clientWidth + 1,
          };
        }
        """
    )
    page.close()
    assert result["density"] == "comfortable"
    assert not result["roomy"]
    assert result["comfortable"]
    assert not result["overflow"]
    assert result["contentFits"]
    assert result["tableFits"]


def test_dense_slide_keeps_standard_density(browser):
    rows = "\n".join(
        f"| 施策{i} | {300 - i} | 根拠を十分に説明するための長い文章 {i} |"
        for i in range(1, 14)
    )
    md = f"""# 密度テスト

## 詳細一覧

この面は十分な情報量があります。

| 施策 | ICE | 理由 |
|---|---:|---|
{rows}

一覧全体を受けた判断です。
"""
    html, _ = build_html(md, Path("density-dense.md"))
    page = _load(browser, html)
    result = page.evaluate(
        """
        () => {
          const sheet = [...document.querySelectorAll('.report-sheet')]
            .find(item => item.querySelector('table.s-table'));
          return {
            density: sheet.dataset.density,
            roomy: sheet.classList.contains('density-roomy'),
            comfortable: sheet.classList.contains('density-comfortable'),
          };
        }
        """
    )
    page.close()
    assert result["density"] == "standard"
    assert not result["roomy"]
    assert not result["comfortable"]


# ---------------------------------------------------------------------------
# 目次: クリックでスクロールし、現在地がハイライトされること
# ---------------------------------------------------------------------------


def test_toc_click_scrolls_and_highlights_current_section(browser):
    html = _build("big_table.md")
    page = _load(browser, html)

    before = page.evaluate("() => window.scrollY")
    # 長い表の直前を選び、最下部のスクロール上限に影響されないようにする。
    page.locator(".report-nav a[data-section]").nth(1).click()
    page.wait_for_function(
        """before => window.scrollY !== before &&
        document.querySelectorAll('.report-nav a[data-section]')[1].classList.contains('is-current') &&
        document.querySelectorAll('.report-nav a.is-current').length === 1""",
        arg=before,
    )
    page.close()


def test_next_sheet_button_advances_and_returns_to_top(browser):
    html = _build("big_table.md")
    page = _load(browser, html)
    button = page.locator(".next-sheet")

    button.click()
    page.wait_for_function("() => window.scrollY > 0")

    page.wait_for_timeout(1000)
    page.evaluate("() => { document.documentElement.style.scrollBehavior = 'auto'; window.scrollTo(0, document.body.scrollHeight); }")
    page.wait_for_function("() => document.querySelector('.next-sheet').dataset.target === 'top'")
    button.click()
    page.wait_for_function("() => window.scrollY <= 40")
    page.close()

# ---------------------------------------------------------------------------
# リサイズで面の数が変わらないこと(セクション境界だけで決まる。実測レイアウト非依存)
# ---------------------------------------------------------------------------


def test_window_height_resize_does_not_change_sheet_count(browser):
    html = _build("big_table.md")
    page = _load(browser, html)
    before = page.evaluate("() => document.querySelectorAll('.report-sheet').length")

    for h in (900, 1200, 500, 900):
        page.set_viewport_size({"width": 1400, "height": h})
        count = page.evaluate("() => document.querySelectorAll('.report-sheet').length")
        assert count == before

    page.close()


# ---------------------------------------------------------------------------
# PDF: 面(セクション)の境界で改ページされること
# ---------------------------------------------------------------------------


def _pdf_page_counts(browser, html: str, out: Path) -> list[int]:
    # export_pdf_from_html は内部で独自の sync_playwright() を起動するため、モジュール
    # 共有の browser フィクスチャ(既にsync_playwright起動済み)とは同居できない
    # (Playwright Sync APIは同一プロセスにPlaywrightインスタンスを二重に持てない)。
    # ここではexport_pdf_from_htmlのラッパー自体(margin/footer_template設定)は
    # test_pdf_export.py側で別途検証されている前提とし、共有browserのpageで直接
    # page.pdf()を呼んで「面の境界のCSSがPDF側で改ページになるか」だけを見る。
    page = browser.new_page()
    page.set_content(html, wait_until="load")
    page.wait_for_function("document.body.dataset.slidesReady === 'true'")
    page.pdf(path=str(out), width="13.333333in", height="7.5in",
             prefer_css_page_size=True, print_background=True,
             margin={"top": "0", "bottom": "0", "left": "0", "right": "0"})
    page.close()
    pdf_bytes = out.read_bytes()
    return [int(m) for m in re.findall(rb"/Count\s*(\d+)", pdf_bytes)]


def test_oversized_atomic_table_is_detected_before_pdf(browser):
    html = _build("big_table.md")
    page = _load(browser, html)
    state = page.evaluate("() => window.__reportSlideState")
    page.close()
    assert state["overflowLabels"] == ["巨大な表を含むセクション"]


def test_pdf_page_count_matches_sheet_count_for_small_fixture(browser, tmp_path):
    # 収まる意味単位では、固定面の数とPDFページ数が一致する。
    html = _build("with_tables.md")
    page = _load(browser, html)
    sheet_count = page.evaluate("() => document.querySelectorAll('.report-sheet-frame').length")
    assert page.evaluate("() => document.body.dataset.slideOverflowCount") == "0"
    page.close()
    counts = _pdf_page_counts(browser, html, tmp_path / "with_tables.pdf")
    assert counts
    assert max(counts) == sheet_count


# ---------------------------------------------------------------------------
# 開発者向けコメントの非流出
# ---------------------------------------------------------------------------


def test_generated_html_has_no_developer_comment_leak():
    html = _build("with_tables.md")
    assert "design-system.md" not in html
    assert "Playwright" not in html
    assert "house_style" not in html
    assert not html.lstrip().startswith("<!--")
