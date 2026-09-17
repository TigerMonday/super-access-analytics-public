from pathlib import Path

import pytest

from report_export.visual_contract import VisualContractError, validate_visual_contract


def _saa_report_path(tmp_path: Path, stem: str) -> Path:
    builder = tmp_path / "common" / "report_index" / "build_index.py"
    builder.parent.mkdir(parents=True, exist_ok=True)
    builder.write_text("# marker", encoding="utf-8")
    return tmp_path / "outputs" / "client" / "report" / f"{stem}.md"


@pytest.mark.parametrize(
    ("stem", "html"),
    [
        ("00_3c_persona_journey_report", '<div class="pictogram-grid"></div>'),
        (
            "basic-analysis-report",
            '<section class="report-sheet report-body"><p>考察</p>'
            '<div class="report-chart"></div><div class="pictogram-grid"></div></section>',
        ),
        (
            "cvr-improvement-plan",
            '<section class="report-sheet report-body"><p>改善方針</p>'
            '<div class="pictogram-grid"></div></section>',
        ),
        (
            "check-report",
            '<section class="report-sheet report-body"><p>確認結果</p>'
            '<div class="table-scroll"><table class="s-table"></table></div></section>',
        ),
    ],
)
def test_major_saa_reports_accept_required_visuals(tmp_path: Path, stem: str, html: str) -> None:
    path = _saa_report_path(tmp_path, stem)
    validate_visual_contract(path, html)


@pytest.mark.parametrize(
    ("stem", "expected"),
    [
        ("00_3c_persona_journey_report", "ピクトグラム"),
        ("basic-analysis-report", "数値グラフ"),
        ("cvr-improvement-plan", "ピクトグラム"),
        ("check-report", "一覧表"),
    ],
)
def test_major_saa_reports_reject_missing_visuals(tmp_path: Path, stem: str, expected: str) -> None:
    path = _saa_report_path(tmp_path, stem)
    with pytest.raises(VisualContractError, match=expected):
        validate_visual_contract(path, "<html></html>")


def test_unrecognized_or_external_reports_are_not_forced(tmp_path: Path) -> None:
    validate_visual_contract(_saa_report_path(tmp_path, "custom-report"), "<html></html>")
    validate_visual_contract(tmp_path / "basic-analysis-report.md", "<html></html>")


def test_other_projects_can_use_report_export_without_saa_contract(tmp_path: Path) -> None:
    path = tmp_path / "outputs" / "client" / "basic-analysis-report.md"
    validate_visual_contract(path, "<html></html>")


def test_unresolved_visual_marker_is_rejected_even_outside_saa(tmp_path: Path) -> None:
    with pytest.raises(VisualContractError, match="未変換"):
        validate_visual_contract(
            tmp_path / "custom-report.md",
            '<html><!-- chart: combo; title: 月次 --><table></table></html>',
        )


def test_basic_analysis_rejects_cvr_left_as_standalone_panel(tmp_path: Path) -> None:
    path = _saa_report_path(tmp_path, "basic-analysis-report")
    html = (
        '<section class="report-sheet report-body"><p>考察</p>'
        '<div class="report-chart report-chart-combo">'
        '<text class="panel-title">問い合わせCVR</text></div>'
        '<div class="pictogram-grid"></div></section>'
    )
    with pytest.raises(VisualContractError, match="二軸"):
        validate_visual_contract(path, html)
