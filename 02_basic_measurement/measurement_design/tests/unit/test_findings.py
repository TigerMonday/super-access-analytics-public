"""findings.py のユニットテスト.

確定所見（人が原因まで特定した事実）を読み出す仕組み。生成器が知らない因果関係を
最優先の制約として渡すためのもので、`docs/findings.md` → 無ければ
`docs/check-report.md` の `## 0.` 節、の順で探す。雛形のまま（人が書いていない）
場合は空扱いにする必要があるので、その境界を押さえる。
"""

from measurement_design.review.findings import is_scaffold, load_findings


# ──────────────────────────────────────
# load_findings: 取得元の優先順位
# ──────────────────────────────────────

def test_load_findings_reads_findings_md_when_present(tmp_path):
    (tmp_path / "findings.md").write_text(
        "- signup と sign_up は別イベント。signup が正。sign_up は旧実装の残骸",
        encoding="utf-8",
    )
    text, source = load_findings(tmp_path)
    assert "signup" in text
    assert source == "docs/findings.md"


def test_load_findings_falls_back_to_check_report_section0(tmp_path):
    (tmp_path / "check-report.md").write_text(
        "# チェックレポート\n\n"
        "## 0. 確定所見\n"
        "調査の結果、送信元は本番環境のみと確認済み。\n\n"
        "## 1. 命名規則\n本文\n",
        encoding="utf-8",
    )
    text, source = load_findings(tmp_path)
    assert "本番環境のみ" in text
    assert "命名規則" not in text  # 次の見出し以降は含めない
    assert source == "docs/check-report.md §0"


def test_load_findings_prefers_findings_md_over_check_report(tmp_path):
    (tmp_path / "findings.md").write_text("findings.md の内容", encoding="utf-8")
    (tmp_path / "check-report.md").write_text(
        "## 0. 確定所見\ncheck-report.md の内容\n\n## 1. 次\n",
        encoding="utf-8",
    )
    text, source = load_findings(tmp_path)
    assert text == "findings.md の内容"
    assert source == "docs/findings.md"


def test_load_findings_returns_empty_when_neither_exists(tmp_path):
    text, source = load_findings(tmp_path)
    assert text == "" and source == ""


def test_load_findings_returns_empty_when_findings_md_is_blank(tmp_path):
    (tmp_path / "findings.md").write_text("   \n", encoding="utf-8")
    text, source = load_findings(tmp_path)
    assert text == "" and source == ""


# ──────────────────────────────────────
# check-report.md §0 が雛形のまま（人が未記入）の場合は無いものとして扱う
# ──────────────────────────────────────

def test_load_findings_ignores_unwritten_scaffold_section0(tmp_path):
    (tmp_path / "check-report.md").write_text(
        "## 0. 確定所見\n"
        "<!-- scaffold:unwritten -->\n"
        "- {{finding}}: {{evidence}} → {{impact}}\n\n"
        "## 1. 次\n",
        encoding="utf-8",
    )
    text, source = load_findings(tmp_path)
    assert text == "" and source == ""


def test_load_findings_ignores_section0_with_placeholder_tokens_even_without_marker(tmp_path):
    """マーカー行を消し忘れていなくても、§0専用プレースホルダが残っていれば未記入とみなす。"""
    (tmp_path / "check-report.md").write_text(
        "## 0. 確定所見\n- {{finding}}\n\n## 1. 次\n",
        encoding="utf-8",
    )
    text, source = load_findings(tmp_path)
    assert text == "" and source == ""


def test_load_findings_does_not_false_positive_on_gtm_variable_syntax(tmp_path):
    """GTM変数記法（{{Event}}等）は§0専用プレースホルダと違うので、雛形と誤判定しない。"""
    (tmp_path / "check-report.md").write_text(
        "## 0. 確定所見\n"
        "`{{Event}}` をそのままイベント名に使っているタグがある。要修正。\n\n"
        "## 1. 次\n",
        encoding="utf-8",
    )
    text, source = load_findings(tmp_path)
    assert "{{Event}}" in text
    assert source == "docs/check-report.md §0"


# ──────────────────────────────────────
# is_scaffold
# ──────────────────────────────────────
