"""イベント命名標準化モジュール."""

from __future__ import annotations

import json


def standardize_events(
    kpi_breakdowns: list[dict],
    review_data: dict,
    naming_conventions_md: str,
    reserved_words_md: str,
    api_key: str,
) -> list[dict]:
    """KPI分解結果のイベント名を命名規則・既存実装に合わせて標準化する."""
    from measurement_design.llm_client import complete_json

    all_events: list[dict] = []
    for breakdown in kpi_breakdowns:
        all_events.extend(breakdown.get("required_events", []))

    existing_events = [e["name"] for e in review_data.get("ga4", {}).get("events_observed", [])]

    prompt = f"""あなたはGA4計測設計のエキスパートです。
以下のKPI分解で提案されたイベント名を命名規則・既存実装と照合して標準化してください。

## 提案されたイベント
{json.dumps(all_events, ensure_ascii=False, indent=2)}

## 既存のGA4イベント (現在計測中)
{json.dumps(existing_events, ensure_ascii=False)}

## 命名規則 (抜粋)
{naming_conventions_md[:1500]}

## 予約語 (抜粋)
{reserved_words_md[:800]}

以下のJSON形式で回答してください:
{{
  "standardized_events": [
    {{
      "event_name": "最終確定イベント名",
      "aliases": ["旧候補名"],
      "params": [{{"name": "パラメータ名", "type": "STRING|INTEGER|FLOAT|BOOLEAN", "source": "dataLayer|URL|DOM|API"}}],
      "review_alignment": {{
        "existing_match": "既存イベント名 or null",
        "action": "use_existing | rename_existing | new"
      }},
      "standards_check": {{
        "naming": "pass | warning | fail",
        "reserved": "pass | conflict_resolved | fail"
      }}
    }}
  ]
}}"""

    try:
        raw = complete_json(prompt, model="claude-sonnet-4-6", max_tokens=2048, api_key=api_key)
        data = json.loads(raw)
        return data.get("standardized_events", [])
    except (json.JSONDecodeError, KeyError, Exception):
        return [{"event_name": e.get("event_name", ""), "params": e.get("params", [])} for e in all_events]
