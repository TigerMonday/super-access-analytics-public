"""audit_matrix.py のユニットテスト.

**この表は「○」を出すのが仕事**なので、誤って○にする壊れ方が一番怖い。
実際に踏んだ誤検知（`テレビ電話相談予約` を電話タップと読む／GA4 の伏せ値
`--sanitized--` を未知の medium と数える／海外ノイズを「成果0件」で切って抜ける）を
ここで固定する。
"""

import json

import pytest

from measurement_design.review import audit_matrix as am


def _write(tmp_path, stem, payload):
    (tmp_path / f"{stem}.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _events(names: dict, key_events=None, firing=None):
    return {
        "events_30d": [{"eventName": n, "eventCount": c} for n, c in names.items()],
        "key_events": [{"event_name": k} for k in (key_events or [])],
        "key_event_firing": [{"eventName": k, "eventCount": c} for k, c in (firing or {}).items()],
    }


# ── 電話タップの拾い方 ──────────────────────────────

def test_tel_event_needs_a_click():
    assert am.TEL_EVENT_RE.search("電話クリック")
    assert am.TEL_EVENT_RE.search("TELクリック物件検索")
    assert am.TEL_EVENT_RE.search("click_tel")
    # オンライン相談のフォームは電話タップではない（実測で誤検知した）
    assert not am.TEL_EVENT_RE.search("テレビ電話相談予約")
    assert not am.TEL_EVENT_RE.search("フォーム閲覧_オンライン相談（テレビ電話）")


def test_key_events_flags_unregistered_phone_tap():
    ds = {"events": _events({"電話クリック": 125, "資料請求": 172},
                            key_events=["資料請求"], firing={"資料請求": 172})}

    judgement, state = am._judge_key_events(ds)

    assert judgement == "ng"
    assert "電話クリック" in state


def test_key_events_ok_when_all_fire():
    ds = {"events": _events({"資料請求": 172}, key_events=["資料請求"], firing={"資料請求": 172})}

    assert am._judge_key_events(ds)[0] == "ok"


# 発火の有無（0件かどうか）の判定は `_judge_unused_events` に一本化した（旧実装は
# ここ `_judge_key_events` と `_judge_unused_events` の両方が「発火0件」という同じ
# 事実から別々に×を立てていた）。旧・発火0件系のテスト（`test_key_events_flags_
# dead_registration` 等）は「── 使われていないイベント ──」節の
# `test_unused_events_flags_real_dead_key_event` 等に統合済み。


# ── medium の値 ──────────────────────────────────

def test_medium_without_channel_group_is_not_guessed():
    """独自medium辞書では判定せず、旧データは未確認にする。"""
    ds = {"traffic": {"source_medium": [
        {"sessionSource": "google", "sessionMedium": "organic", "sessions": "10000"},
        {"sessionSource": "x", "sessionMedium": "--sanitized--", "sessions": "3000"},
        {"sessionSource": "y", "sessionMedium": "(data not available)", "sessions": "2000"},
    ]}}

    judgement, state = am._judge_medium_values(ds)
    assert judgement == "warn"
    assert "取得していない" in state


def test_unassigned_channel_is_flagged_from_ga4_classification():
    """独自語彙ではなく、GA4自身のUnassigned分類と実績量で判断する。"""
    ds = {"traffic": {"source_medium": [
        {"sessionSource": "google", "sessionMedium": "organic",
         "sessionDefaultChannelGroup": "Organic Search", "sessions": "10000"},
        {"sessionSource": "flyer", "sessionMedium": "flyer1",
         "sessionDefaultChannelGroup": "Unassigned", "sessions": "600"},
    ]}}

    judgement, state = am._judge_medium_values(ds)

    assert judgement == "ng"
    assert "flyer1" in state
    assert "未分類" in state


def test_small_unassigned_volume_is_not_reported():
    ds = {"traffic": {"source_medium": [
        {"sessionSource": "google", "sessionMedium": "organic",
         "sessionDefaultChannelGroup": "Organic Search", "sessions": "10000"},
        {"sessionSource": "flyer", "sessionMedium": "flyer1",
         "sessionDefaultChannelGroup": "Unassigned", "sessions": "40"},
    ]}}

    assert am._judge_medium_values(ds)[0] == "ok"


def test_missing_data_never_reads_as_ok():
    """データが無いときに ok を返すと「見たが問題なし」と読まれる。"""
    empty = {"events": {}, "traffic": {}, "pages": {}, "defs": {}, "quality": {}, "property": {}, "gtm": {}}

    for judge in (am._judge_unused_events, am._judge_internal_utm,
                  am._judge_url_variants, am._judge_metrics, am._judge_medium_values,
                  am._judge_cross_domain, am._judge_page_pii):
        assert judge(empty)[0] != "ok", judge.__name__


# ── 使われていないイベント ───────────────────────────

def test_unused_events_flags_real_dead_key_event():
    ds = {"events": _events({"資料請求": 172}, key_events=["資料請求", "line_reserve"],
                            firing={"資料請求": 172, "line_reserve": 0})}

    judgement, state = am._judge_unused_events(ds)

    assert judgement == "ng"
    assert "line_reserve" in state


def test_unused_events_excludes_purchase():
    """purchase はどのプロパティにも既定で入るため、単独の発火0件では×にしない。"""
    ds = {"events": _events({"資料請求": 172}, key_events=["資料請求", "purchase"],
                            firing={"資料請求": 172, "purchase": 0})}

    judgement, state = am._judge_unused_events(ds)

    assert judgement == "ok"
    assert "purchase" in state  # 除外した事実は文に残す


def test_unused_events_still_ng_when_other_event_dead_alongside_purchase():
    """purchase 以外にも発火なしがあれば、除外後も×のまま。"""
    ds = {"events": _events({}, key_events=["資料請求", "purchase"],
                            firing={"資料請求": 0, "purchase": 0})}

    judgement, state = am._judge_unused_events(ds)

    assert judgement == "ng"
    assert "資料請求" in state


def test_ad_conversion_tags_counted_from_tag_type():
    """`counts.ad_conversion_tags` は存在しないキーだった。タグの種類から数える。"""
    ds = {
        "property": {"ads_links": [{"customer_id": "1"}]},
        "gtm": {"tags": [{"function": "__awct"}] * 82 + [{"function": "__html"}]},
    }

    judgement, state = am._judge_ads_links(ds)

    assert judgement == "ok"
    assert "82本" in state


def test_measurement_ids_come_from_tag_destination():
    """公開 GTM JSON にトップレベルの measurement_ids は無い。"""
    ds = {"gtm": {
        "counts": {"tags": 332},
        "tags": [
            {"function": "__gaawe", "destination": "G-KZBRFBG017"},  # leak-ok: 合成テストID（実在の測定IDではない）
            {"function": "__gaawe", "destination": "G-7NSD7H0CLJ"},  # leak-ok: 合成テストID（実在の測定IDではない）
            {"function": "__paused", "destination": "G-KZBRFBG017"},  # leak-ok: 合成テストID（実在の測定IDではない）
            {"function": "__html", "destination": ""},
        ],
    }}

    assert am._measurement_ids(ds) == {"G-KZBRFBG017", "G-7NSD7H0CLJ"}  # leak-ok: 合成テストID（実在の測定IDではない）

    judgement, state = am._judge_tag_containers(ds)

    assert judgement == "warn"
    assert "2種類" in state and "停止中 1本" in state


def test_judge_tag_containers_and_access_support_api_schema():
    """GTM API 経路（gtm.py→run_phase3）は `counts`/`source` を持たない。

    このキー前提で判定していたため、API で24タグ等を正常取得していても
    「タグマネージャーの設定を読めていない」「取得していない」と誤って
    判定されていた（実データの検証で発覚したバグ）。API 経路のスキーマ
    （`live_version`/`tags`（`type`/`paused`）/`measurement_ids`）でも
    正しく判定できることを固定する。
    """
    ds = {"gtm": {
        "live_version": {"version_id": "12", "name": "v12", "description": "定期更新"},
        "tag_analysis": [{"name": "GA4設定タグ", "type": "googtag"}],
        "measurement_ids": ["G-KZBRFBG017"],  # leak-ok: 合成テストID（実在の測定IDではない）
        "tags": [
            {"name": "GA4設定タグ", "type": "googtag", "paused": False},
            {"name": "旧HTML", "type": "html", "paused": True},
        ],
        "triggers": [{"triggerId": "1"}] * 18,
        "variables": [{"name": "v"}] * 50,
    }}

    judgement, state = am._judge_tag_containers(ds)
    assert judgement == "warn"  # 送信先GA4測定IDは1種類のみなので断定はしない
    assert "タグ2本" in state and "独自HTML 1本" in state and "停止中 1本" in state

    judgement, state = am._judge_gtm_access(ds)
    assert judgement == "ok"
    assert "APIで設定を読めている" in state


def test_judge_tag_containers_api_schema_flags_multiple_destinations():
    ds = {"gtm": {
        "live_version": {"name": "v1"},
        "tags": [{"name": "a", "type": "gaawe", "paused": False},
                 {"name": "b", "type": "gaawe", "paused": False}],
        "measurement_ids": ["G-AAAAAAAAAA", "G-BBBBBBBBBB"],  # leak-ok: 合成テストID（実在の測定IDではない）
    }}

    judgement, state = am._judge_tag_containers(ds)

    assert judgement == "warn"
    assert "2種類" in state


def test_judge_gtm_access_warns_when_no_gtm_data_at_all():
    assert am._judge_gtm_access({"gtm": {}}) == ("warn", "タグマネージャーの設定を取得していない")


# ── 海外からの機械的アクセス ─────────────────────────

def test_foreign_noise_does_not_flag_country_or_low_conversion_alone():
    """海外への集中と低成果率だけでは、機械的アクセスと判定しない。"""
    quality = {
        "countries": [
            {"country": "Japan", "sessions": "150000", "keyEvents": "560"},
            {"country": "Singapore", "sessions": "10000", "keyEvents": "2"},
        ],
        "country_environment": [
            {"country": "Japan", "browser": "Chrome", "operatingSystem": "Android", "sessions": "80000"},
            {"country": "Japan", "browser": "Safari", "operatingSystem": "iOS", "sessions": "70000"},
            {"country": "Singapore", "browser": "Chrome", "operatingSystem": "Windows", "sessions": "9990"},
            {"country": "Singapore", "browser": "Safari", "operatingSystem": "iOS", "sessions": "10"},
        ],
    }

    judgement, state = am._judge_foreign_noise({"quality": quality})

    assert judgement == "ok"
    assert "複数異常" in state


def test_foreign_noise_flags_concentration_with_multiple_behavior_signals():
    quality = {
        "countries": [
            {"country": "Japan", "sessions": "150000", "userEngagementDuration": "9000000", "bounceRate": "0.42", "keyEvents": "560"},
            {"country": "Singapore", "sessions": "10000", "userEngagementDuration": "0", "bounceRate": "0.99", "keyEvents": "0"},
        ],
        "country_environment": [
            {"country": "Singapore", "browser": "Chrome", "operatingSystem": "Windows", "sessions": "9990"},
            {"country": "Singapore", "browser": "Safari", "operatingSystem": "iOS", "sessions": "10"},
        ],
    }

    judgement, state = am._judge_foreign_noise({"quality": quality})

    assert judgement == "warn"
    assert "Singapore" in state
    assert "平均エンゲージメント0.0秒" in state
    assert "直帰率99.0%" in state


def test_foreign_noise_keeps_real_overseas_traffic():
    quality = {
        "countries": [
            {"country": "Japan", "sessions": "100000", "userEngagementDuration": "5000000", "bounceRate": "0.45", "keyEvents": "300"},
            {"country": "United States", "sessions": "5000", "userEngagementDuration": "250000", "bounceRate": "0.48", "keyEvents": "18"},
        ],
        "country_environment": [
            {"country": "United States", "browser": "Chrome", "operatingSystem": "Windows", "sessions": "3000"},
            {"country": "United States", "browser": "Safari", "operatingSystem": "iOS", "sessions": "2000"},
        ],
    }

    assert am._judge_foreign_noise({"quality": quality})[0] == "ok"


# ── そのほかの判定 ───────────────────────────────

def test_multiple_scroll_depths_are_allowed_with_enhanced_measurement():
    ds = {
        "property": {"enhanced_measurement_1": {"scrolls_enabled": True}},
        "events": _events({"scroll": 25043, "10%": 197208, "90%": 21587}),
    }

    judgement, state = am._judge_scroll(ds)

    assert judgement == "ok"
    assert "併用は正常" in state


def test_event_names_ignores_japanese_flags_spec_violations():
    """日本語はGA4が公式に許可しているため対象外。数字始まり・空白入りは仕様外として数える。"""
    ds = {"events": _events({"資料請求": 1, "10%": 2, "cv view_area": 3, "page_view": 4})}

    judgement, state = am._judge_event_names(ds)

    assert judgement == "ng"
    assert "資料請求" not in state
    assert "10%" in state or "cv view_area" in state


def test_event_names_uppercase_only_is_warn_not_ng():
    """大文字を含むだけなら仕様違反ではないので warn（分裂のおそれ）止まり。"""
    ds = {"events": _events({"click_CTA": 5, "page_view": 4})}

    judgement, state = am._judge_event_names(ds)

    assert judgement == "warn"
    assert "修正は必須ではない" in state


def test_hyphen_and_uppercase_are_low_priority_notes():
    ds = {"events": _events({"form-submit": 5, "click_CTA": 3})}
    judgement, state = am._judge_event_names(ds)
    assert judgement == "warn"
    assert "大文字・ハイフンを含む名前が2件" in state
    assert "修正は必須ではない" in state


def test_event_names_japanese_requires_data_integration_fix():
    ds = {"events": _events({"資料請求": 1, "page_view": 4})}

    judgement, state = am._judge_event_names(ds)
    assert judgement == "warn"
    assert "データ連携" in state


def test_event_names_notes_the_fetch_cap_when_list_is_at_the_limit():
    """`events_30d` は上位100件の取得上限がある。ちょうど上限件数のときは、
    「◯種のうち」の分母が実際のイベント総数ではなく上限である可能性を本文に注記する
    （分母を鵜呑みにされない）。上限未満なら注記は出さない。"""
    from measurement_design.review.health_checks import EVENTS_LIST_LIMIT

    at_limit = {f"ev_{i}": 1 for i in range(EVENTS_LIST_LIMIT)}
    ds_at_limit = {"events": _events(at_limit)}

    judgement, state = am._judge_event_names(ds_at_limit)

    assert judgement == "ok"
    assert f"取得上限{EVENTS_LIST_LIMIT}件" in state

    below_limit = {f"ev_{i}": 1 for i in range(EVENTS_LIST_LIMIT - 1)}
    ds_below_limit = {"events": _events(below_limit)}

    _, state_below = am._judge_event_names(ds_below_limit)

    assert "取得上限" not in state_below


# ── 申込の手前の計測 ──────────────────────────────

def test_micro_events_accepts_form_page_measurement_for_b2b():
    """名前だけでフォーム到達の実装が正しいとは判定しない。"""
    ds = {"events": _events({"view_form": 10, "view_search_results": 5, "page_view": 100})}

    judgement, state = am._judge_micro_events(ds)

    assert judgement == "warn"
    assert "網羅性は未確認" in state


def test_micro_events_ng_state_explains_why_it_matters_when_none_found():
    ds = {"events": _events({"page_view": 100})}

    judgement, state = am._judge_micro_events(ds)

    assert judgement == "ng"
    assert "離脱したか追えず" in state


def test_internal_utm_flags_popup_medium():
    ds = {"traffic": {"source_medium": [
        {"sessionSource": "satori", "sessionMedium": "pop", "sessions": "3084"},
    ]}}

    assert am._judge_internal_utm(ds)[0] == "ng"


def test_bigquery_and_retention():
    assert am._judge_bigquery({"property": {"bigquery_links": []}})[0] == "warn"
    assert am._judge_bigquery({"property": {"bigquery_links": [{"name": "x"}]}})[0] == "warn"
    assert am._judge_retention({"property": {"data_retention": {"event_data_retention": "FOURTEEN_MONTHS"}}})[0] == "ok"
    assert am._judge_retention({"property": {"data_retention": {"event_data_retention": "TWO_MONTHS"}}})[0] == "warn"


def test_observation_does_not_prove_internal_filter_or_search_working():
    ds = {"quality": {"hosts": [{"hostName": "example.com", "sessions": 100}]}}
    judgement, state = am._judge_internal_traffic(ds)
    assert judgement == "warn"
    assert "除外設定・適用状態は未確認" in state
    ds = {"property": {"enhanced_measurement_x": {"site_search_enabled": True}},
          "events": _events({"page_view": 100}),
          "pages": {"pages": [{"pagePath": "/", "screenPageViews": 100}]}}
    judgement, state = am._judge_site_search(ds)
    assert judgement == "warn"
    assert "0件" in state


def test_internal_traffic_row_shows_major_host_outside_target_site():
    ds = {
        "property": {"data_streams": [{"web_stream_data": {"default_uri": "https://www.example.com"}}]},
        "quality": {"hosts": [
            {"hostName": "www.example.com", "sessions": 900},
            {"hostName": "form.vendor.example", "sessions": 100},
        ]},
    }
    judgement, state = am._judge_internal_traffic(ds)
    assert judgement == "warn"
    assert "対象サイト（example.com）以外" in state
    assert "form.vendor.example" in state


def test_scroll_receipt_does_not_rule_out_gtm_duplicates():
    ds = {"property": {"enhanced_measurement_x": {"scrolls_enabled": True}},
          "events": _events({"scroll": 12})}
    judgement, state = am._judge_scroll(ds)
    assert judgement == "ok"
    assert "12件受信" in state
    assert "識別パラメータ" in state


def test_scroll_depth_events_do_not_prove_duplicate_measurement():
    ds = {"property": {"enhanced_measurement_x": {"scrolls_enabled": True}},
          "events": _events({"scroll": 12, "scroll_50": 30})}
    judgement, state = am._judge_scroll(ds)
    assert judgement == "ok"
    assert "併用は正常" in state


def test_zero_scroll_and_search_named_article_do_not_prove_working_or_broken():
    ds = {"property": {"enhanced_measurement_x": {"scrolls_enabled": True, "site_search_enabled": True}},
          "events": _events({"page_view": 100}),
          "pages": {"pages": [{"pagePath": "/blog/search-marketing", "screenPageViews": 100}]}}
    assert am._judge_scroll(ds)[0] == "warn"
    judgement, state = am._judge_site_search(ds)
    assert judgement == "warn"
    assert "検索結果ページかを確認" in state


def test_attribution_reports_both_lookback_windows():
    ds = {"property": {"attribution": {
        "reporting_attribution_model": "PAID_AND_ORGANIC_CHANNELS_DATA_DRIVEN",
        "acquisition_conversion_event_lookback_window": "ACQUISITION_CONVERSION_EVENT_LOOKBACK_WINDOW_30_DAYS",
        "other_conversion_event_lookback_window": "OTHER_CONVERSION_EVENT_LOOKBACK_WINDOW_90_DAYS"}}}
    _, state = am._judge_attribution(ds)
    assert "新規獲得イベントの参照期間30日" in state
    assert "その他イベント90日" in state


def test_optional_ad_link_and_small_campaign_count_not_error():
    assert am._judge_ads_links({"property": {"ads_links": []}})[0] == "warn"
    assert am._judge_ads_links({"property": {}})[0] == "warn"
    ds = {"traffic": {"campaigns": [
        {"sessionMedium": "cpc", "sessionCampaignName": "spring", "sessions": 3}]}}
    assert am._judge_campaign_values(ds)[0] == "ok"
    ds["traffic"]["campaigns"][0]["sessionCampaignName"] = "(not set)"
    judgement, state = am._judge_campaign_values(ds)
    assert judgement == "warn"
    assert "3セッション" in state


def test_content_groups_counts_paths_not_dimension_rows():
    ds = {"pages": {"content_groups": [{"contentGroup": "(not set)", "screenPageViews": 7}],
                    "pages": [{"pagePath": "/a", "pageTitle": "A"},
                              {"pagePath": "/a", "pageTitle": "B"}, {"pagePath": "/b"}]}}
    judgement, state = am._judge_content_groups(ds)
    assert judgement == "warn"
    assert "2種類のパス" in state


def test_url_variants_do_not_prove_identical_content():
    ds = {"pages": {"pages": [{"pagePath": "/a", "sessions": 30},
                              {"pagePath": "/a/", "sessions": 30}]}}
    judgement, state = am._judge_url_variants(ds)
    assert judgement == "warn"
    assert "内容の同一性" in state
    assert "同じ内容で割れている" not in state


# ── 表全体 ──────────────────────────────────────

def test_audit_matrix_returns_every_item_even_with_no_data(tmp_path):
    """データが無くても表は返す。1項目の欠けで全体が出ないほうが困る。"""
    rows = am.audit_matrix(tmp_path)

    assert len(rows) == len(am.ITEMS)
    assert {r["area"] for r in rows} <= set(am.AREAS)
    assert all(r["judgement"] in ("ok", "warn", "ng") for r in rows)


def test_audit_matrix_wires_public_site_scan_into_ua_continuity(tmp_path):
    """`09-site-implementation.json` がある場合はGTM API欠損で先に止めない。"""
    (tmp_path / "01-property.json").write_text(
        json.dumps({"data_streams": []}), encoding="utf-8",
    )
    (tmp_path / "09-site-implementation.json").write_text(
        json.dumps({
            "source": {"method": "public_site_scan", "url": "https://example.com"},
            "ga4_measurement_ids": ["G-AAA11111"],  # leak-ok: 合成テストID
            "universal_analytics_ids": [],
            "tags": [{"function": "__googtag"}],
        }),
        encoding="utf-8",
    )

    rows = am.audit_matrix(tmp_path)
    ua = next(row for row in rows if row["name"] == "UA経由の計測継続性")

    assert ua["judgement"] == "ok"
    assert "取得した公開実装" in ua["state"]
    assert "データが取れていない" not in ua["state"]


def test_render_matrix_has_counts_and_legend(tmp_path):
    rows = [
        {"area": "GA4本体の設定", "name": "データ保持", "judgement": "ok", "state": "14ヶ月"},
        {"area": "GA4本体の設定", "name": "参照元の除外", "judgement": "ng", "state": "自社が参照扱い"},
    ]

    md = am.render_matrix(rows)

    assert "### GA4本体の設定（2項目のうち ×1 / △0 / ○1）" in md
    assert "| データ保持 | ○ | 14ヶ月 |" in md
    assert "×要修正" in md
    assert "実操作での動作確認を終えた意味ではない" in md


def test_counts_totals():
    rows = [{"judgement": j} for j in ("ok", "ok", "warn", "ng")]

    assert am.counts(rows) == {"ok": 2, "warn": 1, "ng": 1}


def test_referral_exclusion_catches_sibling_domain():
    """`example.jp` と `example.co.jp` は末尾2ラベルが違う。ブランド名で見ないと見逃す。"""
    ds = {
        "property": {"data_streams": [{"web_stream_data": {"default_uri": "https://www.example.jp/"}}]},
        "traffic": {"source_medium": [
            {"sessionSource": "example.co.jp", "sessionMedium": "referral", "sessions": "2414"},
        ]},
    }

    judgement, state = am._judge_referral_exclusion(ds)

    assert judgement == "ng"
    assert "2,414" in state


def test_referral_absence_does_not_prove_exclusion_setting():
    ds = {
        "property": {"data_streams": [{"web_stream_data": {"default_uri": "https://www.example.jp/"}}]},
        "traffic": {"source_medium": [
            {"sessionSource": "suumo.jp", "sessionMedium": "referral", "sessions": "321"},
        ]},
    }

    assert am._judge_referral_exclusion(ds)[0] == "warn"
    assert "除外設定は未確認" in am._judge_referral_exclusion(ds)[1]


def test_referral_exclusion_surfaces_external_checkout_source():
    ds = {
        "property": {"data_streams": [{"web_stream_data": {"default_uri": "https://www.example.jp/"}}]},
        "traffic": {"source_medium": [
            {"sessionSource": "www.paypal.com", "sessionMedium": "referral", "sessions": "18"},
        ]},
    }

    judgement, state = am._judge_referral_exclusion(ds)

    assert judgement == "warn"
    assert "paypal.com" in state
    assert "除外する参照のリスト" in state


def test_enhanced_measurement_summarizes_enabled_and_disabled_features():
    ds = {"property": {"enhanced_measurement_1": {
        "stream_enabled": True,
        "scrolls_enabled": True,
        "outbound_clicks_enabled": False,
    }}}

    judgement, state = am._judge_enhanced_measurement(ds)

    assert judgement == "ok"
    assert "スクロール" in state
    assert "離脱クリック" in state


def test_user_provided_data_reports_collection_and_automatic_detection():
    ds = {"property": {"user_provided_data": {
        "user_provided_data_collection_enabled": True,
        "automatically_detected_data_collection_enabled": False,
    }}}

    assert am._judge_user_provided_data(ds) == ("ok", "有効（自動検出は無効）")


def test_reporting_identity_explains_blended_definition():
    ds = {"property": {"reporting_identity": {"reporting_identity": "BLENDED"}}}

    judgement, state = am._judge_reporting_identity(ds)

    assert judgement == "ok"
    assert "User-ID、デバイスID、モデリング" in state


# ── クロスドメイン計測 ──────────────────────────────

def test_cross_domain_single_host_does_not_prove_scope():
    """未計測の外部フォーム等があり得るため、受信ホストだけで対象外にしない。"""
    ds = {"quality": {"hosts": [{"hostName": "www.example.jp", "sessions": 10000}]}, "traffic": {}}

    judgement, state = am._judge_cross_domain(ds)

    assert judgement == "warn"
    assert "主要ホストは1つ" in state
    assert "www.example.jp" in state


def test_cross_domain_ignores_not_set_and_stray_dev_host():
    """`(not set)`・空文字は数えない。全体の1%未満の単発ホスト（開発端末やbot）も数えない。"""
    ds = {"quality": {"hosts": [
        {"hostName": "www.example.jp", "sessions": 9990},
        {"hostName": "(not set)", "sessions": 5},
        {"hostName": "", "sessions": 4},
        {"hostName": "dev.example.jp", "sessions": 1},  # 全体の1%未満
    ]}, "traffic": {}}

    judgement, state = am._judge_cross_domain(ds)

    assert judgement == "warn"
    assert "主要ホストは1つ" in state


def test_cross_domain_marks_measured_host_referral_for_confirmation():
    """主要ホスト由来のreferralだけでは実際のホスト間分断を確定しない。"""
    ds = {
        "quality": {"hosts": [
            {"hostName": "shop.example.jp", "sessions": 6000},
            {"hostName": "www.example.jp", "sessions": 4000},
        ]},
        "traffic": {"source_medium": [
            {"sessionSource": "www.example.jp", "sessionMedium": "referral", "sessions": "820"},
            {"sessionSource": "google", "sessionMedium": "organic", "sessions": "5000"},
        ]},
    }

    judgement, state = am._judge_cross_domain(ds)

    assert judgement == "warn"
    assert "www.example.jp" in state
    assert "820" in state
    assert "未確定" in state


def test_cross_domain_no_referral_does_not_prove_continuity():
    """自己参照不在だけではユーザー・セッションの継続性を確認できない。"""
    ds = {
        "quality": {"hosts": [
            {"hostName": "shop.example.jp", "sessions": 6000},
            {"hostName": "www.example.jp", "sessions": 4000},
        ]},
        "traffic": {"source_medium": [
            {"sessionSource": "google", "sessionMedium": "organic", "sessions": "5000"},
            {"sessionSource": "suumo.jp", "sessionMedium": "referral", "sessions": "300"},
        ]},
    }

    judgement, state = am._judge_cross_domain(ds)

    assert judgement == "warn"
    assert "自己参照は取得範囲で見つからない" in state


def test_cross_domain_cannot_judge_without_host_data():
    """受信ホスト名が取れていないときは○にしない。"""
    assert am._judge_cross_domain({"quality": {}, "traffic": {}})[0] == "warn"


def test_cross_domain_multi_host_without_traffic_data_is_not_ok():
    """複数ドメインまで分かっても、流入データが無ければ自己参照の有無は判定できない。"""
    ds = {"quality": {"hosts": [
        {"hostName": "shop.example.jp", "sessions": 6000},
        {"hostName": "www.example.jp", "sessions": 4000},
    ]}, "traffic": {}}

    judgement, state = am._judge_cross_domain(ds)

    assert judgement == "warn"
    assert "流入のデータが取れていない" in state


# 注: `audit_matrix` を check-report テンプレートへ差し込む節（{{audit_matrix_table}}）は
# renderer.py の render_check_report / _build_audit_matrix_table 側で統合済み
# （tests/unit/test_renderer.py 参照）。ここでは判定表そのものと、判定表項目と指摘の
# 対応関係（violation_matrix_items。下の「判定表の項目と指摘の対応関係」節）だけを見る。
def test_no_item_reports_ok_without_data(tmp_path):
    """**データが無いときに ○ を返す項目が1つもないこと。**

    codex レビューで3巡連続して「欠損で ok」を指摘された。個別に塞ぐと漏れるので、
    要るデータセットを `ITEMS` に宣言して `audit_matrix` が先に止める形にした。
    この不変条件をここで固定する。
    """
    rows = am.audit_matrix(tmp_path)

    assert len(rows) == len(am.ITEMS)
    assert [r for r in rows if r["judgement"] == "ok"] == []
    assert all("取れていない" in r["state"] for r in rows), [r for r in rows if "取れていない" not in r["state"]]


# ── タグ種別の正規化（API形式／公開gtm.js形式） ────────────

def test_tag_kind_normalizes_both_schemas():
    """`type`（API）と `function`（公開gtm.js）のどちらでも同じ表記になる。"""
    assert am._tag_kind({"type": "awct"}) == "awct"
    assert am._tag_kind({"function": "__awct"}) == "awct"
    assert am._tag_kind({"function": "__paused"}) == "paused"
    assert am._tag_kind({}) == ""


def test_ad_conversion_tags_counted_from_api_schema():
    """GTM API経由（`type`）でも本数を数えられる。

    直した時点では `function == "__awct"`（公開gtm.js形式）専用だったため、
    API経由のデータでは常に0本になっていた（このテストが無いと再発する）。
    """
    ds = {
        "property": {"ads_links": [{"customer_id": "1"}]},
        "gtm": {"tags": [{"type": "awct"}] * 3 + [{"type": "html"}]},
    }

    judgement, state = am._judge_ads_links(ds)

    assert judgement == "ok"
    assert "3本" in state


def test_ads_links_needs_declaration_does_not_require_gtm(tmp_path):
    """「Google広告とのリンク」は GTM 未取得でも GA4 の Admin API だけで判定できる
    (試用フィードバックで検出)。

    見ているのは「リンクされているか」であり、それは `ads_links` だけで分かる。
    GTM未取得（タグ数が確かめられない）を理由に△へ丸めるのは、この項目にとって
    無関係な論点で判定を過剰に慎重にしていた不具合だった（試用フィードバックで検出）。
    リンクがあるなら○を確定させる。旧実装はさらに `ITEMS` の `needs` に "gtm" を
    含めていたため、GTM未取得のとき `audit_matrix` が判定関数を呼ぶ前に「タグマネージャー
    のデータが取れていない」という汎用文へ丸めてしまい、判定関数側の分岐へ処理が
    到達してすらいなかった。
    """
    needs = next(needs for area, name, judge, needs in am.ITEMS if name == "Google広告とのリンク")
    assert "gtm" not in needs

    _write(tmp_path, "01-property", {"ads_links": [{"customer_id": "1"}]})
    # GTM（09）のファイルは書かない = GTM未取得を再現する。

    rows = am.audit_matrix(tmp_path)
    row = next(r for r in rows if r["name"] == "Google広告とのリンク")

    assert row["judgement"] == "ok"
    assert "アカウントとリンク済み" in row["state"]
    assert "タグマネージャーのデータが取れていない" not in row["state"]
    assert "確かめられていない" not in row["state"]


def test_ad_conversion_optimization_is_not_a_machine_item():
    names = {name for _, name, _, _ in am.ITEMS}
    assert "広告コンバージョンの発火条件" not in names
    assert "成果の条件が現行URLと合っているか" not in names
    assert len(am.ITEMS) == 37
    assert {"GA4本体の設定", "広告連携", "GTM"} <= {area for area, _, _, _ in am.ITEMS}


# ── 広告コンバージョンのラベル重複 ────────────────────

def test_duplicate_ad_conversion_labels_no_target_when_no_ad_tags():
    ds = {"gtm_api": {"tags": [{"name": "GA4", "type": "gaawe"}]}}

    judgement, state = am._judge_duplicate_ad_conversion_labels(ds)

    assert judgement == "ok"
    assert "対象なし" in state


def test_duplicate_ad_conversion_labels_flags_shared_pair():
    ds = {"gtm_api": {"tags": [
        {"name": "CV_A", "type": "awct",
         "parameter": [{"key": "conversionId", "value": "AW-111"},
                       {"key": "conversionLabel", "value": "abcDEF"}]},
        {"name": "CV_B", "type": "awct",
         "parameter": [{"key": "conversionId", "value": "AW-111"},
                       {"key": "conversionLabel", "value": "abcDEF"}]},
    ]}}

    judgement, state = am._judge_duplicate_ad_conversion_labels(ds)

    assert judgement == "ng"
    assert "CV_A" in state and "CV_B" in state


def test_duplicate_ad_conversion_labels_ok_when_all_distinct():
    ds = {"gtm_api": {"tags": [
        {"name": "CV_A", "type": "awct",
         "parameter": [{"key": "conversionId", "value": "AW-111"},
                       {"key": "conversionLabel", "value": "abcDEF"}]},
        {"name": "CV_B", "type": "awct",
         "parameter": [{"key": "conversionId", "value": "AW-222"},
                       {"key": "conversionLabel", "value": "ghiJKL"}]},
    ]}}

    judgement, state = am._judge_duplicate_ad_conversion_labels(ds)

    assert judgement == "ok"
    assert "見つからない" in state


def test_duplicate_ad_conversion_labels_warns_when_unresolvable():
    """定数まで解決できない場合は○にせず、判定できないと言い切る。"""
    ds = {"gtm_api": {
        "tags": [
            {"name": "CV_A", "type": "awct",
             "parameter": [{"key": "conversionId", "value": "AW-111"},
                           {"key": "conversionLabel", "value": "{{LT}}"}]},
            {"name": "CV_B", "type": "awct",
             "parameter": [{"key": "conversionId", "value": "AW-111"},
                           {"key": "conversionLabel", "value": "{{LT}}"}]},
        ],
        "variables": [{"name": "LT", "type": "smm", "parameter": [
            {"key": "map", "type": "list", "list": [
                {"type": "map", "map": [{"key": "key", "value": "a"}, {"key": "value", "value": "x"}]},
            ]}]}],
    }}

    judgement, state = am._judge_duplicate_ad_conversion_labels(ds)

    assert judgement == "warn"
    assert "判定できない" in state


# ── キーイベントの発火条件 ──────────────────────────

def test_non_outcome_key_events_no_target_when_no_key_events():
    ds = {"events": {"key_events": []}, "gtm_api": {"tags": []}}

    judgement, state = am._judge_non_outcome_key_events(ds)

    assert judgement == "ok"
    assert "対象なし" in state


def test_non_outcome_key_events_accepts_scroll_as_possible_mcv():
    ds = {
        "events": {"key_events": [{"event_name": "download_thanks"}]},
        "gtm_api": {
            "tags": [{"name": "GA4_DL", "type": "gaawe", "firingTriggerId": ["9"],
                     "parameter": [{"key": "eventName", "value": "download_thanks"}]}],
            "triggers": [{"triggerId": "9", "name": "SD90", "type": "scrollDepth"}],
        },
    }

    judgement, state = am._judge_non_outcome_key_events(ds)

    assert judgement == "ok"
    assert "発火範囲が広すぎる設定は見つからない" in state


def test_non_outcome_key_events_warns_for_unfiltered_link_click():
    ds = {
        "events": {"key_events": [{"event_name": "cta_click"}]},
        "gtm_api": {
            "tags": [{"name": "GA4_CTA", "type": "gaawe", "firingTriggerId": ["9"],
                     "parameter": [{"key": "eventName", "value": "cta_click"}]}],
            "triggers": [{"triggerId": "9", "name": "全リンク", "type": "linkClick"}],
        },
    }

    judgement, state = am._judge_non_outcome_key_events(ds)

    assert judgement == "warn"
    assert "絞り込み条件を確認できない" in state


def test_non_outcome_key_events_ok_when_traced_and_clean():
    ds = {
        "events": {"key_events": [{"event_name": "download_thanks"}]},
        "gtm_api": {
            "tags": [{"name": "GA4_DL", "type": "gaawe", "firingTriggerId": ["1"],
                     "parameter": [{"key": "eventName", "value": "download_thanks"}]}],
            "triggers": [{"triggerId": "1", "name": "DLサンクス", "type": "pageview"}],
        },
    }

    judgement, state = am._judge_non_outcome_key_events(ds)

    assert judgement == "ok"
    assert "追跡できた" in state


def test_non_outcome_key_events_ok_but_notes_when_not_traceable_via_gtm():
    """GTMに対応するタグが無いのは異常ではない。○のまま、その旨を書く。"""
    ds = {
        "events": {"key_events": [{"event_name": "contact_service_thanks"}]},
        "gtm_api": {"tags": [], "triggers": []},
    }

    judgement, state = am._judge_non_outcome_key_events(ds)

    assert judgement == "ok"
    assert "GTMからは確認できない" in state


def test_non_outcome_key_events_warns_when_event_name_unresolvable():
    ds = {
        "events": {"key_events": [{"event_name": "download_thanks"}]},
        "gtm_api": {
            "tags": [{"name": "GA4_不明", "type": "gaawe", "firingTriggerId": ["9"],
                     "parameter": [{"key": "eventName", "value": "{{LT}}"}]}],
            "triggers": [{"triggerId": "9", "name": "SD90", "type": "scrollDepth"}],
            "variables": [{"name": "LT", "type": "smm", "parameter": [
                {"key": "map", "type": "list", "list": [
                    {"type": "map", "map": [{"key": "key", "value": "a"}, {"key": "value", "value": "x"}]},
                ]}]}],
        },
    }

    judgement, state = am._judge_non_outcome_key_events(ds)

    assert judgement == "warn"
    assert "判定できない" in state


# ── UA経由の計測継続性 ──────────────────────────────

def test_ua_continuity_no_target_without_ua_tags():
    ds = {"gtm_api": {"tags": [{"type": "googtag"}]}, "property": {}, "quality": {}}

    judgement, state = am._judge_ua_continuity(ds)

    assert judgement == "ok"
    assert "対象なし" in state


def test_ua_continuity_warns_not_ng_when_bridge_suspected():
    """GA4の測定IDがコンテナに無く、稼働中のUAタグがある＝ブリッジの疑い。

    データだけでは断定できないため（gtag.js直書き・別コンテナの可能性がある）、
    ×ではなく△で言い切る。
    """
    ds = {
        "gtm_api": {"tags": [{"name": "UA本番", "type": "ua"}], "triggers": [], "variables": []},
        "property": {"data_streams": [{"web_stream_data": {"measurement_id": "G-AAA11111"}}]},  # leak-ok: 合成テストID（実在の測定IDではない）
        "quality": {},
    }

    judgement, state = am._judge_ua_continuity(ds)

    assert judgement == "warn"
    assert "G-AAA11111" in state  # leak-ok: 合成テストID（実在の測定IDではない）


def test_ua_continuity_warns_when_active_but_ga4_tag_present():
    """UAタグは残っているが、GA4のGoogleタグが別にあり届いている。"""
    ds = {
        "gtm_api": {"tags": [
            {"name": "UA本番", "type": "ua"},
            {"name": "Gタグ", "type": "googtag", "parameter": [{"key": "tagId", "value": "G-AAA11111"}]},  # leak-ok: 合成テストID（実在の測定IDではない）
        ], "triggers": [], "variables": []},
        "property": {"data_streams": [{"web_stream_data": {"measurement_id": "G-AAA11111"}}]},  # leak-ok: 合成テストID（実在の測定IDではない）
        "quality": {},
    }

    judgement, state = am._judge_ua_continuity(ds)

    assert judgement == "warn"
    assert "UA本番" in state


def test_ua_continuity_warns_on_paused_only_ua_tags():
    ds = {
        "gtm_api": {"tags": [{"name": "UA停止中", "type": "ua", "paused": True}],
                    "triggers": [], "variables": []},
        "property": {},
        "quality": {},
    }

    judgement, state = am._judge_ua_continuity(ds)

    assert judgement == "warn"
    assert "UA停止中" in state


def test_ua_continuity_uses_direct_site_ids_without_gtm_api():
    """GTM APIが無くても、公開HTMLのGA4/UA IDは判定根拠にする。"""
    ds = {
        "gtm_api": {},
        "gtm": {},
        "site_implementation": {
            "source": {"method": "public_site_scan", "url": "https://example.com"},
            "ga4_measurement_ids": ["G-AAA11111"],  # leak-ok: 合成テストID
            "universal_analytics_ids": ["UA-12345-1"],  # leak-ok: 合成テストID
            "tags": [],
        },
        "property": {},
        "quality": {},
    }

    judgement, state = am._judge_ua_continuity(ds)

    assert judgement == "warn"
    assert "UA-12345-1" in state  # leak-ok: 合成テストID
    assert "別経路" in state


def test_ua_continuity_uses_public_gtm_tags_without_gtm_api():
    ds = {
        "gtm_api": {},
        "gtm": {
            "source": {"method": "public_gtm_js"},
            "tags": [
                {"function": "__ua", "container_id": "GTM-TEST001"},  # leak-ok: 合成テストID
                {"function": "__googtag", "destination": "G-AAA11111"},  # leak-ok: 合成テストID
            ],
        },
        "site_implementation": {},
        "property": {},
        "quality": {},
    }

    judgement, state = am._judge_ua_continuity(ds)

    assert judgement == "warn"
    assert "公開GTM" in state
    assert "別経路" in state


def test_ua_continuity_ok_when_public_site_has_ga4_and_no_ua():
    ds = {
        "gtm_api": {},
        "gtm": {},
        "site_implementation": {
            "source": {"method": "public_site_scan", "url": "https://example.com"},
            "ga4_measurement_ids": ["G-AAA11111"],  # leak-ok: 合成テストID
            "universal_analytics_ids": [],
            "tags": [],
        },
        "property": {},
        "quality": {},
    }

    judgement, state = am._judge_ua_continuity(ds)

    assert judgement == "ok"
    assert "公開実装" in state
    assert "残存は見つからない" in state


def test_ua_continuity_explains_missing_both_sources():
    ds = {
        "gtm_api": {}, "gtm": {}, "site_implementation": {},
        "property": {}, "quality": {},
    }

    judgement, state = am._judge_ua_continuity(ds)

    assert judgement == "warn"
    assert "GTM APIと公開サイト" in state


# ── イベント作成ルールの陳腐化・重複 ───────────────────

def _event_rule(dest, value, comparison="EQUALS"):
    # `check_stale_event_create_rules` は field 名に "url"／"location" を含む
    # 条件だけを見る（`page_path` は対象外）。実データの GA4 イベント作成ルールの
    # フィールド名（`page_location`）に合わせる。
    return {
        "destination_event": dest,
        "event_conditions": [
            {"field": "event_name", "comparison_type": "EQUALS", "value": "page_view"},
            {"field": "page_location", "comparison_type": comparison, "value": value},
        ],
    }


def test_duplicate_event_rules_flags_identical_conditions():
    ds = {"defs": {"event_create_rules_1": [
        _event_rule("diag_school", "/trial-lesson"),
        _event_rule("diag_online", "/trial-lesson"),
    ]}}

    judgement, state = am._judge_duplicate_event_rules(ds)

    assert judgement == "ng"
    assert "diag_school" in state and "diag_online" in state


def test_duplicate_event_rules_ok_when_conditions_differ():
    ds = {"defs": {"event_create_rules_1": [
        _event_rule("a", "/one"), _event_rule("b", "/two"),
    ]}}

    judgement, state = am._judge_duplicate_event_rules(ds)

    assert judgement == "ok"


def test_duplicate_event_rules_no_target_when_no_rules():
    ds = {"defs": {"custom_dimensions": []}}

    judgement, state = am._judge_duplicate_event_rules(ds)

    assert judgement == "ok"
    assert "対象なし" in state


# ── 判定表の項目と指摘の対応関係（check-report統合） ─────────────
#
# 判定表の×・△行は state 文にIDを持たない（「指摘IDの羅列が多すぎる」「IDいらない」
# という試用フィードバックへの対応。§2〜§5・改善ロードマップと揃えた）。
# `violation_matrix_items` は id → 判定表項目名 の対応関係だけを計算する
# （内部検証で指摘と判定項目の対応に使う。judge関数が指摘を作る check_* 関数を
# 直接呼んでいる項目に限る）。

def test_violation_matrix_items_links_url_variants_to_matching_id():
    """ユーザー例: 『URLの表記ゆれ ×』の行に対応する health_checks の指摘IDが引ける。"""
    violations = [{
        "id": "V-H-abc123", "severity": "Low", "category": "レポートの分裂",
        "target_kind": "measurement", "target_name": "1組のURL", "location": "GA4",
        "description": "...", "suggested_fix": "...",
    }]

    out = am.violation_matrix_items(violations)

    assert out == {"V-H-abc123": "URLの表記ゆれ"}


def test_violation_matrix_items_leaves_unmapped_categories_out():
    """紐付け対象に登録していない項目（例: クロスドメイン計測。判定関数が check_* を
    直接呼んでおらず、指摘との対応を保証できないため未登録）は対応表に出ない。"""
    violations = [{
        "id": "V-H-999999", "category": "データ品質の何か別軸", "location": "GA4",
        "target_kind": "measurement", "target_name": "検証環境の混入", "severity": "High",
        "description": "", "suggested_fix": "",
    }]

    out = am.violation_matrix_items(violations)

    assert out == {}


def test_violation_matrix_items_mixed_list_maps_only_matched_ones():
    """未紐付け（予約語衝突など判定表に対応項目が無いもの）と紐付け対象が混在しても、

    紐付け対象だけが対応表に入り、未紐付けのIDは含まれない（対応する行が無い＝
    renderer側で「—」表示になるケース）。
    """
    violations = [
        {"id": "V-H-abc123", "category": "レポートの分裂", "location": "GA4",
         "target_kind": "measurement", "target_name": "1組のURL", "severity": "Low",
         "description": "", "suggested_fix": ""},
        {"id": "V-002", "category": "予約語衝突", "location": "GA4",
         "target_kind": "event", "target_name": "error", "severity": "Critical",
         "description": "", "suggested_fix": ""},
    ]

    out = am.violation_matrix_items(violations)

    assert out == {"V-H-abc123": "URLの表記ゆれ"}
    assert "V-002" not in out


def test_violation_matrix_items_empty_when_no_violations():
    assert am.violation_matrix_items([]) == {}
    assert am.violation_matrix_items(None) == {}


def test_violation_matrix_items_links_only_key_event_outcome_check():
    violations = [
        {"id": "V-AD-1", "category": "発火範囲の確認", "location": "GTM", "target_kind": "tag",
         "target_name": "読了率90%", "severity": "High",
         "description": "Google 広告のコンバージョンタグ「読了率90%」が...", "suggested_fix": ""},
        {"id": "V-KE-1", "category": "発火範囲の確認", "location": "GTM", "target_kind": "tag",
         "target_name": "download_thanks", "severity": "Low",
         "description": "キーイベント「download_thanks」に対応するGA4イベントタグ「GA4_DL」が...",
         "suggested_fix": ""},
    ]

    out = am.violation_matrix_items(violations)

    assert out == {"V-KE-1": "キーイベントの発火条件"}


# ── ×でも改善ロードマップに出ない5項目の紐付け（health_checks への一本化） ──
#
# 内部トラフィックの除外・参照元の除外・種類（medium）の値・海外からの機械的アクセス・
# フォーム操作の計測の5項目は、判定関数が check_* を直接呼ぶようになった
# （audit_matrix.py から health_checks.py へロジックを移した）ので、対応する
# 指摘IDが対応表に引けることを確認する。

@pytest.mark.parametrize(("item_name", "category"), [
    ("内部トラフィックの除外", "データ品質"),
    ("参照元の除外", "自己参照"),
    ("種類（medium）の値", "流入分類"),
    ("海外からの機械的アクセス（ノイズ）", "海外ノイズ"),
    ("フォーム操作の計測", "フォーム未計測"),
])
def test_violation_matrix_items_links_newly_wired_items(item_name, category):
    violations = [{
        "id": "V-H-abcdef", "category": category, "location": "GA4",
        "target_kind": "measurement", "target_name": "x", "severity": "High",
        "description": "", "suggested_fix": "",
    }]

    out = am.violation_matrix_items(violations)

    assert out == {"V-H-abcdef": item_name}


def test_violation_matrix_items_maps_many_matches_without_truncating():
    """一致する指摘は全件を対応表に載せる（判定表側には出さないため、上限で切る必要が無い）。"""
    violations = [
        {"id": f"V-{i:06x}", "category": "命名規則", "target_kind": "event",
         "target_name": f"event_{i}", "location": "GA4", "severity": "High",
         "description": "", "suggested_fix": ""}
        for i in range(49)
    ]

    out = am.violation_matrix_items(violations)

    assert len(out) == 49
    assert all(v == "イベント名の表記" for v in out.values())


# ── 個人情報の混入 ───────────────────────────

def test_judge_page_pii_ok_when_nothing_found():
    ds = {"pages": {"pages": [
        {"pagePath": "/blog/how-to-use-ga4/", "screenPageViews": 100, "sessions": 90},
    ]}}
    judgement, state = am._judge_page_pii(ds)
    assert judgement == "ok"
    assert "取得したページパス" in state
    assert "イベントパラメータ全体は未確認" in state


def test_judge_page_pii_ng_when_token_found():
    ds = {"pages": {"pages": [
        {"pagePath": "/mypage/reset_password/aB3dE7fG9hJ2kL4mN6pQ8r/",
         "screenPageViews": 3, "sessions": 3},
    ]}}
    judgement, state = am._judge_page_pii(ds)
    assert judgement == "ng"
    assert "1件" in state


def test_violation_matrix_items_links_page_pii():
    """判定表の「個人情報の混入」行に対応する指摘IDが対応表から引ける.

    `_judge_page_pii` の state 文は件数しか書かない（対象ページ名を出さない）ため、
    この対応関係が無いと判定表の行から詳しい内容に辿り着けない。
    """
    violations = [{
        "id": "V-H-def456", "severity": "Critical", "category": "個人情報の混入",
        "target_kind": "page", "target_name": "/mypage/reset_password/****",
        "location": "GA4", "description": "...", "suggested_fix": "...",
    }]
    out = am.violation_matrix_items(violations)
    assert out == {"V-H-def456": "個人情報の混入"}
