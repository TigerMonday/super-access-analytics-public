"""analysis_calc.py（基本分析レポートの計算ロジック）のユニットテスト

GA4 API・BigQueryへの依存が無い純粋関数のみを対象にする（実データ・認証不要）。
"""

from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import analysis_calc as calc  # noqa: E402


class PrimaryNameFallbackTest(unittest.TestCase):
    def test_single_event_uses_primary_name_when_mapping_is_missing(self):
        self.assertEqual(
            calc.apply_primary_name_fallback(["form_submit"], {}, "お問い合わせ完了数"),
            {"form_submit": "お問い合わせ完了数"},
        )

    def test_multiple_events_are_not_guessed(self):
        self.assertEqual(
            calc.apply_primary_name_fallback(["a", "b"], {}, "お問い合わせ完了数"), {}
        )

# 01の schema.match_site_segment() との二重化パリティテスト専用（依存は増やさない設計のため、
# 02本体からは読み込まず、テストからのみ読み込む。tests/ -> parameter_management/ ->
# 04_traffic_analysis/ -> リポジトリ直下、の3階層上に 01_context_management/ がある）。
# `import context_store` だと context_store/__init__.py 経由で loader.py の
# 依存（pyyaml。02には無い）まで読み込まれてしまうため、schema.py単体をファイルパスから
# 直接ロードする（schema.py自体は標準ライブラリのみに依存）。
import importlib.util

_NINE_SCHEMA_PATH = (
    Path(__file__).resolve().parents[3] / "01_context_management" / "src" / "context_store" / "schema.py"
)
_spec = importlib.util.spec_from_file_location("ctx_schema_09", _NINE_SCHEMA_PATH)
ctx_schema = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ctx_schema)


class DeltaPctTest(unittest.TestCase):
    def test_positive_increase(self):
        self.assertEqual(calc.delta_pct(120, 100), "+20.0%")

    def test_decrease(self):
        self.assertEqual(calc.delta_pct(80, 100), "-20.0%")

    def test_no_change(self):
        self.assertEqual(calc.delta_pct(100, 100), "+0.0%")

    def test_prev_zero_is_dash(self):
        self.assertEqual(calc.delta_pct(50, 0), "-")


class DeltaPtTest(unittest.TestCase):
    """率どうしの差分（ポイント表記）。バグ報告の実例（73.8% → 72.3%）で検証する。"""

    def test_reported_bug_case(self):
        # 73.8% と 72.3% の差は「+1.5pt」であり、delta_pctが返す相対変化率(+2.1%)ではない
        self.assertEqual(calc.delta_pt(0.738, 0.723), "+1.5pt")

    def test_positive_increase(self):
        self.assertEqual(calc.delta_pt(0.60, 0.50), "+10.0pt")

    def test_decrease(self):
        self.assertEqual(calc.delta_pt(0.50, 0.60), "-10.0pt")

    def test_no_change(self):
        self.assertEqual(calc.delta_pt(0.50, 0.50), "+0.0pt")

    def test_prev_zero_still_computes(self):
        # delta_pctと違い、率の差分は比較対象が0でも意味を持つため "-" にはしない
        self.assertEqual(calc.delta_pt(0.10, 0.0), "+10.0pt")


class ComputeFunnelTest(unittest.TestCase):
    def test_normal_funnel_three_steps(self):
        steps = [
            {"label": "流入", "sessions": 1000},
            {"label": "中間ページ到達", "sessions": 300},
            {"label": "CV達成", "sessions": 30},
        ]
        out = calc.compute_funnel(steps)
        self.assertEqual(len(out), 3)
        # 先頭ステップ: step_rateはNone、overall_rateは100%
        self.assertIsNone(out[0]["step_rate"])
        self.assertAlmostEqual(out[0]["overall_rate"], 100.0)
        # 中間ステップ: 到達率(対前ステップ) = 300/1000 = 30%
        self.assertAlmostEqual(out[1]["step_rate"], 30.0)
        self.assertAlmostEqual(out[1]["overall_rate"], 30.0)
        # 最終ステップ: 到達後の転換率(対中間ステップ) = 30/300 = 10%、全体CVR = 30/1000 = 3%
        self.assertAlmostEqual(out[2]["step_rate"], 10.0)
        self.assertAlmostEqual(out[2]["overall_rate"], 3.0)
        self.assertIsNone(out[2]["note"])

    def test_empty_steps(self):
        self.assertEqual(calc.compute_funnel([]), [])

    def test_single_step_only_baseline(self):
        out = calc.compute_funnel([{"label": "流入", "sessions": 500}])
        self.assertEqual(len(out), 1)
        self.assertIsNone(out[0]["step_rate"])

    def test_zero_base_sessions_no_zero_division(self):
        steps = [{"label": "流入", "sessions": 0}, {"label": "中間", "sessions": 0}]
        out = calc.compute_funnel(steps)
        self.assertEqual(out[1]["overall_rate"], 0.0)
        self.assertEqual(out[1]["step_rate"], 0.0)

    def test_clamped_when_later_step_exceeds_prior(self):
        """GA4の少量データ丸め処理により後段が前段を上回るケースをクランプする"""
        steps = [
            {"label": "流入", "sessions": 100},
            {"label": "中間ページ到達", "sessions": 130},  # 前段(100)を上回る異常値
        ]
        out = calc.compute_funnel(steps)
        self.assertEqual(out[1]["step_rate"], 100.0)
        self.assertEqual(out[1]["overall_rate"], 100.0)
        self.assertIsNotNone(out[1]["note"])

    def test_zero_prev_sessions_mid_funnel(self):
        steps = [
            {"label": "流入", "sessions": 100},
            {"label": "中間A", "sessions": 0},
            {"label": "中間B", "sessions": 0},
        ]
        out = calc.compute_funnel(steps)
        self.assertEqual(out[2]["step_rate"], 0.0)


class SelectFunnelsTest(unittest.TestCase):
    """CVごとに1本のファネルを作る設計の本数絞り込み（CV件数の多い順に上限まで）。"""

    def test_zero_key_events(self):
        selected, excluded = calc.select_funnels({}, max_funnels=5)
        self.assertEqual(selected, [])
        self.assertEqual(excluded, [])

    def test_single_key_event(self):
        selected, excluded = calc.select_funnels({"form_submit": 546}, max_funnels=5)
        self.assertEqual(selected, ["form_submit"])
        self.assertEqual(excluded, [])

    def test_multiple_within_limit_ordered_by_count_desc(self):
        counts = {"a": 10, "b": 546, "c": 177}
        selected, excluded = calc.select_funnels(counts, max_funnels=5)
        self.assertEqual(selected, ["b", "c", "a"])
        self.assertEqual(excluded, [])

    def test_caps_at_five_and_records_excluded_with_counts(self):
        # 実データの例（contact_service_thanks等）を模した6件。5本を超えた1件は打ち切り、
        # 黙って消さずに件数付きで記録する。
        counts = {
            "ev_a": 600, "ev_b": 546, "ev_c": 300, "ev_d": 177, "ev_e": 50, "ev_f": 3,
        }
        selected, excluded = calc.select_funnels(counts, max_funnels=5)
        self.assertEqual(len(selected), 5)
        self.assertEqual(selected, ["ev_a", "ev_b", "ev_c", "ev_d", "ev_e"])
        self.assertEqual(excluded, [("ev_f", 3)])

    def test_ties_preserve_dict_order(self):
        counts = {"first": 100, "second": 100}
        selected, _ = calc.select_funnels(counts, max_funnels=5)
        self.assertEqual(selected, ["first", "second"])


class RankPageCandidatesTest(unittest.TestCase):
    """CVファネルの中間ページ候補の順位付け（セッション数の多い順）。"""

    def test_orders_by_sessions_descending(self):
        rows = [
            {"pagePathPlusQueryString": "/contact/", "sessions": 300},
            {"pagePathPlusQueryString": "/contact/service/", "sessions": 900},
            {"pagePathPlusQueryString": "/contact/thanks", "sessions": 826},
        ]
        out = calc.rank_page_candidates(rows)
        self.assertEqual(
            [r["pagePathPlusQueryString"] for r in out],
            ["/contact/service/", "/contact/thanks", "/contact/"],
        )

    def test_limit_truncates(self):
        rows = [{"sessions": i} for i in range(20)]
        out = calc.rank_page_candidates(rows, limit=3)
        self.assertEqual(len(out), 3)
        self.assertEqual([r["sessions"] for r in out], [19, 18, 17])

    def test_empty_rows(self):
        self.assertEqual(calc.rank_page_candidates([]), [])

    def test_thanks_page_type_excludes_self_and_query_variants(self):
        """サンクスページのpage_viewとして発火する型: 完了ページ自身とクエリ文字列違いが
        除外扱いになり、除外候補ではない行が無ければ全行が除外扱いのまま返る
        （黙って消さない。実データ: contact_service_thanksイベントの候補が全て
        /contact/service/thanks/ とそのクエリ文字列違いだったケースの再現）。"""
        rows = [
            {"pagePathPlusQueryString": "/contact/service/thanks/", "sessions": 29},
            {
                "pagePathPlusQueryString": "/contact/service/thanks/?submissionGuid=abc",
                "sessions": 3,
            },
            {
                "pagePathPlusQueryString": "/contact/service/thanks/?submissionGuid=def",
                "sessions": 2,
            },
        ]
        out = calc.rank_page_candidates(rows, event_name="contact_service_thanks")
        self.assertTrue(all(r["excluded_self"] for r in out))
        # セッション数の多い順は除外扱いになっても維持される
        self.assertEqual([r["sessions"] for r in out], [29, 3, 2])

    def test_click_type_keeps_firing_page_as_candidate(self):
        """ボタンクリック等で発火する型: 発火ページ＝入力前ページ＝正解なので、
        イベント名がアクション名（フォームのパスに由来しない命名）であれば除外されない。"""
        rows = [
            {"pagePathPlusQueryString": "/contact/service/", "sessions": 900},
            {"pagePathPlusQueryString": "/contact/", "sessions": 300},
        ]
        out = calc.rank_page_candidates(rows, event_name="form_submit")
        self.assertEqual([r["excluded_self"] for r in out], [False, False])
        self.assertEqual(out[0]["pagePathPlusQueryString"], "/contact/service/")

    def test_mixed_excluded_rows_ranked_after_kept_rows(self):
        """除外候補（自イベント発火ページ）と正規の候補が混在する場合、除外候補は
        セッション数で上回っていても非除外の候補より後ろに回す
        （無人実行で候補1位をそのまま採用する運用が、除外候補を誤って拾わないようにする）。"""
        rows = [
            {"pagePathPlusQueryString": "/download/thanks/", "sessions": 100},
            {"pagePathPlusQueryString": "/download/", "sessions": 40},
        ]
        out = calc.rank_page_candidates(rows, event_name="download_thanks")
        self.assertEqual(
            [r["pagePathPlusQueryString"] for r in out],
            ["/download/", "/download/thanks/"],
        )
        self.assertEqual([r["excluded_self"] for r in out], [False, True])

    def test_no_event_name_keeps_backward_compatible_shape(self):
        """event_name を渡さない場合は従来通り excluded_self を付けない（後方互換）。"""
        rows = [{"pagePathPlusQueryString": "/a/", "sessions": 1}]
        out = calc.rank_page_candidates(rows)
        self.assertNotIn("excluded_self", out[0])


class IsEventSelfPageTest(unittest.TestCase):
    """イベント名とページパスの命名対応から「イベント自身の発火ページ」を推定する判定。"""

    def test_thanks_suffix_matches_own_page(self):
        self.assertTrue(
            calc.is_event_self_page("contact_service_thanks", "/contact/service/thanks/")
        )
        self.assertTrue(
            calc.is_event_self_page(
                "download_thanks",
                "/download/thanks/?submissionGuid=58175e04-450c-41cc-881e-369186b25078",
            )
        )

    def test_pre_submission_page_is_not_self(self):
        self.assertFalse(calc.is_event_self_page("contact_service_thanks", "/contact/service/"))

    def test_action_named_event_is_not_self(self):
        self.assertFalse(calc.is_event_self_page("form_submit", "/contact/service/"))
        self.assertFalse(calc.is_event_self_page("cta_click", "/download/"))


class WithParentPathGuessTest(unittest.TestCase):
    """候補が全て除外扱い（サンクスページ型）のとき、完了ページの親パスを既に取得済みの
    ページ一覧（ランディングページ別など）と照合して「推定候補」を追加するロジック。

    fetch_page_candidates_for_event() 自体は、GA4がディメンションと指標をイベント行で
    結合する構造上、「イベント自身が発火したページ」しか返せない（is_event_self_page()の
    除外を直しても、この関数の戻り値には入力前ページが物理的に含まれない）。実データでも
    contact_service_thanks / download_thanksの候補が完了ページ自身のクエリ文字列違い
    だけになることを確認済み。そのため、完了ページのパスから親パスを辿り、既に取得済みの
    別のデータ（ランディングページ一覧）と突き合わせて推定する。
    """

    def test_finds_immediate_parent_in_landing_pages(self):
        candidates = calc.rank_page_candidates(
            [
                {"pagePathPlusQueryString": "/contact/service/thanks/", "sessions": 29},
                {
                    "pagePathPlusQueryString": "/contact/service/thanks/?submissionGuid=abc",
                    "sessions": 3,
                },
            ],
            event_name="contact_service_thanks",
        )
        landing_pages = [
            {"landingPagePlusQueryString": "/", "sessions": 21582, "conversions": 291},
            {"landingPagePlusQueryString": "/contact/service/", "sessions": 1079, "conversions": 205},
        ]
        out = calc.with_parent_path_guess(candidates, landing_pages)
        self.assertEqual(out[0]["pagePathPlusQueryString"], "/contact/service/")
        self.assertEqual(out[0]["sessions"], 1079)
        self.assertEqual(out[0]["conversions"], 205)
        self.assertFalse(out[0]["excluded_self"])
        self.assertTrue(out[0]["estimated_from_parent"])
        # 元の候補（除外扱い）は消さずにそのまま後ろに残る
        self.assertEqual(len(out), 1 + len(candidates))

    def test_climbs_further_when_immediate_parent_not_in_landing_pages(self):
        """階層が深い場合（/a/b/c/thanks/）に、直近の親（/a/b/c/）がランディングページ一覧に
        無く、さらに上の階層（/a/b/）にあるケース。"""
        candidates = calc.rank_page_candidates(
            [{"pagePathPlusQueryString": "/a/b/c/thanks/", "sessions": 10}],
            event_name="c_thanks",
        )
        landing_pages = [
            {"landingPagePlusQueryString": "/a/b/", "sessions": 500, "conversions": 40},
        ]
        out = calc.with_parent_path_guess(candidates, landing_pages)
        self.assertEqual(out[0]["pagePathPlusQueryString"], "/a/b/")
        self.assertEqual(out[0]["sessions"], 500)
        self.assertTrue(out[0]["estimated_from_parent"])

    def test_no_guess_when_no_ancestor_found(self):
        """親パスをルートまで遡ってもランディングページ一覧に無ければ、何も追加せず
        元の（全件除外扱いの）候補をそのまま返す。"""
        candidates = calc.rank_page_candidates(
            [{"pagePathPlusQueryString": "/download/thanks/", "sessions": 10}],
            event_name="download_thanks",
        )
        landing_pages = [
            {"landingPagePlusQueryString": "/company/", "sessions": 2302, "conversions": 10},
        ]
        out = calc.with_parent_path_guess(candidates, landing_pages)
        self.assertEqual(out, candidates)

    def test_no_guess_when_real_candidates_already_exist(self):
        """クリック発火型など、除外されていない正規の候補が既にあれば推定は行わない
        （素通りする）。"""
        candidates = calc.rank_page_candidates(
            [{"pagePathPlusQueryString": "/contact/service/", "sessions": 900}],
            event_name="form_submit",
        )
        landing_pages = [
            {"landingPagePlusQueryString": "/contact/", "sessions": 5000, "conversions": 50},
        ]
        out = calc.with_parent_path_guess(candidates, landing_pages)
        self.assertEqual(out, candidates)

    def test_aggregates_query_string_variants_in_landing_pages(self):
        """ランディングページ一覧側にクエリ文字列違いが複数あれば、パス単位で合算する。"""
        candidates = calc.rank_page_candidates(
            [{"pagePathPlusQueryString": "/download/thanks/", "sessions": 10}],
            event_name="download_thanks",
        )
        landing_pages = [
            {"landingPagePlusQueryString": "/download/?utm_source=a", "sessions": 300, "conversions": 20},
            {"landingPagePlusQueryString": "/download/?utm_source=b", "sessions": 200, "conversions": 10},
        ]
        out = calc.with_parent_path_guess(candidates, landing_pages)
        self.assertEqual(out[0]["pagePathPlusQueryString"], "/download/")
        self.assertEqual(out[0]["sessions"], 500)
        self.assertEqual(out[0]["conversions"], 30)

    def test_empty_candidates_returns_empty(self):
        self.assertEqual(calc.with_parent_path_guess([], [{"landingPagePlusQueryString": "/", "sessions": 1}]), [])


class UnclassifiedDiffTest(unittest.TestCase):
    """デバイス別・新規/リピーター別のシェアの分母を全体セッションに揃えるための差分算出。

    実データで発生した不具合（デバイス3カテゴリの合計がセッション全体と4,009件ずれ、
    デバイス不明のセッションが出力のどこにも現れなかった）の再発防止。
    """

    def test_positive_diff_when_breakdown_falls_short(self):
        rows = [{"sessions": 205367}, {"sessions": 127380}, {"sessions": 2442}]
        diff = calc.unclassified_diff(339198, rows)
        self.assertEqual(diff, 4009)

    def test_zero_diff_when_breakdown_matches_total(self):
        rows = [{"sessions": 100}, {"sessions": 200}]
        self.assertEqual(calc.unclassified_diff(300, rows), 0)

    def test_clamped_to_zero_when_breakdown_exceeds_total(self):
        # サンプリング等の誤差で内訳合計が全体を上回っても、負の行は作らない
        rows = [{"sessions": 200}, {"sessions": 200}]
        self.assertEqual(calc.unclassified_diff(300, rows), 0)

    def test_empty_rows_returns_full_total(self):
        self.assertEqual(calc.unclassified_diff(100, []), 100)


class ReconciliationDiffTest(unittest.TestCase):
    """課題2: 絞り込み条件付きの取得（フィルタ・クロス集計）の内訳合計と参照値の差を、
    unclassified_diff() と違って符号付き（クランプ無し）で返すことの検証。
    06が実測した実例（ホスト名別+6,645、デバイス別を月で絞ると-1,312 など）を想定。
    """

    def test_positive_diff_when_subtotal_falls_short(self):
        rows = [{"sessions": 300}, {"sessions": 200}]
        self.assertEqual(calc.reconciliation_diff(600, rows), 100)

    def test_negative_diff_when_subtotal_exceeds_reference(self):
        # 例: ホスト名別の内訳合計が全体セッションを上回るケース（+6,645件の実例）
        rows = [{"sessions": 400}, {"sessions": 300}]
        self.assertEqual(calc.reconciliation_diff(600, rows), -100)

    def test_zero_diff_when_matching(self):
        rows = [{"sessions": 300}, {"sessions": 300}]
        self.assertEqual(calc.reconciliation_diff(600, rows), 0)

    def test_empty_rows_returns_full_reference_total(self):
        self.assertEqual(calc.reconciliation_diff(100, []), 100)


class FormatReconciliationNoteTest(unittest.TestCase):
    def test_no_note_when_diff_is_zero(self):
        rows = [{"sessions": 300}, {"sessions": 300}]
        self.assertIsNone(calc.format_reconciliation_note(600, rows))

    def test_shortfall_note_mentions_both_totals_and_diff(self):
        rows = [{"sessions": 300}]
        note = calc.format_reconciliation_note(1000, rows, reference_label="全体セッション")
        self.assertIn("300", note)
        self.assertIn("1,000", note)
        self.assertIn("700", note)
        self.assertIn("届いていない", note)
        self.assertTrue(note.startswith("※"))

    def test_excess_note_mentions_overcounting(self):
        rows = [{"sessions": 700}]
        note = calc.format_reconciliation_note(100, rows, reference_label="全体セッション")
        self.assertIn("700", note)
        self.assertIn("100", note)
        self.assertIn("600", note)
        self.assertIn("上回っている", note)

    def test_custom_labels_are_used_in_note(self):
        rows = [{"sessions": 50}]
        note = calc.format_reconciliation_note(
            100, rows, reference_label="ホスト名別の参照値", subtotal_label="ホスト名別の内訳合計"
        )
        self.assertIn("ホスト名別の参照値", note)
        self.assertIn("ホスト名別の内訳合計", note)


class RankWithGapTest(unittest.TestCase):
    def test_gap_detection(self):
        rows = [
            {"label": "A", "sessions": 1000, "conversions": 5},
            {"label": "B", "sessions": 100, "conversions": 20},
            {"label": "C", "sessions": 500, "conversions": 10},
        ]
        out = calc.rank_with_gap(rows, "sessions", "conversions", "label")
        by_label = {r["label"]: r for r in out}
        # セッション順位: A(1) > C(2) > B(3)
        self.assertEqual(by_label["A"]["session_rank"], 1)
        self.assertEqual(by_label["C"]["session_rank"], 2)
        self.assertEqual(by_label["B"]["session_rank"], 3)
        # CV順位: B(1) > C(2) > A(3)
        self.assertEqual(by_label["B"]["cv_rank"], 1)
        self.assertEqual(by_label["C"]["cv_rank"], 2)
        self.assertEqual(by_label["A"]["cv_rank"], 3)
        # rank_gap = session_rank - cv_rank
        self.assertEqual(by_label["B"]["rank_gap"], 3 - 1)  # 量は少ないが質は高い
        self.assertEqual(by_label["A"]["rank_gap"], 1 - 3)  # 量は多いが質は低い

    def test_empty_rows(self):
        self.assertEqual(calc.rank_with_gap([], "sessions", "conversions", "label"), [])


class AttachEntranceRateTest(unittest.TestCase):
    def test_matching_landing_page(self):
        pages = [{"pagePathPlusQueryString": "/lp/", "screenPageViews": 200}]
        landing_pages = [{"landingPagePlusQueryString": "/lp/", "sessions": 150}]
        out = calc.attach_entrance_rate(pages, landing_pages)
        self.assertEqual(out[0]["entrances"], 150)
        self.assertAlmostEqual(out[0]["entrance_rate"], 75.0)

    def test_page_not_a_landing_page(self):
        pages = [{"pagePathPlusQueryString": "/other/", "screenPageViews": 100}]
        landing_pages = [{"landingPagePlusQueryString": "/lp/", "sessions": 150}]
        out = calc.attach_entrance_rate(pages, landing_pages)
        self.assertEqual(out[0]["entrances"], 0)
        self.assertEqual(out[0]["entrance_rate"], 0.0)

    def test_trailing_slash_difference_uses_normalized_fallback(self):
        pages = [{"pagePathPlusQueryString": "/article/", "screenPageViews": 200}]
        landing_pages = [{"landingPagePlusQueryString": "/article", "sessions": 150}]
        out = calc.attach_entrance_rate(pages, landing_pages)
        self.assertEqual(out[0]["entrances"], 150)
        self.assertAlmostEqual(out[0]["entrance_rate"], 75.0)

    def test_exact_path_takes_precedence_over_normalized_variant(self):
        pages = [{"pagePathPlusQueryString": "/article/", "screenPageViews": 200}]
        landing_pages = [
            {"landingPagePlusQueryString": "/article/", "sessions": 120},
            {"landingPagePlusQueryString": "/article", "sessions": 30},
        ]
        out = calc.attach_entrance_rate(pages, landing_pages)
        self.assertEqual(out[0]["entrances"], 120)

    def test_zero_views_no_zero_division(self):
        pages = [{"pagePathPlusQueryString": "/x/", "screenPageViews": 0}]
        landing_pages = []
        out = calc.attach_entrance_rate(pages, landing_pages)
        self.assertEqual(out[0]["entrance_rate"], 0.0)


class FormatWeekRangeTest(unittest.TestCase):
    def test_week1_starts_january_1_short_week(self):
        # 2026-01-01は木曜（weekday=3）なので第1週は1/1〜1/3の3日間の部分週
        self.assertEqual(calc.format_week_range("202601"), "2026/01/01〜01/03")

    def test_week1_full_when_jan1_is_sunday(self):
        # 2023-01-01は日曜（weekday=6）なので第1週はまるまる7日間
        self.assertEqual(date(2023, 1, 1).weekday(), 6)
        self.assertEqual(calc.format_week_range("202301"), "2023/01/01〜01/07")

    def test_ordinary_week_is_sunday_to_saturday(self):
        # 2026-W32: 第1週(1/1〜1/3)の後、日曜起点で7日ずつ進む
        result = calc.format_week_range("202632")
        self.assertEqual(result, "2026/08/02〜08/08")
        start_str, end_str = result.split("〜")
        self.assertEqual(date(*[int(x) for x in start_str.split("/")]).weekday(), 6)  # 日曜始まり

    def test_last_week_of_year_clamped_to_dec31(self):
        # 2026年は12/31まで、第53週は12/27〜12/31の5日間に打ち切られる
        self.assertEqual(calc.format_week_range("202653"), "2026/12/27〜12/31")


class MarkIncompleteMonthsTest(unittest.TestCase):
    def test_boundary_months_flagged(self):
        rows = [
            {"yearMonth": "202601", "sessions": 100},
            {"yearMonth": "202602", "sessions": 200},
            {"yearMonth": "202603", "sessions": 50},
        ]
        # 期間: 2026-01-15 〜 2026-03-10（両端とも月の途中）
        out = calc.mark_incomplete_months(
            rows, "yearMonth", date(2026, 1, 15), date(2026, 3, 10)
        )
        self.assertTrue(out[0]["incomplete"])  # 1月: 開始が月の途中
        self.assertFalse(out[1]["incomplete"])  # 2月: まるまる1ヶ月
        self.assertTrue(out[2]["incomplete"])  # 3月: 終了が月の途中

    def test_full_month_range_not_flagged(self):
        rows = [{"yearMonth": "202602", "sessions": 100}]
        out = calc.mark_incomplete_months(
            rows, "yearMonth", date(2026, 2, 1), date(2026, 2, 28)
        )
        self.assertFalse(out[0]["incomplete"])

    def test_empty_rows(self):
        self.assertEqual(
            calc.mark_incomplete_months([], "yearMonth", date(2026, 1, 1), date(2026, 1, 31)),
            [],
        )

    def test_single_month_both_ends_incomplete(self):
        rows = [{"yearMonth": "202601", "sessions": 10}]
        out = calc.mark_incomplete_months(
            rows, "yearMonth", date(2026, 1, 10), date(2026, 1, 20)
        )
        self.assertTrue(out[0]["incomplete"])


class ParseEventNamesJsonTest(unittest.TestCase):
    """01の kpis.yaml 由来の {event_name: KPI名} をJSONで受け取るCLI引数のパース。

    レポートを止めないことが最優先のため、不正な入力は例外を出さず空辞書にする。
    """

    def test_valid_json_object(self):
        self.assertEqual(
            calc.parse_event_names_json('{"form_submit": "お問い合わせ完了数"}'),
            {"form_submit": "お問い合わせ完了数"},
        )

    def test_none_returns_empty_dict(self):
        self.assertEqual(calc.parse_event_names_json(None), {})

    def test_empty_string_returns_empty_dict(self):
        self.assertEqual(calc.parse_event_names_json(""), {})

    def test_blank_string_returns_empty_dict(self):
        self.assertEqual(calc.parse_event_names_json("   "), {})

    def test_invalid_json_returns_empty_dict_not_raises(self):
        self.assertEqual(calc.parse_event_names_json("{not valid json"), {})

    def test_non_object_json_returns_empty_dict(self):
        # 配列や文字列など、オブジェクト以外のJSONは無視する
        self.assertEqual(calc.parse_event_names_json('["form_submit"]'), {})
        self.assertEqual(calc.parse_event_names_json('"form_submit"'), {})

    def test_empty_value_entries_are_dropped(self):
        # 名前が空文字/nullのエントリは「未登録」と区別がつくよう保持しない
        self.assertEqual(
            calc.parse_event_names_json('{"form_submit": "問い合わせ", "file_download": ""}'),
            {"form_submit": "問い合わせ"},
        )


class FormatFunnelTitleTest(unittest.TestCase):
    """CVファネル見出し用の表示名（01のKPI名 + イベント名、未登録はイベント名のみ）。"""

    def test_name_registered(self):
        self.assertEqual(
            calc.format_funnel_title("contact_service_thanks", {"contact_service_thanks": "サービス相談数"}),
            "サービス相談数（contact_service_thanks）",
        )

    def test_name_not_registered_falls_back_to_event(self):
        self.assertEqual(calc.format_funnel_title("contact_service_thanks", {}), "contact_service_thanks")

    def test_event_names_none_falls_back_to_event(self):
        # 09未登録のクライアント（event_namesそのものが渡らない）でもエラーにしない
        self.assertEqual(calc.format_funnel_title("contact_service_thanks", None), "contact_service_thanks")

    def test_event_missing_from_mapping_falls_back(self):
        # 01に登録はあるが、このイベント自体はどのKPIにも紐づいていないケース
        self.assertEqual(
            calc.format_funnel_title("untracked_event", {"form_submit": "問い合わせ"}),
            "untracked_event",
        )


class FormatKeyEventsHeaderTest(unittest.TestCase):
    """レポートヘッダーの「キーイベント」表示（イベントコード起点、KPI名を併記）。"""

    def test_empty_key_events(self):
        self.assertEqual(calc.format_key_events_header([], {}), "(なし)")

    def test_single_event_with_name(self):
        self.assertEqual(
            calc.format_key_events_header(["form_submit"], {"form_submit": "お問い合わせ完了数"}),
            "`form_submit`（お問い合わせ完了数）",
        )

    def test_single_event_without_name_falls_back(self):
        # 01が未登録のクライアント（event_namesが空辞書）でもエラーにせずイベント名のみで表示
        self.assertEqual(calc.format_key_events_header(["form_submit"], {}), "`form_submit`")

    def test_event_names_none_falls_back(self):
        self.assertEqual(calc.format_key_events_header(["form_submit"], None), "`form_submit`")

    def test_multiple_events_different_names(self):
        self.assertEqual(
            calc.format_key_events_header(
                ["form_submit", "file_download"],
                {"form_submit": "お問い合わせ完了数", "file_download": "資料ダウンロード数"},
            ),
            "`form_submit`（お問い合わせ完了数）、`file_download`（資料ダウンロード数）",
        )

    def test_one_kpi_with_multiple_events_grouped_together(self):
        # 1つのKPI（kpis.yamlのevents配列）が複数イベントを持つ場合はまとめて1つの名前表記にする
        self.assertEqual(
            calc.format_key_events_header(
                ["generate_lead", "form_submit"],
                {"generate_lead": "お問い合わせ完了数", "form_submit": "お問い合わせ完了数"},
            ),
            "`generate_lead`、`form_submit`（お問い合わせ完了数）",
        )

    def test_mixed_registered_and_unregistered_events(self):
        # 01に登録が無いイベントが分析対象に含まれても壊れず、そのイベントだけ単独表示になる
        self.assertEqual(
            calc.format_key_events_header(
                ["form_submit", "untracked_event"],
                {"form_submit": "お問い合わせ完了数"},
            ),
            "`form_submit`（お問い合わせ完了数）、`untracked_event`",
        )

    def test_multiple_unregistered_events_not_grouped_together(self):
        # 名前が無いイベント同士は、同じ意味であるかのようにまとめない（個別表示のまま）
        self.assertEqual(
            calc.format_key_events_header(["ev_a", "ev_b"], {}),
            "`ev_a`、`ev_b`",
        )


class SelectFunnelsPrimaryTest(unittest.TestCase):
    """主KPI（01の優先度1）のファネルを、CV件数の上限cutoffで黙って落とさない。"""

    def test_primary_event_promoted_ahead_of_higher_count(self):
        # 相談(30件)は資料DL(600件)よりCVが少ないが、主KPIなので先頭に来る
        counts = {"contact_service_thanks": 30, "download_thanks": 600}
        selected, excluded = calc.select_funnels(
            counts, max_funnels=5, primary_events={"contact_service_thanks"}
        )
        self.assertEqual(selected, ["contact_service_thanks", "download_thanks"])
        self.assertEqual(excluded, [])

    def test_primary_event_survives_max_funnels_cutoff(self):
        counts = {"primary_ev": 1, "b": 600, "c": 500, "d": 400, "e": 300, "f": 200}
        selected, excluded = calc.select_funnels(
            counts, max_funnels=5, primary_events={"primary_ev"}
        )
        self.assertIn("primary_ev", selected)
        self.assertEqual(len(selected), 5)
        self.assertNotIn("primary_ev", [name for name, _ in excluded])

    def test_no_primary_events_keeps_old_behavior(self):
        counts = {"a": 10, "b": 546, "c": 177}
        selected, _ = calc.select_funnels(counts, max_funnels=5, primary_events=None)
        self.assertEqual(selected, ["b", "c", "a"])

    def test_empty_primary_events_set_keeps_old_behavior(self):
        counts = {"a": 10, "b": 546}
        selected, _ = calc.select_funnels(counts, max_funnels=5, primary_events=set())
        self.assertEqual(selected, ["b", "a"])


class KpiLabelsAndEventsTest(unittest.TestCase):
    """CVを内訳表示する際の「KPI単位」へのグループ化（表示ラベル確定込み）。"""

    def test_single_event_no_name_uses_event_as_label(self):
        self.assertEqual(
            calc.kpi_labels_and_events(["form_submit"], {}),
            [("form_submit", ["form_submit"])],
        )

    def test_named_event_uses_kpi_name_as_label(self):
        self.assertEqual(
            calc.kpi_labels_and_events(["form_submit"], {"form_submit": "問い合わせ完了数"}),
            [("問い合わせ完了数", ["form_submit"])],
        )

    def test_multiple_events_same_kpi_grouped_under_one_label(self):
        self.assertEqual(
            calc.kpi_labels_and_events(
                ["generate_lead", "form_submit"],
                {"generate_lead": "問い合わせ完了数", "form_submit": "問い合わせ完了数"},
            ),
            [("問い合わせ完了数", ["generate_lead", "form_submit"])],
        )

    def test_two_distinct_kpis_kept_separate(self):
        self.assertEqual(
            calc.kpi_labels_and_events(
                ["contact_service_thanks", "download_thanks"],
                {"contact_service_thanks": "サービス相談数", "download_thanks": "資料ダウンロード数"},
            ),
            [
                ("サービス相談数", ["contact_service_thanks"]),
                ("資料ダウンロード数", ["download_thanks"]),
            ],
        )

    def test_empty_key_events_returns_empty_list(self):
        self.assertEqual(calc.kpi_labels_and_events([], {}), [])


class KpiGroupRowsTest(unittest.TestCase):
    """KPIごとのCV件数（当期・前期）の集計と、主KPIの先頭並べ替え・印付け。"""

    def test_single_kpi_one_event(self):
        rows = calc.kpi_group_rows(["form_submit"], {"form_submit": 100}, {"form_submit": 90})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["label"], "form_submit")
        self.assertEqual(rows[0]["current"], 100)
        self.assertEqual(rows[0]["previous"], 90)
        self.assertFalse(rows[0]["is_primary"])

    def test_real_data_two_kpis_sum_matches_known_total(self):
        # 実データ（my-site 2026-08-26取得分）: contact_service_thanks=546, download_thanks=178,
        # 合計724はGA4の「conversions」集計値（キーイベント合計）と一致する既知の値。
        counts = {"contact_service_thanks": 546, "download_thanks": 178}
        rows = calc.kpi_group_rows(
            ["contact_service_thanks", "download_thanks"],
            counts,
            event_names={
                "contact_service_thanks": "サービス相談数",
                "download_thanks": "資料ダウンロード数",
            },
        )
        self.assertEqual(sum(r["current"] for r in rows), 724)
        labels = [r["label"] for r in rows]
        self.assertIn("サービス相談数", labels)
        self.assertIn("資料ダウンロード数", labels)

    def test_priority_unset_keeps_key_events_order_no_marking(self):
        # 09で優先度が未設定（primary_name=None）の場合、順序も印も変えない
        counts = {"contact_service_thanks": 546, "download_thanks": 178}
        rows = calc.kpi_group_rows(
            ["contact_service_thanks", "download_thanks"], counts, primary_name=None
        )
        self.assertEqual(rows[0]["label"], "contact_service_thanks")
        self.assertTrue(all(not r["is_primary"] for r in rows))

    def test_primary_kpi_promoted_first_and_marked(self):
        # 資料ダウンロード数(178件)の方が件数は多いが、優先度1のサービス相談数を先頭にする
        counts = {"contact_service_thanks": 546, "download_thanks": 178}
        rows = calc.kpi_group_rows(
            ["download_thanks", "contact_service_thanks"],
            counts,
            event_names={
                "contact_service_thanks": "サービス相談数",
                "download_thanks": "資料ダウンロード数",
            },
            primary_name="サービス相談数",
        )
        self.assertEqual(rows[0]["label"], "サービス相談数")
        self.assertTrue(rows[0]["is_primary"])
        self.assertFalse(rows[1]["is_primary"])

    def test_primary_name_not_matching_any_group_is_noop(self):
        counts = {"form_submit": 100}
        rows = calc.kpi_group_rows(["form_submit"], counts, primary_name="存在しないKPI名")
        self.assertEqual(rows[0]["label"], "form_submit")
        self.assertFalse(rows[0]["is_primary"])

    def test_previous_omitted_stays_none(self):
        rows = calc.kpi_group_rows(["form_submit"], {"form_submit": 5})
        self.assertIsNone(rows[0]["previous"])

    def test_missing_event_in_counts_defaults_to_zero(self):
        rows = calc.kpi_group_rows(["form_submit"], {})
        self.assertEqual(rows[0]["current"], 0)


class KpiDisplayLabelTest(unittest.TestCase):
    def test_primary_gets_star_prefix(self):
        self.assertEqual(calc.kpi_display_label({"label": "サービス相談数", "is_primary": True}), "★サービス相談数")

    def test_non_primary_has_no_prefix(self):
        self.assertEqual(calc.kpi_display_label({"label": "資料ダウンロード数", "is_primary": False}), "資料ダウンロード数")


class KpiColumnHeadersAndCellsTest(unittest.TestCase):
    """複数CVを列として並べる表（チャネル別・LP別・デバイス別・新規/リピーター別）の列組み立て。"""

    def test_headers_pair_cv_and_cvr_per_label(self):
        self.assertEqual(
            calc.kpi_column_headers(["相談", "資料DL"]),
            ["CV数: 相談", "CVR: 相談", "CV数: 資料DL", "CVR: 資料DL"],
        )

    def test_cells_compute_cvr_against_row_sessions(self):
        breakdown = [{"label": "相談", "current": 7, "converted_sessions": 5, "is_primary": False}]
        self.assertEqual(calc.kpi_column_cells(breakdown, sessions=1000), ["7", "0.70%"])

    def test_cells_zero_sessions_does_not_divide_by_zero(self):
        breakdown = [{"label": "相談", "current": 0, "is_primary": False}]
        self.assertEqual(calc.kpi_column_cells(breakdown, sessions=0), ["0", "0.00%"])


class AttachKpiBreakdownTest(unittest.TestCase):
    """チャネル別等の既存の集計行へのKPI別CV内訳の付与。"""

    def test_single_dim_key_matches_and_defaults_missing_to_zero(self):
        rows = [
            {"sessionDefaultChannelGroup": "Organic Search", "sessions": 1000},
            {"sessionDefaultChannelGroup": "Direct", "sessions": 200},
        ]
        breakdown_rows = [
            {"sessionDefaultChannelGroup": "Organic Search", "eventName": "contact_service_thanks", "conversions": 30},
            {"sessionDefaultChannelGroup": "Organic Search", "eventName": "download_thanks", "conversions": 50},
            # Direct はキーイベントの発火が無いため breakdown_rows に行が無い
        ]
        out = calc.attach_kpi_breakdown(
            rows, "sessionDefaultChannelGroup", breakdown_rows,
            ["contact_service_thanks", "download_thanks"],
            event_names={"contact_service_thanks": "相談", "download_thanks": "資料DL"},
        )
        organic = next(r for r in out if r["sessionDefaultChannelGroup"] == "Organic Search")
        direct = next(r for r in out if r["sessionDefaultChannelGroup"] == "Direct")
        self.assertEqual({b["label"]: b["current"] for b in organic["kpi_breakdown"]}, {"相談": 30, "資料DL": 50})
        self.assertEqual({b["label"]: b["current"] for b in direct["kpi_breakdown"]}, {"相談": 0, "資料DL": 0})

    def test_composite_dim_keys_for_source_medium(self):
        rows = [{"sessionSource": "google", "sessionMedium": "cpc", "sessions": 500}]
        breakdown_rows = [
            {"sessionSource": "google", "sessionMedium": "cpc", "eventName": "form_submit", "conversions": 12},
        ]
        out = calc.attach_kpi_breakdown(
            rows, ("sessionSource", "sessionMedium"), breakdown_rows, ["form_submit"],
        )
        self.assertEqual(out[0]["kpi_breakdown"][0]["current"], 12)

    def test_original_row_fields_preserved(self):
        rows = [{"sessionDefaultChannelGroup": "Direct", "sessions": 200, "conversions": 3}]
        out = calc.attach_kpi_breakdown(rows, "sessionDefaultChannelGroup", [], ["ev"])
        self.assertEqual(out[0]["sessions"], 200)
        self.assertEqual(out[0]["conversions"], 3)


# ---------------------------------------------------------------------------
# サイトセグメント（分析対象の定義。01の site-segments.yaml 由来）
# ---------------------------------------------------------------------------

def _segments_media_vs_main():
    """本体サイト（既定セグメント）とオウンドメディアの2セグメント。

    01の samples/sample-client/site-segments.yaml の記入例に合わせる。
    """
    return [
        {
            "segment_id": "seg_media",
            "name": "オウンドメディア",
            "match": {"path_prefix": "/media/"},
        },
        {
            "segment_id": "seg_main",
            "name": "本体サイト",
            "default": True,
        },
    ]


class MatchSiteSegmentTest(unittest.TestCase):
    """match_site_segment(): 01の schema.match_site_segment() と同じアルゴリズムの検証。"""

    def test_path_prefix_first_match_wins(self):
        segments = _segments_media_vs_main()
        self.assertEqual(calc.match_site_segment(segments, page_path="/media/knowledge/1/"), "seg_media")
        self.assertEqual(calc.match_site_segment(segments, page_path="/service/"), "seg_main")

    def test_none_returned_when_no_segment_matches_and_no_default(self):
        segments = [
            {"segment_id": "seg_a", "match": {"path_prefix": "/service/"}},
        ]
        self.assertIsNone(calc.match_site_segment(segments, page_path="/other/"))

    def test_empty_segments_always_returns_none(self):
        self.assertIsNone(calc.match_site_segment([], page_path="/anything/"))

    def test_host_name_match_is_case_insensitive(self):
        segments = [
            {"segment_id": "seg_a", "match": {"host_name": "Example.com"}},
        ]
        self.assertEqual(calc.match_site_segment(segments, host_name="example.COM", page_path="/"), "seg_a")

    def test_path_prefix_match_is_case_sensitive(self):
        segments = [{"segment_id": "seg_a", "match": {"path_prefix": "/Service/"}}]
        self.assertIsNone(calc.match_site_segment(segments, page_path="/service/"))

    def test_multiple_keys_in_one_segment_are_and(self):
        # host_nameとpath_prefixを両方指定した場合は両方満たさないと一致しない
        segments = [
            {
                "segment_id": "seg_a",
                "match": {"host_name": "blog.example.com", "path_prefix": "/media/"},
            }
        ]
        self.assertIsNone(
            calc.match_site_segment(segments, host_name="example.com", page_path="/media/x/")
        )
        self.assertEqual(
            calc.match_site_segment(segments, host_name="blog.example.com", page_path="/media/x/"),
            "seg_a",
        )

    def test_list_values_within_one_key_are_or(self):
        segments = [
            {"segment_id": "seg_a", "match": {"path_prefix": ["/media/", "/blog/"]}},
        ]
        self.assertEqual(calc.match_site_segment(segments, page_path="/blog/post-1/"), "seg_a")
        self.assertEqual(calc.match_site_segment(segments, page_path="/media/x/"), "seg_a")
        self.assertIsNone(calc.match_site_segment(segments, page_path="/other/"))

    def test_content_group_exact_match_is_case_sensitive(self):
        segments = [{"segment_id": "seg_a", "match": {"content_group": "Media"}}]
        self.assertEqual(calc.match_site_segment(segments, content_group="Media"), "seg_a")
        self.assertIsNone(calc.match_site_segment(segments, content_group="media"))

    def test_segment_with_empty_match_conditions_never_matches(self):
        # 条件が空のセグメントは「すべてに一致」にしない（安全側）。
        segments = [{"segment_id": "seg_empty", "match": {}}, {"segment_id": "seg_a", "match": {"path_prefix": "/"}}]
        self.assertEqual(calc.match_site_segment(segments, page_path="/anything/"), "seg_a")

    def test_non_dict_segment_entries_are_skipped(self):
        segments = ["not-a-dict", {"segment_id": "seg_a", "match": {"path_prefix": "/"}}]
        self.assertEqual(calc.match_site_segment(segments, page_path="/x/"), "seg_a")

    def test_default_segment_catches_unmatched_pages(self):
        # is_conversion_target廃止後の09仕様: default: true のセグメントは、どの match にも
        # 一致しないページの既定の受け皿になる（「その他」という3つ目のバケツを作らない）。
        segments = _segments_media_vs_main()
        self.assertEqual(calc.match_site_segment(segments, page_path="/about/"), "seg_main")
        self.assertEqual(calc.match_site_segment(segments, page_path="/"), "seg_main")

    def test_default_segment_does_not_shadow_explicit_matches(self):
        # 既定セグメントより、明示的なmatchに一致するセグメントが優先される。
        segments = _segments_media_vs_main()
        self.assertEqual(calc.match_site_segment(segments, page_path="/media/x/"), "seg_media")

    def test_default_segment_ignores_match_field(self):
        # default: true のセグメントはmatchを評価しない（matchを持っていても無視される）。
        segments = [{"segment_id": "seg_default", "default": True, "match": {"path_prefix": "/only-this/"}}]
        self.assertEqual(calc.match_site_segment(segments, page_path="/anything/"), "seg_default")

    def test_default_segment_position_does_not_affect_explicit_match_priority(self):
        # 既定セグメントをリストの先頭に置いても、明示的なmatchの評価順（先勝ち）には影響しない。
        segments = [
            {"segment_id": "seg_main", "default": True},
            {"segment_id": "seg_media", "match": {"path_prefix": "/media/"}},
        ]
        self.assertEqual(calc.match_site_segment(segments, page_path="/media/x/"), "seg_media")
        self.assertEqual(calc.match_site_segment(segments, page_path="/about/"), "seg_main")

    def test_first_default_wins_when_multiple_defaults_defined(self):
        # 複数のdefault:trueは想定外の設定だが（01のvalidate_site_segmentsが警告する）、
        # match_site_segment自体は定義順で最初のものを採用して落ちない。
        segments = [
            {"segment_id": "seg_first", "default": True},
            {"segment_id": "seg_second", "default": True},
        ]
        self.assertEqual(calc.match_site_segment(segments, page_path="/x/"), "seg_first")


class LandingPageAndPagePathDimensionTest(unittest.TestCase):
    def test_default_is_path_only(self):
        self.assertEqual(calc.landing_page_dimension(False), "landingPage")
        self.assertEqual(calc.page_path_dimension(False), "pagePath")

    def test_include_query_params_true_keeps_query_string(self):
        self.assertEqual(calc.landing_page_dimension(True), "landingPagePlusQueryString")
        self.assertEqual(calc.page_path_dimension(True), "pagePathPlusQueryString")


class ParseSiteSegmentsJsonTest(unittest.TestCase):
    def test_empty_or_none_returns_empty_list(self):
        self.assertEqual(calc.parse_site_segments_json(""), [])
        self.assertEqual(calc.parse_site_segments_json(None), [])

    def test_invalid_json_returns_empty_list_without_raising(self):
        self.assertEqual(calc.parse_site_segments_json("{not json"), [])

    def test_non_list_json_returns_empty_list(self):
        self.assertEqual(calc.parse_site_segments_json('{"segment_id": "seg_a"}'), [])

    def test_valid_list_is_parsed_and_non_dict_entries_dropped(self):
        raw = '[{"segment_id": "seg_a"}, "not-a-dict", 123]'
        self.assertEqual(calc.parse_site_segments_json(raw), [{"segment_id": "seg_a"}])


class DetectTrailingSlashDupesTest(unittest.TestCase):
    def test_detects_pair_present_both_ways(self):
        rows = [{"path": "/contact/service"}, {"path": "/contact/service/"}, {"path": "/other/"}]
        self.assertEqual(calc.detect_trailing_slash_dupes(rows, "path"), [("/contact/service", "/contact/service/")])

    def test_no_pair_when_only_one_variant_present(self):
        rows = [{"path": "/contact/service/"}, {"path": "/other/"}]
        self.assertEqual(calc.detect_trailing_slash_dupes(rows, "path"), [])

    def test_root_path_is_not_treated_as_a_pair_with_itself(self):
        rows = [{"path": "/"}]
        self.assertEqual(calc.detect_trailing_slash_dupes(rows, "path"), [])


class ClassifySegmentRowsTest(unittest.TestCase):
    """classify_segment_rows(): セグメントごとのセッション・CV集計（サマリーの内訳表向け）。

    is_conversion_target廃止後は「対象」「対象外」の区分けをしない。どのセグメントを
    CVR分母とみなすかは02側では決めない。
    """

    def test_default_segment_catches_everything_not_explicitly_matched(self):
        segments = _segments_media_vs_main()  # seg_media(/media/) + seg_main(default)
        rows = [
            {"landingPagePlusQueryString": "/media/knowledge/1/", "sessions": 800, "conversions": 0},
            {"landingPagePlusQueryString": "/service/", "sessions": 200, "conversions": 10},
            {"landingPagePlusQueryString": "(not set)", "sessions": 50, "conversions": 0},
        ]
        out = calc.classify_segment_rows(rows, segments, path_key="landingPagePlusQueryString")
        by_id = {s["segment_id"]: s for s in out["segments"]}
        self.assertEqual(by_id["seg_media"]["sessions"], 800)
        self.assertEqual(by_id["seg_media"]["conversions"], 0)
        # /service/ と (not set) はどちらも/media/に一致しないため既定セグメント(seg_main)に落ちる
        self.assertEqual(by_id["seg_main"]["sessions"], 250)
        self.assertEqual(by_id["seg_main"]["conversions"], 10)
        self.assertEqual(out["other"], {"sessions": 0, "conversions": 0, "page_count": 0})
        self.assertEqual(out["total"], {"sessions": 1050, "conversions": 10})

    def test_unclassified_page_is_never_silently_dropped_when_no_default(self):
        # default: true が無いクライアントでは、一致しないページは黙って消えず「その他」に残る。
        segments = [{"segment_id": "seg_a", "match": {"path_prefix": "/service/"}}]
        rows = [{"landingPagePlusQueryString": "/unrelated/", "sessions": 999, "conversions": 5}]
        out = calc.classify_segment_rows(rows, segments, path_key="landingPagePlusQueryString")
        self.assertEqual(out["segments"][0]["sessions"], 0)
        self.assertEqual(out["other"]["sessions"], 999)
        self.assertEqual(out["other"]["page_count"], 1)

    def test_each_segment_gets_its_own_bucket(self):
        segments = [
            {"segment_id": "seg_main", "match": {"path_prefix": "/service/"}},
            {"segment_id": "seg_recruit", "match": {"path_prefix": "/recruit/"}},
            {"segment_id": "seg_media", "name": "オウンドメディア", "match": {"path_prefix": "/media/"}},
        ]
        rows = [
            {"landingPagePlusQueryString": "/service/", "sessions": 100, "conversions": 5},
            {"landingPagePlusQueryString": "/recruit/", "sessions": 40, "conversions": 2},
            {"landingPagePlusQueryString": "/media/x/", "sessions": 300, "conversions": 0},
        ]
        out = calc.classify_segment_rows(rows, segments, path_key="landingPagePlusQueryString")
        by_id = {s["segment_id"]: s for s in out["segments"]}
        self.assertEqual(by_id["seg_main"]["sessions"], 100)
        self.assertEqual(by_id["seg_recruit"]["sessions"], 40)
        self.assertEqual(by_id["seg_media"]["sessions"], 300)
        self.assertEqual(by_id["seg_media"]["name"], "オウンドメディア")

    def test_segment_with_no_matching_rows_still_appears_with_zero(self):
        # 合計の照合をしやすくするため、一致行が無いセグメントも0件のまま表に残す。
        segments = [
            {"segment_id": "seg_a", "match": {"path_prefix": "/a/"}},
            {"segment_id": "seg_b", "match": {"path_prefix": "/b/"}},
        ]
        rows = [{"landingPagePlusQueryString": "/a/", "sessions": 10, "conversions": 1}]
        out = calc.classify_segment_rows(rows, segments, path_key="landingPagePlusQueryString")
        by_id = {s["segment_id"]: s for s in out["segments"]}
        self.assertEqual(by_id["seg_b"]["sessions"], 0.0)
        self.assertEqual(by_id["seg_b"]["conversions"], 0.0)

    def test_host_name_key_used_when_provided(self):
        segments = [{"segment_id": "seg_a", "match": {"host_name": "example.com"}}]
        rows = [
            {"host": "example.com", "landingPagePlusQueryString": "/", "sessions": 10, "conversions": 1},
            {"host": "blog.example.com", "landingPagePlusQueryString": "/", "sessions": 20, "conversions": 0},
        ]
        out = calc.classify_segment_rows(
            rows, segments, path_key="landingPagePlusQueryString", host_key="host",
        )
        self.assertEqual(out["segments"][0]["sessions"], 10)
        self.assertEqual(out["other"]["sessions"], 20)

    def test_segments_plus_other_equal_total(self):
        # 実データで「独立した3つの切り口の合計が全体を29,361件上回っていた」事故の再発防止。
        segments = [{"segment_id": "seg_a", "match": {"path_prefix": "/service/"}}]
        rows = [
            {"landingPagePlusQueryString": "/service/", "sessions": 200, "conversions": 10},
            {"landingPagePlusQueryString": "/unrelated/", "sessions": 50, "conversions": 0},
        ]
        out = calc.classify_segment_rows(rows, segments, path_key="landingPagePlusQueryString")
        recombined = sum(s["sessions"] for s in out["segments"]) + out["other"]["sessions"]
        self.assertEqual(recombined, out["total"]["sessions"])

    def test_conversions_default_to_zero_when_missing_from_row(self):
        # sessions_key/conversions_key に対応するキーが行に無くても例外を出さず0扱いにする。
        segments = [{"segment_id": "seg_a", "match": {"path_prefix": "/service/"}}]
        rows = [{"landingPagePlusQueryString": "/service/", "sessions": 10}]
        out = calc.classify_segment_rows(rows, segments, path_key="landingPagePlusQueryString")
        self.assertEqual(out["segments"][0]["conversions"], 0)
        self.assertEqual(out["total"], {"sessions": 10, "conversions": 0})


class SegmentBreakdownTableLinesTest(unittest.TestCase):
    def test_includes_named_segments_other_row_and_total(self):
        classification = {
            "segments": [
                {"segment_id": "seg_media", "name": "オウンドメディア", "sessions": 800, "conversions": 0},
                {"segment_id": "seg_main", "name": "本体サイト", "sessions": 200, "conversions": 10},
            ],
            "other": {"sessions": 50, "conversions": 2, "page_count": 3},
            "total": {"sessions": 1050, "conversions": 12},
        }
        lines = calc.segment_breakdown_table_lines(classification)
        text = "\n".join(lines)
        self.assertIn("オウンドメディア", text)
        self.assertIn("800", text)
        self.assertIn("その他（分類外、3ページ）", text)
        self.assertIn("50", text)
        self.assertIn("| 合計 | 1,050 |", text)

    def test_other_row_absent_when_no_unclassified_rows(self):
        # default: true のセグメントがあるクライアントでは、その他が0件になり節自体が出ない
        # （節は残すが、該当が無ければ出さない設計）。
        classification = {
            "segments": [{"segment_id": "seg_main", "name": "本体サイト", "sessions": 100, "conversions": 5}],
            "other": {"sessions": 0, "conversions": 0, "page_count": 0},
            "total": {"sessions": 100, "conversions": 5},
        }
        text = "\n".join(calc.segment_breakdown_table_lines(classification))
        self.assertNotIn("その他", text)

    def test_other_row_present_when_page_count_positive_even_if_sessions_zero(self):
        classification = {
            "segments": [],
            "other": {"sessions": 0, "conversions": 0, "page_count": 3},
            "total": {"sessions": 0, "conversions": 0},
        }
        text = "\n".join(calc.segment_breakdown_table_lines(classification))
        self.assertIn("その他（分類外、3ページ）", text)

    def test_zero_sessions_are_rendered(self):
        classification = {
            "segments": [{"segment_id": "seg_a", "name": "セグメントA", "sessions": 0, "conversions": 0}],
            "other": {"sessions": 0, "conversions": 0, "page_count": 0},
            "total": {"sessions": 0, "conversions": 0},
        }
        text = "\n".join(calc.segment_breakdown_table_lines(classification))
        self.assertIn("| セグメントA | 0 |", text)
        self.assertIn("| 合計 | 0 |", text)


class MatchSiteSegmentParityWithSchemaTest(unittest.TestCase):
    """analysis_calc.match_site_segment() は01の context_store.schema.match_site_segment()
    の完全な複製（02は01に依存しない設計のため、判定ロジックをここに複製している）。
    片方だけ直すと2つが違う結果を返す事故になるため、同じ入力に同じ結果を返すことを
    ここで固定する。09を直したときはこのテストが通ることを確認してから複製側も直すこと。
    依存を増やす設計は採らないため、01のパッケージはこのテストからのみ読み込む。
    """

    CASES: list[tuple[list, dict]] = [
        (_segments_media_vs_main(), {"page_path": "/media/knowledge/1/"}),
        (_segments_media_vs_main(), {"page_path": "/service/"}),
        (_segments_media_vs_main(), {"page_path": "/"}),
        (_segments_media_vs_main(), {"page_path": "/about/"}),
        ([], {"page_path": "/anything/"}),
        (
            [{"segment_id": "seg_a", "match": {"host_name": "Example.com"}}],
            {"host_name": "example.COM", "page_path": "/"},
        ),
        (
            [{"segment_id": "seg_a", "match": {"path_prefix": ["/media/", "/blog/"]}}],
            {"page_path": "/blog/post-1/"},
        ),
        (
            [{"segment_id": "seg_a", "match": {"content_group": "Media"}}],
            {"content_group": "media"},
        ),
        (
            [
                {"segment_id": "seg_empty", "match": {}},
                {"segment_id": "seg_a", "match": {"path_prefix": "/"}},
            ],
            {"page_path": "/anything/"},
        ),
        (
            [
                {"segment_id": "seg_first", "default": True},
                {"segment_id": "seg_second", "default": True},
            ],
            {"page_path": "/x/"},
        ),
        (
            [{"segment_id": "seg_default", "default": True, "match": {"path_prefix": "/only-this/"}}],
            {"page_path": "/anything/"},
        ),
    ]

    def test_same_input_returns_same_result_as_01_schema(self):
        for segments, kwargs in self.CASES:
            with self.subTest(segments=segments, kwargs=kwargs):
                self.assertEqual(
                    calc.match_site_segment(segments, **kwargs),
                    ctx_schema.match_site_segment(segments, **kwargs),
                )

    def test_default_position_does_not_affect_result_parity(self):
        # 既定セグメントをリスト先頭に置いた場合も、02と09で結果が一致することを確認する
        # （defaultの位置に関わらず明示matchが優先される、という仕様の複製漏れを検出する）。
        segments = [
            {"segment_id": "seg_main", "default": True},
            {"segment_id": "seg_media", "match": {"path_prefix": "/media/"}},
        ]
        for page_path in ("/media/x/", "/about/"):
            with self.subTest(page_path=page_path):
                self.assertEqual(
                    calc.match_site_segment(segments, page_path=page_path),
                    ctx_schema.match_site_segment(segments, page_path=page_path),
                )


if __name__ == "__main__":
    unittest.main()
