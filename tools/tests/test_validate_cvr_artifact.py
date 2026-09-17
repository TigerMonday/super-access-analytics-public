from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import validate_cvr_artifact as validator  # noqa: E402


VALID = """# 改善案

## 使った前提
| 入力 | 状態 |
|---|---|
| 計測チェック | 使用 |
| 基本分析 | 使用 |
| 市場・顧客理解 | 使用 |

`barrier_id: persona_001_research_b1`
`stimulus_id: persona_001_research_s1`
"""


def test_valid_artifact_passes():
    assert validator.validate_text(VALID) == []


def test_client_report_must_start_with_conclusion():
    assert validator.validate_text("# Report\n\n## 根拠\nデータ\n\n## 結論\n結論", client_facing=True)
    assert validator.validate_text("# Report\n\n## 改善方針\n<!-- pictograms: issue,target,growth -->\n| 課題 | 施策 | 変化 |\n|---|---|---|\n| A | B | C |", client_facing=True) == []


def test_requires_premise_as_first_h2():
    text = VALID.replace("## 使った前提", "## 結論\n\n## 使った前提")
    assert any("最初のH2" in error for error in validator.validate_text(text))


def test_premise_rows_must_be_inside_premise_section():
    text = VALID.replace("| 基本分析 | 使用 |\n", "")
    text = text.replace(
        "`barrier_id: persona_001_research_b1`",
        "## 分析結果\n基本分析\n\n`barrier_id: persona_001_research_b1`",
    )
    assert any("基本分析" in error for error in validator.validate_text(text))


def test_explicit_no_match_is_accepted():
    text = VALID.replace("`barrier_id: persona_001_research_b1`", "対応する障壁は見当たらない")
    text = text.replace("`stimulus_id: persona_001_research_s1`", "対応する刺激は見当たらない")
    assert validator.validate_text(text) == []


CLIENT_REPORT = """# サイト改善レポート

## 結論

<!-- pictograms: issue,target,growth -->
| 改善課題 | 優先施策 | 期待する変化 |
|---|---|---|
| 判断材料が不足 | 判断材料を追加 | 相談前の不安を減らす |

相談前に判断材料を示す。

## 根拠と範囲

計測チェック、基本分析、市場・顧客理解を参照した。
"""


def test_client_facing_report_hides_internal_scaffolding():
    assert validator.validate_text(CLIENT_REPORT, client_facing=True) == []


def test_client_facing_report_requires_pictogram_summary():
    text = CLIENT_REPORT.replace("<!-- pictograms: issue,target,growth -->", "")
    assert any("ピクトグラム" in error for error in validator.validate_text(text, client_facing=True))


def test_client_facing_report_rejects_internal_ids_and_premise_heading():
    text = CLIENT_REPORT.replace("## 結論", "## 使った前提") + "\nbarrier_id: b1\n"
    errors = validator.validate_text(text, client_facing=True)
    assert any("使った前提" in error for error in errors)
    assert any("内部ID" in error for error in errors)


def test_client_facing_report_rejects_progress_confirmation_section():
    text = CLIENT_REPORT + "\n## 個別ページ改善へ進む前の確認\n\nこの全体方針を確認いただいた後、次工程へ進みます。\n"
    errors = validator.validate_text(text, client_facing=True)
    assert any("確認待ち" in error and "チャット" in error for error in errors)
