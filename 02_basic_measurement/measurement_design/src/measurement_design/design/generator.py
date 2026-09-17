"""計測設計書 章生成モジュール."""

from __future__ import annotations

import json
from pathlib import Path

HAIKU_CHAPTER_NUMS = frozenset([1, 2, 3, 5, 9, 10, 14, 15, 16])

# LLM プロンプトに埋め込む一覧系データの安全上限。
# GA4/GTM から正しく全件取得できていても、この件数を超える極端なケースで
# プロンプトサイズ（claude -p の argv 渡し）が膨れすぎないための保険であり、
# 通常のプロパティ規模（イベント/タグとも数件〜100件程度）では発動しない値にする。
# 「抜粋」目的で小さく切り詰めていた旧実装（kpis[:3] / standardized_events[:5]）が
# GA4イベント設定・GTM変数のほとんどを章生成プロンプトから欠落させていたバグの修正。
_PROMPT_LIST_CAP = 200


def _capped(items: list, cap: int = _PROMPT_LIST_CAP) -> tuple[list, int]:
    """一覧を上限件数に丸め、(丸めた一覧, 元の件数) を返す。"""
    items = items or []
    return items[:cap], len(items)


def _findings_block(context: dict) -> str:
    """人が確定させた所見をプロンプトに載せる。

    章生成はデータセットしか見ないため、調査で判明した因果関係を知らない。
    その結果、似た名前のイベント（`signup` と `sign_up` 等）を取り違えたり、
    人が出した結論と逆の推奨を書くことがある（実際の案件で発生した）。
    確定所見（`context["findings"]`、`measurement_design.review.findings.load_findings`
    が読み出す `docs/findings.md` 等）を渡して、それを最優先の制約にする。
    """
    findings = (context.get("findings") or "").strip()
    if not findings:
        return (
            "（未整備）確定所見のファイルが無い。`docs/findings.md` に「原因まで特定できた事項」を"
            "置くと、生成物が実測と矛盾しなくなる。今回は根拠データだけから判断すること。"
        )
    return findings


CHAPTER_FILENAMES = {
    1: "01-cover",
    2: "02-basic-settings",
    3: "03-account-property",
    4: "04-cv-mcv",
    5: "05-internal-traffic",
    6: "06-event-config",
    7: "07-variables",
    8: "08-ecommerce-main",
    9: "09-ecommerce-lp",
    10: "10-content-groups",
    11: "11-event-tracking-cta",
    12: "12-event-tracking-general",
    13: "13-event-tracking-spec",
    14: "14-data-import",
    15: "15-audiences",
    16: "16-linked-tools",
}


def generate_chapter(
    chapter_num: int,
    template_path: Path,
    context: dict,
    api_key: str,
) -> str:
    """1章分をLLMで生成する."""
    from measurement_design.llm_client import complete_text

    model = "claude-haiku-4-5-20251001" if chapter_num in HAIKU_CHAPTER_NUMS else "claude-sonnet-4-6"
    template = template_path.read_text(encoding="utf-8") if template_path.exists() else f"# 章 {chapter_num}\n{{{{内容}}}}"

    review_data = context.get("review_data") or {}
    ga4 = review_data.get("ga4") or {}
    gtm = review_data.get("gtm") or {}

    kpis, kpis_total = _capped(context.get("kpis", []))
    events, events_total = _capped(context.get("standardized_events", []))
    observed, observed_total = _capped(ga4.get("events_observed", []))
    gtm_tags, gtm_tags_total = _capped(gtm.get("tags_detail", []))

    prompt = f"""あなたはGA4/GTM計測設計のエキスパートです。
以下のテンプレートとコンテキストを使って計測設計書の章 {chapter_num} を生成してください。

## クライアント情報
- クライアント名: {context.get('client_name', '')}
- プロパティ名: {ga4.get('property', {}).get('name', '')}

## 確定している事実（最優先の制約。他の情報と矛盾する場合はこれを優先すること）
{_findings_block(context)}

## KPI情報（全 {kpis_total} 件）
{json.dumps(kpis, ensure_ascii=False, indent=2)}

## 設計イベント（全 {events_total} 件。KPIから分解・命名標準化されたイベント）
{json.dumps(events, ensure_ascii=False, indent=2)}

## GA4 既存イベント（実測・直近30日、全 {observed_total} 件）
{json.dumps(observed, ensure_ascii=False)}

## GA4 カスタムディメンション・カスタム指標（登録済み）
{json.dumps(ga4.get('custom_definitions', {}), ensure_ascii=False)}

## GTM 実装（コンテナ内タグ・発火イベント名・パラメータ、全 {gtm_tags_total} 件）
{json.dumps(gtm_tags, ensure_ascii=False)}

## テンプレート
{template}

指示:
- 上記の「GA4 既存イベント」「GTM 実装」は全件のGA4/GTM設定を反映したものです。イベント一覧・変数一覧は一部の抜粋で済ませず、渡された全件を反映してください
- {{{{...}}}}プレースホルダをすべて埋めるか削除してください
- 章ヘッダー (# 章 NN:...) は変更しないでください
- 日本語で記述してください"""

    return complete_text(prompt, model=model, max_tokens=3000, api_key=api_key)


def save_chapter(chapter_num: int, content: str, design_doc_dir: Path) -> Path:
    """章をファイルに保存する."""
    design_doc_dir.mkdir(parents=True, exist_ok=True)
    filename = CHAPTER_FILENAMES.get(chapter_num, f"{chapter_num:02d}-chapter")
    out = design_doc_dir / f"{filename}.md"
    out.write_text(content, encoding="utf-8")
    return out


def generate_all_chapters(
    selected_chapters: list[int],
    templates_dir: Path,
    context: dict,
    api_key: str,
    design_doc_dir: Path,
) -> list[Path]:
    """選定された全章を生成・保存してPathリストを返す."""
    saved = []
    for num in selected_chapters:
        filename = CHAPTER_FILENAMES.get(num, f"{num:02d}-chapter")
        template_path = templates_dir / f"{filename}.template.md"
        try:
            content = generate_chapter(num, template_path, context, api_key)
            path = save_chapter(num, content, design_doc_dir)
            saved.append(path)
            print(f"  章 {num:02d} 生成完了: {path.name}")
        except Exception as e:
            print(f"  章 {num:02d} 生成失敗: {e}")
    return saved
