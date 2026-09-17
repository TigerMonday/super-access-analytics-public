"""2026-08 のミライズ英会話案件で見つけた不備を一般化した検査のテスト。

この案件では、**キットの review を通しても検出されなかった**不備が手作業で見つかった。
同じものを次の案件で機械的に拾えるようにするのがこのファイルの目的。

とくに「イベント作成ルールの取りこぼし」は、ルール自体は発火しているため
既存の `check_stale_event_create_rules`（条件URLに実績が無いルールを探す）では
原理的に見つからない。境界を間違えると誤報も見逃しも起きるので、ここで固定する。
"""


# ──────────────────────────────────────
# 共通のダミーデータ
# ──────────────────────────────────────

def _defs(rules):
    return {"event_create_rules_1": rules}


def _rule(dest, value, comparison="EQUALS_CASE_INSENSITIVE", field="page_path"):
    return {
        "destination_event": dest,
        "event_conditions": [
            {"field": "event_name", "comparison_type": "EQUALS", "value": "page_view"},
            {"field": field, "comparison_type": comparison, "value": value},
        ],
    }


def _pages(rows):
    return {"pages": [{"pagePath": p, "screenPageViews": str(pv), "sessions": str(se)}
                      for p, pv, se in rows]}


def _gtm(tags=(), triggers=(), measurement_ids=()):
    return {"tags": list(tags), "triggers": list(triggers),
            "measurement_ids": list(measurement_ids)}


# ──────────────────────────────────────
# イベント作成ルール — 同じページの別URL表記の取りこぼし
# ──────────────────────────────────────

def test_url_variants_flags_html_suffix_miss():
    """完全一致で、拡張子つきの主導線を丸ごと落としているケース。

    実案件の数値そのまま: `/trial-lesson` 31セッション /
    `/trial-lesson.html` 102セッション。後者がサイト内リンクの行き先だった。
    """
    from measurement_design.review.health_checks import check_event_rule_url_variants
    out = check_event_rule_url_variants(
        _defs([_rule("form_view", "/trial-lesson")]),
        _pages([("/trial-lesson", 62, 31), ("/trial-lesson.html", 275, 102)]),
        [0],
    )
    assert len(out) == 1
    # 取りこぼしのほうが多いので Critical
    assert out[0]["severity"] == "Critical"
    assert "/trial-lesson.html" in out[0]["description"]
    assert "102" in out[0]["description"]
    assert "133" in out[0]["description"]


def _suggested_regex(violation):
    """指摘の修正案に載っている、最初の完全一致の正規表現を取り出す。

    `page_location` の場合は注記に `page_path` 用の代替式も併記されるので、
    **先頭に出てくる主たる式**を取る（バッククォートで囲まれた `^...$`）。
    """
    import re
    m = re.search(r"`(\^[^`]+\$)`", violation["suggested_fix"])
    assert m, violation["suggested_fix"]
    return re.compile(m.group(1))


def test_url_variants_warns_against_contains_fix():
    """直し方の落とし穴を必ず書く。

    「含む」「前方一致」にすると /trial-lesson-complete まで拾って
    今度は逆に水増しになる。実際にこの誤った直し方をレビューで指摘された。
    """
    from measurement_design.review.health_checks import check_event_rule_url_variants
    out = check_event_rule_url_variants(
        _defs([_rule("form_view", "/trial-lesson")]),
        _pages([("/trial-lesson", 62, 31), ("/trial-lesson.html", 275, 102)]),
        [0],
    )
    fix = out[0]["suggested_fix"]
    assert "してはいけない" in fix
    assert "正規表現" in fix
    # 提示した式が、実際に両方の表記へ当たること
    rx = _suggested_regex(out[0])
    assert rx.fullmatch("/trial-lesson")
    assert rx.fullmatch("/trial-lesson.html")
    assert not rx.fullmatch("/trial-lesson-complete.html")


def test_url_variants_regex_works_for_reverse_case():
    """条件が拡張子つき側で、取りこぼしが拡張子なし側のとき。

    値に (.html)? を足す組み立て方だと、条件が既に .html 側のときに
    拡張子なしへ当たらない式になる。提示する式が両方へ当たることを確かめる。
    """
    from measurement_design.review.health_checks import check_event_rule_url_variants
    out = check_event_rule_url_variants(
        _defs([_rule("form_view", "/foo.html")]),
        _pages([("/foo.html", 60, 30), ("/foo", 280, 110)]),
        [0],
    )
    assert len(out) == 1
    rx = _suggested_regex(out[0])
    assert rx.fullmatch("/foo.html")
    assert rx.fullmatch("/foo")
    # 完了ページのような前方一致する別ページは拾わない
    assert not rx.fullmatch("/foo-complete.html")


def test_url_variants_regex_works_for_root_case():
    """ルートと index.html でも提示式が両方に当たる。"""
    from measurement_design.review.health_checks import check_event_rule_url_variants
    out = check_event_rule_url_variants(
        _defs([_rule("top_view", "/")]),
        _pages([("/", 200, 100), ("/index.html", 900, 400)]),
        [0],
    )
    rx = _suggested_regex(out[0])
    assert rx.fullmatch("/")
    assert rx.fullmatch("/index.html")


def test_url_variants_groups_rules_sharing_one_condition():
    """同一条件のルールが複数あっても、指摘は1件にまとめる。"""
    from measurement_design.review.health_checks import check_event_rule_url_variants
    out = check_event_rule_url_variants(
        _defs([_rule("a", "/trial-lesson"), _rule("b", "/trial-lesson"),
               _rule("c", "/trial-lesson")]),
        _pages([("/trial-lesson", 62, 31), ("/trial-lesson.html", 275, 102)]),
        [0],
    )
    assert len(out) == 1
    for name in ("a", "b", "c"):
        assert name in out[0]["target_name"]


def test_url_variants_ignores_contains_comparison():
    """`含む` は別表記も拾えるので、この検査の対象外。"""
    from measurement_design.review.health_checks import check_event_rule_url_variants
    out = check_event_rule_url_variants(
        _defs([_rule("form_view", "/trial-lesson", comparison="CONTAINS")]),
        _pages([("/trial-lesson", 62, 31), ("/trial-lesson.html", 275, 102)]),
        [0],
    )
    assert out == []


def test_url_variants_ignores_small_miss():
    """取りこぼしが誤差の範囲なら指摘しない（誤報を避ける）。"""
    from measurement_design.review.health_checks import check_event_rule_url_variants
    out = check_event_rule_url_variants(
        _defs([_rule("form_view", "/trial-lesson")]),
        _pages([("/trial-lesson", 900, 400), ("/trial-lesson.html", 5, 2)]),
        [0],
    )
    assert out == []


def test_url_variants_treats_index_html_as_same_page():
    """`/` と `/index.html` は同じページとして扱う。

    ただし取りこぼし率が閾値未満（実案件では 8.1%）なら計測漏れとしては出さない。
    数字が2行に割れること自体は check_duplicate_page_urls が拾う。
    """
    from measurement_design.review.health_checks import (
        _page_variants, check_event_rule_url_variants)
    assert "/index.html" in _page_variants("/")
    out = check_event_rule_url_variants(
        _defs([_rule("top_view", "/")]),
        _pages([("/", 4275, 1996), ("/index.html", 432, 176)]),
        [0],
    )
    assert out == []


def test_url_variants_flags_index_html_when_miss_is_large():
    """同じ `/` でも、取りこぼしが大きければ計測漏れとして出す。"""
    from measurement_design.review.health_checks import check_event_rule_url_variants
    out = check_event_rule_url_variants(
        _defs([_rule("top_view", "/")]),
        _pages([("/", 200, 100), ("/index.html", 900, 400)]),
        [0],
    )
    assert len(out) == 1
    assert out[0]["severity"] == "Critical"


def test_url_variants_ignores_click_rules():
    """クリックから作るルールは対象外。

    `link_url` の値はクリック先であってページではない。`/trial-lesson.html` に
    ページ実績があっても「そのリンクが押された」証拠にはならないため、
    ページ実績と突き合わせると生きているルールを誤って計測漏れにする。
    """
    from measurement_design.review.health_checks import check_event_rule_url_variants
    click_rule = {
        "destination_event": "cta_click",
        "event_conditions": [
            {"field": "event_name", "comparison_type": "EQUALS", "value": "click"},
            {"field": "link_url", "comparison_type": "EQUALS", "value": "/trial-lesson"},
        ],
    }
    out = check_event_rule_url_variants(
        _defs([click_rule]),
        _pages([("/trial-lesson", 62, 31), ("/trial-lesson.html", 275, 102)]),
        [0],
    )
    assert out == []


def test_url_variants_ignores_rule_without_page_view_condition():
    """`event_name = page_view` の条件が無いルールは判定しない。"""
    from measurement_design.review.health_checks import check_event_rule_url_variants
    rule = {
        "destination_event": "something",
        "event_conditions": [
            {"field": "page_path", "comparison_type": "EQUALS", "value": "/trial-lesson"},
        ],
    }
    out = check_event_rule_url_variants(
        _defs([rule]),
        _pages([("/trial-lesson", 62, 31), ("/trial-lesson.html", 275, 102)]),
        [0],
    )
    assert out == []


def test_url_variants_regex_matches_field_page_location():
    """`page_location` はフルURLなので、提示式にホスト部分を含める。

    パスだけの式を同じフィールドに当てるとどちらにも一致せず、
    指摘した漏れが直らない修正案になる。
    """
    from measurement_design.review.health_checks import check_event_rule_url_variants
    out = check_event_rule_url_variants(
        _defs([_rule("form_view", "https://ex.com/foo", field="page_location")]),
        _pages([("/foo", 60, 30), ("/foo.html", 280, 110)]),
        [0],
    )
    assert len(out) == 1
    rx = _suggested_regex(out[0])
    assert rx.fullmatch("https://ex.com/foo")
    assert rx.fullmatch("https://ex.com/foo.html")
    assert not rx.fullmatch("https://ex.com/foo-complete.html")
    # フィールド名を本文に出す（どちらの条件の話か分かるように）
    assert "page_location" in out[0]["description"]


def test_ua_bridge_resolves_lookup_table_variable():
    """ルックアップテーブル変数で測定IDを渡している構成を誤検知しない。

    ホスト別に本番／検証を切り替える書き方では `G-` の値が map の中に入る。
    `value` だけを見ると空になり、偽の停止リスクを出す。
    """
    from measurement_design.review.health_checks import check_ga4_via_ua_bridge
    prop = {"data_streams": [{"web_stream_data": {"measurement_id": "G-PROD1111"}}]}  # leak-ok: 合成テストID（実在の測定IDではない）
    gtm = _gtm(tags=[{"name": "UA本番", "type": "ua"},
                     {"name": "Gタグ", "type": "googtag",
                      "parameter": [{"key": "tagId", "value": "{{測定ID_LT}}"}]}])
    gtm["variables"] = [{
        "name": "測定ID_LT",
        "type": "smm",
        "parameter": [
            {"key": "input", "value": "{{Page Hostname}}"},
            {"key": "map", "type": "list", "list": [
                {"type": "map", "map": [
                    {"key": "key", "value": "example.com"},
                    {"key": "value", "value": "G-PROD1111"}]},  # leak-ok: 合成テストID（実在の測定IDではない）
                {"type": "map", "map": [
                    {"key": "key", "value": "stg.example.com"},
                    {"key": "value", "value": "G-STG2222"}]},  # leak-ok: 合成テストID（実在の測定IDではない）
            ]},
        ],
    }]
    assert check_ga4_via_ua_bridge(gtm, prop, [0]) == []


def test_active_measurement_ids_from_lookup_table():
    from measurement_design.review.health_checks import _active_ga4_measurement_ids
    gtm = _gtm(tags=[{"name": "Gタグ", "type": "googtag",
                      "parameter": [{"key": "tagId", "value": "{{LT}}"}]}])
    gtm["variables"] = [{"name": "LT", "parameter": [
        {"key": "map", "type": "list", "list": [
            {"type": "map", "map": [{"key": "value", "value": "G-AAA"}]},
            {"type": "map", "map": [{"key": "value", "value": "G-BBB"}]},
        ]}]}]
    assert _active_ga4_measurement_ids(gtm) == {"G-AAA", "G-BBB"}


# ──────────────────────────────────────
# 同じページが複数URLで計測されている（レポートの分裂）
# ──────────────────────────────────────

def test_duplicate_page_urls_reports_split():
    from measurement_design.review.health_checks import check_duplicate_page_urls
    out = check_duplicate_page_urls(
        _pages([("/", 4275, 1996), ("/index.html", 432, 176),
                ("/plan.html", 596, 240), ("/plan", 100, 60)]),
        [0],
    )
    assert len(out) == 1
    assert out[0]["category"] == "レポートの分裂"
    assert "2組" in out[0]["description"]


def test_duplicate_page_urls_cannot_see_moved_paths():
    """ディレクトリ違いの重複は、この検査では拾えない。

    実案件の `/plan/online.html` と `/online.html` は同じ内容だったが、
    それは両方を取得してバイト比較して分かったこと。GA4 のデータだけでは
    別ページと区別できない。**拾えないことを既知の制約として固定する**
    （将来 URL を実際に取得して比べる検査を足すなら、そちらの仕事）。
    """
    from measurement_design.review.health_checks import check_duplicate_page_urls
    out = check_duplicate_page_urls(
        _pages([("/plan/online.html", 686, 277), ("/online.html", 50, 22)]), [0])
    assert out == []


def test_duplicate_page_urls_ignores_tiny_second_url():
    """片方がごく少数なら、実質分裂していないので出さない。"""
    from measurement_design.review.health_checks import check_duplicate_page_urls
    out = check_duplicate_page_urls(
        _pages([("/", 4275, 1996), ("/index.html", 2, 1)]), [0])
    assert out == []


def test_duplicate_page_urls_silent_when_single_representation():
    from measurement_design.review.health_checks import check_duplicate_page_urls
    out = check_duplicate_page_urls(
        _pages([("/", 4275, 1996), ("/plan.html", 596, 240)]), [0])
    assert out == []


def test_url_variants_does_not_treat_complete_page_as_variant():
    """`/trial-lesson-complete` は別のページ。別表記として数えてはいけない。"""
    from measurement_design.review.health_checks import check_event_rule_url_variants
    out = check_event_rule_url_variants(
        _defs([_rule("form_view", "/trial-lesson")]),
        _pages([("/trial-lesson", 62, 31),
                ("/trial-lesson-complete.html", 100, 45)]),
        [0],
    )
    assert out == []


# ──────────────────────────────────────
# イベント作成ルール — 条件が同一で多重計上
# ──────────────────────────────────────

def test_duplicate_event_rules_detects_identical_conditions():
    from measurement_design.review.health_checks import check_duplicate_event_rules
    out = check_duplicate_event_rules(
        _defs([_rule("diag_school", "/trial-lesson"),
               _rule("diag_online", "/trial-lesson"),
               _rule("diag_coaching", "/trial-lesson")]),
        [0],
    )
    assert len(out) == 1
    assert "3 件" in out[0]["description"]
    assert out[0]["category"] == "多重計上"


def test_duplicate_event_rules_ignores_distinct_conditions():
    from measurement_design.review.health_checks import check_duplicate_event_rules
    out = check_duplicate_event_rules(
        _defs([_rule("a", "/one"), _rule("b", "/two")]), [0])
    assert out == []


# ──────────────────────────────────────
# 拡張計測が実質すべて無効
# ──────────────────────────────────────

def test_enhanced_measurement_all_off():
    from measurement_design.review.health_checks import check_enhanced_measurement_disabled
    prop = {"enhanced_measurement_1": {"stream_enabled": True,
                                       "search_query_parameter": "q,s"}}
    out = check_enhanced_measurement_disabled(prop, [0])
    assert len(out) == 1
    # パラメータだけ設定されていて機能が無効、という状態も言い当てる
    assert "サイト内検索そのものが無効" in out[0]["description"]


def test_enhanced_measurement_partially_on_is_ok():
    from measurement_design.review.health_checks import check_enhanced_measurement_disabled
    prop = {"enhanced_measurement_1": {"stream_enabled": True, "scrolls_enabled": True}}
    assert check_enhanced_measurement_disabled(prop, [0]) == []


def test_enhanced_measurement_ignores_disabled_stream():
    """ストリーム自体が無効なら、拡張計測の話にはならない。"""
    from measurement_design.review.health_checks import check_enhanced_measurement_disabled
    prop = {"enhanced_measurement_1": {"stream_enabled": False}}
    assert check_enhanced_measurement_disabled(prop, [0]) == []


# ──────────────────────────────────────
# GTM — Universal Analytics の残存
# ──────────────────────────────────────

def test_universal_analytics_tags_active_and_paused():
    from measurement_design.review.health_checks import check_universal_analytics_tags
    out = check_universal_analytics_tags(_gtm(tags=[
        {"name": "UA本番", "type": "ua"},
        {"name": "UA停止中", "type": "ua", "paused": True},
        {"name": "Gタグ", "type": "googtag"},
    ]), [0])
    assert [v["severity"] for v in out] == ["High", "Low"]
    # 消すと GA4 の計測が止まる可能性への注意が入っていること
    assert "先に確認する" in out[0]["suggested_fix"]


def test_universal_analytics_tags_silent_without_ua():
    from measurement_design.review.health_checks import check_universal_analytics_tags
    assert check_universal_analytics_tags(
        _gtm(tags=[{"name": "Gタグ", "type": "googtag"}]), [0]) == []


# ──────────────────────────────────────
# GTM — GA4 が UA タグ経由でしか送られていない（計測の停止リスク）
# ──────────────────────────────────────

def test_ga4_via_ua_bridge_detected():
    from measurement_design.review.health_checks import check_ga4_via_ua_bridge
    prop = {"data_streams": [{"web_stream_data": {"measurement_id": "G-AAA11111"}}]}  # leak-ok: 合成テストID（実在の測定IDではない）
    gtm = _gtm(tags=[{"name": "UA本番", "type": "ua"}, _googtag("G-BBB22222")])  # leak-ok: 合成テストID（実在の測定IDではない）
    out = check_ga4_via_ua_bridge(gtm, prop, [0])
    assert len(out) == 1
    # **断定しない。** データだけでは UA ブリッジ／直書き／別コンテナを切り分けられない
    assert out[0]["severity"] == "High"
    assert "G-AAA11111" in out[0]["description"]  # leak-ok: 合成テストID（実在の測定IDではない）
    assert "候補は3つ" in out[0]["description"]
    assert "全量止まる" in out[0]["description"]
    # 切り分け方（analytics.js の遮断）と、確定前に消さない注意
    assert "analytics.js" in out[0]["suggested_fix"]
    assert "確定するまで UA タグを消さない" in out[0]["suggested_fix"]


def _googtag(mid, paused=False):
    return {"name": f"Gタグ {mid}", "type": "googtag", "paused": paused,
            "parameter": [{"key": "tagId", "value": mid}]}


def _ga4_event(mid, key="measurementIdOverride", paused=False):
    return {"name": "GA4イベント", "type": "gaawe", "paused": paused,
            "parameter": [{"key": "eventName", "value": "cv"},
                          {"key": key, "value": mid}]}


def test_ga4_via_ua_bridge_silent_when_tag_present():
    """コンテナに稼働中の Google タグがあるなら、直接送られているので対象外。"""
    from measurement_design.review.health_checks import check_ga4_via_ua_bridge
    prop = {"data_streams": [{"web_stream_data": {"measurement_id": "G-AAA11111"}}]}  # leak-ok: 合成テストID（実在の測定IDではない）
    gtm = _gtm(tags=[{"name": "UA本番", "type": "ua"}, _googtag("G-AAA11111")])  # leak-ok: 合成テストID（実在の測定IDではない）
    assert check_ga4_via_ua_bridge(gtm, prop, [0]) == []


def test_ga4_via_ua_bridge_reads_measurement_id_override():
    """GA4 イベントタグの `measurementIdOverride` も宛先として数える。

    ここを見落とすと、イベントタグの上書きにしか測定IDが無いコンテナで
    誤った停止リスクを出す。
    """
    from measurement_design.review.health_checks import check_ga4_via_ua_bridge
    prop = {"data_streams": [{"web_stream_data": {"measurement_id": "G-AAA11111"}}]}  # leak-ok: 合成テストID（実在の測定IDではない）
    gtm = _gtm(tags=[{"name": "UA本番", "type": "ua"}, _ga4_event("G-AAA11111")])  # leak-ok: 合成テストID（実在の測定IDではない）
    assert check_ga4_via_ua_bridge(gtm, prop, [0]) == []


def test_ga4_via_ua_bridge_ignores_paused_tag():
    """一時停止タグは「送っている」に数えない。"""
    from measurement_design.review.health_checks import check_ga4_via_ua_bridge
    prop = {"data_streams": [{"web_stream_data": {"measurement_id": "G-AAA11111"}}]}  # leak-ok: 合成テストID（実在の測定IDではない）
    gtm = _gtm(tags=[{"name": "UA本番", "type": "ua"},
                     _googtag("G-AAA11111", paused=True),  # leak-ok: 合成テストID（実在の測定IDではない）
                     _googtag("G-OTHER222")])  # leak-ok: 合成テストID（実在の測定IDではない）
    out = check_ga4_via_ua_bridge(gtm, prop, [0])
    assert len(out) == 1
    assert "G-AAA11111" in out[0]["description"]  # leak-ok: 合成テストID（実在の測定IDではない）


def test_ga4_via_ua_bridge_resolves_variable_reference():
    """測定IDが変数参照でも辿る。"""
    from measurement_design.review.health_checks import check_ga4_via_ua_bridge
    prop = {"data_streams": [{"web_stream_data": {"measurement_id": "G-AAA11111"}}]}  # leak-ok: 合成テストID（実在の測定IDではない）
    gtm = _gtm(
        tags=[{"name": "UA本番", "type": "ua"},
              {"name": "Gタグ", "type": "googtag",
               "parameter": [{"key": "tagId", "value": "{{測定ID}}"}]}],
    )
    gtm["variables"] = [{"name": "測定ID",
                         "parameter": [{"key": "value", "value": "G-AAA11111"}]}]  # leak-ok: 合成テストID（実在の測定IDではない）
    assert check_ga4_via_ua_bridge(gtm, prop, [0]) == []


def test_ga4_via_ua_bridge_silent_without_ua_tags():
    """UA タグが無ければ原因が別なので、この検査では断定しない。"""
    from measurement_design.review.health_checks import check_ga4_via_ua_bridge
    prop = {"data_streams": [{"web_stream_data": {"measurement_id": "G-AAA11111"}}]}  # leak-ok: 合成テストID（実在の測定IDではない）
    gtm = _gtm(tags=[_googtag("G-BBB22222")])  # leak-ok: 合成テストID（実在の測定IDではない）
    assert check_ga4_via_ua_bridge(gtm, prop, [0]) == []


def test_ga4_via_ua_bridge_scopes_to_measured_stream():
    """別サイト用のストリームを巻き込まない。

    複数ストリームのプロパティで、いま見ているコンテナが担当していない
    ストリームまで「停止リスク」として挙げるのは誤報。
    """
    from measurement_design.review.health_checks import check_ga4_via_ua_bridge
    prop = {"data_streams": [
        {"web_stream_data": {"measurement_id": "G-SITEA111",  # leak-ok: 合成テストID（実在の測定IDではない）
                             "default_uri": "https://a.example.com"}},
        {"web_stream_data": {"measurement_id": "G-SITEB222",  # leak-ok: 合成テストID（実在の測定IDではない）
                             "default_uri": "https://b.example.com"}},
    ]}
    gtm = _gtm(tags=[{"name": "UA本番", "type": "ua"}, _googtag("G-OTHER999")])  # leak-ok: 合成テストID（実在の測定IDではない）
    quality = {"hosts": [{"hostName": "a.example.com", "sessions": "1000"}]}
    out = check_ga4_via_ua_bridge(gtm, prop, [0], quality)
    assert len(out) == 1
    # 実測ホストに結びつく A だけを挙げる
    assert "G-SITEA111" in out[0]["description"]  # leak-ok: 合成テストID（実在の測定IDではない）
    assert "G-SITEB222" not in out[0]["description"]  # leak-ok: 合成テストID（実在の測定IDではない）
    # 複数ストリームであることを断り書きする
    assert "web ストリームが2本" in out[0]["description"]


def test_ga4_via_ua_bridge_needs_host_data_when_multi_stream():
    """ホスト名が取れていない複数ストリームでは判定しない。"""
    from measurement_design.review.health_checks import check_ga4_via_ua_bridge
    prop = {"data_streams": [
        {"web_stream_data": {"measurement_id": "G-A", "default_uri": "https://a.example.com"}},
        {"web_stream_data": {"measurement_id": "G-B", "default_uri": "https://b.example.com"}},
    ]}
    gtm = _gtm(tags=[{"name": "UA", "type": "ua"}, _googtag("G-OTHER")])
    assert check_ga4_via_ua_bridge(gtm, prop, [0], None) == []


# ──────────────────────────────────────
# GTM — 使われていないトリガー
# ──────────────────────────────────────

def test_unused_triggers_listed():
    from measurement_design.review.health_checks import check_unused_triggers
    gtm = _gtm(
        tags=[{"name": "t", "type": "html", "firingTriggerId": ["1"]}],
        triggers=[{"triggerId": "1", "name": "使用中", "type": "pageview"},
                  {"triggerId": "2", "name": "未使用", "type": "scrollDepth"}],
    )
    out = check_unused_triggers(gtm, [0])
    assert len(out) == 1
    assert "未使用" in out[0]["description"]


def test_unused_triggers_counts_blocking_as_used():
    """ブロックトリガーとして使われていれば未使用ではない。"""
    from measurement_design.review.health_checks import check_unused_triggers
    gtm = _gtm(
        tags=[{"name": "t", "type": "html", "firingTriggerId": ["1"],
               "blockingTriggerId": ["2"]}],
        triggers=[{"triggerId": "1", "name": "発火", "type": "pageview"},
                  {"triggerId": "2", "name": "除外", "type": "pageview"}],
    )
    assert check_unused_triggers(gtm, [0]) == []


# ──────────────────────────────────────
# GTM — トリガーグループ / 旧世代のGA4設定タグ
# ──────────────────────────────────────

def _trigger_group(tid, name, member_ids):
    return {"triggerId": tid, "name": name, "type": "triggerGroup",
            "parameter": [{"key": "triggerIds", "type": "list", "list": [
                {"type": "triggerReference", "value": m} for m in member_ids]}]}


def test_unused_triggers_counts_group_members_as_used():
    """グループのメンバーを「未使用」として削除を勧めてはいけない。"""
    from measurement_design.review.health_checks import check_unused_triggers
    gtm = _gtm(
        tags=[{"name": "タグ", "type": "html", "firingTriggerId": ["100"]}],
        triggers=[_trigger_group("100", "グループ", ["9"]),
                  {"triggerId": "9", "name": "メンバー", "type": "scrollDepth"},
                  {"triggerId": "2", "name": "本当に未使用", "type": "pageview"}],
    )
    out = check_unused_triggers(gtm, [0])
    assert len(out) == 1
    assert "本当に未使用" in out[0]["description"]
    assert "メンバー" not in out[0]["description"]


def test_trigger_group_cycle_does_not_hang():
    """グループが互いを参照していても止まらない。"""
    from measurement_design.review.health_checks import check_unused_triggers
    gtm = _gtm(
        tags=[{"name": "タグ", "type": "html", "firingTriggerId": ["100"]}],
        triggers=[_trigger_group("100", "A", ["101"]),
                  _trigger_group("101", "B", ["100"])],
    )
    assert check_unused_triggers(gtm, [0]) == []


def test_ua_bridge_accepts_legacy_ga4_config_tag():
    """旧世代の GA4 設定タグ（gaawc）でも設置済みと認める。"""
    from measurement_design.review.health_checks import check_ga4_via_ua_bridge
    prop = {"data_streams": [{"web_stream_data": {"measurement_id": "G-AAA11111"}}]}  # leak-ok: 合成テストID（実在の測定IDではない）
    gtm = _gtm(tags=[
        {"name": "UA本番", "type": "ua"},
        {"name": "GA4設定", "type": "gaawc",
         "parameter": [{"key": "measurementId", "value": "G-AAA11111"}]},  # leak-ok: 合成テストID（実在の測定IDではない）
    ])
    assert check_ga4_via_ua_bridge(gtm, prop, [0]) == []


def test_url_variants_skips_negated_condition():
    """否定条件（`/foo` ではない）を完全一致と読まない。"""
    from measurement_design.review.health_checks import check_event_rule_url_variants
    rule = {
        "destination_event": "not_form",
        "event_conditions": [
            {"field": "event_name", "comparison_type": "EQUALS", "value": "page_view"},
            {"field": "page_path", "comparison_type": "EQUALS",
             "value": "/trial-lesson", "negated": True},
        ],
    }
    out = check_event_rule_url_variants(
        _defs([rule]),
        _pages([("/trial-lesson", 62, 31), ("/trial-lesson.html", 275, 102)]),
        [0],
    )
    assert out == []


def test_url_variants_skips_page_location_when_multi_host():
    """計測ホストが複数あるとき、page_location は突き合わせられない。

    ページ実績はホストを跨いで pagePath で合算されるため、
    別ホストに同じパスがあるだけで取りこぼしと誤判定する。
    """
    from measurement_design.review.health_checks import check_event_rule_url_variants
    quality = {"hosts": [{"hostName": "a.example.com"}, {"hostName": "b.example.com"}]}
    out = check_event_rule_url_variants(
        _defs([_rule("form_view", "https://a.example.com/foo", field="page_location")]),
        _pages([("/foo", 60, 30), ("/foo.html", 280, 110)]),
        [0], quality,
    )
    assert out == []


def test_url_variants_allows_page_location_on_single_host():
    from measurement_design.review.health_checks import check_event_rule_url_variants
    quality = {"hosts": [{"hostName": "a.example.com"}]}
    out = check_event_rule_url_variants(
        _defs([_rule("form_view", "https://a.example.com/foo", field="page_location")]),
        _pages([("/foo", 60, 30), ("/foo.html", 280, 110)]),
        [0], quality,
    )
    assert len(out) == 1


def test_unused_triggers_marks_nested_group_as_used():
    """入れ子のグループの中間段も使用中に数える。

    タグ → グループA → グループB → 実トリガー のとき、B を未使用として
    削除を勧めると A が壊れる。
    """
    from measurement_design.review.health_checks import check_unused_triggers
    gtm = _gtm(
        tags=[{"name": "タグ", "type": "html", "firingTriggerId": ["100"]}],
        triggers=[_trigger_group("100", "グループA", ["101"]),
                  _trigger_group("101", "グループB", ["9"]),
                  {"triggerId": "9", "name": "実トリガー", "type": "scrollDepth"},
                  {"triggerId": "2", "name": "本当に未使用", "type": "pageview"}],
    )
    out = check_unused_triggers(gtm, [0])
    assert len(out) == 1
    assert "本当に未使用" in out[0]["description"]
    assert "グループB" not in out[0]["description"]
    assert "実トリガー" not in out[0]["description"]


# ──────────────────────────────────────
# 09-gtm.json の読み分け
# ──────────────────────────────────────

def test_load_gtm_api_ignores_public_reconstruction(tmp_path):
    """公開 gtm.js 由来のデータを API 版として扱わない。

    公開版にはタグ名・トリガー種別が無いため、名前で語る検査に渡すと
    空文字だらけの指摘が出る。
    """
    import json
    from measurement_design.review.health_checks import load_gtm_api
    (tmp_path / "09-gtm.json").write_text(
        json.dumps({"source": {"method": "public_gtm_js"}, "tags": [{"name": ""}]}),
        encoding="utf-8")
    assert load_gtm_api(tmp_path) == {}


def test_load_gtm_api_reads_api_dump(tmp_path):
    import json
    from measurement_design.review.health_checks import load_gtm_api
    (tmp_path / "09-gtm.json").write_text(
        json.dumps({"tags": [{"name": "Gタグ", "type": "googtag"}]}), encoding="utf-8")
    assert load_gtm_api(tmp_path)["tags"][0]["name"] == "Gタグ"


def test_load_gtm_api_missing_file(tmp_path):
    from measurement_design.review.health_checks import load_gtm_api
    assert load_gtm_api(tmp_path) == {}


# ──────────────────────────────────────
# GTM — 広告コンバージョンのラベル重複（同じID・ラベルが複数タグに）
# ──────────────────────────────────────

def _awct(name, conversion_id, conversion_label, paused=False):
    return {"name": name, "type": "awct", "paused": paused,
            "parameter": [{"key": "conversionId", "value": conversion_id},
                          {"key": "conversionLabel", "value": conversion_label}]}


def test_duplicate_ad_conversion_labels_detects_literal_match():
    from measurement_design.review.health_checks import check_duplicate_ad_conversion_labels
    gtm = _gtm(tags=[_awct("CV_申込A", "AW-111", "abcDEF"),
                     _awct("CV_申込B", "AW-111", "abcDEF")])
    out = check_duplicate_ad_conversion_labels(gtm, [0])
    assert len(out) == 1
    assert out[0]["category"] == "多重計上"
    assert "CV_申込A" in out[0]["target_name"] and "CV_申込B" in out[0]["target_name"]


def test_duplicate_ad_conversion_labels_ignores_different_labels():
    from measurement_design.review.health_checks import check_duplicate_ad_conversion_labels
    gtm = _gtm(tags=[_awct("CV_申込", "AW-111", "abcDEF"),
                     _awct("CV_資料請求", "AW-111", "ghiJKL")])
    assert check_duplicate_ad_conversion_labels(gtm, [0]) == []


def test_duplicate_ad_conversion_labels_ignores_paused_tag():
    from measurement_design.review.health_checks import check_duplicate_ad_conversion_labels
    gtm = _gtm(tags=[_awct("CV_申込", "AW-111", "abcDEF"),
                     _awct("旧CV", "AW-111", "abcDEF", paused=True)])
    assert check_duplicate_ad_conversion_labels(gtm, [0]) == []


def test_duplicate_ad_conversion_labels_resolves_shared_constant_variable():
    """変数名が違っても、定数まで解決した値が同じなら重複として拾う。

    逆方向の見落とし（「違う変数が同じ値を指していても気づかない」）を防ぐ。
    """
    from measurement_design.review.health_checks import check_duplicate_ad_conversion_labels
    gtm = _gtm(tags=[
        {"name": "CV_申込A", "type": "awct",
         "parameter": [{"key": "conversionId", "value": "{{CV_ID_A}}"},
                       {"key": "conversionLabel", "value": "{{CV_LABEL_A}}"}]},
        {"name": "CV_申込B", "type": "awct",
         "parameter": [{"key": "conversionId", "value": "{{CV_ID_B}}"},
                       {"key": "conversionLabel", "value": "{{CV_LABEL_B}}"}]},
    ])
    gtm["variables"] = [
        {"name": "CV_ID_A", "type": "c", "parameter": [{"key": "value", "value": "AW-111"}]},
        {"name": "CV_ID_B", "type": "c", "parameter": [{"key": "value", "value": "AW-111"}]},
        {"name": "CV_LABEL_A", "type": "c", "parameter": [{"key": "value", "value": "abcDEF"}]},
        {"name": "CV_LABEL_B", "type": "c", "parameter": [{"key": "value", "value": "abcDEF"}]},
    ]
    out = check_duplicate_ad_conversion_labels(gtm, [0])
    assert len(out) == 1
    assert out[0]["category"] == "多重計上"


def test_duplicate_ad_conversion_labels_cannot_resolve_lookup_table():
    """ルックアップテーブル（実行時に値が変わる）は判定できないとして別枠で出す。

    同じ変数を指す2タグを、値を解決せずに「重複」と決め打ちしてはいけない
    （「同じ変数を使う2タグを誤って重複と判定する」を防ぐ）。
    """
    from measurement_design.review.health_checks import check_duplicate_ad_conversion_labels
    gtm = _gtm(tags=[
        {"name": "CV_申込A", "type": "awct",
         "parameter": [{"key": "conversionId", "value": "AW-111"},
                       {"key": "conversionLabel", "value": "{{CV_LABEL_LT}}"}]},
        {"name": "CV_申込B", "type": "awct",
         "parameter": [{"key": "conversionId", "value": "AW-111"},
                       {"key": "conversionLabel", "value": "{{CV_LABEL_LT}}"}]},
    ])
    gtm["variables"] = [{
        "name": "CV_LABEL_LT", "type": "smm",
        "parameter": [
            {"key": "input", "value": "{{Page Hostname}}"},
            {"key": "map", "type": "list", "list": [
                {"type": "map", "map": [{"key": "key", "value": "a.example.com"},
                                        {"key": "value", "value": "abcDEF"}]},
                {"type": "map", "map": [{"key": "key", "value": "b.example.com"},
                                        {"key": "value", "value": "ghiJKL"}]},
            ]},
        ],
    }]
    out = check_duplicate_ad_conversion_labels(gtm, [0])
    assert len(out) == 1
    assert out[0]["category"] == "判定不能"
    assert "CV_申込A" in out[0]["target_name"] and "CV_申込B" in out[0]["target_name"]


# ──────────────────────────────────────
# GTM — GA4キーイベントのクリック発火範囲
# ──────────────────────────────────────

def _gaawe(name, event_name, firing_trigger_ids, paused=False):
    return {"name": name, "type": "gaawe", "paused": paused,
            "firingTriggerId": firing_trigger_ids,
            "parameter": [{"key": "eventName", "value": event_name}]}


def test_non_outcome_key_events_does_not_reject_scroll_mcv():
    from measurement_design.review.health_checks import check_non_outcome_key_events
    events = {"key_events": [{"event_name": "download_thanks"}]}
    gtm = _gtm(
        tags=[_gaawe("GA4_資料DL", "download_thanks", ["9"])],
        triggers=[{"triggerId": "9", "name": "SD90", "type": "scrollDepth"}],
    )
    assert check_non_outcome_key_events(events, gtm, [0]) == []


def test_non_outcome_key_events_unfiltered_clicks_get_distinct_ids():
    """同じキーイベントに複数の無条件クリックが絡む場合、それぞれ別のIDになる.

    target_name（キーイベント名）だけをIDの素にすると同じIDになってしまう
    （今回の改修で見つけた収束漏れ）。タグ名・トリガー名を識別要素に加えて防ぐ。
    """
    from measurement_design.review.health_checks import check_non_outcome_key_events
    events = {"key_events": [{"event_name": "download_thanks"}]}
    gtm = _gtm(
        tags=[_gaawe("GA4_資料DL", "download_thanks", ["9", "10"])],
        triggers=[
            {"triggerId": "9", "name": "全要素クリック", "type": "click"},
            {"triggerId": "10", "name": "外部リンククリック", "type": "linkClick"},
        ],
    )
    out = check_non_outcome_key_events(events, gtm, [0])
    assert len(out) == 2
    assert len({v["id"] for v in out}) == 2
    assert {v["category"] for v in out} == {"発火範囲の確認"}
    assert {v["severity"] for v in out} == {"Low"}
    assert all("キーイベントの登録から外す" not in v["suggested_fix"] for v in out)


def test_non_outcome_key_events_accepts_filtered_link_click_mcv():
    from measurement_design.review.health_checks import check_non_outcome_key_events
    events = {"key_events": [{"event_name": "cta_click"}]}
    gtm = _gtm(
        tags=[_gaawe("GA4_CTAクリック", "cta_click", ["9"])],
        triggers=[{"triggerId": "9", "name": "CTAリンク", "type": "linkClick",
                   "filter": [{"type": "contains", "parameter": []}]}],
    )
    assert check_non_outcome_key_events(events, gtm, [0]) == []


def test_non_outcome_key_events_does_not_flatten_trigger_group_to_all_clicks():
    """全クリックAND別条件のグループを、無条件の全クリックと誤判定しない。"""
    from measurement_design.review.health_checks import check_non_outcome_key_events
    events = {"key_events": [{"event_name": "cta_click"}]}
    group = {
        "triggerId": "group", "name": "CTAクリック条件グループ", "type": "triggerGroup",
        "parameter": [{"key": "triggerIds", "type": "list", "list": [
            {"type": "triggerReference", "value": "click"},
            {"type": "triggerReference", "value": "condition"},
        ]}],
    }
    gtm = _gtm(
        tags=[_gaawe("GA4_CTAクリック", "cta_click", ["group"])],
        triggers=[
            group,
            {"triggerId": "click", "name": "全リンク", "type": "linkClick"},
            {"triggerId": "condition", "name": "CTA条件", "type": "customEvent",
             "filter": [{"type": "equals", "parameter": []}]},
        ],
    )
    assert check_non_outcome_key_events(events, gtm, [0]) == []


def test_ad_conversion_link_click_is_not_treated_as_invalid_outcome():
    """添付例の再発防止: 広告タグのリンククリックはMCVになり得るため自動否定しない。"""
    from measurement_design.review.health_checks import check_non_outcome_key_events
    events = {"key_events": [{"event_name": "cta_click"}]}
    gtm = _gtm(
        tags=[{"name": "AD_CV_CTAクリック", "type": "awct", "firingTriggerId": ["9"]}],
        triggers=[{"triggerId": "9", "name": "LinkClick_CTA", "type": "linkClick"}],
    )
    assert check_non_outcome_key_events(events, gtm, [0]) == []


def test_non_outcome_key_events_ok_when_trigger_is_pageview():
    from measurement_design.review.health_checks import check_non_outcome_key_events
    events = {"key_events": [{"event_name": "download_thanks"}]}
    gtm = _gtm(
        tags=[_gaawe("GA4_資料DL", "download_thanks", ["1"])],
        triggers=[{"triggerId": "1", "name": "DLサンクス", "type": "pageview"}],
    )
    assert check_non_outcome_key_events(events, gtm, [0]) == []


def test_non_outcome_key_events_silent_when_no_matching_tag():
    """GTMに対応するgaaweタグが無い＝異常ではない。黙ってスキップする。

    GA4管理画面のイベント作成ルール・gtag直書き・サイト側実装のことがある。
    """
    from measurement_design.review.health_checks import check_non_outcome_key_events
    events = {"key_events": [{"event_name": "contact_service_thanks"}]}
    gtm = _gtm(tags=[_gaawe("GA4_別イベント", "other_event", ["1"])],
              triggers=[{"triggerId": "1", "name": "T", "type": "pageview"}])
    assert check_non_outcome_key_events(events, gtm, [0]) == []


def test_non_outcome_key_events_resolves_event_name_via_constant_variable():
    from measurement_design.review.health_checks import check_non_outcome_key_events
    events = {"key_events": [{"event_name": "download_thanks"}]}
    gtm = _gtm(
        tags=[{"name": "GA4_資料DL", "type": "gaawe", "firingTriggerId": ["9"],
              "parameter": [{"key": "eventName", "value": "{{イベント名}}"}]}],
        triggers=[{"triggerId": "9", "name": "全リンク", "type": "linkClick"}],
    )
    gtm["variables"] = [{"name": "イベント名", "type": "c",
                         "parameter": [{"key": "value", "value": "download_thanks"}]}]
    out = check_non_outcome_key_events(events, gtm, [0])
    assert len(out) == 1
    assert out[0]["category"] == "発火範囲の確認"


def test_non_outcome_key_events_cannot_resolve_lookup_table_event_name():
    """eventNameがルックアップテーブル参照で解決できないときは判定不能として出す。

    どのキーイベントに対応するかも分からないため、個別のキーイベントには紐付けない。
    """
    from measurement_design.review.health_checks import check_non_outcome_key_events
    events = {"key_events": [{"event_name": "download_thanks"}]}
    gtm = _gtm(
        tags=[{"name": "GA4_不明", "type": "gaawe", "firingTriggerId": ["9"],
              "parameter": [{"key": "eventName", "value": "{{イベント名_LT}}"}]}],
        triggers=[{"triggerId": "9", "name": "SD90", "type": "scrollDepth"}],
    )
    gtm["variables"] = [{
        "name": "イベント名_LT", "type": "smm",
        "parameter": [{"key": "map", "type": "list", "list": [
            {"type": "map", "map": [{"key": "key", "value": "a.example.com"},
                                    {"key": "value", "value": "download_thanks"}]},
        ]}],
    }]
    out = check_non_outcome_key_events(events, gtm, [0])
    assert len(out) == 1
    assert out[0]["category"] == "判定不能"
    assert "GA4_不明" in out[0]["target_name"]


def test_non_outcome_key_events_excludes_purchase_noise():
    """`purchase` はどのプロパティにも既定で候補として入るため対象外。"""
    from measurement_design.review.health_checks import check_non_outcome_key_events
    events = {"key_events": [{"event_name": "purchase"}]}
    gtm = _gtm(
        tags=[_gaawe("GA4_購入", "purchase", ["9"])],
        triggers=[{"triggerId": "9", "name": "SD90", "type": "scrollDepth"}],
    )
    assert check_non_outcome_key_events(events, gtm, [0]) == []


def test_resolve_gaawe_event_names_groups_by_resolved_name():
    from measurement_design.review.health_checks import resolve_gaawe_event_names
    gtm = _gtm(tags=[_gaawe("t1", "form_view", ["1"]), _gaawe("t2", "form_view", ["2"])])
    by_event, unresolved = resolve_gaawe_event_names(gtm)
    assert {t["name"] for t in by_event["form_view"]} == {"t1", "t2"}
    assert unresolved == []
