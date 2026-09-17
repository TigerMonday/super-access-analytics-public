"""SAAの主要レポートに対する、HTML/PDF用の可視化完成条件。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


@dataclass(frozen=True)
class VisualRequirement:
    selector: str
    label: str


_REPORT_REQUIREMENTS: dict[str, tuple[VisualRequirement, ...]] = {
    "check-report": (
        VisualRequirement('<table class="s-table"', "判定・状態・確認根拠の一覧表"),
    ),
    "00_3c_persona_journey_report": (
        VisualRequirement('class="pictogram-grid', "3C・顧客理解の要点ピクトグラム"),
    ),
    "basic-analysis-report": (
        VisualRequirement('class="report-chart', "独立した数値グラフ"),
        VisualRequirement('class="pictogram-grid', "分析サマリーのピクトグラム"),
    ),
    "cvr-improvement-plan": (
        VisualRequirement('class="pictogram-grid', "改善方針の要点ピクトグラム"),
    ),
}

_UNRESOLVED_VISUAL_RE = re.compile(r"<!--\s*(?:chart|pictograms):", re.IGNORECASE)
_UNPAIRED_CVR_PANEL_RE = re.compile(
    r'class="panel-title">([^<]*(?:CVR|CV率|コンバージョン率))</text>',
    re.IGNORECASE,
)


class VisualContractError(ValueError):
    """主要レポートの可視化完成条件を満たしていない。"""


def _is_saa_output(path: Path) -> bool:
    """``outputs/{client_id}/`` 配下の成果物だけをSAAの契約対象とする。"""
    resolved = path.resolve()
    for client_dir in resolved.parents:
        outputs_dir = client_dir.parent
        if outputs_dir.name.casefold() != "outputs":
            continue
        builder = outputs_dir.parent / "common" / "report_index" / "build_index.py"
        return builder.is_file()
    return False


def validate_visual_contract(input_path: Path, html: str) -> None:
    """主要レポートのHTML/PDF出力に必要な可視化が実際に描画されたか確認する。"""
    if _UNRESOLVED_VISUAL_RE.search(html):
        raise VisualContractError(
            f"{input_path.name} のHTML/PDF出力を中止しました。未変換の可視化指定が残っています。"
            "指定コメントの形式と、その直後の表を確認してください。"
        )
    if not _is_saa_output(input_path):
        return
    stem = input_path.stem.casefold()
    requirements = _REPORT_REQUIREMENTS.get(stem)
    if not requirements:
        return
    missing = [requirement.label for requirement in requirements if requirement.selector not in html]
    if missing:
        labels = "、".join(missing)
        raise VisualContractError(
            f"{input_path.name} のHTML/PDF出力を中止しました。必要な可視化がありません: {labels}。"
            "Markdownの可視化指定コメントと、その直後の表を確認してください。"
        )
    if stem == "basic-analysis-report":
        unpaired = _UNPAIRED_CVR_PANEL_RE.findall(html)
        if unpaired:
            labels = "、".join(dict.fromkeys(label.strip() for label in unpaired))
            raise VisualContractError(
                f"{input_path.name} のHTML/PDF出力を中止しました。CV数と二軸で重なっていない"
                f"CVRがあります: {labels}。件数列とCVR列のKPI名を揃えてください。"
            )
