"""KPI → 必要イベント分解モジュール."""

from __future__ import annotations

import json


def decompose_kpi(
    kpi: dict,
    screen_flow: dict,
    naming_conventions_md: str,
    api_key: str,
) -> dict:
    """KPI 1件を必要なGA4イベント・パラメータに分解する (LLM使用)."""
    from measurement_design.llm_client import complete_json

    related_page_ids = [p.get("page_id", "") for p in kpi.get("related_pages", [])]
    related_pages = [
        p for p in screen_flow.get("pages", [])
        if p.get("page_id", "") in related_page_ids
    ]
    related_flows = [
        f for f in screen_flow.get("flows", [])
        if f.get("related_kpi") == kpi.get("kpi_id")
    ]

    prompt = f"""あなたはGA4計測設計のエキスパートです。
以下のKPIを達成するために必要なGA4イベントとパラメータを特定してください。

## KPI
{json.dumps(kpi, ensure_ascii=False, indent=2)}

## 関連ページ
{json.dumps(related_pages, ensure_ascii=False, indent=2)}

## 関連フロー
{json.dumps(related_flows, ensure_ascii=False, indent=2)}

## 命名規則 (抜粋)
{naming_conventions_md[:1500]}

以下のJSON形式で回答してください:
{{
  "kpi_breakdown": {{
    "kpi_id": "{kpi.get('kpi_id', '')}",
    "required_events": [
      {{
        "event_name": "イベント名(snake_case)",
        "timing": "計測タイミングの説明",
        "page_ids": ["page_id"],
        "params": [
          {{"name": "パラメータ名", "type": "STRING|INTEGER|FLOAT|BOOLEAN", "source": "dataLayer|URL|DOM|API"}}
        ],
        "rationale": "なぜ必要か"
      }}
    ],
    "mcv_candidates": []
  }}
}}"""

    try:
        raw = complete_json(prompt, model="claude-sonnet-4-6", max_tokens=2048, api_key=api_key)
        data = json.loads(raw)
        return data.get("kpi_breakdown", {"kpi_id": kpi.get("kpi_id", ""), "required_events": [], "mcv_candidates": []})
    except (json.JSONDecodeError, KeyError, Exception):
        return {"kpi_id": kpi.get("kpi_id", ""), "required_events": [], "mcv_candidates": []}


def decompose_all_kpis(
    kpis: list[dict],
    screen_flow: dict,
    naming_conventions_md: str,
    api_key: str,
) -> list[dict]:
    """全KPIを分解してリストを返す."""
    return [decompose_kpi(kpi, screen_flow, naming_conventions_md, api_key) for kpi in kpis]
