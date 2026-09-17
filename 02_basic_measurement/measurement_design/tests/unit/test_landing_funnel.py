"""landing_funnel.py のユニットテスト.

CTR/CVR は「率が小さい」ことそのものが結論になる。丸めや分母の扱いを誤ると、
実態と違う結論をクライアントに渡すことになるので、そこを固定する。

- 0.06% を「0.1%」に丸めると、目標1%との距離が1桁分ぼやける
- 分母0で例外を出すと、発火0の記事が並ぶ表が作れない
- 着地ページが `(not set)` のセッションは分母の欠落。警告を出さないと
  「取れている範囲での率」を全体の率として読まれる
- 分子が小さい記事を並べると、順位がその月のブレでしかないのに
  「この記事が強い」と読まれる
"""

import pytest

from landing_funnel import (
    LANDING_UNKNOWN_WARN,
    MIN_NUMERATOR_FOR_COMPARISON,
    build_report,
    comparable_articles,
    fmt_rate,
    rate,
)


# ──────────────────────────────────────
# 率の計算と表示
# ──────────────────────────────────────

def test_rate_is_percent():
    assert rate(69, 107054) == pytest.approx(0.0644, abs=1e-4)


def test_rate_with_zero_denominator_is_zero():
    """分母0で例外を出すと、発火0の記事を含む表が作れない。"""
    assert rate(0, 0) == 0.0
    assert rate(5, 0) == 0.0


def test_small_rate_keeps_three_decimals():
    """0.06% を 0.1% に丸めると目標1%との距離が1桁ぼやける。"""
    assert fmt_rate(69, 107054) == "0.064%"


def test_large_rate_uses_two_decimals():
    assert fmt_rate(57, 6317) == "0.90%"


def test_zero_is_plain_zero():
    assert fmt_rate(0, 107054) == "0%"


# ──────────────────────────────────────
# 記事別比較の足切り
# ──────────────────────────────────────

def _article(path, sessions, **events):
    return {"path": path, "sessions": sessions, "events": events}


def test_articles_below_threshold_are_not_comparable():
    arts = [_article("/blogs/a", 9823, form_request=11),
            _article("/blogs/b", 6317, form_request=3)]
    assert comparable_articles(arts, "form_request") == []


def test_article_at_threshold_is_comparable():
    arts = [_article("/blogs/a", 6317, signup=MIN_NUMERATOR_FOR_COMPARISON)]
    assert [a["path"] for a in comparable_articles(arts, "signup")] == ["/blogs/a"]


def test_missing_event_is_treated_as_zero():
    assert comparable_articles([_article("/blogs/a", 100)], "signup") == []


# ──────────────────────────────────────
# レポート
# ──────────────────────────────────────

def _data(**kw):
    base = {
        "prefix": "/blogs", "host": "example.com", "events": ["form_request", "signup"],
        "period": {"start": "30daysAgo", "end": "yesterday"},
        "total_sessions": 854676, "landed_sessions": 107054,
        "landing_unknown_sessions": 0,
        "event_sessions": {"form_request": 69, "signup": 180},
        "articles": [_article("/blogs/a", 9823, form_request=11)],
    }
    base.update(kw)
    return base


def test_report_warns_when_landing_page_is_missing():
    text = build_report(_data(landing_unknown_sessions=341161))
    assert "分母にも分子にも入っていない" in text
    assert "341,161" in text


def test_report_does_not_claim_the_rate_direction():
    """ は分子も同時に欠けうる。率がどちらに動くかは断定できない。"""
    text = build_report(_data(landing_unknown_sessions=341161))
    assert "率がどちらに動くかは" in text
    assert "実際の率はこれより低い" not in text


def test_report_is_quiet_when_landing_page_coverage_is_fine():
    small = int(854676 * LANDING_UNKNOWN_WARN / 2)
    assert "分母にも分子にも入っていない" not in build_report(_data(landing_unknown_sessions=small))


def test_report_flags_when_no_article_is_comparable():
    text = build_report(_data())
    assert "記事間の優劣を数字で比べられる水準にない" in text


def test_report_lists_comparable_articles():
    text = build_report(_data(articles=[_article("/blogs/x", 6317, signup=57)]))
    assert "`/blogs/x`（57）" in text


def test_report_shows_small_rate_without_rounding_to_zero():
    """全体表で 0.064% がそのまま出る（0.1% や 0% に丸まらない）。"""
    assert "0.064%" in build_report(_data())


# ──────────────────────────────────────
# 取得ロジック（ga4_data.run_report を差し替えて検証）
# ──────────────────────────────────────

class _FakeGA4:
    """run_report の呼び出しを記録して、決め打ちの行を返す。"""

    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    # フィルタヘルパーは本物と同じ形の dict を返せばよい
    def filter_exact(self, f, v, case_sensitive=False):
        return {"type": "filter", "field_name": f,
                "string_filter": {"match_type": "EXACT", "value": v}}

    def filter_begins_with(self, f, v, case_sensitive=False):
        return {"type": "filter", "field_name": f,
                "string_filter": {"match_type": "BEGINS_WITH", "value": v}}

    def filter_in_list(self, f, values, case_sensitive=False):
        return {"type": "filter", "field_name": f, "in_list_filter": {"values": values}}

    def filter_and(self, filters):
        return {"type": "and", "filters": filters}

    def run_report(self, config, dimensions, metrics, start, end,
                   dimension_filter=None, order_by_metric=None, limit=0):
        self.calls.append({"dimensions": list(dimensions), "metrics": list(metrics),
                           "filter": dimension_filter, "limit": limit})
        return self.responses.pop(0)


def _install(monkeypatch, responses):
    import sys
    fake = _FakeGA4(responses)
    monkeypatch.setitem(sys.modules, "ga4_data", fake)
    return fake


def _fields(f, out=None):
    """フィルタ dict から (field_name, 値) を再帰的に集める。"""
    out = [] if out is None else out
    if not isinstance(f, dict):
        return out
    if f.get("type") == "and":
        for x in f["filters"]:
            _fields(x, out)
    elif f.get("type") == "filter":
        sf = f.get("string_filter") or {}
        il = f.get("in_list_filter") or {}
        out.append((f["field_name"], sf.get("value") or il.get("values")))
    return out


def test_fetch_uses_landing_page_not_page_path(monkeypatch):
    """分子を `pagePath` で絞ると 0 になる。着地ページで揃っていることを固定する。"""
    from landing_funnel import fetch
    fake = _install(monkeypatch, [
        [{"sessions": "854676"}], [{"sessions": "107054"}], [{"sessions": "341161"}],
        [{"sessions": "180"}],
        [{"landingPagePlusQueryString": "/blogs/a", "sessions": "9823"}],
        [{"landingPagePlusQueryString": "/blogs/a", "eventName": "signup", "sessions": "11"}],
    ])
    fetch(object(), "/blogs", ["signup"], host="example.com")
    used = {name for call in fake.calls for name, _ in _fields(call["filter"] or {})}
    assert "landingPagePlusQueryString" in used
    assert "pagePathPlusQueryString" not in used


def test_fetch_scopes_every_query_by_host(monkeypatch):
    """1本でもホスト絞りが抜けると、検証環境が混ざった率になる。"""
    from landing_funnel import fetch
    fake = _install(monkeypatch, [
        [{"sessions": "10"}], [{"sessions": "5"}], [{"sessions": "1"}], [{"sessions": "2"}],
        [{"landingPagePlusQueryString": "/blogs/a", "sessions": "5"}],
        [],
    ])
    fetch(object(), "/blogs", ["signup"], host="example.com")
    for call in fake.calls:
        assert ("hostName", "example.com") in _fields(call["filter"] or {})


def test_fetch_keeps_articles_missing_from_the_session_list(monkeypatch):
    """イベント側にだけ現れた記事を捨てると、比較対象の判定が狂う。"""
    from landing_funnel import fetch
    _install(monkeypatch, [
        [{"sessions": "1000"}], [{"sessions": "500"}], [{"sessions": "0"}], [{"sessions": "40"}],
        [{"landingPagePlusQueryString": "/blogs/a", "sessions": "400"}],
        [{"landingPagePlusQueryString": "/blogs/a", "eventName": "signup", "sessions": "5"},
         {"landingPagePlusQueryString": "/blogs/rare", "eventName": "signup", "sessions": "35"}],
    ])
    d = fetch(object(), "/blogs", ["signup"], host="example.com")
    paths = {a["path"] for a in d["articles"]}
    assert "/blogs/rare" in paths
    from landing_funnel import comparable_articles
    assert [a["path"] for a in comparable_articles(d["articles"], "signup")] == ["/blogs/rare"]


def test_fetch_flags_truncated_article_list(monkeypatch):
    from landing_funnel import fetch
    _install(monkeypatch, [
        [{"sessions": "10"}], [{"sessions": "5"}], [{"sessions": "0"}], [{"sessions": "1"}],
        [{"landingPagePlusQueryString": "/blogs/a", "sessions": "3"},
         {"landingPagePlusQueryString": "/blogs/b", "sessions": "2"}],
        [],
    ])
    d = fetch(object(), "/blogs", ["signup"], host="example.com", max_articles=2)
    assert d["articles_truncated"] is True
    assert "記事の取得が上限に達した" in build_report(d)


def test_report_is_quiet_when_article_list_is_complete():
    assert "記事の取得が上限に達した" not in build_report(_data(articles_truncated=False))
