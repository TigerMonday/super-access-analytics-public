"""Validate the fixed market/customer report structure before distribution."""
from pathlib import Path
import argparse
import json
import re

TEMPLATE = Path(__file__).resolve().parents[1] / "03_external_research/web_research/market-report-template.md"
TABLE_RE = re.compile(r"(?:^\|.*\|[ \t]*\n?){2,}", re.M)
TABLE_REQUIRED_SECTIONS = (
    "市場", "顧客", "競合・代替手段", "自社", "自社が選ばれる理由",
    "顧客像の整理", "カスタマージャーニー", "分析から導く示唆",
)

INTAKE_FILENAME = "research-intake.json"
FINAL_INTAKE_STATUSES = {"confirmed", "not_available", "not_applicable", "default_applied"}
INTAKE_SOURCES = {"user_request", "user_reply", "saved_context", "workflow_default"}
DEFAULTABLE_INTAKE_FIELDS = {"research_period", "source_requirements"}
REQUIRED_INTAKE_FIELDS = (
    "decision_purpose",
    "target_scope",
    "research_period",
    "output_format",
    "source_requirements",
    "existing_materials",
    "priority_customer",
    "customer_voice",
    "why_chosen",
    "why_not_chosen",
    "service_limits",
)
INTERNAL_CAVEAT_PATTERNS = (
    "顧客の実際の声は未取得",
    "成功事例の選択標本",
    "会社側仮説であり",
    "確認済み顧客ではない",
)


def sections(text):
    # Ignore fenced examples, which cannot satisfy actual report headings.
    text = re.sub(r"(?ms)^(`{3,}|~{3,})[^\n]*\n.*?^\1\s*$", "", text)
    matches = list(re.finditer(r"(?m)^## (.+?)\s*$", text))
    return [(m.group(1), text[m.end():matches[i + 1].start() if i + 1 < len(matches) else len(text)].strip()) for i, m in enumerate(matches)]


def tables(text):
    result = []
    for block in TABLE_RE.findall(text):
        rows = [
            [cell.strip() for cell in line.strip().strip("|").split("|")]
            for line in block.strip().splitlines()
        ]
        if len(rows) >= 2:
            result.append(rows)
    return result


def _validate_intake(report_path: Path):
    """Validate the private, user-confirmed pre-research intake record."""
    intake_path = report_path.parent / "data" / INTAKE_FILENAME
    if not intake_path.exists():
        return [f"事前確認記録がありません: data/{INTAKE_FILENAME}"]
    try:
        data = json.loads(intake_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"事前確認記録を読めません: {exc}"]

    errors = []
    if data.get("schema_version") != 1:
        errors.append("事前確認記録の schema_version は1にしてください")

    responses = data.get("responses")
    if not isinstance(responses, dict):
        errors.append("事前確認記録に responses がありません")
        responses = {}
    for field in REQUIRED_INTAKE_FIELDS:
        item = responses.get(field)
        if not isinstance(item, dict):
            errors.append(f"事前確認がありません: {field}")
            continue
        status = item.get("status")
        if status == "not_asked":
            errors.append(f"事前確認をまだ質問していません: {field}")
            continue
        if status == "awaiting_reply":
            if not str(item.get("asked_at", "")).strip():
                errors.append(f"質問済み状態ですが質問日の記録がありません: {field}")
            errors.append(f"事前確認は質問済みですが回答待ちです: {field}")
            continue
        if status not in FINAL_INTAKE_STATUSES:
            errors.append(f"事前確認の状態が不正です: {field}（status={status or '未設定'}）")
            continue
        if item.get("source") not in INTAKE_SOURCES:
            errors.append(f"回答または標準値の出所がありません: {field}")
        if item.get("source") == "workflow_default" and (
            field not in DEFAULTABLE_INTAKE_FIELDS or status != "default_applied"
        ):
            errors.append(f"標準値を自動適用できない項目です: {field}")
        if status == "default_applied" and item.get("source") != "workflow_default":
            errors.append(f"標準値適用の出所は workflow_default にしてください: {field}")
        if not str(item.get("value", "")).strip():
            errors.append(f"事前確認の回答内容が空です: {field}")

    competitors = data.get("competitors")
    if not isinstance(competitors, dict):
        errors.append("競合確認記録がありません: competitors")
        return errors
    competitor_status = competitors.get("status")
    if competitor_status == "not_asked":
        errors.append("競合候補をまだ利用者へ質問していません")
        return errors
    if competitor_status == "awaiting_reply":
        if not str(competitors.get("asked_at", "")).strip():
            errors.append("競合候補は質問済み状態ですが質問日の記録がありません")
        errors.append("競合候補は質問済みですが回答待ちです")
        return errors
    if competitor_status not in {"confirmed", "not_applicable"}:
        errors.append("競合確認の状態が不正です")
        return errors
    if competitors.get("source") not in INTAKE_SOURCES:
        errors.append("競合確認に利用者回答または保存済み前提の出所がありません")
    if competitors.get("selection_mode") not in {
        "user_specified", "agent_proposed_confirmed", "no_named_competitors"
    }:
        errors.append("競合確認の selection_mode が不正です")
    if not str(competitors.get("user_response", "")).strip():
        errors.append("競合候補に対する利用者回答が空です")
    if competitors.get("status") == "confirmed":
        items = competitors.get("items")
        if not isinstance(items, list) or not items:
            errors.append("確認済み競合が1社もありません")
        else:
            for index, item in enumerate(items, start=1):
                if not isinstance(item, dict):
                    errors.append(f"競合{index}の記録形式が不正です")
                    continue
                for key in ("name", "official_url", "selection_reason"):
                    if not str(item.get(key, "")).strip():
                        errors.append(f"競合{index}に {key} がありません")
    return errors


def _validate_caveat_placement(text):
    """Keep internal methodology caveats out of client-facing analysis prose."""
    errors = []
    in_limits = False
    for line_no, line in enumerate(text.splitlines(), start=1):
        if line.startswith("## "):
            in_limits = line.strip() == "## 調査方法と限界"
        stripped = line.strip()
        if in_limits or not stripped or stripped.startswith("|") or stripped.startswith("<small>"):
            continue
        for pattern in INTERNAL_CAVEAT_PATTERNS:
            if pattern in stripped:
                errors.append(
                    f"内部的な留保は表下の<small>注記か「調査方法と限界」へ移してください"
                    f"（{line_no}行: {pattern}）"
                )
    return errors


def validate(text, report_path=None):
    template = sections(TEMPLATE.read_text(encoding="utf-8"))
    actual = sections(text)
    errors = []
    if not re.search(r"<!--\s*pictograms:\s*insight\s*,\s*analysis\s*,\s*target\s*-->", text, re.IGNORECASE):
        errors.append("表紙直後の要点ピクトグラム指定がありません")
    if [h for h, _ in actual] != [h for h, _ in template]:
        errors.append("固定8項目＋調査方法と限界の見出し・順序が不一致（欠落・重複・改名・追加を確認）")
    instructions = dict(template)
    actual_sections = dict(actual)
    for heading, body in actual:
        if not body or not re.sub(r"(?m)^#{3,} .*?$", "", body).strip():
            errors.append(f"空の章: {heading}")
        if instructions.get(heading) and instructions[heading] in body:
            errors.append(f"テンプレートの執筆指示が残存: {heading}")
    for heading in TABLE_REQUIRED_SECTIONS:
        if heading in actual_sections and not tables(actual_sections[heading]):
            errors.append(f"比較表またはジャーニー表がない章: {heading}")

    journey = actual_sections.get("カスタマージャーニー", "")
    persona_matches = list(re.finditer(r"(?m)^###\s+(.+?)\s*$", journey))
    if journey and not persona_matches:
        errors.append("カスタマージャーニーに顧客像ごとの小見出しがありません")
    for index, match in enumerate(persona_matches):
        end = persona_matches[index + 1].start() if index + 1 < len(persona_matches) else len(journey)
        persona_name = match.group(1)
        persona_tables = tables(journey[match.end():end])
        if not persona_tables:
            errors.append(f"カスタマージャーニー表がありません: {persona_name}")
            continue
        rows = persona_tables[0]
        header = rows[0]
        if len(header) != 6 or header[0] != "観点":
            errors.append(f"ジャーニー表は観点＋5段階の6列にします: {persona_name}")
        row_labels = {row[0] for row in rows[2:] if row}
        required_labels = {"状況・行動", "認識", "障壁", "次へ進むきっかけ"}
        if not required_labels.issubset(row_labels):
            errors.append(f"ジャーニー表の4観点が不足しています: {persona_name}")
        for row in rows[2:]:
            for cell in row[1:]:
                plain = re.sub(r"!?\[([^]]*)\]\([^)]*\)", r"\1", cell)
                if len(plain) > 60:
                    errors.append(f"ジャーニー表のセルが長すぎます（60字超）: {persona_name}")
                    break
    errors.extend(_validate_caveat_placement(text))
    if report_path is not None:
        errors.extend(_validate_intake(Path(report_path)))
    return errors


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    errors = validate(args.report.read_text(encoding="utf-8-sig"), report_path=args.report)
    print("\n".join(errors) if errors else "市場・顧客理解の固定構成: OK")
    raise SystemExit(bool(errors))
