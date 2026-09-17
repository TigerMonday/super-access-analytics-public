"""house_style._load_template() が開発者向けコメントだけを落とすことを検証する。

report-template.html には2種類の開発者向けコメントがあり、どちらも生成HTMLに
そのまま出ると内部仕様(プレースホルダ仕様・design-system.mdへの参照・実装手段
Playwright・デザイン判断の理由等)が読めてしまう不具合があった。

  1. ファイル先頭のHTMLコメント(<!-- ... -->)
  2. <style>ブロック内のCSSコメント(/* ... */)

修正はどちらも「テンプレートファイル自体には残す・読み込み時にだけ落とす」
「対象範囲を厳密に限定し、他の場所のコメントは巻き込まない」という同じ方針。
このテストは (1)(2)それぞれが落ちること (3)<style>の外にあるコメントは
巻き込まないこと (4)CSSの宣言と本文が残ること、を確認する。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from report_export import house_style

# 先頭コメント・<style>内コメント・<style>外のコメント・__BODY__ を持つ
# 最小のダミーテンプレート。実物の report-template.html を変更してもテストが
# 壊れないよう、ロジック検証はこのダミーで行う。
_FAKE_TEMPLATE = """<!--
  レポート用テンプレート。
  report_export はこのファイルを読み込み、__TITLE__ / __GENERATED_AT__ /
  __LOGO_B64__ / __ACCENT_OVERRIDE__ / __BODY__ の5つのプレースホルダを
  置換して本文を流し込む。
-->
<!doctype html>
<html lang="ja">
<head>
<title>__TITLE__</title>
<style>
/* コアCSSのコメント。design-system.md参照などが入る想定。style内なので除去対象 */
:root{ --gold:#D4AF37; }
.card{ padding:18px 20px; background:var(--gray-50); }
</style>
</head>
<body>
<script>
/* style外のコメント。除去対象外(styleブロックにだけ触れる実装のため) */
console.log("ok");
</script>
<main class="report-body">__BODY__</main>
</body>
</html>
"""


def _patch_template(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, content: str) -> None:
    template_path = tmp_path / "report-template.html"
    template_path.write_text(content, encoding="utf-8")
    monkeypatch.setattr(house_style, "_TEMPLATE_PATH", template_path)


@pytest.mark.parametrize("leading_comment", [True, False])
def test_wrap_removes_only_developer_comments(monkeypatch, tmp_path, leading_comment):
    template = _FAKE_TEMPLATE if leading_comment else _FAKE_TEMPLATE.split("-->\n", 1)[1]
    _patch_template(monkeypatch, tmp_path, template)
    body = '<p>本文</p><!-- 本文由来のコメント -->'
    html = house_style.wrap_html("タイトル", body, "2026-08-25")
    assert html.lstrip().startswith("<!doctype html>")
    assert "プレースホルダ" not in html
    assert "__TITLE__" not in html
    assert "コアCSSのコメント" not in html
    assert "design-system.md" not in html
    style = html.split("<style>", 1)[1].split("</style>", 1)[0]
    assert ":root{ --gold:#D4AF37; }" in style
    assert ".card{ padding:18px 20px; background:var(--gray-50); }" in style
    assert "/* style外のコメント。除去対象外" in html
    assert 'console.log("ok");' in html
    assert body in html


def test_real_template_keeps_styles_and_body_without_developer_text():
    html = house_style.wrap_html("タイトル", "<p>本文</p>", "2026-08-25")
    assert not html.lstrip().startswith("<!--")
    for forbidden in ("プレースホルダ", "半角スペースを挟んで表記する", "design-system.md", "Playwright"):
        assert forbidden not in html
    assert "<p>本文</p>" in html
    style = html.split("<style>", 1)[1].split("</style>", 1)[0]
    assert "/*" not in style
    assert "*/" not in style
    for selector in ("table.s-table", ".kpi-box{"):
        assert selector in style
