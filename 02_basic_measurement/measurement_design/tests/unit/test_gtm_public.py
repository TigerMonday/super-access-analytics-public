"""gtm_public.py のユニットテスト.

`Event` を対象にした述語の解釈は、誤ると診断の結論が変わる。

- 広い正規表現を取りこぼす → 全イベントを二重送信しているタグが一覧に出ない
- 狭い正規表現を広く解釈する → 「全イベントに掛かる」Critical の誤検知
- 列挙を合成名1つで返す → 個別タグと関連づかず実在する多重発火を見落とす

3つとも実際に踏んだので、境界をテストで固定する。
"""

import pytest


def _resolver(fn, arg1, arg0=None):
    from gtm_public import Resolver
    return Resolver({
        "macros": [{"function": "__e"}],
        "predicates": [{"function": fn, "arg0": arg0 or ["macro", 0], "arg1": arg1}],
    })


# ──────────────────────────────────────
# 完全一致
# ──────────────────────────────────────

def test_exact_match_returns_event_name():
    assert _resolver("_eq", "signup").datalayer_events_of(0) == ["signup"]


def test_non_event_predicate_ignored():
    """Event 以外（URL 等）を見ている述語は対象にしない。"""
    r = _resolver("_eq", "/thankyou", arg0=["macro", 9])
    assert r.datalayer_events_of(0) == []


@pytest.mark.parametrize("fn", ["_neq", "_nc", "_nr"])
def test_negations_are_not_targets(fn):
    """`gtm.` を含まない等の否定形は絞り込みであって対象の指定ではない。"""
    assert _resolver(fn, "gtm.").datalayer_events_of(0) == []


# ──────────────────────────────────────
# 広い正規表現（全イベント扱い）
# ──────────────────────────────────────

@pytest.mark.parametrize("pattern", [".+", ".*", ".", "^.*$", "^.+$"])
def test_broad_patterns_are_all_events(pattern):
    from gtm_public import ANY_DATALAYER_EVENT
    assert _resolver("_re", pattern).datalayer_events_of(0) == [ANY_DATALAYER_EVENT]


# ──────────────────────────────────────
# 列挙は1件ずつに展開する
# ──────────────────────────────────────

@pytest.mark.parametrize("pattern,expected", [
    ("^(login|sign_up)$", ["login", "sign_up"]),
    ("(login|sign_up)", ["login", "sign_up"]),
    ("^login$", ["login"]),
])
def test_alternatives_split_into_individual_events(pattern, expected):
    """合成名1つにすると個別タグと関連づかず、多重発火を見落とす。"""
    assert _resolver("_re", pattern).datalayer_events_of(0) == expected


@pytest.mark.parametrize("pattern", ["^checkout_", "signup", "note_.*_click"])
def test_non_enumeration_patterns_kept_as_condition(pattern):
    """前方一致などは列挙ではない。名前に見せると実在しないイベント名を作る。"""
    from gtm_public import ANY_DATALAYER_EVENT
    got = _resolver("_re", pattern).datalayer_events_of(0)
    assert len(got) == 1
    assert got[0].startswith("(条件:")
    assert got[0] != ANY_DATALAYER_EVENT


def test_contains_predicate_kept_as_condition():
    got = _resolver("_cn", "signup").datalayer_events_of(0)
    assert got and got[0].startswith("(条件:")


# ──────────────────────────────────────
# レポートの集計は保存済みフィールドを使う
# ──────────────────────────────────────

def test_datalayer_events_uses_normalized_field_not_display_text():
    """`fire_on` の表示文字列を再解析すると完全一致以外を取りこぼす。"""
    from gtm_public import datalayer_events
    data = {"tags": [
        {"index": 1, "function": "__gaawe", "event_name": "signup",
         "datalayer_events": ["sign_up"],
         "fire_on": ["Event = sign_up"]},
        {"index": 2, "function": "__gaawe", "event_name": "Event",
         "datalayer_events": ["(すべてのカスタムイベント)"],
         # 表示文字列には `Event = ` の形が出てこない
         "fire_on": ["Event 正規表現一致 .+ かつ NOT(Event 含む gtm.)"]},
    ]}
    got = datalayer_events(data)
    assert "sign_up" in got
    assert "(すべてのカスタムイベント)" in got, "正規表現のタグが集計から漏れている"


# ──────────────────────────────────────
# 公開サイトの実装スキャン
# ──────────────────────────────────────

def test_inspect_site_combines_direct_ids_and_public_container(monkeypatch):
    import gtm_public

    html = (
        '<script src="https://www.googletagmanager.com/gtm.js?id=GTM-XXXXXXX"></script>'
        '<script>gtag("config", "G-XXXXXXXXXX"); gtag("config", "UA-0000-0")</script>'
    )
    monkeypatch.setattr(gtm_public, "http_get", lambda url: html)
    monkeypatch.setattr(gtm_public, "fetch_container", lambda container_id: "raw")
    monkeypatch.setattr(gtm_public, "parse_resource", lambda raw: {"tags": []})
    monkeypatch.setattr(
        gtm_public,
        "normalize",
        lambda resource, container_id, source_url: {
            "source": {"method": "public_gtm_js", "container_id": container_id},
            "tags": [{"function": "__ua"}],
        },
    )

    got = gtm_public.inspect_site("https://example.com")

    assert got["gtm_containers"] == ["GTM-XXXXXXX"]
    assert got["ga4_measurement_ids"] == ["G-XXXXXXXXXX"]
    assert got["universal_analytics_ids"] == ["UA-0000-0"]
    assert got["tags"] == [{"function": "__ua", "container_id": "GTM-XXXXXXX"}]
    assert got["counts"] == {"tags": 1, "containers": 1}


def test_inspect_site_keeps_direct_ids_when_public_container_fails(monkeypatch):
    import gtm_public

    monkeypatch.setattr(
        gtm_public,
        "http_get",
        lambda url: '<script src="https://x.test/?id=GTM-XXXXXXX"></script>'
                    '<script>gtag("config", "G-XXXXXXXXXX")</script>',
    )
    monkeypatch.setattr(
        gtm_public, "fetch_container",
        lambda container_id: (_ for _ in ()).throw(OSError("network")),
    )

    got = gtm_public.inspect_site("https://example.com")

    assert got["ga4_measurement_ids"] == ["G-XXXXXXXXXX"]
    assert got["tags"] == []
    assert got["container_errors"] == [{"container_id": "GTM-XXXXXXX", "error": "OSError"}]
