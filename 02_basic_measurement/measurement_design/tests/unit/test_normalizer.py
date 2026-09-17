"""normalizer.py のユニットテスト."""
import json
import pytest
from pathlib import Path

FIXTURES = Path(__file__).parent.parent / "fixtures"





def test_build_review_data_property_fields():
    from measurement_design.review.normalizer import build_review_data
    result = build_review_data(FIXTURES)
    assert result["ga4"]["property"]["id"] == "123456789"
    assert result["ga4"]["property"]["name"] == "テストサイト"
    assert result["ga4"]["property"]["data_streams"][0]["web_stream_data"]["measurement_id"] == "G-XXXXXXXX"


def test_build_review_data_events_observed():
    from measurement_design.review.normalizer import build_review_data
    result = build_review_data(FIXTURES)
    events = result["ga4"]["events_observed"]
    names = [e["name"] for e in events]
    assert "page_view" in names
    assert "purchase" in names


def test_build_review_data_keeps_full_event_counts_separate_from_top_100(tmp_path):
    from measurement_design.review.normalizer import build_review_data

    phase1 = {"property": {"name": "properties/1"}, "key_events": []}
    phase2 = {
        "events_30d": [{"eventName": "page_view", "eventCount": "1000"}],
        "event_name_counts_30d": [
            {"eventName": "page_view", "eventCount": "1000"},
            {"eventName": "rare_conversion", "eventCount": "1"},
        ],
        "event_name_counts_status": "complete",
    }
    (tmp_path / "phase1.json").write_text(json.dumps(phase1), encoding="utf-8")
    (tmp_path / "phase2.json").write_text(json.dumps(phase2), encoding="utf-8")

    ga4 = build_review_data(tmp_path)["ga4"]

    assert ga4["events_observed"] == [{"name": "page_view", "count": 1000}]
    assert {row["name"] for row in ga4["event_counts_all"]} == {"page_view", "rare_conversion"}
    assert ga4["event_counts_status"] == "complete"


def test_build_review_data_marks_legacy_event_counts_missing(tmp_path):
    from measurement_design.review.normalizer import build_review_data

    (tmp_path / "phase1.json").write_text(
        json.dumps({"property": {"name": "properties/1"}, "key_events": []}), encoding="utf-8"
    )
    (tmp_path / "phase2.json").write_text(
        json.dumps({"events_30d": [{"eventName": "page_view", "eventCount": "1000"}]}),
        encoding="utf-8",
    )

    ga4 = build_review_data(tmp_path)["ga4"]

    assert ga4["event_counts_all"] == []
    assert ga4["event_counts_status"] == "missing"


def test_build_review_data_key_events():
    from measurement_design.review.normalizer import build_review_data
    result = build_review_data(FIXTURES)
    key_event_names = result["ga4"]["key_events"]
    assert "purchase" in key_event_names
    assert "FormSubmit" in key_event_names


def test_build_review_data_custom_dimensions():
    from measurement_design.review.normalizer import build_review_data
    result = build_review_data(FIXTURES)
    dims = result["ga4"]["custom_definitions"]["dimensions"]
    assert len(dims) == 1
    assert dims[0]["parameter_name"] == "user_type"


def test_build_review_data_missing_phase1_raises():
    from measurement_design.review.normalizer import build_review_data
    with pytest.raises(FileNotFoundError):
        build_review_data(Path("/nonexistent"))


def test_build_review_data_no_gtm_when_phase3_missing():
    from measurement_design.review.normalizer import build_review_data
    result = build_review_data(FIXTURES)
    assert result.get("gtm") is None


def test_build_review_data_gtm_section_when_phase3_exists(tmp_path):
    from measurement_design.review.normalizer import build_review_data
    import json

    phase1 = {
        "property": {
            "name": "properties/123456789",
            "display_name": "テストサイト",
            "time_zone": "Asia/Tokyo",
            "currency_code": "JPY"
        },
        "custom_dimensions": [],
        "custom_metrics": [],
        "key_events": []
    }

    phase2 = {
        "events_30d": []
    }

    phase3 = {
        "tags": [
            {"name": "GA4 タグ", "tagId": "1"},
            {"name": "ダミータグ", "tagId": "2"}
        ],
        "triggers": [
            {"name": "ページビュー", "triggerId": "t1"},
            {"name": "未使用トリガー", "triggerId": "t2"}
        ],
        "variables": [
            {"name": "変数1", "variableId": "v1"}
        ],
        "tag_analysis": [
            {
                "name": "GA4 タグ",
                "firing_trigger_ids": ["t1"],
                "ga4_event": {"event_name": "page_view"}
            }
        ]
    }

    (tmp_path / "phase1.json").write_text(json.dumps(phase1), encoding="utf-8")
    (tmp_path / "phase2.json").write_text(json.dumps(phase2), encoding="utf-8")
    (tmp_path / "phase3.json").write_text(json.dumps(phase3), encoding="utf-8")

    result = build_review_data(tmp_path)

    assert "gtm" in result
    assert result["gtm"]["container"]["counts"]["tags"] == 2
    assert result["gtm"]["container"]["counts"]["triggers"] == 2
    assert result["gtm"]["container"]["counts"]["variables"] == 1
    assert len(result["gtm"]["ga4_event_tags"]) == 1
    assert result["gtm"]["ga4_event_tags"][0]["event_name"] == "page_view"
    assert "ダミータグ" in result["gtm"]["orphans"]["tags_without_trigger"]
    assert "未使用トリガー" in result["gtm"]["orphans"]["triggers_without_tag"]


def test_build_review_data_gtm_tags_detail(tmp_path):
    """phase3.json から tags_detail（paused・params・トリガーID）が構築される."""
    from measurement_design.review.normalizer import build_review_data

    phase1 = {"property": {"name": "properties/1", "display_name": "T"}}
    phase3 = {
        "tags": [
            {
                "name": "GA4 購入 店舗A",
                "type": "gaawe",
                "paused": False,
                "firingTriggerId": ["10"],
                "blockingTriggerId": [],
                "parameter": [
                    {"type": "TEMPLATE", "key": "eventName", "value": "purchase"},
                    {"type": "TEMPLATE", "key": "send_to", "value": "AW-111/storeA"},
                    {"type": "LIST", "key": "eventSettingsTable", "list": []},
                ],
            },
            {
                "name": "旧_GA4購入タグ",
                "type": "gaawe",
                "paused": True,
                "firingTriggerId": ["10"],
                "blockingTriggerId": [],
                "parameter": [
                    {"type": "TEMPLATE", "key": "eventName", "value": "purchase"},
                ],
            },
        ],
        "triggers": [{"triggerId": "10", "name": "購入完了"}],
        "variables": [{"name": "DLV - store_id"}],
        "tag_analysis": [
            {"name": "GA4 購入 店舗A", "type": "gaawe",
             "type_label": "GA4 イベントタグ", "firing_trigger_ids": ["10"],
             "ga4_event": {"event_name": "purchase"}},
            {"name": "旧_GA4購入タグ", "type": "gaawe",
             "type_label": "GA4 イベントタグ", "firing_trigger_ids": ["10"]},
        ],
    }
    (tmp_path / "phase1.json").write_text(json.dumps(phase1), encoding="utf-8")
    (tmp_path / "phase3.json").write_text(json.dumps(phase3), encoding="utf-8")

    result = build_review_data(tmp_path)
    detail = result["gtm"]["tags_detail"]
    assert len(detail) == 2

    by_name = {t["name"]: t for t in detail}
    active = by_name["GA4 購入 店舗A"]
    paused = by_name["旧_GA4購入タグ"]

    assert active["paused"] is False
    assert paused["paused"] is True
    assert active["type"] == "gaawe"
    assert active["type_label"] == "GA4 イベントタグ"
    assert active["event_name"] == "purchase"
    assert active["firing_trigger_ids"] == ["10"]
    assert active["firing_trigger_names"] == ["購入完了"]
    assert active["destination"] == ""
    # スカラー params は残り、LIST/MAP は除外される
    assert active["params"]["send_to"] == "AW-111/storeA"
    assert "eventSettingsTable" not in active["params"]


def test_ga4_event_inventory_keeps_trigger_and_destination_context(tmp_path):
    """イベントの用途説明に必要なタグ・トリガー・送信先を正規化後も残す。"""
    from measurement_design.review.normalizer import build_review_data

    phase1 = {"property": {"name": "properties/1", "display_name": "T"}}
    phase3 = {
        "tags": [{
            "name": "GA4 資料請求完了", "type": "gaawe", "firingTriggerId": ["20"],
            "parameter": [
                {"type": "TEMPLATE", "key": "eventName", "value": "generate_lead"},
                {"type": "TEMPLATE", "key": "measurementIdOverride", "value": "G-XXXXXXXXXX"},
            ],
        }],
        "triggers": [{"triggerId": "20", "name": "資料請求 完了ページ", "type": "PAGEVIEW"}],
        "variables": [],
        "tag_analysis": [{
            "name": "GA4 資料請求完了", "type_label": "GA4 イベントタグ",
            "firing_trigger_ids": ["20"], "ga4_event": {"event_name": "generate_lead"},
        }],
    }
    (tmp_path / "phase1.json").write_text(json.dumps(phase1), encoding="utf-8")
    (tmp_path / "phase3.json").write_text(json.dumps(phase3), encoding="utf-8")

    result = build_review_data(tmp_path)
    event_tag = result["gtm"]["ga4_event_tags"][0]
    assert event_tag["firing_trigger_names"] == ["資料請求 完了ページ"]
    assert event_tag["destination"] == "G-XXXXXXXXXX"
    assert result["gtm"]["triggers"][0]["name"] == "資料請求 完了ページ"
