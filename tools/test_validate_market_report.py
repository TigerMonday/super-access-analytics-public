import json
import re

from validate_market_report import TEMPLATE, sections, validate


def report():
    summary = "<!-- pictograms: insight,analysis,target -->\n| 要点 | 違い | 次の判断 |\n|---|---|---|\n| A | B | C |"
    bodies = {}
    for heading, _ in sections(TEMPLATE.read_text(encoding="utf-8")):
        bodies[heading] = "具体的な確認結果。"
        if heading in {
            "市場", "顧客", "競合・代替手段", "自社", "自社が選ばれる理由",
            "顧客像の整理", "分析から導く示唆",
        }:
            bodies[heading] += "\n\n| 比較軸 | 結果 |\n|---|---|\n| A | B |"
    bodies["カスタマージャーニー"] = (
        "推定です。\n\n### 顧客像A\n\n"
        "| 観点 | 日常 | 課題発生 | 調査 | 検討 | 相談 |\n"
        "|---|---|---|---|---|---|\n"
        "| 状況・行動 | A | B | C | D | E |\n"
        "| 認識 | A | B | C | D | E |\n"
        "| 障壁 | A | B | C | D | E |\n"
        "| 次へ進むきっかけ | A | B | C | D | E |"
    )
    return summary + "\n\n" + "\n\n".join(f"## {h}\n{bodies[h]}" for h, _ in sections(TEMPLATE.read_text(encoding="utf-8")))


def test_valid():
    assert not validate(report())


def valid_intake():
    response = {"status": "confirmed", "source": "user_reply", "value": "確認済み"}
    return {
        "schema_version": 1,
        "responses": {
            name: dict(response)
            for name in (
                "decision_purpose", "target_scope", "research_period", "output_format",
                "source_requirements", "existing_materials", "priority_customer",
                "customer_voice", "why_chosen", "why_not_chosen", "service_limits",
            )
        },
        "competitors": {
            "status": "confirmed",
            "source": "user_reply",
            "selection_mode": "agent_proposed_confirmed",
            "user_response": "候補Aで確認済み",
            "items": [{
                "name": "候補A",
                "official_url": "https://example.com/",
                "selection_reason": "提供領域が重なる",
            }],
        },
    }


def write_report_with_intake(tmp_path, intake=None):
    report_path = tmp_path / "00_3c_persona_journey_report.md"
    report_path.write_text(report(), encoding="utf-8")
    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)
    if intake is not None:
        (data_dir / "research-intake.json").write_text(
            json.dumps(intake, ensure_ascii=False), encoding="utf-8"
        )
    return report_path


def test_cli_validation_requires_intake(tmp_path):
    report_path = write_report_with_intake(tmp_path)
    assert any("事前確認記録" in error for error in validate(report(), report_path))


def test_confirmed_intake_is_valid(tmp_path):
    report_path = write_report_with_intake(tmp_path, valid_intake())
    assert not validate(report(), report_path)


def test_period_and_source_requirements_may_use_workflow_defaults(tmp_path):
    intake = valid_intake()
    for field in ("research_period", "source_requirements"):
        intake["responses"][field] = {
            "status": "default_applied",
            "source": "workflow_default",
            "value": "標準条件",
        }
    report_path = write_report_with_intake(tmp_path, intake)
    assert not validate(report(), report_path)

    intake["responses"]["why_chosen"] = {
        "status": "default_applied",
        "source": "workflow_default",
        "value": "公開情報から推定",
    }
    report_path = write_report_with_intake(tmp_path, intake)
    assert any("標準値を自動適用できない項目です: why_chosen" in error for error in validate(report(), report_path))


def test_not_asked_is_distinct_from_awaiting_reply(tmp_path):
    intake = valid_intake()
    intake["competitors"]["status"] = "not_asked"
    intake["responses"]["why_chosen"]["status"] = "not_asked"
    report_path = write_report_with_intake(tmp_path, intake)
    errors = validate(report(), report_path)
    assert any("競合候補をまだ利用者へ質問していません" in error for error in errors)
    assert any("まだ質問していません: why_chosen" in error for error in errors)

    intake["competitors"]["status"] = "awaiting_reply"
    intake["competitors"]["asked_at"] = "2026-09-17"
    intake["responses"]["why_chosen"]["status"] = "awaiting_reply"
    intake["responses"]["why_chosen"]["asked_at"] = "2026-09-17"
    report_path = write_report_with_intake(tmp_path, intake)
    errors = validate(report(), report_path)
    assert any("競合候補は質問済みですが回答待ち" in error for error in errors)
    assert any("回答待ちです: why_chosen" in error for error in errors)
    assert not any("質問日の記録がありません" in error for error in errors)


def test_internal_caveat_must_be_note_or_limits():
    text = report().replace(
        "具体的な確認結果。",
        "顧客の実際の声は未取得である。",
        1,
    )
    assert any("内部的な留保" in error for error in validate(text))
    noted = text.replace(
        "顧客の実際の声は未取得である。",
        "<small>※ 顧客の実際の声は未取得である。</small>",
        1,
    )
    assert not any("内部的な留保" in error for error in validate(noted))


def test_missing_duplicate_order_and_rename():
    for text in [report().replace("## 市場\n", ""), report() + "\n## 市場\n追加", report().replace("## 市場", "## TEMP").replace("## 顧客\n", "## 市場\n").replace("## TEMP", "## 顧客"), report().replace("## 自社が選ばれる理由", "## 勝ち筋")]:
        assert validate(text)


def test_empty_and_template():
    empty_market = re.sub(r"(?ms)^## 市場\s*$.*?(?=^## 顧客\s*$)", "## 市場\n\n", report())
    assert validate(empty_market)
    assert validate(TEMPLATE.read_text(encoding="utf-8"))


def test_fenced_headings_do_not_count():
    assert validate("```markdown\n" + report() + "\n```")


def test_missing_pictogram_summary_is_invalid():
    assert validate(report().replace("<!-- pictograms: insight,analysis,target -->", ""))


def test_text_only_core_section_is_invalid():
    text = report().replace("| 比較軸 | 結果 |\n|---|---|\n| A | B |", "文章だけです。", 1)
    assert any("表" in error for error in validate(text))


def test_journey_requires_persona_table():
    text = report().replace("### 顧客像A", "#### 顧客像A")
    assert any("小見出し" in error for error in validate(text))
