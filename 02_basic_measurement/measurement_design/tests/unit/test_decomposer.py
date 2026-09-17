"""decomposer.py のユニットテスト."""
import json
from unittest.mock import patch


KPI = {
    "kpi_id": "kpi_001",
    "name": "資料ダウンロード数",
    "description": "コーポレートサイト経由の資料ダウンロード完了",
    "related_pages": [{"page_id": "page_download"}],
}

SCREEN_FLOW = {
    "pages": [
        {"page_id": "page_download", "name": "資料ダウンロードページ", "screen_type": "form", "url_pattern": "^/download"},
    ],
    "flows": [
        {"flow_id": "flow_dl", "name": "資料DL導線", "related_kpi": "kpi_001", "steps": [{"page_id": "page_download"}]},
    ],
}

# llm_client.complete_json が返す JSON 文字列（フェンス除去済み相当）
LLM_RESPONSE = """{
  "kpi_breakdown": {
    "kpi_id": "kpi_001",
    "required_events": [
      {
        "event_name": "file_download",
        "timing": "ダウンロードボタンクリック時",
        "page_ids": ["page_download"],
        "params": [
          {"name": "file_name", "type": "STRING", "source": "DOM"},
          {"name": "file_extension", "type": "STRING", "source": "DOM"}
        ],
        "rationale": "ダウンロード完了を計測"
      }
    ],
    "mcv_candidates": []
  }
}"""


def test_decompose_kpi_preserves_response_fields():
    from measurement_design.design.decomposer import decompose_kpi

    with patch("measurement_design.llm_client.complete_json", return_value=LLM_RESPONSE):
        result = decompose_kpi(KPI, SCREEN_FLOW, "naming rules", "fake-key")

    assert result == json.loads(LLM_RESPONSE)["kpi_breakdown"]


def test_decompose_kpi_handles_bad_json():
    from measurement_design.design.decomposer import decompose_kpi

    with patch("measurement_design.llm_client.complete_json", return_value="invalid json"):
        result = decompose_kpi(KPI, SCREEN_FLOW, "naming rules", "fake-key")

    assert result["kpi_id"] == "kpi_001"
    assert result.get("required_events") == []


def test_decompose_all_kpis_keeps_distinct_results_in_order():
    from measurement_design.design.decomposer import decompose_all_kpis

    second_kpi = {**KPI, "kpi_id": "kpi_002", "name": "お問い合わせ数"}
    second_response = {"kpi_breakdown": {
        "kpi_id": "kpi_002", "required_events": [{"event_name": "generate_lead"}],
        "mcv_candidates": [],
    }}
    with patch("measurement_design.llm_client.complete_json", side_effect=[
        LLM_RESPONSE, json.dumps(second_response),
    ]):
        result = decompose_all_kpis([KPI, second_kpi], SCREEN_FLOW, "naming rules", "fake-key")

    assert result == [json.loads(LLM_RESPONSE)["kpi_breakdown"], second_response["kpi_breakdown"]]
