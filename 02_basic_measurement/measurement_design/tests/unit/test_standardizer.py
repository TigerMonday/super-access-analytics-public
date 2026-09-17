"""standardizer.py のユニットテスト."""
import json
from unittest.mock import patch


KPI_BREAKDOWNS = [
    {
        "kpi_id": "kpi_001",
        "required_events": [
            {
                "event_name": "file_download",
                "params": [{"name": "file_name", "type": "STRING", "source": "DOM"}],
            }
        ],
        "mcv_candidates": [],
    }
]

REVIEW_DATA = {
    "ga4": {
        "events_observed": [{"name": "file_download", "count": 50}],
        "key_events": [],
        "custom_definitions": {"dimensions": [], "metrics": []},
    }
}

LLM_RESPONSE = """{
  "standardized_events": [
    {
      "event_name": "file_download",
      "aliases": [],
      "params": [{"name": "file_name", "type": "STRING", "source": "DOM"}],
      "review_alignment": {"existing_match": "file_download", "action": "use_existing"},
      "standards_check": {"naming": "pass", "reserved": "pass"}
    }
  ]
}"""


def test_standardize_events_preserves_response_fields():
    from measurement_design.design.standardizer import standardize_events

    with patch("measurement_design.llm_client.complete_json", return_value=LLM_RESPONSE):
        result = standardize_events(KPI_BREAKDOWNS, REVIEW_DATA, "naming", "reserved", "fake-key")

    assert result == json.loads(LLM_RESPONSE)["standardized_events"]


def test_standardize_events_handles_bad_json():
    from measurement_design.design.standardizer import standardize_events

    with patch("measurement_design.llm_client.complete_json", return_value="bad json"):
        result = standardize_events(KPI_BREAKDOWNS, REVIEW_DATA, "naming", "reserved", "fake-key")

    assert result == [{
        "event_name": "file_download",
        "params": [{"name": "file_name", "type": "STRING", "source": "DOM"}],
    }]
