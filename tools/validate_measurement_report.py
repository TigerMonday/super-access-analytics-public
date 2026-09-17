"""Validate the internal audit inventory and the minimal client report contract."""
from __future__ import annotations

import argparse
import ast
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "02_basic_measurement/measurement_design"

INTERNAL_MACHINE_COUNT = 37
INTERNAL_MANUAL_COUNT = 19

# This is the stable client-facing checklist. The broader 34 + 19 inventory is
# still run internally, but is not copied wholesale into the report.
PUBLIC_AUTOMATIC_ITEMS = (
    "拡張計測機能",
    "計測対象ホスト",
    "クロスドメイン設定",
    "除外する参照のリスト",
    "Google シグナル",
    "ユーザー提供データの収集",
    "イベントデータの保持",
    "現在の設定と定義",
    "モデルとルックバック期間",
    "Google広告とのリンク",
    "BigQueryとのリンク",
    "UA経由の計測継続性",
)

PUBLIC_MANUAL_ITEMS = (
    "Google タグの管理：ページ上の設定の重複インスタンスを無視します",
    "内部トラフィックの定義",
    "セッションのタイムアウト",
    "地域とデバイスに関する詳細なデータの収集",
    "Internal Traffic",
    "Search Console連携",
)

PUBLIC_SETTING_ITEMS = PUBLIC_AUTOMATIC_ITEMS + PUBLIC_MANUAL_ITEMS

_FORBIDDEN_PUBLIC_HEADINGS = (
    "KPIと計測イベントの対応",
    "パラメータ",
    "カスタム計測",
    "カスタムイベント",
    "指定期間の受信イベント",
    "現在計測されているイベント",
    "イベント棚卸し",
    "その他推奨設定事項",
)

_REPORT_TEMPLATE_PLACEHOLDERS = (
    "public_summary",
    "fixed_check_table",
    "findings_result",
    "findings_evidence",
    "roadmap_result",
    "roadmap_evidence",
    # Legacy placeholders stay in the validator so an old template cannot be
    # distributed silently. GTM variables such as {{event_name}} are valid
    # report evidence and therefore must not be rejected generically.
    "matrix_summary",
    "audit_matrix_table",
    "manual_check_table",
    "machine_item_count",
    "manual_item_count",
    "kpi_result",
    "kpi_evidence",
    "naming_result",
    "naming_evidence",
    "param_scope",
    "param_result",
    "param_evidence",
    "health_result",
    "health_evidence",
    "gtmcfg_result",
    "gtmcfg_evidence",
    "gtm_result",
    "gtm_evidence",
    "unresolved_evidence",
)


def _source_inventory() -> tuple[list[str], list[str]]:
    tree = ast.parse(
        (MODULE / "src/measurement_design/review/audit_matrix.py").read_text(encoding="utf-8")
    )
    machine: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == "ITEMS":
            machine = [ast.literal_eval(row.elts[1]) for row in node.value.elts]

    standard = (MODULE / "standards/audit-items.md").read_text(encoding="utf-8")
    try:
        manual_section = standard.split("## 目視で判定する", 1)[1].split("\n## ", 1)[0]
    except IndexError as exc:
        raise ValueError("目視監査項目の正本を読み取れません") from exc
    manual: list[str] = []
    for line in manual_section.splitlines():
        if line.startswith("| "):
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if cells[0] != "領域" and len(cells) >= 4:
                manual.append(cells[1])
    if not machine or not manual:
        raise ValueError("監査項目の正本を読み取れません")
    return machine, manual


def expected_internal_items() -> list[str]:
    """Return the complete inventory used by internal diagnostics."""
    machine, manual = _source_inventory()
    return machine + manual


def expected_items() -> list[str]:
    """Backward-compatible alias for callers that inspect the internal inventory."""
    return expected_internal_items()


def validate_internal_contract() -> list[str]:
    """Validate the source-of-truth inventory without requiring it in client copy."""
    machine, manual = _source_inventory()
    errors: list[str] = []
    if len(machine) != INTERNAL_MACHINE_COUNT:
        errors.append(
            f"内部監査の機械項目は{INTERNAL_MACHINE_COUNT}件必要（現在{len(machine)}件）"
        )
    if len(manual) != INTERNAL_MANUAL_COUNT:
        errors.append(
            f"内部監査の目視項目は{INTERNAL_MANUAL_COUNT}件必要（現在{len(manual)}件）"
        )
    all_items = machine + manual
    duplicates = sorted({item for item in all_items if all_items.count(item) > 1})
    if duplicates:
        errors.append("内部監査項目が重複しています: " + "、".join(duplicates))
    return errors


def _table_labels(text: str, items: tuple[str, ...] | list[str]) -> list[str]:
    labels: list[str] = []
    for line in text.splitlines():
        if line.startswith("|"):
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            labels.extend(cell for cell in cells if cell in items)
    return labels


def validate_public_report(
    text: str,
    items: tuple[str, ...] | list[str] | None = None,
) -> list[str]:
    """Validate only what a client-facing report must expose."""
    public_items = list(PUBLIC_SETTING_ITEMS if items is None else items)
    labels = _table_labels(text, public_items)
    errors: list[str] = []
    for item in public_items:
        count = labels.count(item)
        if count != 1:
            errors.append(f"{item}: 公開固定表に1回必要（現在{count}回）")

    required_header = "| カテゴリ | 確認項目 | 判定 | 結果 | 対応事項 |"
    if required_header not in text:
        errors.append("設定確認表は『カテゴリ／確認項目／判定／結果／対応事項』の5列にしてください")

    if items is None:
        manual_heading = "### 管理画面でまとめて目視確認"
        if manual_heading not in text:
            errors.append("APIで取得できない設定をまとめる目視確認ブロックがありません")
        else:
            automatic_section, manual_tail = text.split(manual_heading, 1)
            manual_section = manual_tail.split("\n## ", 1)[0]
            if "| 目視確認項目 | 確認すること |" not in manual_section:
                errors.append("目視確認ブロックは『目視確認項目／確認すること』の2列にしてください")
            for item in PUBLIC_MANUAL_ITEMS:
                if item in automatic_section:
                    errors.append(f"{item}: 自動判定表ではなく目視確認ブロックへまとめてください")
                if item not in manual_section:
                    errors.append(f"{item}: 目視確認ブロックに必要です")

    required_sections = {
        "異常のみの指摘": r"^#{2,3}\s+.*(?:要対応・要確認|異常|指摘)",
        "改善順": r"^#{2,3}\s+.*(?:改善順|改善ロードマップ)",
    }
    for label, pattern in required_sections.items():
        if not re.search(pattern, text, flags=re.MULTILINE):
            errors.append(f"公開レポートに必要な節がありません: {label}")

    for heading in _FORBIDDEN_PUBLIC_HEADINGS:
        suffix = r"(?:（[^\n]*）)?" if heading == "カスタムイベント" else ""
        if re.search(rf"^##+\s+(?:\d+\.\s*)?{re.escape(heading)}{suffix}\s*$", text, flags=re.MULTILINE):
            errors.append(f"公開本文から除外する節が残っています: {heading}")

    search_console_lines = [line for line in text.splitlines() if "Search Console" in line]
    if not search_console_lines:
        errors.append("Search Console連携の手動確認がありません")
    elif not any(
        any(term in line for term in ("手動", "目視", "管理画面", "未確認"))
        for line in search_console_lines
    ):
        errors.append("Search Console連携はAdmin APIの自動判定ではなく手動確認と明記してください")

    # A tag count alone is not evidence that tags should be consolidated. A
    # concrete grouping axis and variable/lookup design may still be proposed.
    for paragraph in re.split(r"\n\s*\n", text):
        count_only_proposal = re.search(
            r"タグ(?:数|が|は|を).{0,40}\d+\s*本.{0,100}(?:一本化|統合(?:する|を推奨|すべき))",
            paragraph,
        )
        has_concrete_design = any(
            term in paragraph for term in ("共通部分", "束ねる軸", "変数", "ルックアップ", "トリガー", "対応表")
        )
        if count_only_proposal and not has_concrete_design:
            errors.append("タグ本数だけを根拠にした一本化・統合提案があります")
            break

    for term in ("フォーム通過率", "フォーム完了率", "問い合わせ減", "BtoB平均", "市場縮小", "受注率", "目標達成率"):
        if term in text:
            errors.append(f"計測監査の範囲外の記述: {term}")
    if any(f"{{{{{name}}}}}" in text for name in _REPORT_TEMPLATE_PLACEHOLDERS):
        errors.append("未展開の監査テンプレートがあります")
    return errors


def validate(text: str, items: list[str] | tuple[str, ...] | None = None) -> list[str]:
    """Validate both contracts; ``items`` customizes public rows in tests/tools."""
    return validate_internal_contract() + validate_public_report(text, items)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    errors = validate(args.report.read_text(encoding="utf-8"))
    for error in errors:
        print(error)
    print(
        f"内部監査 {len(expected_internal_items())}件 / "
        f"公開自動確認 {len(PUBLIC_AUTOMATIC_ITEMS)}件 / 目視確認 {len(PUBLIC_MANUAL_ITEMS)}件 / "
        f"エラー {len(errors)}件"
    )
    return bool(errors)


if __name__ == "__main__":
    raise SystemExit(main())
