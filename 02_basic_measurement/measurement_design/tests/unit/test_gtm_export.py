"""gtm_export.py のユニットテスト.

エクスポート JSON の読み方を誤ると、診断の結論がそのまま変わる箇所を固定する。

- `negate` は条件の `type` ではなく `parameter` 側に入る。読み落とすと除外条件が
  包含条件に反転し、「全イベント転送タグ」の発火条件を逆に読む
- `filter` と `customEventFilter` は AND。片方だけ見ると条件を取り違える
- `containerVersionId` が 0 のものはワークスペースのエクスポート。公開中と限らない
- 組み込みトリガー（All Pages 等）は `trigger` 配列に無く ID だけが参照される。
  引けないと全ページで動くタグの発火条件が「?」になって見落とす
- `tagFiringOption` の未設定は「イベントごと」。多重計上の判定に直結する
"""

import pytest

from gtm_export import (
    ANY_DATALAYER_EVENT,
    is_ga4_tag,
    build_diff,
    build_report,
    datalayer_events_of,
    duplicate_sends,
    firing_option,
    hardcoded_destinations,
    is_workspace_export,
    scan_secrets,
    trigger_conditions,
    wildcard_tags,
)


def _param(key, value, type_="TEMPLATE"):
    return {"type": type_, "key": key, "value": value}


def _cond(type_, arg0, arg1, negate=False):
    params = [_param("arg0", arg0), _param("arg1", arg1)]
    if negate:
        params.append(_param("negate", "true", "BOOLEAN"))
    return {"type": type_, "parameter": params}


def _container(tags=None, triggers=None, version="121", **kw):
    return {
        "containerVersionId": version,
        "container": {"name": "example", "publicId": "GTM-XXXXXXX"},
        "tag": tags or [],
        "trigger": triggers or [],
        "variable": [],
        **kw,
    }


# ──────────────────────────────────────
# 条件の解釈
# ──────────────────────────────────────

def test_negate_is_read_from_parameter():
    """`negate` を落とすと除外条件が包含条件に反転する。"""
    trigger = {
        "type": "CUSTOM_EVENT",
        "customEventFilter": [_cond("MATCH_REGEX", "{{_event}}", ".+")],
        "filter": [_cond("CONTAINS", "{{Event}}", "gtm.", negate=True)],
    }
    assert trigger_conditions(trigger) == [
        "{{_event}} 正規表現一致 .+ かつ NOT({{Event}} 含む gtm.)"
    ]


def test_filter_and_custom_event_filter_are_combined():
    """イベント名の条件と URL 条件は AND。片方だけ見ると対象を広く読む。"""
    trigger = {
        "type": "CUSTOM_EVENT",
        "customEventFilter": [_cond("EQUALS", "{{_event}}", "conversion")],
        "filter": [_cond("MATCH_REGEX", "{{Page URL}}", "/form/.*request_material")],
    }
    assert trigger_conditions(trigger) == [
        "{{_event}} = conversion かつ {{Page URL}} 正規表現一致 /form/.*request_material"
    ]


# ──────────────────────────────────────
# dataLayer イベントの抽出
# ──────────────────────────────────────

def test_exact_match_returns_event_name():
    trigger = {"type": "CUSTOM_EVENT",
               "customEventFilter": [_cond("EQUALS", "{{_event}}", "sign_up")]}
    assert datalayer_events_of(trigger) == ["sign_up"]


def test_regex_on_event_is_wildcard():
    """広い正規表現は個別イベント名に落とせないのでワイルドカード扱いにする。"""
    trigger = {"type": "CUSTOM_EVENT",
               "customEventFilter": [_cond("MATCH_REGEX", "{{_event}}", ".+")]}
    assert datalayer_events_of(trigger) == [ANY_DATALAYER_EVENT]


def test_negated_equals_is_not_a_target():
    """否定形は絞り込みであって対象の指定ではない。"""
    trigger = {"type": "CUSTOM_EVENT",
               "customEventFilter": [_cond("EQUALS", "{{_event}}", "gtm.dom", negate=True)]}
    assert datalayer_events_of(trigger) == [ANY_DATALAYER_EVENT]


def test_non_event_condition_ignored():
    """URL 等を見ている条件は dataLayer イベント名ではない。"""
    trigger = {"type": "CUSTOM_EVENT",
               "customEventFilter": [_cond("EQUALS", "{{Page URL}}", "/thankyou")]}
    assert datalayer_events_of(trigger) == [ANY_DATALAYER_EVENT]


# ──────────────────────────────────────
# 多重計上の検出
# ──────────────────────────────────────

def _ga4_tag(name, event_name, dest="{{GoogleAnalyticsID}}", trigger_ids=(), **kw):
    return {
        "name": name,
        "type": "gaawe",
        "parameter": [_param("eventName", event_name),
                      _param("measurementIdOverride", dest)],
        "firingTriggerId": list(trigger_ids),
        **kw,
    }


def _conv_triggers(n=2):
    return [{"triggerId": str(i), "name": f"t{i}", "type": "CUSTOM_EVENT",
             "customEventFilter": [_cond("EQUALS", "{{_event}}", "conversion")]}
            for i in range(1, n + 1)]


def test_same_event_name_and_destination_is_certain_duplicate():
    """送信先と GA4 イベント名が同じなら、GA4 上で確実に二重計上される。"""
    cv = _container(
        tags=[_ga4_tag("a", "conversion", trigger_ids=["1"]),
              _ga4_tag("b", "conversion", trigger_ids=["2"])],
        triggers=_conv_triggers())
    tags, certain = duplicate_sends(cv)["conversion"]
    assert sorted(t["name"] for t in tags) == ["a", "b"]
    assert certain is True


def test_different_event_names_are_not_certain_duplicates():
    """同じ dataLayer イベントでも、別の GA4 イベント名で送り分けるのは意図的な設計。

    `conversion` を `conversion` と `generate_lead` に切り出す構成を「二重計上」と
    断定すると、クライアントに誤った修正指示を出すことになる。
    """
    cv = _container(
        tags=[_ga4_tag("a", "conversion", trigger_ids=["1"]),
              _ga4_tag("b", "generate_lead", trigger_ids=["2"])],
        triggers=_conv_triggers())
    tags, certain = duplicate_sends(cv)["conversion"]
    assert sorted(t["name"] for t in tags) == ["a", "b"]
    assert certain is False


def test_same_event_name_to_different_destinations_is_not_certain():
    """送信先が別プロパティなら、同名でも同じプロパティ内の重複ではない。"""
    cv = _container(
        tags=[_ga4_tag("a", "conversion", dest="G-AAAAAAAAAA", trigger_ids=["1"]),  # leak-ok: 合成テストID（実在の測定IDではない）
              _ga4_tag("b", "conversion", dest="G-BBBBBBBBBB", trigger_ids=["2"])],  # leak-ok: 合成テストID（実在の測定IDではない）
        triggers=_conv_triggers())
    assert duplicate_sends(cv)["conversion"][1] is False


def test_paused_tags_are_not_counted():
    """一時停止タグは配信されない。多重計上の候補に混ぜると誤検知になる。"""
    triggers = [{"triggerId": "1", "name": "t1", "type": "CUSTOM_EVENT",
                 "customEventFilter": [_cond("EQUALS", "{{_event}}", "conversion")]}]
    cv = _container(
        tags=[_ga4_tag("a", "conversion", trigger_ids=["1"]),
              _ga4_tag("b", "conversion", trigger_ids=["1"], paused=True)],
        triggers=triggers)
    assert duplicate_sends(cv) == {}


# ──────────────────────────────────────
# googtag は GA4 専用ではない
# ──────────────────────────────────────

def _google_tag(name, tag_id):
    return {"name": name, "type": "googtag", "parameter": [_param("tagId", tag_id)]}


def test_google_ads_tag_is_not_a_ga4_tag():
    """googtag は Google 広告にも使う。種別だけで GA4 と判定すると送信先集計が壊れる。"""
    assert is_ga4_tag(_google_tag("ads", "AW-123456789")) is False  # leak-ok: ダミーの広告コンバージョンID
    assert is_ga4_tag(_google_tag("floodlight", "DC-1234567")) is False
    assert is_ga4_tag(_google_tag("ga4", "G-XXXXXXXXXX")) is True
    assert is_ga4_tag(_google_tag("var", "{{GoogleAnalyticsID}}")) is True


def test_unclassifiable_google_tag_is_not_counted_as_ga4():
    """判別できない googtag を GA4 に数えると、指摘件数が水増しされる。"""
    assert is_ga4_tag({"name": "no-id", "type": "googtag", "parameter": []}) is False
    assert is_ga4_tag(_google_tag("unknown", "XX-123")) is False


def test_ga4_event_tag_is_always_ga4():
    """gaawe は GA4 専用の種別。測定IDが読めなくても GA4 として扱う。"""
    assert is_ga4_tag({"name": "e", "type": "gaawe", "parameter": []}) is True


def test_extra_url_filter_downgrades_certainty():
    """送信先もイベント名も同じでも、URL 条件で相互排他なら同時発火しない。

    「確実に二重計上」と断定すると、実際には重複していない設定にクライアントを
    修正させることになる。
    """
    triggers = [
        {"triggerId": "1", "name": "t1", "type": "CUSTOM_EVENT",
         "customEventFilter": [_cond("EQUALS", "{{_event}}", "conversion")],
         "filter": [_cond("MATCH_REGEX", "{{Page URL}}", "/a")]},
        {"triggerId": "2", "name": "t2", "type": "CUSTOM_EVENT",
         "customEventFilter": [_cond("EQUALS", "{{_event}}", "conversion")],
         "filter": [_cond("MATCH_REGEX", "{{Page URL}}", "/b")]},
    ]
    cv = _container(
        tags=[_ga4_tag("a", "conversion", trigger_ids=["1"]),
              _ga4_tag("b", "conversion", trigger_ids=["2"])],
        triggers=triggers)
    assert duplicate_sends(cv)["conversion"][1] is False


def test_tag_with_both_conditional_and_unconditional_triggers_counts_as_unconditional():
    """1本のタグが同じイベントを無条件トリガーからも拾っていれば、無条件で発火する。

    タグ単位で「条件付きトリガーを1つでも持つか」を見ると、この構成を条件付き扱いし、
    本物の二重計上を取りこぼす。
    """
    triggers = [
        {"triggerId": "1", "name": "plain", "type": "CUSTOM_EVENT",
         "customEventFilter": [_cond("EQUALS", "{{_event}}", "conversion")]},
        {"triggerId": "2", "name": "scoped", "type": "CUSTOM_EVENT",
         "customEventFilter": [_cond("EQUALS", "{{_event}}", "conversion")],
         "filter": [_cond("MATCH_REGEX", "{{Page URL}}", "/a")]},
    ]
    cv = _container(
        tags=[_ga4_tag("a", "conversion", trigger_ids=["1", "2"]),
              _ga4_tag("b", "conversion", trigger_ids=["1"])],
        triggers=triggers)
    assert duplicate_sends(cv)["conversion"][1] is True


def test_conditional_tag_does_not_mask_unconditional_duplicate():
    """条件付きのタグが混ざっても、無条件タグ同士の確実な重複は見逃さない。

    行全体で「条件が1つでもあれば要仕分け」にすると、本物の二重計上を取りこぼす。
    """
    triggers = [
        {"triggerId": "1", "name": "t1", "type": "CUSTOM_EVENT",
         "customEventFilter": [_cond("EQUALS", "{{_event}}", "conversion")]},
        {"triggerId": "2", "name": "t2", "type": "CUSTOM_EVENT",
         "customEventFilter": [_cond("EQUALS", "{{_event}}", "conversion")]},
        {"triggerId": "3", "name": "t3", "type": "CUSTOM_EVENT",
         "customEventFilter": [_cond("EQUALS", "{{_event}}", "conversion")],
         "filter": [_cond("MATCH_REGEX", "{{Page URL}}", "/a")]},
    ]
    cv = _container(
        tags=[_ga4_tag("a", "conversion", trigger_ids=["1"]),
              _ga4_tag("b", "conversion", trigger_ids=["2"]),
              _ga4_tag("c", "conversion", trigger_ids=["3"])],
        triggers=triggers)
    assert duplicate_sends(cv)["conversion"][1] is True


def test_google_ads_tag_excluded_from_hardcoded_destinations():
    """広告タグの直書きは「検証環境が本番 GA4 に混ざる」話ではない。"""
    cv = _container(tags=[_google_tag("ads", "AW-123456789"),  # leak-ok: ダミーの広告コンバージョンID
                          _ga4_tag("hard", "x", dest="G-XXXXXXXXXX")])
    assert [t["name"] for t in hardcoded_destinations(cv)] == ["hard"]


def test_google_ads_id_not_listed_as_ga4_destination():
    cv = _container(tags=[_google_tag("ads", "AW-123456789")])  # leak-ok: ダミーの広告コンバージョンID
    text = build_report(cv)
    assert "AW-123456789" not in text.split("## 発火オプション")[0].split("## GA4 の送信先")[1]  # leak-ok: ダミーの広告コンバージョンID


def test_wildcard_tag_is_listed_separately():
    """全イベント転送タグは個別イベントの表に現れないので独立して拾う。"""
    triggers = [{"triggerId": "1", "name": "all", "type": "CUSTOM_EVENT",
                 "customEventFilter": [_cond("MATCH_REGEX", "{{_event}}", ".+")]}]
    cv = _container(tags=[_ga4_tag("forwarder", "{{Event}}", trigger_ids=["1"])],
                    triggers=triggers)
    assert [t["name"] for t in wildcard_tags(cv)] == ["forwarder"]
    assert duplicate_sends(cv) == {}


def test_hardcoded_destination_detected():
    cv = _container(tags=[_ga4_tag("var", "a"),
                          _ga4_tag("hard", "b", dest="G-XXXXXXXXXX")])
    assert [t["name"] for t in hardcoded_destinations(cv)] == ["hard"]


def test_firing_option_defaults_to_once_per_event():
    """未設定は「イベントごと」。既定を取り違えると多重計上の判定が狂う。"""
    assert firing_option({}) == "イベントごと"
    assert firing_option({"tagFiringOption": "ONCE_PER_LOAD"}) == "1ページに1回"


# ──────────────────────────────────────
# ワークスペース取り違えの検出
# ──────────────────────────────────────

@pytest.mark.parametrize("version", ["0", "", None])
def test_workspace_export_is_flagged(version):
    cv = _container(version=version)
    if version is None:
        del cv["containerVersionId"]
    assert is_workspace_export(cv) is True


def test_published_version_is_not_flagged():
    assert is_workspace_export(_container(version="121")) is False


def test_report_warns_on_workspace_export():
    text = build_report(_container(version="0"))
    assert "公開中の内容とは限らない" in text


# ──────────────────────────────────────
# 組み込みトリガー
# ──────────────────────────────────────

def test_built_in_trigger_is_named():
    """All Pages は trigger 配列に無い。ID のままだと全ページ発火を見落とす。"""
    cv = _container(tags=[_ga4_tag("pv", "page_view", trigger_ids=["2147479553"])])  # leak-ok: GTMの組み込みトリガーID（Google共通の固定値）
    assert "All Pages" in build_report(cv)


def test_unknown_built_in_trigger_is_still_visible():
    cv = _container(tags=[_ga4_tag("x", "y", trigger_ids=["2147479999"])])  # leak-ok: 未知の組み込みトリガーIDを模した合成値
    text = build_report(cv)
    assert "組み込みトリガー（ID 2147479999）" in text  # leak-ok: 未知の組み込みトリガーIDを模した合成値
    assert "?（?）" not in text


# ──────────────────────────────────────
# 差分
# ──────────────────────────────────────

def test_diff_ignores_fingerprint_and_ids():
    """fingerprint と ID の差だけで「変更」と出ると、本当の差分が埋もれる。"""
    old = _container(tags=[_ga4_tag("a", "x", fingerprint="1", tagId="10")])
    new = _container(tags=[_ga4_tag("a", "x", fingerprint="2", tagId="99")])
    assert "完全に一致している" in build_diff(old, new)


def test_diff_ignores_renumbered_trigger_ids():
    old = _container(triggers=[{"triggerId": "1", "name": "t", "type": "CUSTOM_EVENT",
                                "customEventFilter": [_cond("EQUALS", "{{_event}}", "a")]}])
    new = _container(triggers=[{"triggerId": "500", "name": "t", "type": "CUSTOM_EVENT",
                                "customEventFilter": [_cond("EQUALS", "{{_event}}", "a")]}])
    assert "完全に一致している" in build_diff(old, new)


def test_diff_reports_added_tag():
    old = _container(tags=[_ga4_tag("a", "x")])
    new = _container(tags=[_ga4_tag("a", "x"), _ga4_tag("b", "y")])
    text = build_diff(old, new)
    assert "**追加** `b`" in text
    assert "完全に一致している" not in text


# ──────────────────────────────────────
# 秘匿情報スキャン
# ──────────────────────────────────────

def test_scan_finds_token_in_custom_html():
    cv = _container(tags=[{
        "name": "leaky", "type": "html",
        "parameter": [_param("html", "<script>fetch(x,{headers:{Authorization:'Bearer abcdefghijklmnop1234'}})</script>")],
    }])
    assert scan_secrets(cv)[0][0] == "leaky"


def test_scan_is_quiet_on_clean_container():
    cv = _container(tags=[_ga4_tag("a", "x")])
    assert scan_secrets(cv) == []
