"""dataset.py のユニットテスト.

観点別ファイルの読み書きと、旧 phase*.json からのフォールバック・移行を検証する。
"""
import json

import pytest

import dataset

PHASE1 = {
    "property": {"name": "properties/1"},
    "data_streams": [{"name": "s"}],
    "enhanced_measurement_999": {"scrolls_enabled": True},
    "event_create_rules_999": [{"destination_event": "x"}],
    "data_retention": {"event_data_retention": "FOURTEEN_MONTHS"},
    "user_provided_data": {"user_provided_data_collection_enabled": True},
    "reporting_identity": {"reporting_identity": "BLENDED"},
    "custom_dimensions": [{"parameter_name": "d1"}],
    "key_events": [{"event_name": "cv_reserve"}],
}
PHASE2 = {
    "events_30d": [{"eventName": "cv_reserve", "eventCount": "10"}],
    "event_name_counts_30d": [{"eventName": "cv_reserve", "eventCount": "10"}],
    "event_name_counts_status": "complete",
    "key_event_firing": [{"eventName": "cv_reserve", "eventCount": "10"}],
    "channel_performance": [{"sessionDefaultChannelGroup": "Direct", "sessions": "5"}],
    "dimension_values": {"d1": ["a"]},
}
PHASE3 = {"tags": [{"name": "t"}], "triggers": []}


@pytest.fixture
def legacy_dir(tmp_path):
    for name, payload in (("phase1.json", PHASE1), ("phase2.json", PHASE2), ("phase3.json", PHASE3)):
        (tmp_path / name).write_text(json.dumps(payload), encoding="utf-8")
    return tmp_path


def test_load_falls_back_to_legacy_phase_files(legacy_dir):
    """観点別ファイルが無くても旧 phase*.json から組み立てて読める."""
    prop = dataset.load(legacy_dir, "property")
    assert prop["property"]["name"] == "properties/1"
    assert "enhanced_measurement_999" in prop        # prefix 指定が効く
    assert prop["user_provided_data"]["user_provided_data_collection_enabled"] is True
    assert prop["reporting_identity"]["reporting_identity"] == "BLENDED"
    assert "custom_dimensions" not in prop           # 別の観点へ振り分けられている

    events = dataset.load(legacy_dir, "events")
    assert events["key_events"][0]["event_name"] == "cv_reserve"   # phase1 由来
    assert events["events_30d"][0]["eventCount"] == "10"           # phase2 由来
    assert events["event_name_counts_30d"][0]["eventName"] == "cv_reserve"
    assert events["event_name_counts_status"] == "complete"

    defs = dataset.load(legacy_dir, "custom_definitions")
    assert "event_create_rules_999" in defs
    assert defs["dimension_values"] == {"d1": ["a"]}

    assert dataset.load(legacy_dir, "traffic")["channel_performance"][0]["sessions"] == "5"
    assert dataset.load(legacy_dir, "gtm")["tags"] == [{"name": "t"}]


def test_load_prefers_new_files_over_legacy(legacy_dir):
    dataset.save(legacy_dir, "events", {"events_30d": [{"eventName": "new", "eventCount": "1"}]})

    events = dataset.load(legacy_dir, "events")

    assert events["events_30d"][0]["eventName"] == "new"


def test_load_missing_returns_empty_or_raises(tmp_path):
    assert dataset.load(tmp_path, "events") == {}
    with pytest.raises(FileNotFoundError):
        dataset.load(tmp_path, "events", required=True)


def test_migrate_splits_and_can_remove_legacy(legacy_dir):
    written = dataset.migrate(legacy_dir, remove_legacy=True)

    names = {p.name for p in written}
    assert names == {"01-property.json", "02-events.json", "03-custom-definitions.json",
                     "05-traffic.json", "09-gtm.json"}
    assert not (legacy_dir / "phase1.json").exists()
    # 移行後も同じ内容が読める
    assert dataset.load(legacy_dir, "events")["key_events"][0]["event_name"] == "cv_reserve"


def test_migrate_does_not_wipe_traffic_detail_written_before_it(tmp_path):
    """`fetch` の実際の順序（run_traffic_detail の split_and_save → 最後に migrate）を再現する.

    `migrate()` が旧実装のまま単純な上書き保存だと、"traffic" データセットは
    phase2.json 由来の channel_performance だけで 05-traffic.json を丸ごと
    上書きし、直前に split_and_save で書かれた source_medium/campaigns が
    消える（実データで発覚したバグ）。
    """
    (tmp_path / "phase2.json").write_text(json.dumps(PHASE2), encoding="utf-8")

    # run_traffic_detail が fetch の後半で split_and_save する（migrate() より前）
    dataset.split_and_save(tmp_path, "traffic.json", {
        "source_medium": [{"sessionSource": "google", "sessionMedium": "cpc", "sessions": "50"}] * 108,
        "campaigns": [{"sessionCampaignName": "spring_sale"}] * 112,
    })

    written = dataset.migrate(tmp_path)

    traffic = dataset.load(tmp_path, "traffic")
    assert len(traffic["source_medium"]) == 108
    assert len(traffic["campaigns"]) == 112
    assert traffic["channel_performance"][0]["sessions"] == "5"  # phase2.json 由来も残る


def test_split_and_save_routes_keys_to_observations(tmp_path):
    """取得直後の dict が観点別ファイルへ振り分けられる."""
    dataset.split_and_save(tmp_path, "phase1.json", PHASE1)

    assert "property" in dataset.load(tmp_path, "property")
    assert "key_events" in dataset.load(tmp_path, "events")
    assert "custom_dimensions" in dataset.load(tmp_path, "custom_definitions")


def test_split_and_save_merges_into_existing_file(tmp_path):
    """02-events は phase1（登録）と phase2（実績）の両方から書かれるため上書きしない."""
    dataset.split_and_save(tmp_path, "phase1.json", PHASE1)
    dataset.split_and_save(tmp_path, "phase2.json", PHASE2)

    events = dataset.load(tmp_path, "events")
    assert "key_events" in events and "events_30d" in events


def test_split_and_save_keeps_unmapped_keys(tmp_path):
    """どの観点にも割り当てられないキーを取りこぼさない."""
    dataset.split_and_save(tmp_path, "phase1.json", {**PHASE1, "brand_new_section": [1, 2]})

    unmapped = json.loads((tmp_path / "_unmapped.json").read_text(encoding="utf-8"))
    assert unmapped["brand_new_section"] == [1, 2]


def test_split_and_save_traffic_keeps_channel_performance(tmp_path):
    """観点05 の取得を足しても phase2 のチャネル別が消えないこと。"""
    import dataset

    dataset.save(tmp_path, "traffic", {
        "channel_performance": [{"sessionDefaultChannelGroup": "Direct", "sessions": "100"}]
    })
    dataset.split_and_save(tmp_path, "traffic.json", {
        "source_medium": [{"sessionSource": "google", "sessionMedium": "cpc", "sessions": "50"}],
        "campaigns": [],
    })

    loaded = dataset.load(tmp_path, "traffic")
    assert set(loaded) == {"channel_performance", "source_medium", "campaigns"}
    assert loaded["channel_performance"][0]["sessionDefaultChannelGroup"] == "Direct"
    # 0行でもキーは入る（design の観点05 はキーの有無で判定する）
    assert loaded["campaigns"] == []


# 注: 「観点別の必須キー」(`measurement_design.design.perspectives.REQUIRED_KEYS`) は
# 公開版では未採用（章ベースの設計書生成 generator.py/selector.py を使うため）。
# そのためこのテストは対象外。
