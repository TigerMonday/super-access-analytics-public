"""kpi_coverage.py の check_coverage ユニットテスト.

KPIに `events`（登録済みGA4イベント名）があればそれを優先してGA4実態と突合し、
無いKPIだけ decomposer の分解結果（一般的なイベント名の提案）で判定する優先順位を検証する。
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

REVIEW_DATA = {
    "ga4": {
        "events_observed": [
            {"name": "file_download", "count": 500},
            {"name": "page_view", "count": 10000},
        ],
        "key_events": ["file_download"],
    }
}


def test_check_coverage_uses_registered_events_when_present():
    """events登録済みKPIは、decomposerの分解結果を使わずGA4実態と直接突合する."""
    from measurement_design.review.kpi_coverage import check_coverage

    kpis = [
        {"kpi_id": "kpi_001", "name": "資料ダウンロード数", "events": ["file_download"]},
    ]
    # わざと breakdowns を空にする（events登録済みなら分解結果に依存しないはず）
    kpi_breakdowns: list[dict] = []

    rows = check_coverage(kpi_breakdowns, kpis, REVIEW_DATA)

    assert len(rows) == 1
    assert rows[0]["kpi_id"] == "kpi_001"
    assert rows[0]["event"] == "file_download"
    assert rows[0]["status"] == "実装済み"
    assert rows[0]["action"] == "—"


def test_check_coverage_flags_unimplemented_registered_event():
    from measurement_design.review.kpi_coverage import check_coverage

    kpis = [
        {"kpi_id": "kpi_002", "name": "お問い合わせ完了数", "events": ["generate_lead"]},
    ]
    rows = check_coverage([], kpis, REVIEW_DATA)

    assert len(rows) == 1
    assert rows[0]["status"] == "未実装"
    assert "generate_lead" in rows[0]["action"]


def test_check_coverage_supports_multiple_registered_events():
    from measurement_design.review.kpi_coverage import check_coverage

    kpis = [
        {"kpi_id": "kpi_001", "name": "資料ダウンロード数", "events": ["file_download", "generate_lead"]},
    ]
    rows = check_coverage([], kpis, REVIEW_DATA)

    assert len(rows) == 2
    statuses = {r["event"]: r["status"] for r in rows}
    assert statuses["file_download"] == "実装済み"
    assert statuses["generate_lead"] == "未実装"


def test_check_coverage_falls_back_to_breakdown_when_no_events_registered():
    """events未登録のKPIは、従来どおり decomposer の分解結果で判定する（後方互換）."""
    from measurement_design.review.kpi_coverage import check_coverage

    kpis = [{"kpi_id": "kpi_003", "name": "会員登録数"}]  # events キーなし
    breakdowns = [
        {
            "kpi_id": "kpi_003",
            "required_events": [
                {"event_name": "sign_up", "timing": "登録完了時"},
            ],
        }
    ]

    rows = check_coverage(breakdowns, kpis, REVIEW_DATA)

    assert len(rows) == 1
    assert rows[0]["event"] == "sign_up"
    assert rows[0]["status"] == "未実装"
    assert rows[0]["action"] == "登録完了時"


def test_check_coverage_mixed_registered_and_unregistered_kpis():
    """一部のKPIだけeventsが登録済みの混在ケース."""
    from measurement_design.review.kpi_coverage import check_coverage

    kpis = [
        {"kpi_id": "kpi_001", "name": "資料ダウンロード数", "events": ["file_download"]},
        {"kpi_id": "kpi_003", "name": "会員登録数"},
    ]
    breakdowns = [
        {"kpi_id": "kpi_003", "required_events": [{"event_name": "sign_up", "timing": ""}]},
    ]

    rows = check_coverage(breakdowns, kpis, REVIEW_DATA)

    by_kpi = {r["kpi_id"]: r for r in rows}
    assert by_kpi["kpi_001"]["event"] == "file_download"
    assert by_kpi["kpi_001"]["status"] == "実装済み"
    assert by_kpi["kpi_003"]["event"] == "sign_up"


def test_check_coverage_no_events_and_no_breakdown_reports_unresolved():
    from measurement_design.review.kpi_coverage import check_coverage

    kpis = [{"kpi_id": "kpi_004", "name": "未分解KPI"}]
    rows = check_coverage([], kpis, REVIEW_DATA)

    assert len(rows) == 1
    assert rows[0]["status"] == "要件未分解"


def test_check_coverage_includes_fired_count():
    """発火しているか・何件かを行データに持たせる（KPIセクションで表示するため）."""
    from measurement_design.review.kpi_coverage import check_coverage

    kpis = [{"kpi_id": "kpi_001", "name": "資料ダウンロード数", "events": ["file_download"]}]
    rows = check_coverage([], kpis, REVIEW_DATA)

    assert rows[0]["count"] == 500


def test_confirmed_event_uses_full_counts_beyond_top_100():
    from measurement_design.review.kpi_coverage import check_coverage

    review = {"ga4": {
        "events_observed": [{"name": "page_view", "count": 10000}],
        "event_counts_all": [
            {"name": "page_view", "count": 10000},
            {"name": "rare_conversion", "count": 1},
        ],
        "event_counts_status": "complete",
        "key_events": [],
    }}
    rows = check_coverage(
        [], [{"kpi_id": "kpi_rare", "name": "低頻度の成果", "events": ["rare_conversion"]}], review,
    )

    assert rows[0]["count"] == 1
    assert rows[0]["status"] == "実装済み"


def test_confirmed_event_is_unverified_when_full_counts_are_missing():
    from measurement_design.review.kpi_coverage import check_coverage

    review = {"ga4": {
        "events_observed": [{"name": "page_view", "count": 10000}],
        "event_counts_all": [],
        "event_counts_status": "missing",
        "key_events": [],
    }}
    rows = check_coverage(
        [], [{"kpi_id": "kpi_rare", "name": "低頻度の成果", "events": ["rare_conversion"]}], review,
    )

    assert rows[0]["count"] is None
    assert rows[0]["status"] == "未確認"
    assert "0件" not in rows[0]["action"]


def test_legacy_top_100_still_proves_positive_reception():
    from measurement_design.review.kpi_coverage import check_coverage

    review = {"ga4": {
        "events_observed": [{"name": "reserve_complete", "count": 2}],
        "event_counts_all": [],
        "event_counts_status": "missing",
        "key_events": [],
    }}
    rows = check_coverage(
        [], [{"kpi_id": "kpi_reserve", "name": "予約完了", "events": ["reserve_complete"]}], review,
    )

    assert rows[0]["count"] == 2
    assert rows[0]["status"] == "実装済み"


def test_confirmed_event_is_zero_only_when_full_counts_are_complete():
    from measurement_design.review.kpi_coverage import check_coverage

    review = {"ga4": {
        "events_observed": [{"name": "page_view", "count": 10000}],
        "event_counts_all": [{"name": "page_view", "count": 10000}],
        "event_counts_status": "complete",
        "key_events": [],
    }}
    rows = check_coverage(
        [], [{"kpi_id": "kpi_rare", "name": "低頻度の成果", "events": ["rare_conversion"]}], review,
    )

    assert rows[0]["count"] == 0
    assert rows[0]["status"] == "未実装"


# ── default_key_event_rows: KPIもkey_eventsも登録が無いときの既定の答え ──────


def _review_with_key_events(key_events, observed):
    return {"ga4": {"key_events": key_events, "events_observed": observed}}


def test_default_key_event_rows_uses_ga4_key_events():
    review = _review_with_key_events(
        ["download_thanks", "contact_service_thanks"],
        [{"name": "download_thanks", "count": 12}, {"name": "contact_service_thanks", "count": 40}],
    )

    rows = kpi_default_rows(review)

    by_event = {r["event"]: r for r in rows}
    assert by_event["download_thanks"]["status"] == "実装済み"
    assert by_event["download_thanks"]["count"] == 12
    assert by_event["contact_service_thanks"]["count"] == 40


def test_default_key_event_rows_flags_zero_firing():
    review = _review_with_key_events(["download_thanks"], [])

    rows = kpi_default_rows(review)

    assert rows[0]["status"] == "未実装"
    assert rows[0]["count"] == 0


def test_default_key_event_rows_excludes_purchase():
    """purchase はどのGA4プロパティにも既定で入りがちで、毎回ノイズになるため除外する."""
    review = _review_with_key_events(
        ["purchase", "download_thanks"],
        [{"name": "download_thanks", "count": 12}],
    )

    rows = kpi_default_rows(review)

    events = [r["event"] for r in rows]
    assert "purchase" not in events
    assert "download_thanks" in events


def test_default_key_event_rows_empty_without_key_events():
    assert kpi_default_rows({"ga4": {"key_events": [], "events_observed": []}}) == []


def kpi_default_rows(review_data):
    from measurement_design.review.kpi_coverage import default_key_event_rows
    return default_key_event_rows(review_data)


# ── source タグ: 「イベント名が分かっているか」をレンダラー側に伝える ────


def test_check_coverage_tags_registered_source():
    """events登録済み（優先1）は source=registered。"""
    from measurement_design.review.kpi_coverage import check_coverage

    kpis = [{"kpi_id": "kpi_001", "name": "資料ダウンロード数", "events": ["file_download"]}]
    rows = check_coverage([], kpis, REVIEW_DATA)
    assert rows[0]["source"] == "registered"


def test_check_coverage_tags_key_event_source_for_kpi_id_less_pseudo_kpi():
    """kpi_id が空（01の key_events から作った仮KPI）は source=key_event（registered ではない）.

    「KPI名」列と「イベント名」列に同じ値が2列並ぶ不具合の原因。kpi_id を持つ本物の
    登録KPI（kpis.yaml/01の `kpis`）と区別できるよう、レンダラー側で判定できる別の
    source タグを付ける。
    """
    from measurement_design.review.kpi_coverage import check_coverage

    kpis = [{"kpi_id": "", "name": "download_thanks", "events": ["download_thanks"]}]
    rows = check_coverage([], kpis, REVIEW_DATA)
    assert rows[0]["source"] == "key_event"


def test_check_coverage_tags_candidate_source():
    """events未登録でdecomposerの提案を使う（優先2）は source=candidate。"""
    from measurement_design.review.kpi_coverage import check_coverage

    kpis = [{"kpi_id": "kpi_003", "name": "会員登録数"}]
    breakdowns = [
        {"kpi_id": "kpi_003", "required_events": [{"event_name": "sign_up", "timing": ""}]},
    ]
    rows = check_coverage(breakdowns, kpis, REVIEW_DATA)
    assert rows[0]["source"] == "candidate"


def test_default_key_event_rows_tags_ga4_key_event_source():
    review = _review_with_key_events(["download_thanks"], [{"name": "download_thanks", "count": 12}])
    rows = kpi_default_rows(review)
    assert rows[0]["source"] == "ga4_key_event"


# ── find_funnel_pairs: イベント名の接尾辞から「手前→完了」の対応を推定する ──


def test_find_funnel_pairs_matches_form_to_thanks():
    from measurement_design.review.kpi_coverage import find_funnel_pairs

    events = [
        {"name": "contact_form", "count": 264},
        {"name": "contact_thanks", "count": 72},
        {"name": "page_view", "count": 10000},
    ]
    pairs = find_funnel_pairs(events)
    assert len(pairs) == 1
    assert pairs[0]["entry_event"] == "contact_form"
    assert pairs[0]["entry_count"] == 264
    assert pairs[0]["completion_event"] == "contact_thanks"
    assert pairs[0]["completion_count"] == 72


def test_find_funnel_pairs_ignores_unrelated_events():
    """対になる接尾辞が両方揃っていなければ対応と見なさない."""
    from measurement_design.review.kpi_coverage import find_funnel_pairs

    events = [{"name": "download_form", "count": 166}, {"name": "page_view", "count": 10000}]
    assert find_funnel_pairs(events) == []


# ── check_unregistered_outcome_events: 成果らしいのに未登録のイベント候補 ──


def test_check_unregistered_outcome_events_finds_candidate():
    review = {
        "ga4": {
            "key_events": ["contact_service_thanks"],
            "events_observed": [
                {"name": "contact_service_form", "count": 352},
                {"name": "contact_service_thanks", "count": 41},
                {"name": "contact_form", "count": 264},
                {"name": "contact_thanks", "count": 72},
            ],
        }
    }
    from measurement_design.review.kpi_coverage import check_unregistered_outcome_events

    kpis = [{"kpi_id": "k1", "name": "問い合わせ", "events": ["contact_service_thanks"]}]
    out = check_unregistered_outcome_events(review, kpis)

    assert len(out) == 1
    assert out[0]["event"] == "contact_thanks"
    assert out[0]["count"] == 72


def test_check_unregistered_outcome_events_excludes_key_event_registered():
    """GA4のキーイベントに登録済みなら候補から除外する（重複報告しない）."""
    review = {
        "ga4": {
            "key_events": ["download_thanks"],
            "events_observed": [
                {"name": "download_form", "count": 166},
                {"name": "download_thanks", "count": 13},
            ],
        }
    }
    from measurement_design.review.kpi_coverage import check_unregistered_outcome_events

    assert check_unregistered_outcome_events(review, []) == []


def test_check_unregistered_outcome_events_excludes_kpi_registered():
    """KPIのeventsに登録済みなら候補から除外する（重複報告しない）."""
    review = {
        "ga4": {
            "key_events": [],
            "events_observed": [
                {"name": "download_form", "count": 166},
                {"name": "download_thanks", "count": 13},
            ],
        }
    }
    from measurement_design.review.kpi_coverage import check_unregistered_outcome_events

    kpis = [{"kpi_id": "k1", "name": "資料DL", "events": ["download_thanks"]}]
    assert check_unregistered_outcome_events(review, kpis) == []


def test_check_unregistered_outcome_events_excludes_enhanced_measurement_events():
    """`video_complete` のようなGA4拡張計測イベントは候補から外す (試用フィードバックで検出).

    拡張計測が有効なだけで `_start`→`_complete` の対応が自動的にできてしまい、
    サイト独自の成果イベントと区別できない。`purchase`（DEFAULT_NOISE_KEY_EVENTS）と
    同じ考え方で、GA4が自動収集する名前は最初から候補に入れない。
    """
    review = {
        "ga4": {
            "key_events": [],
            "events_observed": [
                {"name": "video_start", "count": 22},
                {"name": "video_complete", "count": 11},
                # 独自の成果イベントは、拡張計測イベントに混じっていても普通に候補になる
                {"name": "contact_form", "count": 264},
                {"name": "contact_thanks", "count": 72},
            ],
        }
    }
    from measurement_design.review.kpi_coverage import check_unregistered_outcome_events

    out = check_unregistered_outcome_events(review, [])

    names = {c["event"] for c in out}
    assert "video_complete" not in names
    assert "contact_thanks" in names


# ── check_funnel_completion_rates: 0%・100%超だけを指摘する ──────────────


def test_check_funnel_completion_rates_flags_zero_percent():
    review = {"ga4": {"events_observed": [
        {"name": "newsletter_form", "count": 44}, {"name": "newsletter_thanks", "count": 0},
    ]}}
    from measurement_design.review.kpi_coverage import check_funnel_completion_rates

    out = check_funnel_completion_rates(review)
    assert len(out) == 1
    assert "0%" in out[0]["issue"]


def test_check_funnel_completion_rates_flags_over_100_percent():
    review = {"ga4": {"events_observed": [
        {"name": "download_form", "count": 100}, {"name": "download_thanks", "count": 150},
    ]}}
    from measurement_design.review.kpi_coverage import check_funnel_completion_rates

    out = check_funnel_completion_rates(review)
    assert len(out) == 1
    assert "100%超" in out[0]["issue"]


def test_check_funnel_completion_rates_ignores_normal_range():
    """完了率はサイトによって差が大きいため、中間の値（実データで11.6%等）は指摘しない."""
    review = {"ga4": {"events_observed": [
        {"name": "contact_service_form", "count": 352}, {"name": "contact_service_thanks", "count": 41},
    ]}}
    from measurement_design.review.kpi_coverage import check_funnel_completion_rates

    assert check_funnel_completion_rates(review) == []


# ── build_target_comparison: 目標値との対比（参考情報） ──────────────────


def test_build_target_comparison_sums_counts_by_kpi_id():
    kpis = [{"kpi_id": "kpi_001", "name": "資料ダウンロード数",
             "target_value": {"goal": 200, "unit": "件/月"}}]
    kpi_rows = [{"kpi_id": "kpi_001", "event": "download_thanks", "count": 13, "status": "実装済み"}]
    from measurement_design.review.kpi_coverage import build_target_comparison

    out = build_target_comparison(kpis, kpi_rows)
    assert out == [{"kpi_id": "kpi_001", "kpi_name": "資料ダウンロード数", "actual": 13,
                     "goal": 200, "unit": "件/月"}]


def test_build_target_comparison_skips_kpis_without_target_value():
    kpis = [{"kpi_id": "kpi_003", "name": "会員登録数"}]
    kpi_rows = [{"kpi_id": "kpi_003", "event": "sign_up", "count": 5}]
    from measurement_design.review.kpi_coverage import build_target_comparison

    assert build_target_comparison(kpis, kpi_rows) == []


# ── source_kpis: 01コンテキストの key_events フォールバック ──────────────


def _install_fake_context_store(monkeypatch, kpis=None, key_events=None):
    """`context_store.loader.load_context` を差し替える（実ファイルは読まない）."""

    class _FakeKpisDict(dict):
        pass

    class _FakeContext:
        def __init__(self):
            self.kpis = _FakeKpisDict(kpis=kpis or [], key_events=key_events or [])

    context_store_pkg = types.ModuleType("context_store")
    loader_mod = types.ModuleType("context_store.loader")
    loader_mod.load_context = lambda client_id: _FakeContext()
    context_store_pkg.loader = loader_mod
    monkeypatch.setitem(sys.modules, "context_store", context_store_pkg)
    monkeypatch.setitem(sys.modules, "context_store.loader", loader_mod)


def test_source_kpis_falls_back_to_01_key_events_when_no_kpis_registered(monkeypatch, tmp_path):
    """KPIごとの登録が無くても、01の key_events（全KPI横断のCV用イベント一覧）を使う.

    旧実装は ctx.kpis の 'kpis' しか見ておらず、'key_events' を無視していた
    （KPIが1件も無いクライアントでは常に §1 が「未連携」になっていたバグ）。
    """
    from measurement_design.review.kpi_coverage import source_kpis

    _install_fake_context_store(monkeypatch, kpis=[], key_events=["download_thanks", "contact_service_thanks"])
    project_root = Path(__file__).resolve().parents[2]  # measurement_design/（実物の01_context_managementを使う）
    client_dir = tmp_path / "no-such-client"  # inputs/kpis.yaml は無い

    kpis, _flow, source = source_kpis(client_dir, project_root)

    assert source == "01コンテキストのkey_events"
    events = {e for k in kpis for e in k.get("events", [])}
    assert events == {"download_thanks", "contact_service_thanks"}


def test_source_kpis_prefers_local_kpis_over_09(monkeypatch, tmp_path):
    from measurement_design.review.kpi_coverage import source_kpis

    _install_fake_context_store(monkeypatch, kpis=[], key_events=["should_not_be_used"])
    project_root = Path(__file__).resolve().parents[2]
    client_dir = tmp_path / "client-with-local-kpis"
    inputs_dir = client_dir / "inputs"
    inputs_dir.mkdir(parents=True)
    (inputs_dir / "kpis.yaml").write_text(
        "kpis:\n  - kpi_id: kpi_001\n    name: 資料請求\n    events: [download_thanks]\n",
        encoding="utf-8",
    )

    kpis, _flow, source = source_kpis(client_dir, project_root)

    assert source == "inputs/kpis.yaml"
    assert kpis[0]["kpi_id"] == "kpi_001"


# ── 登録名と送信名の食い違い（find_similar_firing_events / check_key_event_name_mismatches） ──
#
# 実データで見つかった、キーイベントの登録名（例: `generate_lead`）と実際の送信名
# （例: `gen_lead_form`）が前方一致で食い違っているケースを拾えるかどうかと、
# 誤検出（共通の接頭辞だけで似て見える無関係なイベント）を拾わないことの両方を確認する。

def test_find_similar_firing_events_catches_abbreviated_prefix():
    """登録 `generate_lead` に対し、送信 `gen_lead_form`（`gen`は`generate`の省略）を拾う."""
    from measurement_design.review.kpi_coverage import find_similar_firing_events

    events_observed = [
        {"name": "gen_lead_form", "count": 42},
        {"name": "page_view", "count": 10000},
    ]

    out = find_similar_firing_events("generate_lead", events_observed)

    assert [c["event"] for c in out] == ["gen_lead_form"]
    assert out[0]["count"] == 42


def test_find_similar_firing_events_ignores_shared_generic_prefix_only():
    """`click_tel`（電話タップ）と`click_email`は`click`しか共通せず、無関係なので拾わない.

    文字列全体の類似度（difflibのSequenceMatcher等）だと`click_`という共通の接頭辞
    だけで7〜8割似てしまい誤検出する。単語（トークン）単位で見て、登録名の
    全トークンが候補側に対応づけられる場合だけを候補にすることで、これを避ける。
    """
    from measurement_design.review.kpi_coverage import find_similar_firing_events

    events_observed = [{"name": "click_email", "count": 100}]

    out = find_similar_firing_events("click_tel", events_observed)

    assert out == []


def test_find_similar_firing_events_excludes_enhanced_measurement():
    """GA4拡張計測イベントは有効化するだけで発火するため候補から外す."""
    from measurement_design.review.kpi_coverage import find_similar_firing_events

    events_observed = [{"name": "video_complete", "count": 999}]

    out = find_similar_firing_events("video_completed", events_observed)

    assert out == []


def test_find_similar_firing_events_excludes_already_registered_names():
    """他のKPI/キーイベントとして既に登録済みのイベント名は候補にしない."""
    from measurement_design.review.kpi_coverage import find_similar_firing_events

    events_observed = [{"name": "gen_lead_form", "count": 42}]

    out = find_similar_firing_events("generate_lead", events_observed, exclude={"gen_lead_form"})

    assert out == []


def test_find_similar_firing_events_skips_zero_count_candidates():
    """候補側も実際に発火していない（0件）なら、送信名として意味が無いので除外する."""
    from measurement_design.review.kpi_coverage import find_similar_firing_events

    events_observed = [{"name": "gen_lead_form", "count": 0}]

    out = find_similar_firing_events("generate_lead", events_observed)

    assert out == []


def test_check_key_event_name_mismatches_flags_zero_fire_registered_event():
    """source=registered・0件発火のイベントについて、似た名前の候補を返す."""
    from measurement_design.review.kpi_coverage import check_key_event_name_mismatches

    kpi_rows = [{
        "kpi_id": "kpi_001", "kpi_name": "問い合わせ数", "event": "generate_lead",
        "status": "未実装", "count": 0, "source": "registered",
    }]
    review_data = {"ga4": {"events_observed": [{"name": "gen_lead_form", "count": 42}]}}

    out = check_key_event_name_mismatches(kpi_rows, review_data)

    assert len(out) == 1
    assert out[0]["registered_event"] == "generate_lead"
    assert out[0]["candidates"][0]["event"] == "gen_lead_form"


def test_check_key_event_name_mismatches_skips_candidate_source():
    """イベント名自体がLLM推定（source=candidate）の行は対象外（二重の当てずっぽうを避ける）."""
    from measurement_design.review.kpi_coverage import check_key_event_name_mismatches

    kpi_rows = [{
        "kpi_id": "kpi_002", "kpi_name": "会員登録数", "event": "sign_up",
        "status": "未実装", "count": 0, "source": "candidate",
    }]
    review_data = {"ga4": {"events_observed": [{"name": "sign_up_complete", "count": 10}]}}

    out = check_key_event_name_mismatches(kpi_rows, review_data)

    assert out == []


def test_check_key_event_name_mismatches_skips_already_firing_events():
    """発火している（status=実装済み）行は0件発火ではないので対象外."""
    from measurement_design.review.kpi_coverage import check_key_event_name_mismatches

    kpi_rows = [{
        "kpi_id": "kpi_003", "kpi_name": "資料請求", "event": "download_thanks",
        "status": "実装済み", "count": 5, "source": "registered",
    }]
    review_data = {"ga4": {"events_observed": [{"name": "download_thanks_v2", "count": 5}]}}

    out = check_key_event_name_mismatches(kpi_rows, review_data)

    assert out == []
