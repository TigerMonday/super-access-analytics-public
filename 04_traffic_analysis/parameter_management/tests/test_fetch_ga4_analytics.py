"""fetch_ga4_analytics.py（基本分析データ取得）のうち、GA4 API呼び出しを含まない
純粋な組み立てロジックの単体テスト。

対象:
- _build_funnel_filters: CVファネル1本分のフィルタ組み立て（分子が対応するキーイベント
  だけを数えることの検証。実データで見つかった「分母に無関係なフォームが混入し、
  分子から対応しないCVが漏れる」不具合の再発防止）
- _parse_funnel_events: --funnel-events のパース
- funnel_markdown_lines: CVファネル（7）のMarkdown組み立て（GA4 API呼び出しなし。
  fetch_cv_funnels() の戻り値と同じ形の辞書を手作りして検証する）
"""

from __future__ import annotations

import io
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import date
from pathlib import Path
from unittest.mock import patch

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from google.analytics.data_v1beta.types import (  # noqa: E402
    DimensionValue,
    Filter,
    MetricValue,
    Row,
    RunReportResponse,
)

import fetch_ga4_analytics as ga  # noqa: E402


def test_zero_count_key_events_treats_missing_rows_as_zero():
    rows = [{"eventName": "form_submit", "conversions": 4}]
    assert ga.zero_count_key_events(["form_submit", "download"], rows) == ["download"]


def test_channel_period_breakdown_fetches_previous_for_ecommerce_path():
    """ECでも使う共通取得は当期・前期を必ずセットで返す。"""
    current = ga.Period(date(2026, 1, 1), date(2026, 1, 31))
    previous = ga.Period(date(2025, 1, 1), date(2025, 1, 31))
    current_rows = [{"sessionDefaultChannelGroup": "Organic Search", "conversions": 4}]
    previous_rows = [{"sessionDefaultChannelGroup": "Organic Search", "conversions": 3}]

    with patch.object(
        ga, "fetch_conversions_by_event", side_effect=[current_rows, previous_rows],
    ) as fetch:
        result = ga.fetch_channel_period_breakdown(
            object(), "123456", current, previous, ["purchase"],
        )

    assert result == {
        "channel_rows": current_rows,
        "channel_previous_rows": previous_rows,
    }
    assert fetch.call_args_list[0].args[2] == current
    assert fetch.call_args_list[1].args[2] == previous


def _eventname_values(expr):
    """FilterExpression から eventName の in_list_filter の値を取り出す（and_group内も探す）。"""
    if expr is None:
        return None
    if expr.filter.field_name == "eventName":
        return list(expr.filter.in_list_filter.values)
    if expr.and_group.expressions:
        for e in expr.and_group.expressions:
            found = _eventname_values(e)
            if found is not None:
                return found
    return None


def _page_filter_part(expr):
    """FilterExpression から pagePathPlusQueryString の filter 部分を取り出す（and_group内も探す）。"""
    if expr is None:
        return None
    if expr.filter.field_name == "pagePathPlusQueryString":
        return expr.filter
    if expr.and_group.expressions:
        for e in expr.and_group.expressions:
            found = _page_filter_part(e)
            if found is not None:
                return found
    return None


class BuildFunnelFiltersTest(unittest.TestCase):
    """CVごとに1本のファネルを作る設計の核心: 分子(cv_filter)は常にそのキーイベント1件のみ。"""

    def test_cv_filter_targets_only_this_event_not_all_key_events(self):
        # 実データの再現: contact_service_thanks 用のファネルで、CV件数を数えるフィルタに
        # 他のキーイベント（例: download_thanks）が混ざっていないことを確認する。
        _, cv_filter = ga._build_funnel_filters(
            "contact_service_thanks", "/contact/service/", "contains"
        )
        self.assertEqual(_eventname_values(cv_filter), ["contact_service_thanks"])

    def test_page_filter_uses_contains_by_default(self):
        page_filter, _ = ga._build_funnel_filters("ev", "/contact/service/", "contains")
        part = _page_filter_part(page_filter)
        self.assertEqual(part.string_filter.value, "/contact/service/")
        self.assertEqual(part.string_filter.match_type, Filter.StringFilter.MatchType.CONTAINS)

    def test_page_filter_uses_exact_when_specified(self):
        page_filter, _ = ga._build_funnel_filters("ev", "/contact/service/", "exact")
        part = _page_filter_part(page_filter)
        self.assertEqual(part.string_filter.match_type, Filter.StringFilter.MatchType.EXACT)

    def test_no_page_means_no_page_filter_but_cv_filter_still_scoped_to_event(self):
        page_filter, cv_filter = ga._build_funnel_filters("ev_no_page", None, "contains")
        self.assertIsNone(page_filter)
        self.assertEqual(_eventname_values(cv_filter), ["ev_no_page"])

    def test_cv_filter_includes_page_condition_when_page_given(self):
        _, cv_filter = ga._build_funnel_filters("ev", "/download/", "contains")
        part = _page_filter_part(cv_filter)
        self.assertIsNotNone(part, "CV達成のフィルタに中間ページ条件が含まれていない")
        self.assertEqual(part.string_filter.value, "/download/")


class FetchCvFunnelsTest(unittest.TestCase):
    def test_missing_form_page_does_not_guess_or_query(self):
        """フォームページ未確認なら通過率を捏造せず、追加問い合わせもしない。"""
        with patch.object(ga, "_run_report") as run_report:
            out = ga.fetch_cv_funnels(
                object(), "properties/123", ga.Period(date(2025, 1, 1), date(2025, 12, 31)),
                ["form_submit"], {"form_submit": {"page": None}},
                completion_event_counts={"form_submit": 42},
            )

        self.assertEqual(run_report.call_count, 0)
        self.assertEqual(out["funnels"][0]["cv_count"], 42)
        self.assertIsNone(out["funnels"][0]["form_page_views"])
        self.assertIsNone(out["funnels"][0]["completion_rate"])

    def test_form_page_uses_page_views_as_denominator(self):
        response = RunReportResponse(rows=[Row(metric_values=[MetricValue(value="200")])])
        with patch.object(ga, "_run_report", return_value=response):
            out = ga.fetch_cv_funnels(
                object(), "properties/123", ga.Period(date(2025, 1, 1), date(2025, 12, 31)),
                ["form_submit"], {"form_submit": {"page": "/contact/"}},
                completion_event_counts={"form_submit": 40},
            )
        self.assertEqual(out["funnels"][0]["form_page_views"], 200)
        self.assertEqual(out["funnels"][0]["completion_events"], 40)
        self.assertEqual(out["funnels"][0]["completion_rate"], 20.0)


class ParseFunnelEventsTest(unittest.TestCase):
    def test_empty_spec_returns_empty_dict(self):
        self.assertEqual(ga._parse_funnel_events(""), {})

    def test_full_spec_single_entry(self):
        out = ga._parse_funnel_events("contact_service_thanks:/contact/service/:contains:confirmed")
        self.assertEqual(
            out["contact_service_thanks"],
            {"page": "/contact/service/", "match_type": "contains", "confirmed": True},
        )

    def test_multiple_entries_separated_by_semicolon(self):
        out = ga._parse_funnel_events(
            "a:/a/:contains:confirmed;b:/b/:exact:unconfirmed"
        )
        self.assertEqual(set(out.keys()), {"a", "b"})
        self.assertEqual(out["b"]["match_type"], "exact")
        self.assertFalse(out["b"]["confirmed"])

    def test_event_only_no_page_defaults_to_none_page(self):
        out = ga._parse_funnel_events("newsletter_signup")
        self.assertEqual(out["newsletter_signup"]["page"], None)
        self.assertEqual(out["newsletter_signup"]["match_type"], "contains")
        self.assertTrue(out["newsletter_signup"]["confirmed"])

    def test_event_with_empty_page_field(self):
        out = ga._parse_funnel_events("newsletter_signup::: unconfirmed")
        self.assertIsNone(out["newsletter_signup"]["page"])
        self.assertFalse(out["newsletter_signup"]["confirmed"])

    def test_rejects_invalid_match_type(self):
        with self.assertRaises(ValueError):
            ga._parse_funnel_events("ev:/p/:startswith:confirmed")

    def test_rejects_invalid_status(self):
        with self.assertRaises(ValueError):
            ga._parse_funnel_events("ev:/p/:contains:maybe")


class FunnelMarkdownLinesTest(unittest.TestCase):
    """フォーム通過率（7）のMarkdown組み立て。"""

    def test_no_funnels_shows_omission_note(self):
        lines = ga.funnel_markdown_lines({"funnels": [], "excluded": []})
        text = "\n".join(lines)
        self.assertIn("## 7. フォーム通過率", text)
        self.assertIn("フォームページが未確認", text)

    def test_single_confirmed_funnel_with_intermediate_page(self):
        funnel_data = {
            "funnels": [
                {
                    "key_event": "contact_service_thanks",
                    "cv_count": 546,
                    "confirmed": True,
                    "match_type": "contains",
                    "has_intermediate": True,
                    "page": "/contact/service/",
                    "form_page_views": 1079,
                    "completion_events": 546,
                    "completion_rate": 50.60,
                    "steps": [
                        {"label": "全体（セッション）", "sessions": 339198},
                        {"label": "中間ページ到達: /contact/service/", "sessions": 1079},
                        {"label": "CV達成", "sessions": 546},
                    ],
                }
            ],
            "excluded": [],
        }
        text = "\n".join(ga.funnel_markdown_lines(funnel_data))
        self.assertIn("### contact_service_thanks", text)
        self.assertNotIn("未確認", text)
        self.assertIn("部分一致", text)
        self.assertIn("/contact/service/", text)
        self.assertIn("1,079", text)
        self.assertIn("546", text)

    def test_unconfirmed_funnel_marked_in_title(self):
        funnel_data = {
            "funnels": [
                {
                    "key_event": "download_thanks",
                    "cv_count": 177,
                    "confirmed": False,
                    "match_type": "contains",
                    "has_intermediate": True,
                    "page": "/download/",
                    "form_page_views": 578,
                    "completion_events": 177,
                    "completion_rate": 30.62,
                    "steps": [
                        {"label": "全体（セッション）", "sessions": 339198},
                        {"label": "中間ページ到達: /download/", "sessions": 578},
                        {"label": "CV達成", "sessions": 177},
                    ],
                }
            ],
            "excluded": [],
        }
        text = "\n".join(ga.funnel_markdown_lines(funnel_data))
        self.assertIn("### download_thanks（フォームページ未確認）", text)

    def test_funnel_without_intermediate_page_renders_two_step_note(self):
        funnel_data = {
            "funnels": [
                {
                    "key_event": "newsletter_signup",
                    "cv_count": 40,
                    "confirmed": True,
                    "match_type": "contains",
                    "has_intermediate": False,
                    "page": None,
                    "steps": [
                        {"label": "全体（セッション）", "sessions": 339198},
                        {"label": "CV達成", "sessions": 40},
                    ],
                }
            ],
            "excluded": [],
        }
        text = "\n".join(ga.funnel_markdown_lines(funnel_data))
        self.assertIn("フォームページが未確認", text)
        self.assertIn("通過率は算出していない", text)

    def test_exact_match_type_footnote(self):
        funnel_data = {
            "funnels": [
                {
                    "key_event": "ev",
                    "cv_count": 10,
                    "confirmed": True,
                    "match_type": "exact",
                    "has_intermediate": True,
                    "page": "/contact/service/",
                    "form_page_views": 100,
                    "completion_events": 10,
                    "completion_rate": 10.0,
                    "steps": [
                        {"label": "全体（セッション）", "sessions": 1000},
                        {"label": "中間ページ到達: /contact/service/", "sessions": 100},
                        {"label": "CV達成", "sessions": 10},
                    ],
                }
            ],
            "excluded": [],
        }
        text = "\n".join(ga.funnel_markdown_lines(funnel_data))
        self.assertIn("完全一致", text)

    def test_excluded_events_listed_with_counts(self):
        funnel_data = {
            "funnels": [
                {
                    "key_event": "top_event",
                    "cv_count": 600,
                    "confirmed": True,
                    "match_type": "contains",
                    "has_intermediate": False,
                    "page": None,
                    "steps": [
                        {"label": "全体（セッション）", "sessions": 1000},
                        {"label": "CV達成", "sessions": 600},
                    ],
                }
            ],
            "excluded": [("minor_event", 3)],
        }
        text = "\n".join(ga.funnel_markdown_lines(funnel_data))
        self.assertIn("minor_event", text)
        self.assertIn("3件", text)
        self.assertIn("対象外", text)

    def test_event_names_replaces_title_with_kpi_name(self):
        # 01の kpis.yaml に業務名が登録されているイベントは「KPI名（event名）」の見出しになる。
        # イベント名自体は消えず併記される（計測の技術名として必要なため）
        funnel_data = {
            "funnels": [
                {
                    "key_event": "contact_service_thanks",
                    "cv_count": 546,
                    "confirmed": True,
                    "match_type": "contains",
                    "has_intermediate": True,
                    "page": "/contact/service/",
                    "form_page_views": 1079,
                    "completion_events": 546,
                    "completion_rate": 50.60,
                    "steps": [
                        {"label": "全体（セッション）", "sessions": 339198},
                        {"label": "中間ページ到達: /contact/service/", "sessions": 1079},
                        {"label": "CV達成", "sessions": 546},
                    ],
                }
            ],
            "excluded": [],
        }
        text = "\n".join(
            ga.funnel_markdown_lines(funnel_data, {"contact_service_thanks": "サービス相談数"})
        )
        self.assertIn("### サービス相談数（contact_service_thanks）", text)

    def test_event_names_missing_entry_falls_back_to_event_name(self):
        # 01に登録が無いイベントが分析対象に含まれても、そのイベントだけイベント名のまま表示される
        funnel_data = {
            "funnels": [
                {
                    "key_event": "untracked_event",
                    "cv_count": 12,
                    "confirmed": True,
                    "match_type": "contains",
                    "has_intermediate": False,
                    "page": None,
                    "steps": [
                        {"label": "全体（セッション）", "sessions": 1000},
                        {"label": "CV達成", "sessions": 12},
                    ],
                }
            ],
            "excluded": [],
        }
        text = "\n".join(
            ga.funnel_markdown_lines(funnel_data, {"form_submit": "お問い合わせ完了数"})
        )
        self.assertIn("### untracked_event", text)

    def test_excluded_events_use_kpi_name_when_registered(self):
        funnel_data = {
            "funnels": [
                {
                    "key_event": "top_event",
                    "cv_count": 600,
                    "confirmed": True,
                    "match_type": "contains",
                    "has_intermediate": False,
                    "page": None,
                    "steps": [
                        {"label": "全体（セッション）", "sessions": 1000},
                        {"label": "CV達成", "sessions": 600},
                    ],
                }
            ],
            "excluded": [("minor_event", 3)],
        }
        text = "\n".join(
            ga.funnel_markdown_lines(funnel_data, {"minor_event": "資料ダウンロード数"})
        )
        self.assertIn("資料ダウンロード数（minor_event）（3件）", text)


class HostnameMarkdownLinesTest(unittest.TestCase):
    """課題2: ホスト名別（絞り込み条件付きの取得）の内訳合計と全体セッションの差が
    出力から読み取れることの検証（GA4 API呼び出し無し）。"""

    def test_no_note_when_totals_match(self):
        rows = [{"hostName": "example.com", "sessions": 100, "conversions": 5}]
        text = "\n".join(ga.hostname_markdown_lines(rows, overall_sessions=100))
        self.assertNotIn("※", text)
        self.assertIn("example.com", text)
        self.assertIn("100", text)

    def test_excess_diff_is_shown_when_subtotal_exceeds_overall(self):
        # 07の実測例（ホスト名別+6,645件）を単純化して再現
        rows = [{"hostName": "example.com", "sessions": 700, "conversions": 5}]
        text = "\n".join(ga.hostname_markdown_lines(rows, overall_sessions=100))
        self.assertIn("※", text)
        self.assertIn("上回っている", text)
        self.assertIn("600", text)

    def test_shortfall_diff_is_shown_when_subtotal_falls_short(self):
        rows = [{"hostName": "example.com", "sessions": 40, "conversions": 5}]
        text = "\n".join(ga.hostname_markdown_lines(rows, overall_sessions=100))
        self.assertIn("※", text)
        self.assertIn("届いていない", text)
        self.assertIn("60", text)


def _minimal_markdown_fixtures():
    """to_markdown() の必須引数一式（1KPI/2KPI共通で使い回せる最小構成）を組み立てる。"""
    period = ga.Period(start=date(2025, 8, 26), end=date(2026, 8, 25))
    prev_period = ga.Period(start=date(2024, 8, 26), end=date(2025, 8, 25))
    summary = {
        "current": {
            "sessions": 1000, "totalUsers": 800, "newUsers": 500,
            "conversions": 100,
        },
        "previous": {
            "sessions": 900, "totalUsers": 700, "newUsers": 400,
            "conversions": 80,
        },
    }
    timeseries = {"monthly": [
        {"yearMonth": "202508", "sessions": 1000, "totalUsers": 800, "conversions": 100}
    ]}
    channel = [{
        "sessionDefaultChannelGroup": "Organic Search", "sessions": 1000,
        "conversions": 100, "totalUsers": 800, "prev_sessions": 900,
    }]
    landing_pages = [{"landingPagePlusQueryString": "/", "sessions": 1000, "conversions": 100}]
    pages = [{"pagePathPlusQueryString": "/", "screenPageViews": 1000}]
    device = [{"deviceCategory": "desktop", "sessions": 1000, "conversions": 100, "totalUsers": 800}]
    new_vs_returning = [{"newVsReturning": "new", "sessions": 1000, "conversions": 100}]
    funnel_data = {"funnels": [], "excluded": []}
    source_medium = [{"sessionSource": "google", "sessionMedium": "organic", "sessions": 1000, "conversions": 100}]
    return dict(
        summary=summary, timeseries=timeseries, channel=channel, landing_pages=landing_pages,
        pages=pages, device=device, new_vs_returning=new_vs_returning, funnel_data=funnel_data,
        source_medium=source_medium, period=period, prev_period=prev_period,
        lp_display_limit=10, page_display_limit=10, weekly_display_weeks=12,
    )


class ToMarkdownKpiSplitTest(unittest.TestCase):
    """複数CVの内訳表示（実データの不具合修正: 合算のCV列だけでは打ち手が決まらない）。"""

    def test_single_key_event_without_breakdown_is_not_misreported(self):
        fx = _minimal_markdown_fixtures()
        md = ga.to_markdown(**fx, key_events=["form_submit"], primary_kpi_name="無視される名前")
        self.assertIn("CVイベント未指定", md)
        self.assertNotIn("★", md)
        self.assertNotIn("優先度は未設定", md)

    def test_multi_kpi_without_breakdown_data_falls_back_defensively(self):
        # 01登録はあるがpriority未設定、かつ呼び出し側がkpi_breakdownを渡さない場合でも
        # 例外を出さず、従来どおりの合算表示にフォールバックする（レポートを止めない）。
        fx = _minimal_markdown_fixtures()
        md = ga.to_markdown(**fx, key_events=["form_submit", "file_download"])
        self.assertIn("優先度は未設定", md)
        self.assertIn("CVイベント未指定", md)

    def test_priority_unset_shows_all_kpis_without_star_or_reorder(self):
        fx = _minimal_markdown_fixtures()
        kpi_breakdown = {
            "summary_rows": {
                "current": [{"eventName": "contact_service_thanks", "conversions": 30, "convertedSessions": 25}, {"eventName": "download_thanks", "conversions": 70, "convertedSessions": 60}],
                "previous": [{"eventName": "contact_service_thanks", "conversions": 20, "convertedSessions": 18}, {"eventName": "download_thanks", "conversions": 60, "convertedSessions": 50}],
            },
        }
        md = ga.to_markdown(
            **fx, key_events=["contact_service_thanks", "download_thanks"],
            event_names={"contact_service_thanks": "サービス相談数", "download_thanks": "資料ダウンロード数"},
            kpi_breakdown=kpi_breakdown,
        )
        self.assertIn("※ 複数のCV（キーイベント）があるが、優先度は未設定", md)
        self.assertNotIn("★", md)
        self.assertIn("| CV数: サービス相談数 | 30 | 20 | +50.0% |", md)
        self.assertIn("| CV数: 資料ダウンロード数 | 70 | 60 | +16.7% |", md)
        self.assertNotIn("CV（キーイベント合計）", md)

    def test_priority_set_promotes_primary_kpi_first_with_star(self):
        fx = _minimal_markdown_fixtures()
        kpi_breakdown = {
            "summary_rows": {
                "current": [{"eventName": "contact_service_thanks", "conversions": 30, "convertedSessions": 25}, {"eventName": "download_thanks", "conversions": 70, "convertedSessions": 60}],
                "previous": [{"eventName": "contact_service_thanks", "conversions": 20, "convertedSessions": 18}, {"eventName": "download_thanks", "conversions": 60, "convertedSessions": 50}],
            },
        }
        md = ga.to_markdown(
            **fx, key_events=["download_thanks", "contact_service_thanks"],
            event_names={"contact_service_thanks": "サービス相談数", "download_thanks": "資料ダウンロード数"},
            primary_kpi_name="サービス相談数",
            kpi_breakdown=kpi_breakdown,
        )
        self.assertIn("優先KPI: ★サービス相談数", md)
        summary_section = md.split("## 0.")[1].split("## 1.")[0]
        self.assertLess(
            summary_section.index("★サービス相談数"), summary_section.index("資料ダウンロード数")
        )

    def test_property_conversion_total_is_not_mixed_with_selected_event_total(self):
        # プロパティ全体のconversionsと、ユーザー確認済みイベントのeventCountは別基準。
        fx = _minimal_markdown_fixtures()
        fx["summary"]["current"]["conversions"] = 150  # 内訳合計100とは別に、集計自体は150件
        kpi_breakdown = {
            "summary_rows": {
                "current": [{"eventName": "contact_service_thanks", "conversions": 30, "convertedSessions": 25}, {"eventName": "download_thanks", "conversions": 70, "convertedSessions": 60}],
                "previous": [{"eventName": "contact_service_thanks", "conversions": 20, "convertedSessions": 18}, {"eventName": "download_thanks", "conversions": 60, "convertedSessions": 50}],
            },
        }
        md = ga.to_markdown(
            **fx, key_events=["contact_service_thanks", "download_thanks"],
            event_names={"contact_service_thanks": "サービス相談数", "download_thanks": "資料ダウンロード数"},
            kpi_breakdown=kpi_breakdown,
        )
        self.assertNotIn("CVの内訳合計", md)
        self.assertIn("CV数は確認済みのCVイベント発生回数", md)

    def test_reconciliation_note_absent_when_sums_match(self):
        # 実データ（my-site）: contact_service_thanks(546) + download_thanks(178) = 724 が
        # プロパティ全体のconversions集計(724)と一致するケース。注記が出ないことを確認する。
        fx = _minimal_markdown_fixtures()
        fx["summary"]["current"]["conversions"] = 100
        kpi_breakdown = {
            "summary_rows": {
                "current": [{"eventName": "contact_service_thanks", "conversions": 30, "convertedSessions": 25}, {"eventName": "download_thanks", "conversions": 70, "convertedSessions": 60}],
                "previous": [{"eventName": "contact_service_thanks", "conversions": 20, "convertedSessions": 18}, {"eventName": "download_thanks", "conversions": 60, "convertedSessions": 50}],
            },
        }
        md = ga.to_markdown(
            **fx, key_events=["contact_service_thanks", "download_thanks"],
            event_names={"contact_service_thanks": "サービス相談数", "download_thanks": "資料ダウンロード数"},
            kpi_breakdown=kpi_breakdown,
        )
        self.assertNotIn("CVの内訳合計", md)

    def test_channel_section_splits_cv_columns_per_kpi(self):
        fx = _minimal_markdown_fixtures()
        kpi_breakdown = {
            "channel_rows": [
                {"sessionDefaultChannelGroup": "Organic Search", "eventName": "contact_service_thanks", "conversions": 30, "convertedSessions": 25},
                {"sessionDefaultChannelGroup": "Organic Search", "eventName": "download_thanks", "conversions": 70, "convertedSessions": 60},
            ],
            "channel_previous_rows": [
                {"sessionDefaultChannelGroup": "Organic Search", "eventName": "contact_service_thanks", "conversions": 20, "convertedSessions": 18},
                {"sessionDefaultChannelGroup": "Organic Search", "eventName": "download_thanks", "conversions": 60, "convertedSessions": 50},
            ],
        }
        md = ga.to_markdown(
            **fx, key_events=["contact_service_thanks", "download_thanks"],
            event_names={"contact_service_thanks": "サービス相談数", "download_thanks": "資料ダウンロード数"},
            kpi_breakdown=kpi_breakdown,
        )
        self.assertIn("当期 CV数: サービス相談数 | 当期 CVR: サービス相談数", md)
        self.assertIn("前年同期 CV数: サービス相談数 | 前年同期 CVR: サービス相談数", md)
        self.assertIn(
            "| Organic Search | 1,000 | 900 | 100.0% | +11.1% | "
            "30 | 3.00% | 70 | 7.00% | 20 | 2.22% | 60 | 6.67% |",
            md,
        )


class ToMarkdownCvrIsPairedWithCvTest(unittest.TestCase):
    """セッション・CV・CVRはセットで出す（0. 全体サマリ数値・1. 月次推移はCVR列/行が
    抜けていた不具合の修正）。他の表（2〜6）は既にCV・CVRを並べており、この2箇所だけ
    揃っていなかった。"""

    def test_summary_headers_include_actual_period_ranges(self):
        md = ga.to_markdown(**_minimal_markdown_fixtures(), key_events=[])

        self.assertIn(
            "| 指標 | 当期（2025/8/26〜2026/8/25） | "
            "前年同期（2024/8/26〜2025/8/25） | 増減 |",
            md,
        )

    def test_complete_month_period_is_compact(self):
        period = ga.Period(start=date(2025, 9, 1), end=date(2026, 8, 31))
        self.assertEqual(ga._format_report_period(period), "2025/9〜2026/8")

    def test_client_report_contains_monthly_section_only(self):
        fx = _minimal_markdown_fixtures()
        fx["timeseries"]["weekly"] = [
            {"yearWeek": "202633", "sessions": 100, "totalUsers": 80, "conversions": 10},
        ]
        md = ga.to_markdown(**fx, key_events=[])

        self.assertIn("## 1. 月次推移", md)
        self.assertNotIn("月次/週次", md)
        self.assertNotIn("### 週次", md)

    def test_summary_single_kpi_row_has_cvr_next_to_cv(self):
        fx = _minimal_markdown_fixtures()
        breakdown = {"summary_rows": {
            "current": [{"eventName": "form_submit", "conversions": 100, "convertedSessions": 90}],
            "previous": [{"eventName": "form_submit", "conversions": 80, "convertedSessions": 70}],
        }}
        md = ga.to_markdown(**fx, key_events=["form_submit"], kpi_breakdown=breakdown)
        summary_section = md.split("## 0.")[1].split("## 1.")[0]
        self.assertIn("| CVR: form_submit | 10.00% | 8.89% | +1.1pt |", summary_section)

    def test_summary_multi_kpi_has_cvr_row_per_kpi(self):
        fx = _minimal_markdown_fixtures()
        kpi_breakdown = {
            "summary_rows": {
                "current": [{"eventName": "contact_service_thanks", "conversions": 30, "convertedSessions": 25}, {"eventName": "download_thanks", "conversions": 70, "convertedSessions": 60}],
                "previous": [{"eventName": "contact_service_thanks", "conversions": 20, "convertedSessions": 18}, {"eventName": "download_thanks", "conversions": 60, "convertedSessions": 50}],
            },
        }
        md = ga.to_markdown(
            **fx, key_events=["contact_service_thanks", "download_thanks"],
            event_names={"contact_service_thanks": "サービス相談数", "download_thanks": "資料ダウンロード数"},
            kpi_breakdown=kpi_breakdown,
        )
        summary_section = md.split("## 0.")[1].split("## 1.")[0]
        self.assertIn("| CV数: サービス相談数 | 30 | 20 | +50.0% |", summary_section)
        self.assertIn("| CVR: サービス相談数 | 3.00% | 2.22% | +0.8pt |", summary_section)
        self.assertIn("| CV数: 資料ダウンロード数 | 70 | 60 | +16.7% |", summary_section)
        self.assertIn("| CVR: 資料ダウンロード数 | 7.00% | 6.67% | +0.3pt |", summary_section)

    def test_timeseries_single_kpi_table_has_cvr_column(self):
        fx = _minimal_markdown_fixtures()
        breakdown = {"timeseries": {"monthly": [
            {"yearMonth": "202508", "eventName": "form_submit", "conversions": 100, "convertedSessions": 90}
        ]}}
        md = ga.to_markdown(**fx, key_events=["form_submit"], kpi_breakdown=breakdown)
        self.assertIn("| 月 | セッション | ユーザー | CV数: form_submit | CVR: form_submit |", md)
        self.assertIn("| 100 | 10.00% |", md)

    def test_timeseries_multi_kpi_table_has_cv_cvr_pairs(self):
        fx = _minimal_markdown_fixtures()
        kpi_breakdown = {
            "timeseries": {
                "monthly": [
                    {"yearMonth": "202508", "eventName": "contact_service_thanks", "conversions": 30, "convertedSessions": 25},
                    {"yearMonth": "202508", "eventName": "download_thanks", "conversions": 70, "convertedSessions": 60},
                ],
            },
        }
        md = ga.to_markdown(
            **fx, key_events=["contact_service_thanks", "download_thanks"],
            event_names={"contact_service_thanks": "サービス相談数", "download_thanks": "資料ダウンロード数"},
            kpi_breakdown=kpi_breakdown,
        )
        timeseries_section = md.split("## 1.")[1].split("## 2.")[0]
        self.assertIn(
            "| 月 | セッション | ユーザー | "
            "CV数: サービス相談数 | CVR: サービス相談数 | CV数: 資料ダウンロード数 | CVR: 資料ダウンロード数 |",
            timeseries_section,
        )
        # セッション1,000に対しイベント数30/CVR 3.00%、70/CVR 7.00%がセットで並ぶ
        self.assertIn("| 1,000 | 800 | 30 | 3.00% | 70 | 7.00% |", timeseries_section)


class _FakeGa4ClientCapturingRequest:
    """直近の run_report() 呼び出しのrequestを記録し、固定のレスポンスを返すフェイクGA4クライアント。

    fetch_landing_pages() / fetch_pages() が include_query_params に応じて実際にどの
    ディメンション名でリクエストしているかを検証するために使う。
    """

    def __init__(self, response):
        self._response = response
        self.last_request = None

    def run_report(self, request):
        self.last_request = request
        return self._response


class FetchLandingPagesQueryParamDimensionTest(unittest.TestCase):
    """fetch_landing_pages(): include_query_params の既定（False=パスのみ）の検証。"""

    def _response(self):
        row = Row(
            dimension_values=[DimensionValue(value="/service/")],
            metric_values=[MetricValue(value="10"), MetricValue(value="2"), MetricValue(value="0.5")],
        )
        return RunReportResponse(rows=[row], row_count=1)

    def test_default_requests_path_only_dimension(self):
        client = _FakeGa4ClientCapturingRequest(self._response())
        period = ga.Period(start=date(2026, 1, 1), end=date(2026, 1, 31))
        rows = ga.fetch_landing_pages(client, "123", period)
        self.assertEqual(client.last_request.dimensions[0].name, "landingPage")
        # 戻り値のキーは呼び出し側との互換性のため常に landingPagePlusQueryString のまま
        self.assertEqual(rows[0]["landingPagePlusQueryString"], "/service/")

    def test_include_query_params_true_requests_plus_query_string_dimension(self):
        client = _FakeGa4ClientCapturingRequest(self._response())
        period = ga.Period(start=date(2026, 1, 1), end=date(2026, 1, 31))
        rows = ga.fetch_landing_pages(client, "123", period, include_query_params=True)
        self.assertEqual(client.last_request.dimensions[0].name, "landingPagePlusQueryString")
        self.assertEqual(rows[0]["landingPagePlusQueryString"], "/service/")


class FetchPagesQueryParamDimensionTest(unittest.TestCase):
    """fetch_pages(): include_query_params の既定（False=パスのみ）の検証。"""

    def _response(self):
        row = Row(dimension_values=[DimensionValue(value="/service/")], metric_values=[MetricValue(value="100")])
        return RunReportResponse(rows=[row], row_count=1)

    def test_default_requests_path_only_dimension(self):
        client = _FakeGa4ClientCapturingRequest(self._response())
        period = ga.Period(start=date(2026, 1, 1), end=date(2026, 1, 31))
        rows = ga.fetch_pages(client, "123", period)
        self.assertEqual(client.last_request.dimensions[0].name, "pagePath")
        self.assertEqual(rows[0]["pagePathPlusQueryString"], "/service/")

    def test_include_query_params_true_requests_plus_query_string_dimension(self):
        client = _FakeGa4ClientCapturingRequest(self._response())
        period = ga.Period(start=date(2026, 1, 1), end=date(2026, 1, 31))
        rows = ga.fetch_pages(client, "123", period, include_query_params=True)
        self.assertEqual(client.last_request.dimensions[0].name, "pagePathPlusQueryString")


class ToMarkdownSegmentScopeTest(unittest.TestCase):
    """to_markdown(): サイトセグメント別内訳（サマリー内）・末尾スラッシュ注記。

    is_conversion_target廃止後は基本分析0〜9をセグメントで絞り込まない。segments /
    segment_classification が渡されたときだけ、「0. 全体サマリ数値」にセグメント別の
    内訳表を追加する。
    """

    def test_no_segments_shows_no_breakdown(self):
        fx = _minimal_markdown_fixtures()
        md = ga.to_markdown(**fx, key_events=["form_submit"])
        self.assertNotIn("サイトセグメント別内訳", md)
        self.assertNotIn("対象外セグメント", md)

    def test_segments_without_classification_shows_no_breakdown(self):
        # segmentsは渡されていても、segment_classificationが無ければ内訳は出さない
        # （main()がGA4を追加で叩けなかった場合に、中途半端な表を出さないためのガード）。
        fx = _minimal_markdown_fixtures()
        segments = [{"segment_id": "seg_main", "name": "本体サイト", "default": True}]
        md = ga.to_markdown(**fx, key_events=["form_submit"], segments=segments)
        self.assertNotIn("サイトセグメント別内訳", md)

    def test_segment_breakdown_appears_in_summary_section(self):
        fx = _minimal_markdown_fixtures()
        segments = [
            {"segment_id": "seg_media", "name": "オウンドメディア", "match": {"path_prefix": "/media/"}},
            {"segment_id": "seg_main", "name": "本体サイト", "default": True},
        ]
        classification = {
            "segments": [
                {"segment_id": "seg_media", "name": "オウンドメディア", "sessions": 800, "conversions": 0},
                {"segment_id": "seg_main", "name": "本体サイト", "sessions": 200, "conversions": 10},
            ],
            "other": {"sessions": 0, "conversions": 0, "page_count": 0},
            "total": {"sessions": 1000, "conversions": 10},
        }
        md = ga.to_markdown(
            **fx, key_events=["form_submit"],
            segments=segments, segment_classification=classification,
        )
        summary_section = md.split("## 0.")[1].split("## 1.")[0]
        self.assertIn("### サイトセグメント別内訳", summary_section)
        self.assertIn("オウンドメディア", summary_section)
        self.assertIn("本体サイト", summary_section)
        self.assertIn("| 合計 | 1,000 |", summary_section)
        # 本文0〜9はセグメントで絞り込んでいない（サイト全体のまま）ため、この注記は出さない。
        self.assertNotIn("対象外セグメント", md)

    def test_other_row_appears_when_no_default_segment_defined(self):
        fx = _minimal_markdown_fixtures()
        segments = [{"segment_id": "seg_a", "name": "サービスサイト", "match": {"path_prefix": "/service/"}}]
        classification = {
            "segments": [{"segment_id": "seg_a", "name": "サービスサイト", "sessions": 200, "conversions": 10}],
            "other": {"sessions": 50, "conversions": 0, "page_count": 2},
            "total": {"sessions": 250, "conversions": 10},
        }
        md = ga.to_markdown(
            **fx, key_events=["form_submit"],
            segments=segments, segment_classification=classification,
        )
        self.assertIn("その他（分類外、2ページ）", md)

    def test_truncated_segmentation_is_noted(self):
        fx = _minimal_markdown_fixtures()
        segments = [{"segment_id": "seg_main", "name": "本体サイト", "default": True}]
        classification = {
            "segments": [{"segment_id": "seg_main", "name": "本体サイト", "sessions": 0, "conversions": 0}],
            "other": {"sessions": 0, "conversions": 0, "page_count": 0},
            "total": {"sessions": 0, "conversions": 0},
        }
        md = ga.to_markdown(
            **fx, key_events=["form_submit"],
            segments=segments, segment_classification=classification, segment_truncated=True,
        )
        self.assertIn("取得の上限に達しており", md)

    def test_trailing_slash_dupes_are_noted(self):
        fx = _minimal_markdown_fixtures()
        md = ga.to_markdown(
            **fx, key_events=["form_submit"],
            trailing_slash_dupes=[("/contact/service", "/contact/service/")],
        )
        self.assertIn("末尾スラッシュ違い", md)
        self.assertIn("/contact/service", md)


class ProgressOutputTest(unittest.TestCase):
    """GA4への1リクエストごとの進捗表示（_progress/_progress_summary）。

    実データで本体実行が8分15秒かかり、その間まったく標準出力に何も出さなかったため、
    実行していたAIエージェントが「止まっている」と誤判定した（正常終了はしていた）。
    リクエストごとにstderrへ1行進捗が出ることをここで固定する
    （無いと次の改修で黙って消えて再発する）。
    """

    def _response(self):
        row = Row(
            dimension_values=[DimensionValue(value="/service/")],
            metric_values=[MetricValue(value="10")],
        )
        return RunReportResponse(rows=[row], row_count=1)

    def setUp(self):
        ga._reset_progress()

    def test_run_report_emits_one_progress_line_to_stderr(self):
        client = _FakeGa4ClientCapturingRequest(self._response())
        period = ga.Period(start=date(2026, 1, 1), end=date(2026, 1, 31))
        buf = io.StringIO()
        with redirect_stderr(buf):
            ga._run_report(
                client, "123", ["pagePath"], ["screenPageViews"], period, label="ページ別",
            )
        out = buf.getvalue()
        self.assertIn("1本目のリクエスト送信中", out)
        self.assertIn("ページ別", out)
        self.assertIn("経過", out)

    def test_progress_does_not_write_to_stdout(self):
        # レポート本体は --output 省略時にstdoutへ出る。進捗表示が混ざるとMarkdownが壊れるため、
        # 進捗はstderr専用であることを固定する。
        client = _FakeGa4ClientCapturingRequest(self._response())
        period = ga.Period(start=date(2026, 1, 1), end=date(2026, 1, 31))
        stdout_buf = io.StringIO()
        with redirect_stdout(stdout_buf):
            ga._run_report(
                client, "123", ["pagePath"], ["screenPageViews"], period, label="ページ別",
            )
        self.assertEqual(stdout_buf.getvalue(), "")

    def test_progress_counter_increments_across_requests(self):
        client = _FakeGa4ClientCapturingRequest(self._response())
        period = ga.Period(start=date(2026, 1, 1), end=date(2026, 1, 31))
        buf = io.StringIO()
        with redirect_stderr(buf):
            ga.fetch_pages(client, "123", period)
            ga.fetch_pages(client, "123", period)
        lines = [line for line in buf.getvalue().splitlines() if line.strip()]
        self.assertEqual(len(lines), 2)
        self.assertIn("1本目のリクエスト送信中", lines[0])
        self.assertIn("2本目のリクエスト送信中", lines[1])

    def test_reset_progress_restarts_counter(self):
        client = _FakeGa4ClientCapturingRequest(self._response())
        period = ga.Period(start=date(2026, 1, 1), end=date(2026, 1, 31))
        buf = io.StringIO()
        with redirect_stderr(buf):
            ga.fetch_pages(client, "123", period)
            ga._reset_progress()
            ga.fetch_pages(client, "123", period)
        lines = [line for line in buf.getvalue().splitlines() if line.strip()]
        self.assertIn("1本目のリクエスト送信中", lines[-1])

    def test_progress_summary_reports_total_count_to_stderr(self):
        ga._progress("x")
        ga._progress("y")
        buf = io.StringIO()
        with redirect_stderr(buf):
            ga._progress_summary()
        out = buf.getvalue()
        self.assertIn("完了", out)
        self.assertIn("2本", out)


if __name__ == "__main__":
    unittest.main()
