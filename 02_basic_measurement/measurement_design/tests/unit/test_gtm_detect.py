"""gtm_mechanical_checks のユニットテスト（GTM コンテナのルールベース検出）."""


def _tag(name, type="gaawe", paused=False, firing=None, blocking=None,
         event_name="", destination="", params=None):
    return {
        "name": name,
        "type": type,
        "type_label": "GA4 イベントタグ" if type == "gaawe" else type,
        "paused": paused,
        "firing_trigger_ids": firing or [],
        "blocking_trigger_ids": blocking or [],
        "event_name": event_name,
        "destination": destination,
        "params": params or {},
    }


def _review(tags):
    return {"gtm": {"tags_detail": tags}}


def _run(tags):
    from measurement_design.review.diagnoser import gtm_mechanical_checks
    return gtm_mechanical_checks(_review(tags))


def test_no_gtm_section_returns_empty():
    from measurement_design.review.diagnoser import gtm_mechanical_checks
    assert gtm_mechanical_checks({"ga4": {}}) == []
    assert gtm_mechanical_checks({"gtm": {"tags_detail": []}}) == []


def test_zombie_active_is_high():
    v = _run([_tag("old_purchase_tag")])
    zombies = [x for x in v if x["category"] == "残骸候補"]
    assert len(zombies) == 1
    assert zombies[0]["severity"] == "High"
    assert zombies[0]["location"] == "GTM"


def test_zombie_paused_is_low():
    v = _run([_tag("旧_購入タグ", paused=True)])
    zombies = [x for x in v if x["category"] == "残骸候補"]
    assert len(zombies) == 1
    assert zombies[0]["severity"] == "Low"


def test_clean_name_not_flagged_as_zombie():
    v = _run([_tag("GA4 購入 店舗A")])
    assert [x for x in v if x["category"] == "残骸候補"] == []


def test_duplicate_firing_detected():
    tags = [
        _tag("GA4購入A", firing=["5"], event_name="purchase", destination="G-TEST"),
        _tag("GA4購入B", firing=["5"], event_name="purchase", destination="G-TEST"),
    ]
    dup = [x for x in _run(tags) if x["category"] == "二重計測"]
    assert len(dup) == 1
    assert dup[0]["severity"] == "Medium"
    assert "GA4購入A" in dup[0]["target_name"]
    assert "GA4購入B" in dup[0]["target_name"]


def test_duplicate_firing_not_flagged_when_blocking_differs():
    """ブロックトリガーが異なれば実際には重複しないので検出しない（誤検知防止）."""
    tags = [
        _tag("GA4購入A", firing=["5"], blocking=["9"], event_name="purchase"),
        _tag("GA4購入B", firing=["5"], blocking=[], event_name="purchase"),
    ]
    assert [x for x in _run(tags) if x["category"] == "二重計測"] == []


def test_different_event_names_not_duplicate():
    tags = [
        _tag("GA4購入", firing=["5"], event_name="purchase"),
        _tag("GA4閲覧", firing=["5"], event_name="view_item"),
    ]
    assert [x for x in _run(tags) if x["category"] == "二重計測"] == []


def test_same_event_to_different_destinations_is_not_duplicate():
    tags = [
        _tag("GA4購入A", firing=["5"], event_name="purchase", destination="G-A"),
        _tag("GA4購入B", firing=["5"], event_name="purchase", destination="G-B"),
    ]
    assert [x for x in _run(tags) if x["category"] == "二重計測"] == []


def test_unresolved_destination_or_dynamic_event_is_not_duplicate():
    tags = [
        _tag("送信先不明A", firing=["5"], event_name="purchase"),
        _tag("送信先不明B", firing=["5"], event_name="purchase"),
        _tag("動的イベントA", firing=["6"], event_name="{{Event}}", destination="G-A"),
        _tag("動的イベントB", firing=["6"], event_name="{{Event}}", destination="G-A"),
    ]
    assert [x for x in _run(tags) if x["category"] == "二重計測"] == []


def test_custom_html_on_same_trigger_not_flagged_as_duplicate():
    """実データで誤検知だった V-G-001。ヒートマップ等の外部SaaSは同一トリガー
    （オールページ等）から複数のカスタムHTMLが発火するのが仕様として正常な状態なので、
    二重計測候補に入れない。"""
    tags = [
        _tag("HubSpot", type="html", firing=["123456789"]),
        _tag("MIERUCA Heatmap", type="html", firing=["123456789"]),
        _tag("ヒートマップ導入タグ", type="html", firing=["123456789"]),
        _tag("チャットタグ", type="html", firing=["123456789"]),
    ]
    assert [x for x in _run(tags) if x["category"] == "二重計測"] == []


def test_custom_html_ga4_style_names_on_same_trigger_not_flagged():
    """実データで誤検知だった V-G-002。タグ名がGA4計測を示唆していても、
    カスタムHTMLは機械では宛先が判定できないため候補に入れない
    （本当の二重計測かどうかは目視項目 audit-items.md に回す）。"""
    tags = [
        _tag("GA_Event_Code_クリック計測", type="html", firing=["275"]),
        _tag("GA_Event_Code_クリック計測_data-gtm", type="html", firing=["275"]),
    ]
    assert [x for x in _run(tags) if x["category"] == "二重計測"] == []


def test_gaawe_duplicate_still_detected_when_html_present():
    """カスタムHTMLの除外が、本物のGA4イベントタグの二重計測検出まで消していないことを確認する。"""
    tags = [
        _tag("GA4購入A", type="gaawe", firing=["5"], event_name="purchase", destination="G-TEST"),
        _tag("GA4購入B", type="gaawe", firing=["5"], event_name="purchase", destination="G-TEST"),
        _tag("ヒートマップ", type="html", firing=["5"]),
    ]
    dup = [x for x in _run(tags) if x["category"] == "二重計測"]
    assert len(dup) == 1
    assert "GA4購入A" in dup[0]["target_name"]
    assert "GA4購入B" in dup[0]["target_name"]


def test_shared_value_detected():
    """ほぼ固有のはずの識別子が複数タグで共有されていれば検出する."""
    tags = [
        _tag("店舗A", params={"send_to": "AW-1/labelA"}),
        _tag("店舗B", params={"send_to": "AW-1/labelB"}),
        _tag("店舗C", params={"send_to": "AW-1/labelC"}),
        _tag("店舗D", params={"send_to": "AW-1/labelD"}),
        _tag("店舗E", params={"send_to": "AW-1/labelA"}),  # A と使い回し
    ]
    shared = [x for x in _run(tags) if x["category"] == "値の使い回し"]
    assert len(shared) == 1
    assert "send_to" in shared[0]["target_name"]
    assert "labelA" in shared[0]["description"]


def test_boolean_like_param_not_flagged_as_shared():
    """true/false のような少値パラメータは使い回しとして検出しない."""
    tags = [_tag(f"タグ{i}", params={"send_ecommerce": "true"}) for i in range(6)]
    assert [x for x in _run(tags) if x["category"] == "値の使い回し"] == []


def test_constant_id_not_flagged_as_shared():
    """全タグ共通の固定値（measurementId 等）は使い回しではない."""
    tags = [_tag(f"タグ{i}", params={"measurementId": "G-XXXX"}) for i in range(6)]
    assert [x for x in _run(tags) if x["category"] == "値の使い回し"] == []


def test_mass_duplication_flagged_at_threshold():
    tags = [
        _tag(
            f"GA4_店舗_{i}", firing=[str(i)], event_name=f"shop_{i}",
            params={"send_to": f"G-SHOP-{i}"},
        )
        for i in range(12)
    ]
    mass = [x for x in _run(tags) if x["category"] == "GTMタグ量産"]
    assert len(mass) == 1
    assert mass[0]["severity"] == "Low"
    assert "12" in mass[0]["description"]
    assert "現在の取得データだけでは" in mass[0]["description"]
    assert "統合を勧めない" in mass[0]["suggested_fix"]
    assert "構成案:" not in mass[0]["suggested_fix"]
    assert "一本化" not in mass[0]["suggested_fix"]


def test_mass_duplication_without_inferable_axis_does_not_recommend_consolidation():
    names = [
        "資料請求", "電話タップ", "料金閲覧", "会社情報", "採用応募",
        "動画再生", "検索利用", "外部遷移", "会員登録", "ログイン",
    ]
    mass = [x for x in _run([_tag(name, firing=[str(i)]) for i, name in enumerate(names)])
            if x["category"] == "GTMタグ量産"]
    assert len(mass) == 1
    assert "共通軸" in mass[0]["description"]
    assert "統合を勧めない" in mass[0]["suggested_fix"]
    assert "一本化" not in mass[0]["suggested_fix"]


def test_mass_duplication_generic_prefix_does_not_create_fake_plan():
    """`GA4_event_` が共通でも、異なる役割を同じ軸と決めつけない。"""
    roles = [
        "資料請求", "動画再生", "電話タップ", "料金閲覧", "会社情報",
        "採用応募", "検索利用", "外部遷移", "会員登録", "ログイン",
    ]
    mass = [x for x in _run([_tag(f"GA4_event_{role}") for role in roles])
            if x["category"] == "GTMタグ量産"]
    assert len(mass) == 1
    assert "構成案:" not in mass[0]["suggested_fix"]
    assert "統合を勧めない" in mass[0]["suggested_fix"]


def test_below_threshold_not_mass_duplication():
    tags = [_tag(f"GA4イベント{i}", firing=[str(i)]) for i in range(9)]
    assert [x for x in _run(tags) if x["category"] == "GTMタグ量産"] == []


def test_paused_tags_excluded_from_mass_duplication():
    """一時停止タグは量産カウントから除く."""
    tags = [_tag(f"GA4イベント{i}", firing=[str(i)], paused=True) for i in range(12)]
    assert [x for x in _run(tags) if x["category"] == "GTMタグ量産"] == []


def test_violation_schema_fields():
    tags = [_tag("old_tag"), _tag("GA4購入A", firing=["5"], event_name="purchase"),
            _tag("GA4購入B", firing=["5"], event_name="purchase")]
    for v in _run(tags):
        for field in ("id", "severity", "category", "target_name",
                      "description", "location"):
            assert field in v
        assert v["id"].startswith("V-G-")


def test_ids_stable_across_tag_reordering():
    """タグの並び順（GTM APIが返す順）が変わっても、同じ指摘は同じIDのままにする.

    通し番号だった旧実装は、並び順が変わると同じ指摘に別のIDを振ってしまっていた。
    """
    tags = [
        _tag("old_purchase_tag"),
        _tag("GA4購入A", firing=["5"], event_name="purchase"),
        _tag("GA4購入B", firing=["5"], event_name="purchase"),
    ]
    v1 = _run(tags)
    v2 = _run(list(reversed(tags)))

    def _by_target(violations):
        return {(v["category"], v["target_name"]): v["id"] for v in violations}

    assert _by_target(v1) == _by_target(v2)


def test_different_tag_names_do_not_collide():
    """カテゴリが同じでも対象タグ名が違えば違うIDになる（衝突しないこと）."""
    v = _run([_tag("old_a"), _tag("old_b")])
    zombies = {x["target_name"]: x["id"] for x in v if x["category"] == "残骸候補"}
    assert len(zombies) == 2
    assert len(set(zombies.values())) == 2
