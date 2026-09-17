"""health_checks.py のユニットテスト.

codex レビューで3回連続して「判定の境界」を指摘されたため、
直した境界条件をテストで固定する。特に次の3つは誤判定の方向が逆なので個別に押さえる。

- 0件・欠落を見逃さない（一番深刻な状態を落とすと診断が意味を失う）
- ただし一覧が上限で切られている場合は0件と断定しない（誤警報になる）
- 限られた集合を指す正規表現を「全イベント」扱いにしない（Critical の誤検知になる）
"""

import pytest


# ──────────────────────────────────────
# セッション健全性
# ──────────────────────────────────────

def _events(sessions, rows):
    return {"totals": {"sessions": sessions}, "events_30d": rows}


def test_session_health_reports_low_ratio():
    from measurement_design.review.health_checks import check_session_health
    # 対象の2イベントを両方入れる。片方だけだと、もう片方の欠落も同時に検出されて
    # 何を確かめているのか分からなくなる
    ev = _events(1000, [{"eventName": "session_start", "eventCount": "490"},
                        {"eventName": "user_engagement", "eventCount": "980"}])
    out = [v for v in check_session_health(ev, [0]) if v["target_name"] == "session_start"]
    assert len(out) == 1
    assert out[0]["severity"] == "Critical"
    assert "0.49" in out[0]["description"]


def test_session_health_ignores_healthy_ratio():
    from measurement_design.review.health_checks import check_session_health
    ev = _events(1000, [{"eventName": "session_start", "eventCount": "980"},
                        {"eventName": "user_engagement", "eventCount": "990"}])
    assert check_session_health(ev, [0]) == []


def test_session_health_reports_explicit_zero_as_critical():
    """0件の行があるなら、それは確実に異常。一番深刻な状態を落とさない。"""
    from measurement_design.review.health_checks import check_session_health
    ev = _events(1000, [{"eventName": "session_start", "eventCount": "0"}])
    out = [v for v in check_session_health(ev, [0]) if v["target_name"] == "session_start"]
    assert out and out[0]["severity"] == "Critical"
    assert "1件も記録されていない" in out[0]["description"]


def test_session_health_missing_in_short_list_is_critical():
    """一覧が上限未満なら、名前が無い＝0件と断定できる。"""
    from measurement_design.review.health_checks import check_session_health
    ev = _events(1000, [{"eventName": "page_view", "eventCount": "5000"}])
    out = [v for v in check_session_health(ev, [0]) if v["target_name"] == "session_start"]
    assert out and out[0]["severity"] == "Critical"


def test_session_health_missing_in_truncated_list_is_not_asserted_zero():
    """一覧が上限に達しているなら「切られただけ」の可能性があるので断定しない。"""
    from measurement_design.review.health_checks import (
        EVENTS_LIST_LIMIT, check_session_health,
    )
    rows = [{"eventName": f"e{i}", "eventCount": "9999"} for i in range(EVENTS_LIST_LIMIT)]
    out = [v for v in check_session_health(_events(1000, rows), [0])
           if v["target_name"] == "session_start"]
    assert out and out[0]["severity"] == "High"
    assert "断定できない" in out[0]["description"]


def test_session_health_skips_when_no_event_data():
    from measurement_design.review.health_checks import check_session_health
    assert check_session_health(_events(1000, []), [0]) == []
    assert check_session_health(_events(0, [{"eventName": "session_start", "eventCount": "1"}]), [0]) == []


def test_user_engagement_below_session_ratio_is_not_flagged():
    """user_engagement はエンゲージメントが成立したときだけ飛ぶので、
    セッション数の0.84倍（実データで見つかった誤検知）を指摘してはいけない。
    """
    from measurement_design.review.health_checks import check_session_health
    ev = _events(13_095, [{"eventName": "session_start", "eventCount": "13000"},
                          {"eventName": "user_engagement", "eventCount": "11007"}])
    out = [v for v in check_session_health(ev, [0]) if v["target_name"] == "user_engagement"]
    assert out == []


def test_user_engagement_zero_is_still_critical():
    """比率判定は捨てたが、0件（基盤タグが全く動いていない）は見逃さない。"""
    from measurement_design.review.health_checks import check_session_health
    ev = _events(1000, [{"eventName": "session_start", "eventCount": "990"},
                        {"eventName": "user_engagement", "eventCount": "0"}])
    out = [v for v in check_session_health(ev, [0]) if v["target_name"] == "user_engagement"]
    assert out and out[0]["severity"] == "Critical"
    assert "1件も記録されていない" in out[0]["description"]


def test_user_engagement_missing_in_short_list_is_critical():
    """一覧が上限未満で名前が無いなら、user_engagement も0件と断定できる。"""
    from measurement_design.review.health_checks import check_session_health
    ev = _events(1000, [{"eventName": "session_start", "eventCount": "990"},
                        {"eventName": "page_view", "eventCount": "5000"}])
    out = [v for v in check_session_health(ev, [0]) if v["target_name"] == "user_engagement"]
    assert out and out[0]["severity"] == "Critical"


def test_session_start_low_ratio_still_flagged_when_user_engagement_healthy():
    """session_start 側の判定（比率ベース）は変えていないことを確認する。"""
    from measurement_design.review.health_checks import check_session_health
    ev = _events(1000, [{"eventName": "session_start", "eventCount": "490"},
                        {"eventName": "user_engagement", "eventCount": "600"}])
    out = check_session_health(ev, [0])
    session_start = [v for v in out if v["target_name"] == "session_start"]
    user_engagement = [v for v in out if v["target_name"] == "user_engagement"]
    assert session_start and session_start[0]["severity"] == "Critical"
    assert user_engagement == []


# ──────────────────────────────────────
# user_id の潰れ
# ──────────────────────────────────────

def test_user_id_collapse_detected():
    from measurement_design.review.health_checks import check_user_id_collapse
    ev = {"events_30d": [{"eventName": "page_view_ga4", "eventCount": "546556", "totalUsers": "1"}]}
    out = check_user_id_collapse(ev, [0])
    assert len(out) == 1 and out[0]["severity"] == "Critical"


def test_user_id_collapse_ignores_low_volume():
    """件数が少ないイベントでユーザー数が少ないのは普通のこと。"""
    from measurement_design.review.health_checks import check_user_id_collapse
    ev = {"events_30d": [{"eventName": "rare_event", "eventCount": "3", "totalUsers": "1"}]}
    assert check_user_id_collapse(ev, [0]) == []


# ──────────────────────────────────────
# イベント名のカーディナリティ
# ──────────────────────────────────────

def test_event_name_cardinality_uses_dedicated_count():
    """`events_30d` の行数ではなく専用の取得値を見る（行数は上限で切られる）。"""
    from measurement_design.review.health_checks import check_event_name_cardinality
    ev = {"events_30d": [{"eventName": f"e{i}", "eventCount": "1"} for i in range(100)],
          "event_name_total": {"distinct_event_names": 450}}
    out = check_event_name_cardinality(ev, [0])
    assert len(out) == 1 and "450種" in out[0]["description"]


def test_event_name_cardinality_silent_when_not_fetched():
    from measurement_design.review.health_checks import check_event_name_cardinality
    ev = {"events_30d": [{"eventName": f"e{i}", "eventCount": "1"} for i in range(100)]}
    assert check_event_name_cardinality(ev, [0]) == []


# ──────────────────────────────────────
# SPA計測ギャップ（旧・ページ逆転を置き換え）
# ──────────────────────────────────────
#
# 旧 check_page_view_reversal（「PVがセッション数を下回るページがN件」）は
# 実データで見ると誤検知だらけだった（PV219/セッション254程度の差はどのサイトでも
# 普通に出る）。廃止して check_spa_tracking_gap に置き換えたので、ここのテストも
# 新しい検査の観点（タイトル未設定・タイトル固定・誤検知しないこと）に揃える。

def test_spa_gap_skips_without_page_title():
    """`pageTitle` が1件も無いデータでは何も判定しない（0件を返す）。

    実データの `_data/06-pages.json` はタイトルを取得していないため、
    ここが正しく振る舞わないと実データで常に誤検知することになる。
    """
    from measurement_design.review.health_checks import check_spa_tracking_gap
    pages = [{"pagePath": "/a", "screenPageViews": 5000, "sessions": 3000}]
    assert check_spa_tracking_gap({"pages": pages}, [0]) == []


def test_spa_gap_detects_unset_title_on_high_traffic():
    """実績のあるページでタイトルが空・`(not set)` のまま、というのはSPAでdocument.titleを
    更新していない疑いがある。"""
    from measurement_design.review.health_checks import check_spa_tracking_gap
    pages = [
        {"pagePath": "/app/1", "pageTitle": "(not set)", "screenPageViews": 60, "sessions": 50},
        {"pagePath": "/app/2", "pageTitle": "", "screenPageViews": 60, "sessions": 50},
    ]
    out = check_spa_tracking_gap({"pages": pages}, [0])
    assert out and out[0]["category"] == "SPA計測ギャップ"
    assert "未設定" in out[0]["description"]


def test_spa_gap_detects_title_stuck_across_sections():
    """明らかに違うセクションにまたがって同じタイトルが使われているのは、
    画面遷移でタイトルが更新されていない疑いが強い。"""
    from measurement_design.review.health_checks import check_spa_tracking_gap
    sections = ["/media", "/service", "/company", "/contact", "/faq",
                "/blog", "/case", "/pricing", "/about", "/news"]
    pages = [
        {"pagePath": f"{s}/{i}", "pageTitle": "マイアプリ", "screenPageViews": 30, "sessions": 20}
        for i, s in enumerate(sections)
    ]
    out = check_spa_tracking_gap({"pages": pages}, [0])
    assert any("マイアプリ" in v["target_name"] for v in out)


def test_spa_gap_reframes_404_title_as_broken_link_not_spa_bug():
    """404・エラーページが複数セクションで同じタイトルなのは当然の挙動 (試用フィードバックで検出:
    「404ページのタイトル重複指摘は仕方ないのでは」)。

    「document.titleを更新していない」という的外れな指摘にはせず、
    「壊れたリンクの疑い」として別カテゴリ・別の対応内容で出す。
    """
    from measurement_design.review.health_checks import check_spa_tracking_gap
    sections = ["/media", "/service", "/company", "/contact", "/faq",
                "/blog", "/case", "/pricing", "/about", "/news"]
    pages = [
        {"pagePath": f"{s}/{i}", "pageTitle": "404 NOT FOUND ／ サイト名", "screenPageViews": 30, "sessions": 20}
        for i, s in enumerate(sections)
    ]
    out = check_spa_tracking_gap({"pages": pages}, [0])

    assert out and all(v["category"] != "SPA計測ギャップ" for v in out)
    assert any(v["category"] == "リンク切れ" for v in out)
    row = next(v for v in out if v["category"] == "リンク切れ")
    assert "document.title" not in row["description"]
    assert "404" in row["description"]


def test_spa_gap_does_not_flag_pagination_within_one_section():
    """ページネーション・絞り込みで同一セクション内に同じタイトルが並ぶのは正常。
    先頭パスが同じなら（セクション数が足りないので）指摘しない。"""
    from measurement_design.review.health_checks import check_spa_tracking_gap
    pages = [
        {"pagePath": f"/blog/page/{i}", "pageTitle": "ブログ一覧", "screenPageViews": 30, "sessions": 20}
        for i in range(20)
    ]
    assert check_spa_tracking_gap({"pages": pages}, [0]) == []


def test_spa_gap_no_false_positive_on_diverse_real_data():
    """実データ相当（各ページにタイトルがあり、573ページにPVが分散している）では
    何も検出しない。"""
    from measurement_design.review.health_checks import check_spa_tracking_gap
    pages = [
        {"pagePath": f"/media/knowledge/{i}", "pageTitle": f"記事{i} | サイト名",
         "screenPageViews": 200 + i, "sessions": 150 + i}
        for i in range(573)
    ]
    assert check_spa_tracking_gap({"pages": pages}, [0]) == []


# ──────────────────────────────────────
# 検証環境の混入
# ──────────────────────────────────────

@pytest.mark.parametrize("host", [
    "example-stg.co.jp", "localhost", "preview.example.co.jp",
    "review-x--pr-1.web.app", "app.vercel.app", "127.0.0.1",
])
def test_non_production_hosts_detected(host):
    from measurement_design.review.health_checks import check_non_production_hosts
    out = check_non_production_hosts({"hosts": [{"hostName": host, "sessions": 100}]}, [0])
    assert out, f"{host} を検証環境として検出できていない"


def test_production_host_not_flagged():
    from measurement_design.review.health_checks import check_non_production_hosts
    assert check_non_production_hosts({"hosts": [{"hostName": "example.co.jp", "sessions": 100}]}, [0]) == []


# ──────────────────────────────────────
# 多重発火（全イベントタグの扱い）
# ──────────────────────────────────────

def _tag(index, event_name, datalayer_events, function="__gaawe", destination="G-X"):
    return {"index": index, "function": function, "type_label": "GA4 イベント",
            "event_name": event_name, "destination": destination,
            "datalayer_events": datalayer_events}


def test_all_event_tag_reported_once_not_per_event():
    """動的な全イベント転送タグ1本だけなら、変数利用を不備扱いしない。"""
    from measurement_design.review.health_checks import (
        ANY_DATALAYER_EVENT, check_duplicate_datalayer_fires,
    )
    tags = [_tag(1, "signup", ["sign_up"]),
            _tag(2, "upload_ga4", ["upload"]),
            _tag(99, "Event", [ANY_DATALAYER_EVENT])]
    out = check_duplicate_datalayer_fires({"tags": tags}, [0])
    assert out == []


def test_dedicated_duplicates_still_reported():
    from measurement_design.review.health_checks import check_duplicate_datalayer_fires
    tags = [_tag(1, "login", ["login"]), _tag(2, "login", ["login"])]
    out = check_duplicate_datalayer_fires({"tags": tags}, [0])
    assert len(out) == 1 and out[0]["target_name"] == "login"


def test_all_event_and_dedicated_tag_overlap_is_reported_once():
    from measurement_design.review.health_checks import (
        ANY_DATALAYER_EVENT, check_duplicate_datalayer_fires,
    )
    tags = [
        _tag(1, "purchase", [ANY_DATALAYER_EVENT], destination="G-TEST"),
        _tag(2, "purchase", ["purchase"], destination="G-TEST"),
    ]
    out = check_duplicate_datalayer_fires({"tags": tags}, [0])
    assert len(out) == 1
    assert out[0]["target_name"] == "purchase"
    assert "すべてのカスタムイベント対象タグと専用タグ" in out[0]["description"]


def test_single_tag_with_all_event_and_dedicated_triggers_is_not_duplicate():
    from measurement_design.review.health_checks import (
        ANY_DATALAYER_EVENT, check_duplicate_datalayer_fires,
    )
    tag = _tag(
        1, "purchase", [ANY_DATALAYER_EVENT, "purchase"], destination="G-TEST",
    )
    assert check_duplicate_datalayer_fires({"tags": [tag]}, [0]) == []


def test_same_trigger_but_different_sent_event_is_not_duplicate():
    from measurement_design.review.health_checks import check_duplicate_datalayer_fires
    tags = [_tag(1, "login", ["conversion"]), _tag(2, "generate_lead", ["conversion"])]
    assert check_duplicate_datalayer_fires({"tags": tags}, [0]) == []


def test_same_event_but_different_destination_is_not_duplicate():
    from measurement_design.review.health_checks import check_duplicate_datalayer_fires
    tags = [_tag(1, "login", ["login"], destination="G-A"),
            _tag(2, "login", ["login"], destination="G-B")]
    assert check_duplicate_datalayer_fires({"tags": tags}, [0]) == []


def test_variable_event_name_is_not_statically_judged_duplicate():
    from measurement_design.review.health_checks import check_duplicate_datalayer_fires
    tags = [_tag(1, "Event", ["login"]), _tag(2, "Event", ["login"])]
    assert check_duplicate_datalayer_fires({"tags": tags}, [0]) == []


def test_gtm_internal_events_not_counted_as_duplicates():
    from measurement_design.review.health_checks import check_duplicate_datalayer_fires
    tags = [_tag(1, "a", ["gtm.dom"]), _tag(2, "b", ["gtm.dom"])]
    assert check_duplicate_datalayer_fires({"tags": tags}, [0]) == []


# ──────────────────────────────────────
# 基盤タグの発火タイミング
# ──────────────────────────────────────

def _googtag(index, destination, fire_on):
    return {"index": index, "function": "__googtag", "type_label": "Google タグ（基盤設定）",
            "event_name": "", "destination": destination,
            "datalayer_events": [], "fire_on": fire_on}


def test_base_tag_without_initialization_is_critical():
    from measurement_design.review.health_checks import check_base_tag_trigger
    data = {"tags": [_googtag(1, "G-X", ["Event = gtm.dom"])]}
    out = [v for v in check_base_tag_trigger(data, [0]) if v["target_name"].startswith("Google")]
    assert out and out[0]["severity"] == "Critical"


def test_base_tag_with_initialization_is_ok():
    from measurement_design.review.health_checks import check_base_tag_trigger
    data = {"tags": [_googtag(1, "G-X", ["Event = gtm.init"])]}
    assert [v for v in check_base_tag_trigger(data, [0]) if v["target_name"].startswith("Google")] == []


def test_mixed_measurement_id_resolution_flagged():
    from measurement_design.review.health_checks import check_base_tag_trigger
    data = {"tags": [_googtag(1, "G-X", ["Event = gtm.init"]),
                     _googtag(2, "ルックアップ(URL:HOST: ...)", ["Event = gtm.init"])]}
    out = [v for v in check_base_tag_trigger(data, [0]) if v["target_name"] == "測定IDの決定方法"]
    assert out and out[0]["severity"] == "High"

# ──────────────────────────────────────
# イベント作成ルールの陳腐化（条件の一致方式に従う）
# ──────────────────────────────────────

PAGES_FOR_RULES = {"pages": [
    {"pagePath": "/form/request_material", "screenPageViews": 2091},
    {"pagePath": "/form/overview-doc", "screenPageViews": 30},
]}


def _rule(value, comparison, dest="X"):
    return {"event_create_rules_1": [{
        "destination_event": dest,
        "event_conditions": [{"field": "link_url", "value": value,
                              "comparison_type": comparison}],
    }]}


EVENTS_FOR_RULES = {"events_30d": [{"eventName": "page_view", "eventCount": "5000"}]}


def test_health_checks_does_not_run_removed_stale_url_rule(tmp_path, monkeypatch):
    """廃止したURL条件チェックが別セクションから再出現しない。"""
    from measurement_design.review import health_checks as module

    def fail_if_called(*_args, **_kwargs):
        pytest.fail("廃止したURL条件チェックが通常診断から呼ばれています")

    monkeypatch.setattr(module, "check_stale_event_create_rules", fail_if_called)
    module.health_checks(tmp_path)


def test_stale_rule_detected_for_dead_url():
    """生成先イベントの発火が0件なら決定的なので Critical。"""
    from measurement_design.review.health_checks import check_stale_event_create_rules
    defs = _rule("https://example.co.jp/form/overview-doc", "CONTAINS")
    out = check_stale_event_create_rules(defs, PAGES_FOR_RULES, [0], None, EVENTS_FOR_RULES)
    assert out and out[0]["severity"] == "Critical"
    assert "発火も0件" in out[0]["description"]


def test_rule_with_firing_destination_not_reported():
    """生成先イベントが発火していればルールは生きている。"""
    from measurement_design.review.health_checks import check_stale_event_create_rules
    defs = _rule("https://example.co.jp/form/overview-doc", "CONTAINS", dest="alive_event")
    events = {"events_30d": [{"eventName": "alive_event", "eventCount": "500"}]}
    assert check_stale_event_create_rules(defs, PAGES_FOR_RULES, [0], None, events) == []


@pytest.mark.parametrize("target", [
    "mailto:info@example.com", "tel:0312345678",  # leak-ok: 合成の電話番号（実在の番号ではない）
    "https://example.co.jp/files/guide.pdf", "https://external.example.com/page",
])
def test_non_page_click_targets_skipped(target):
    """外部リンク・PDF・mailto はページ実績に出てこない。PVで判定すると誤報になる。"""
    from measurement_design.review.health_checks import check_stale_event_create_rules
    quality = {"hosts": [{"hostName": "example.co.jp", "sessions": 100}]}
    defs = _rule(target, "CONTAINS")
    assert check_stale_event_create_rules(defs, PAGES_FOR_RULES, [0], quality, EVENTS_FOR_RULES) == []


def test_live_rule_not_reported():
    from measurement_design.review.health_checks import check_stale_event_create_rules
    defs = _rule("https://example.co.jp/form/request_material", "CONTAINS")
    assert check_stale_event_create_rules(defs, PAGES_FOR_RULES, [0]) == []


def test_regex_condition_not_treated_as_literal_prefix():
    """正規表現条件を前方一致で数えると、生きているルールを陳腐化と誤報する。"""
    from measurement_design.review.health_checks import check_stale_event_create_rules
    defs = _rule("/form/.*request_material", "FULL_REGEXP")
    assert check_stale_event_create_rules(defs, PAGES_FOR_RULES, [0]) == []


def test_invalid_regex_is_skipped():
    from measurement_design.review.health_checks import check_stale_event_create_rules
    defs = _rule("/form/[unclosed", "FULL_REGEXP")
    assert check_stale_event_create_rules(defs, PAGES_FOR_RULES, [0]) == []


# ──────────────────────────────────────
# 指摘IDの安定性（内容から決まる／再取得のたびに振り直されない）
# ──────────────────────────────────────

def test_stale_rule_multiple_conditions_get_distinct_ids():
    """同じ生成先イベントに複数の陳腐化した条件が付く場合、それぞれ別のIDになる.

    `target_name`（生成先イベント名）だけをIDの素にすると、この2件が同じIDに
    なってしまう（今回の改修で見つけた収束漏れ）。条件の値を識別要素に加えて防ぐ。
    """
    from measurement_design.review.health_checks import check_stale_event_create_rules

    defs = {"event_create_rules_1": [{
        "destination_event": "X",
        "event_conditions": [
            {"field": "link_url", "value": "https://example.co.jp/form/overview-doc",
             "comparison_type": "CONTAINS"},
            {"field": "link_url", "value": "https://example.co.jp/form/another-dead-page",
             "comparison_type": "CONTAINS"},
        ],
    }]}
    out = check_stale_event_create_rules(defs, PAGES_FOR_RULES, [0], None, EVENTS_FOR_RULES)
    assert len(out) == 2
    assert len({v["id"] for v in out}) == 2


def test_enhanced_measurement_disabled_multiple_streams_get_distinct_ids():
    """複数ストリームがそれぞれ無効化されている場合、target_name（"拡張計測"）が
    共通でも、ストリームごとに別のIDになることを確認する。"""
    from measurement_design.review.health_checks import check_enhanced_measurement_disabled

    prop = {
        "enhanced_measurement_STREAM1": {"stream_enabled": True},
        "enhanced_measurement_STREAM2": {"stream_enabled": True},
    }
    out = check_enhanced_measurement_disabled(prop, [0])
    assert len(out) == 2
    assert len({v["id"] for v in out}) == 2


def test_user_id_collapse_ids_stable_across_row_reordering():
    """`events_30d` の行の並び順（API が返す順）が変わっても、同じ指摘は同じIDになる."""
    from measurement_design.review.health_checks import check_user_id_collapse

    rows = [
        {"eventName": "login", "eventCount": 2000, "totalUsers": 1},
        {"eventName": "signup", "eventCount": 3000, "totalUsers": 2},
    ]
    v1 = check_user_id_collapse({"events_30d": rows}, [0])
    v2 = check_user_id_collapse({"events_30d": list(reversed(rows))}, [0])

    id_by_name_1 = {v["target_name"]: v["id"] for v in v1}
    id_by_name_2 = {v["target_name"]: v["id"] for v in v2}
    assert id_by_name_1 == id_by_name_2
    assert len(id_by_name_1) == 2


# ──────────────────────────────────────
# 個人情報の混入（check_page_pii）
# ──────────────────────────────────────

def test_page_pii_detects_reset_password_token():
    """試用で実際にあった事象: パスワード再設定トークンがパスにそのまま入っている."""
    from measurement_design.review.health_checks import check_page_pii

    pages = {"pages": [
        {"pagePath": "/mypage/reset_password/aB3dE7fG9hJ2kL4mN6pQ8r/",
         "screenPageViews": 3, "sessions": 3},
    ]}
    out = check_page_pii(pages, [0])
    hits = [v for v in out if v["target_kind"] == "page"]
    assert len(hits) == 1
    assert hits[0]["severity"] == "Critical"
    assert hits[0]["category"] == "個人情報の混入"
    # 実トークンをレポートに残さない。ディレクトリ構造だけ残す。
    assert "aB3dE7fG9hJ2kL4mN6pQ8r" not in hits[0]["description"]
    assert "aB3dE7fG9hJ2kL4mN6pQ8r" not in hits[0]["target_name"]
    assert "/mypage/reset_password/****" in hits[0]["description"]


def test_page_pii_groups_multiple_tokens_under_same_directory():
    """ユーザーごとに変わるトークンを1件ずつ挙げると件数がユーザー数になってしまう。
    同じディレクトリ配下は1件に束ね、件数・PVだけ積み上げる."""
    from measurement_design.review.health_checks import check_page_pii

    pages = {"pages": [
        {"pagePath": "/mypage/reset_password/aB3dE7fG9hJ2kL4mN6pQ8r/",
         "screenPageViews": 3, "sessions": 3},
        {"pagePath": "/mypage/reset_password/zZ9yY8xX7wW6vV5uU4tT3s/",
         "screenPageViews": 2, "sessions": 2},
    ]}
    out = check_page_pii(pages, [0])
    hits = [v for v in out if v["target_kind"] == "page"]
    assert len(hits) == 1
    assert "2件" in hits[0]["description"]
    assert "5PV" in hits[0]["description"]


def test_page_pii_ignores_article_slug_without_sensitive_context():
    """記事ID・商品IDのような長い英数字を誤検知しない。文脈（隣接ディレクトリ名）が
    パスワード再設定・認証系でなければ、形が似ていても対象にしない."""
    from measurement_design.review.health_checks import check_page_pii

    pages = {"pages": [
        {"pagePath": "/blog/how-to-use-ga4-and-gtm-together-2024/",
         "screenPageViews": 100, "sessions": 90},
        {"pagePath": "/products/AbCdEf12Gh34Ij56Kl78ProductSku/",
         "screenPageViews": 50, "sessions": 40},
    ]}
    assert check_page_pii(pages, [0]) == []


def test_page_pii_ignores_numeric_only_value_even_with_sensitive_context():
    """`confirm` 配下でも、値が数字だけ（注文番号らしき連番）なら対象にしない。
    英字・数字の両方が混在するものだけをトークンとみなす。"""
    from measurement_design.review.health_checks import check_page_pii

    pages = {"pages": [
        {"pagePath": "/order/confirm/20240101123456789012/",
         "screenPageViews": 10, "sessions": 10},
    ]}
    out = check_page_pii(pages, [0])
    assert [v for v in out if v["target_kind"] == "page"] == []


def test_page_pii_detects_uuid_token():
    """UUID形式（ハイフン込み36文字）もトークンとして検出する."""
    from measurement_design.review.health_checks import check_page_pii

    pages = {"pages": [
        {"pagePath": "/account/activate/550e8400-e29b-41d4-a716-446655440000/",
         "screenPageViews": 1, "sessions": 1},
    ]}
    out = check_page_pii(pages, [0])
    hits = [v for v in out if v["target_kind"] == "page"]
    assert len(hits) == 1
    assert hits[0]["severity"] == "Critical"


def test_page_pii_detects_email_in_path_and_masks_it():
    """メールアドレスがパス・クエリの値としてそのまま記録されている場合を検出し、
    レポートには実アドレスを残さずマスクした形だけを出す."""
    from measurement_design.review.health_checks import check_page_pii

    pages = {"pages": [
        {"pagePath": "/channels/user@example.com/", "screenPageViews": 4, "sessions": 4},
    ]}
    out = check_page_pii(pages, [0])
    assert len(out) == 1
    assert out[0]["severity"] == "Critical"
    assert "user@example.com" not in out[0]["description"]
    assert "****@****" in out[0]["description"]


def test_page_pii_detects_sensitive_query_key_names():
    """`email=` `password=` のようなキー名そのものが個人情報の送信を示す場合を検出する.
    値がハッシュ化されていても、キー名だけで指摘する（値は判定条件にしない）。"""
    from measurement_design.review.health_checks import check_page_pii

    pages = {"pages": [
        {"pagePath": "/search?email=abc123hash&q=shoes", "screenPageViews": 7, "sessions": 7},
    ]}
    out = check_page_pii(pages, [0])
    query_hits = [v for v in out if "クエリキー" in v["target_name"]]
    assert len(query_hits) == 1
    assert query_hits[0]["severity"] == "Critical"


def test_page_pii_ignores_ordinary_query_keys():
    """`q=` `page=` のような通常のクエリキーは対象にしない（過検出しない）。"""
    from measurement_design.review.health_checks import check_page_pii

    pages = {"pages": [
        {"pagePath": "/search?q=shoes&page=2&sort=price", "screenPageViews": 7, "sessions": 7},
    ]}
    assert check_page_pii(pages, [0]) == []


def test_page_pii_no_pages_data_returns_empty():
    """`06-pages.json` が未取得なら何も判定しない（0件を返す）。"""
    from measurement_design.review.health_checks import check_page_pii

    assert check_page_pii({}, [0]) == []


def test_page_pii_raw_email_in_query_value_counts_once():
    """`?email=生のメール` は値レベルの検出だけが立つ（キー名の指摘は出さない）。

    実データ確認: 同じ1本のURLが「メールアドレス」と「クエリキー email」の
    2件に水増しされていた不具合の再発防止。値が読めた時点でキー名の指摘は
    情報を足さないので、値レベルが当たったキーはキー名の検出から除く。
    """
    from measurement_design.review.health_checks import check_page_pii

    pages = {"pages": [
        {"pagePath": "/contact/?email=taro.yamada@example.com",
         "screenPageViews": 5, "sessions": 5},
    ]}
    out = check_page_pii(pages, [0])
    assert len(out) == 1
    assert "メールアドレス" in out[0]["target_name"]
    assert "クエリキー" not in out[0]["target_name"]


def test_page_pii_hashed_email_query_value_counts_once():
    """`?email=ハッシュ` は値がメールの形に見えないので、キー名の検出だけが立つ。

    ここがキー名検出の本来の担当範囲（値レベルが空振りするケース）。
    """
    from measurement_design.review.health_checks import check_page_pii

    pages = {"pages": [
        {"pagePath": "/contact/?email=8f3a9c2b7d1e4fa5b6c7d8e9f0a1b2c3",
         "screenPageViews": 5, "sessions": 5},
    ]}
    out = check_page_pii(pages, [0])
    assert len(out) == 1
    assert "クエリキー" in out[0]["target_name"]
    assert "メールアドレス" not in out[0]["target_name"]


def test_page_pii_raw_and_hashed_email_mixed_site_counts_two():
    """生値のURLとハッシュ済みのURLが混在するサイトでは、別の問題として両方出る
    （キー名単位で丸ごと消すと、後者が落ちてしまうため）。"""
    from measurement_design.review.health_checks import check_page_pii

    pages = {"pages": [
        {"pagePath": "/contact/?email=taro.yamada@example.com",
         "screenPageViews": 5, "sessions": 5},
        {"pagePath": "/contact/?email=8f3a9c2b7d1e4fa5b6c7d8e9f0a1b2c3",
         "screenPageViews": 3, "sessions": 3},
    ]}
    out = check_page_pii(pages, [0])
    assert len(out) == 2
    kinds = {("メールアドレス" in v["target_name"], "クエリキー" in v["target_name"]) for v in out}
    assert kinds == {(True, False), (False, True)}


def test_page_pii_raw_tel_in_query_value_counts_once():
    """`?tel=` もメールと同じ構図で、値が電話番号の形なら値レベルの検出だけが立つ。"""
    from measurement_design.review.health_checks import check_page_pii

    pages = {"pages": [
        {"pagePath": "/contact/?tel=080-1234-5678", "screenPageViews": 5, "sessions": 5},
    ]}
    out = check_page_pii(pages, [0])
    assert len(out) == 1
    assert "電話番号" in out[0]["target_name"]
    assert "クエリキー" not in out[0]["target_name"]


# ──────────────────────────────────────
# 流入計測の指摘（audit_matrix.py から一本化した4つの check_*）
#
# 旧実装は audit_matrix.py の判定関数にしかロジックが無く、×判定でも
# check-report の指摘（改善ロードマップ）を作っていなかった。判定を作る側の
# ロジックをここに移したので、判定そのものの正しさをここで固定する。
# ──────────────────────────────────────

def test_self_referral_detects_sibling_domain():
    """`www.example.jp` と `example.co.jp` は末尾2ラベルが違う。ブランド名で見る。"""
    from measurement_design.review.health_checks import check_self_referral

    prop = {"data_streams": [{"web_stream_data": {"default_uri": "https://www.example.jp/"}}]}
    traffic = {"source_medium": [
        {"sessionSource": "example.co.jp", "sessionMedium": "referral", "sessions": "2414"},
    ]}

    out = check_self_referral(prop, traffic, [0])

    assert len(out) == 1
    assert out[0]["category"] == "自己参照"
    assert "2,414" in out[0]["description"]


def test_self_referral_ok_without_own_domain():
    from measurement_design.review.health_checks import check_self_referral

    prop = {"data_streams": [{"web_stream_data": {"default_uri": "https://www.example.jp/"}}]}
    traffic = {"source_medium": [{"sessionSource": "suumo.jp", "sessionMedium": "referral", "sessions": "321"}]}

    assert check_self_referral(prop, traffic, [0]) == []


def test_cross_domain_referral_candidate_detects_booking_host_referral_without_declaring_break():
    from measurement_design.review.health_checks import check_cross_domain_referral_candidates

    quality = {"hosts": [
        {"hostName": "www.example.jp", "sessions": "9000"},
        {"hostName": "reserve.booking-system.jp", "sessions": "1000"},
    ]}
    traffic = {"source_medium": [
        {"sessionSource": "reserve.booking-system.jp", "sessionMedium": "referral", "sessions": "240"},
        {"sessionSource": "google", "sessionMedium": "organic", "sessions": "5000"},
    ]}

    out = check_cross_domain_referral_candidates(quality, traffic, [0])

    assert len(out) == 1
    assert out[0]["category"] == "クロスドメイン計測"
    assert out[0]["severity"] == "Medium"
    assert "予約・決済・オンラインサービス" in out[0]["description"]
    assert "未確定" in out[0]["description"]
    assert "240" in out[0]["description"]
    assert "同じWebストリーム・タグID" in out[0]["suggested_fix"]


def test_cross_domain_referral_candidate_ignores_single_or_tiny_hosts():
    from measurement_design.review.health_checks import check_cross_domain_referral_candidates

    quality = {"hosts": [
        {"hostName": "www.example.jp", "sessions": "9995"},
        {"hostName": "preview.example.dev", "sessions": "5"},
    ]}
    traffic = {"source_medium": [
        {"sessionSource": "preview.example.dev", "sessionMedium": "referral", "sessions": "5"},
    ]}

    assert check_cross_domain_referral_candidates(quality, traffic, [0]) == []


def test_unassigned_channel_is_reported_when_material():
    from measurement_design.review.health_checks import check_unknown_medium_values

    traffic = {"source_medium": [
        {"sessionSource": "google", "sessionMedium": "organic",
         "sessionDefaultChannelGroup": "Organic Search", "sessions": "10000"},
        {"sessionSource": "flyer", "sessionMedium": "flyer1",
         "sessionDefaultChannelGroup": "Unassigned", "sessions": "600"},
    ]}

    out = check_unknown_medium_values(traffic, [0])

    assert len(out) == 1
    assert out[0]["severity"] == "High"
    assert "flyer / flyer1" in out[0]["description"]


def test_unassigned_channel_below_threshold_is_not_reported():
    from measurement_design.review.health_checks import check_unknown_medium_values

    traffic = {"source_medium": [
        {"sessionSource": "google", "sessionMedium": "organic",
         "sessionDefaultChannelGroup": "Organic Search", "sessions": "10000"},
        {"sessionSource": "flyer", "sessionMedium": "flyer1",
         "sessionDefaultChannelGroup": "Unassigned", "sessions": "40"},
    ]}

    assert check_unknown_medium_values(traffic, [0]) == []


def test_old_traffic_data_without_channel_group_is_not_guessed_from_medium():
    from measurement_design.review.health_checks import check_unknown_medium_values

    traffic = {"source_medium": [
        {"sessionSource": "x", "sessionMedium": "custom-medium", "sessions": "3000"},
    ]}

    assert check_unknown_medium_values(traffic, [0]) == []


def test_foreign_noise_does_not_flag_country_or_low_conversion_alone():
    """海外への集中と低成果率だけでは、機械的アクセスと判定しない。"""
    from measurement_design.review.health_checks import check_foreign_noise

    quality = {
        "countries": [
            {"country": "Japan", "sessions": "150000", "keyEvents": "560"},
            {"country": "Singapore", "sessions": "10000", "keyEvents": "2"},
        ],
        "country_environment": [
            {"country": "Japan", "browser": "Chrome", "operatingSystem": "Android", "sessions": "80000"},
            {"country": "Singapore", "browser": "Chrome", "operatingSystem": "Windows", "sessions": "9990"},
            {"country": "Singapore", "browser": "Safari", "operatingSystem": "iOS", "sessions": "10"},
        ],
    }

    assert check_foreign_noise(quality, [0]) == []


def test_foreign_noise_flags_concentration_with_multiple_behavior_signals():
    from measurement_design.review.health_checks import check_foreign_noise

    quality = {
        "countries": [
            {"country": "Japan", "sessions": "150000", "userEngagementDuration": "9000000", "bounceRate": "0.42", "keyEvents": "560"},
            {"country": "China", "sessions": "10000", "userEngagementDuration": "0", "bounceRate": "1.0", "keyEvents": "0"},
        ],
        "country_environment": [
            {"country": "China", "browser": "Chrome", "operatingSystem": "Linux", "sessions": "9900"},
            {"country": "China", "browser": "Safari", "operatingSystem": "iOS", "sessions": "100"},
        ],
    }

    out = check_foreign_noise(quality, [0])

    assert len(out) == 1
    assert out[0]["severity"] == "Medium"
    assert "China" in out[0]["description"]
    assert "平均エンゲージメント0.0秒" in out[0]["description"]
    assert "直帰率100.0%" in out[0]["description"]


def test_foreign_noise_keeps_real_overseas_traffic():
    from measurement_design.review.health_checks import check_foreign_noise

    quality = {
        "countries": [
            {"country": "Japan", "sessions": "100000", "userEngagementDuration": "5000000", "bounceRate": "0.45", "keyEvents": "300"},
            {"country": "United States", "sessions": "5000", "userEngagementDuration": "250000", "bounceRate": "0.48", "keyEvents": "18"},
        ],
        "country_environment": [
            {"country": "United States", "browser": "Chrome", "operatingSystem": "Windows", "sessions": "3000"},
        ],
    }

    assert check_foreign_noise(quality, [0]) == []


def test_form_measurement_gap_ok_when_form_start_recorded():
    from measurement_design.review.health_checks import check_form_measurement_gap

    events = {"events_30d": [{"eventName": "form_start", "eventCount": 50}]}

    assert check_form_measurement_gap(events, [0]) == []


def test_form_measurement_gap_accepts_view_without_start():
    """フォーム表示を分母にできるなら、入力開始の未取得だけでは指摘しない。"""
    from measurement_design.review.health_checks import check_form_measurement_gap

    events = {"events_30d": [{"eventName": "view_form", "eventCount": 300}]}

    out = check_form_measurement_gap(events, [0])

    assert out == []


def test_form_measurement_gap_flags_no_form_events_at_all():
    from measurement_design.review.health_checks import check_form_measurement_gap

    events = {"events_30d": [{"eventName": "page_view", "eventCount": 3000}]}

    out = check_form_measurement_gap(events, [0])

    assert len(out) == 1
    assert out[0]["severity"] == "Medium"
    assert "フォームページ" in out[0]["description"]
