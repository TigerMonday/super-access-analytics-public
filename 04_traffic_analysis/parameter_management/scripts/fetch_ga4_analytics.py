"""GA4 から基本分析レポート用のデータを取得する

取得するセクション（`docs/standard-run-order.md` 準拠、03の基本分析構成）:
- summary: 全体サマリ数値（セッション・ユーザー・指定CV、前期比。レポート冒頭のサマリ作成に使う）
- timeseries: 月次/週次/日次推移（セッション・ユーザー・指定CV）
- channel: チャネル別パフォーマンス（デフォルトチャネルグループ、前期比つき）
- landing_pages: ランディングページ別（セッション上位・CVR）
- pages: ページ別（PV上位。回遊も含めた人気ページ）
- device: デバイス別（mobile/desktop/tablet の3カテゴリのみ）
- new_vs_returning: 新規/リピーター別
- form_completion: キーイベントごとに、フォームページPVを分母、完了イベント数を分子とする通過率
- ecommerce: ECサイトではGA4推奨eコマースイベントの取得状況と購入プロセス

CVの経路（どのページを経てCVに至ったか）は、着地ページと閲覧ページの共起では見えない
（着地ページでしか絞り込めず、CVしたセッションに絞り込めないため。着地ページ×閲覧ページの
クロス集計だった旧項目9「CVパス簡易近似」は、実データで着地ページのCVRが0.12%だった
ケースで表の99.88%がCVしなかった人の行動になり、「CVに至る経路」としては読めなかった
ため削除した）。CVの経路は、BigQuery連携があるクライアントのみ bq_cv_paths.py の
ページ遷移（セッション単位で実際の発生順に組み立てた経路）で見る。

計算ロジック（前期比・ファネルの到達率/転換率・ランキングの量質比較）は
analysis_calc.py の純粋関数に切り出してあり、tests/test_analysis_calc.py で単体テストできる。

従量への配慮: 既定期間は直近の完了した12か月。GA4 Data APIの消費量は単純なリクエスト本数ではなく、
期間・行数・カーディナリティ等で変わるトークン制のため、各レスポンスでクォータ情報を要求する。
長期間や高カーディナリティの調査は必要なときだけ明示的に期間・上限を広げる。

複数CV（キーイベント）の内訳: `--key-events` が業務名（またはイベント名）で2グループ以上に
分かれる場合のみ、fetch_conversions_by_event() で summary/timeseries/channel/device/
new_vs_returning/landing_pages の内訳を追加取得する。
キーイベントが1件、またはグループが1つしかできない場合はこの追加取得自体を行わない＝
単一CVのクライアントは従来と同じリクエスト数のまま）。合算せず内訳表示する狙いは、
複数CVを持つクライアントで「合算のCV列だけでは、どのCVを増やす施策を打つべきか決められない」
という実例を踏まえたもの。

Usage:
    uv run python scripts/fetch_ga4_analytics.py \
        --property-id 123456789 \
        --start-date 2025-09-01 --end-date 2026-08-31 \
        --key-events form_submit,file_download \
        --funnel-events "form_submit:/contact/service/:contains:confirmed" \
        --output samples/_analytics_{client}.md

`--event-names-json` は任意（01の kpis.yaml に業務名が登録されているクライアントで、
レポートの「指定キーイベント」表示とフォーム通過率の見出しにイベント名ではなく業務名を
使いたい場合に指定する。未指定ならイベント名のみで出力される。詳細は該当引数のhelp参照）。

`--primary-kpi-name` も任意（01の kpis.yaml で `priority: 1` が一意に決まっているクライアントで、
そのKPIを各セクションの先頭に並べ★印で示したい場合に指定する。未指定・空文字は「優先度は
未設定」として全KPIを対等に扱う。詳細は該当引数のhelp参照）。

進捗表示: 実データでは本体実行に8分超かかることがあり、無言のままだと無人実行（`claude -p`等）
で「止まっている」と誤判定される。GA4への1リクエストごとに「何本目か」「経過時間」を
stderrへ1行だけ出す（`_progress()` 参照。レポート本体はstdoutのまま汚さない。1リクエスト=1行の
ため無人実行のログを埋めない）。
"""

from __future__ import annotations

import argparse
import calendar
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    DateRange,
    Dimension,
    Filter,
    FilterExpression,
    FilterExpressionList,
    Metric,
    OrderBy,
    RunReportRequest,
)

# Windows + Git Bash等では既定の画面エンコーディングがUTF-8にならず、日本語の
# 表示だけが文字化けすることがある（ファイル自体はUTF-8で正しく書かれている）。
# 明示的にUTF-8へ揃えて防ぐ。reconfigure非対応の環境（一部のリダイレクト等）では
# 何もしない（元の表示に戻るだけで、実行そのものは失敗させない）。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

sys.path.insert(0, str(Path(__file__).resolve().parent))
from auth import get_credentials  # noqa: E402
import analysis_calc as calc  # noqa: E402
from analysis_period import resolve_analysis_periods  # noqa: E402

# 時系列トレンドの粒度 → GA4 ディメンション名
# yearWeek/yearMonth はいずれも GA4 標準ディメンション（形式は YYYYWW / YYYYMM）。
# 「isoYearIsoWeek」のような ISO 週専用ディメンションは GA4 Data API に存在しないため使わない。
GRANULARITY_DIMENSIONS = {
    "daily": "date",
    "weekly": "yearWeek",
    "monthly": "yearMonth",
}
GRANULARITY_LABELS = {
    "daily": "日次",
    "weekly": "週次",
    "monthly": "月次",
}

DEVICE_CATEGORIES = ["mobile", "desktop", "tablet"]
ECOMMERCE_STAGES = [
    ("商品リスト閲覧", "view_item_list"),
    ("商品詳細表示", "view_item"),
    ("カート追加", "add_to_cart"),
    ("購入手続き開始", "begin_checkout"),
    ("配送情報入力", "add_shipping_info"),
    ("支払い情報入力", "add_payment_info"),
    ("購入", "purchase"),
]

# ---------------------------------------------------------------------------
# 進捗表示
# ---------------------------------------------------------------------------
# 実データでの本体実行が8分15秒かかり、その間に標準出力へ一切何も出さなかったため、
# 実行していたAIエージェントが「止まっている」と誤判定した（正常終了はしていた）。
# 無人実行（claude -p 等）でも扱えるよう、GA4へのリクエスト1回につき1行だけ、
# 「何本目か」「経過時間」をstderrへ出す（大量のログでrun_phase.py等の実行ログを
# 埋めないための抑制策。詳細は _run_report() のdocstring参照）。
_progress_count = 0
_progress_start: float | None = None
_data_quality_warnings: set[str] = set()


def _reset_progress() -> None:
    """進捗カウンタと計測開始時刻をリセットする（main() の先頭で呼ぶ。テストでも使う）。"""
    global _progress_count, _progress_start, _data_quality_warnings
    _progress_count = 0
    _progress_start = time.monotonic()
    _data_quality_warnings = set()


def _progress_summary() -> None:
    """全リクエスト完了後に、合計本数と所要時間を1行だけstderrへ出す（出力直前に呼ぶ）。"""
    elapsed = time.monotonic() - _progress_start if _progress_start is not None else 0.0
    print(
        f"[fetch_ga4_analytics] 完了: 計{_progress_count}本のリクエスト、所要 {elapsed:.0f}秒",
        file=sys.stderr,
    )


def _progress(label: str) -> None:
    """GA4へのリクエスト送信直前に、進捗を1行だけstderrへ出す。

    出力先はstderr固定（`--output` 省略時はレポートMarkdown本体をstdoutに出すため、
    進捗表示をそこに混ぜない）。1リクエスト=1行に抑え、既存の run_phase.py の
    「Getting X...」に文言の調子を合わせる。
    """
    global _progress_count
    _progress_count += 1
    elapsed = time.monotonic() - _progress_start if _progress_start is not None else 0.0
    print(
        f"[fetch_ga4_analytics] {_progress_count}本目のリクエスト送信中: {label}"
        f"（経過 {elapsed:.0f}秒）",
        file=sys.stderr,
    )


@dataclass
class Period:
    start: date
    end: date

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1


def _run_report(
    client: BetaAnalyticsDataClient,
    property_id: str,
    dimensions: list[str],
    metrics: list[str],
    period: Period,
    order_by_metric: str | None = None,
    limit: int = 100,
    filter_expression: FilterExpression | None = None,
    label: str | None = None,
):
    """GA4 Data API へ1リクエスト送る（全呼び出し箇所がここを通る共通口）。

    label: 進捗表示（_progress()）に出す日本語の説明。呼び出し側が指定しなければ
    ディメンション名から簡易に組み立てる（無指定でも進捗表示自体は必ず出る）。
    """
    _progress(label or (" × ".join(dimensions) if dimensions else "全体集計"))
    forbidden = {"engagedSessions", "engagementRate"}.intersection(metrics)
    if forbidden:
        raise ValueError(f"本プロダクトでは取得しない指標が指定されました: {sorted(forbidden)}")
    api_metrics = ["keyEvents" if m == "conversions" else m for m in metrics]
    api_order_metric = "keyEvents" if order_by_metric == "conversions" else order_by_metric
    request_kwargs = {
        "property": f"properties/{property_id}",
        "dimensions": [Dimension(name=d) for d in dimensions],
        "metrics": [Metric(name=m) for m in api_metrics],
        "date_ranges": [
            DateRange(start_date=period.start.isoformat(), end_date=period.end.isoformat())
        ],
        "limit": limit,
        "return_property_quota": True,
    }
    if api_order_metric:
        request_kwargs["order_bys"] = [
            OrderBy(metric=OrderBy.MetricOrderBy(metric_name=api_order_metric), desc=True)
        ]
    if filter_expression:
        request_kwargs["dimension_filter"] = filter_expression
    response = client.run_report(RunReportRequest(**request_kwargs))
    metadata = getattr(response, "metadata", None)
    if metadata and getattr(metadata, "subject_to_thresholding", False):
        _data_quality_warnings.add("Googleのしきい値適用により一部データが省略されている可能性があります")
    if metadata and getattr(metadata, "data_loss_from_other_row", False):
        _data_quality_warnings.add("高カーディナリティにより(other)行へ集約されたデータがあります")
    sampling = getattr(metadata, "sampling_metadatas", None) if metadata else None
    if sampling:
        _data_quality_warnings.add("サンプリングされたデータが含まれます")
    quota = getattr(response, "property_quota", None)
    for attr, label in (
        ("tokens_per_hour", "1時間あたりトークン"),
        ("tokens_per_project_per_hour", "プロジェクトの1時間あたりトークン"),
        ("concurrent_requests", "同時リクエスト"),
    ):
        status = getattr(quota, attr, None) if quota is not None else None
        remaining = getattr(status, "remaining", None) if status is not None else None
        if remaining is not None and int(remaining) <= 10:
            _data_quality_warnings.add(f"GA4 Data APIの{label}残量が{int(remaining)}です")
    return response


def _rows_to_dicts(response, dimension_names: list[str], metric_names: list[str]):
    out = []
    for row in response.rows:
        d = {}
        for i, dim in enumerate(dimension_names):
            d[dim] = row.dimension_values[i].value
        for i, met in enumerate(metric_names):
            v = row.metric_values[i].value
            d[met] = float(v) if "." in v else int(v) if v.isdigit() else float(v)
        out.append(d)
    return out


def _in_list_filter(field_name: str, values: list[str]) -> FilterExpression:
    return FilterExpression(
        filter=Filter(field_name=field_name, in_list_filter=Filter.InListFilter(values=values))
    )


def _contains_filter(field_name: str, value: str) -> FilterExpression:
    return FilterExpression(
        filter=Filter(
            field_name=field_name,
            string_filter=Filter.StringFilter(
                value=value, match_type=Filter.StringFilter.MatchType.CONTAINS
            ),
        )
    )


def _exact_filter(field_name: str, value: str) -> FilterExpression:
    return FilterExpression(
        filter=Filter(
            field_name=field_name,
            string_filter=Filter.StringFilter(
                value=value, match_type=Filter.StringFilter.MatchType.EXACT
            ),
        )
    )


def _and_filters(*filters: FilterExpression | None) -> FilterExpression | None:
    parts = [f for f in filters if f is not None]
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0]
    return FilterExpression(and_group=FilterExpressionList(expressions=parts))


# ---------------------------------------------------------------------------
# 0. 全体サマリ数値
# ---------------------------------------------------------------------------

def fetch_summary(client, property_id, period: Period, prev_period: Period, extra_filter=None):
    """全体サマリ: sessions, totalUsers, newUsers, conversions

    extra_filter: 呼び出し側が渡す追加のAND絞り込み条件。省略時（None）は絞り込み無し
    （サイトセグメントによるフィルタリングはしない。01の site_segments はサマリーの
    セグメント別内訳表示にのみ使う。判断根拠は run.md 参照）。
    """
    metrics = ["sessions", "totalUsers", "newUsers", "conversions"]
    curr = _run_report(
        client, property_id, [], metrics, period, limit=1, filter_expression=extra_filter,
        label="全体サマリ（当期）",
    )
    prev = _run_report(
        client, property_id, [], metrics, prev_period, limit=1, filter_expression=extra_filter,
        label="全体サマリ（前期）",
    )

    def first_row(resp):
        if not resp.rows:
            return {m: 0 for m in metrics}
        out = {}
        for i, m in enumerate(metrics):
            v = resp.rows[0].metric_values[i].value
            out[m] = int(float(v))
        return out

    return {"current": first_row(curr), "previous": first_row(prev)}


# ---------------------------------------------------------------------------
# 1. 月次/週次/日次推移
# ---------------------------------------------------------------------------

def fetch_timeseries(client, property_id, period: Period, granularities: list[str], extra_filter=None):
    """粒度別トレンド: 粒度ごとに (sessions, totalUsers, conversions) を取得

    granularities: ["daily", "weekly", "monthly"] の部分集合。
    粒度ごとに1クエリ（GRANULARITY_DIMENSIONS の1ディメンションのみ）で、
    行数は取得期間の日数程度以下（軽量）。
    extra_filter: 呼び出し側が渡す追加のAND絞り込み条件。省略時（None）は絞り込み無し。
    """
    mets = ["sessions", "totalUsers", "conversions"]
    results: dict[str, list[dict]] = {}
    for g in granularities:
        dim = GRANULARITY_DIMENSIONS[g]
        resp = _run_report(
            client, property_id, [dim], mets, period, limit=400, filter_expression=extra_filter,
            label=f"{GRANULARITY_LABELS[g]}推移",
        )
        rows = _rows_to_dicts(resp, [dim], mets)
        rows.sort(key=lambda r: r[dim])
        results[g] = rows
    return results


def fetch_timeseries_by_event(
    client, property_id, period: Period, granularities: list[str], key_events: list[str],
    extra_filter=None,
) -> dict[str, list[dict]]:
    """粒度別トレンドのCVを、eventName別に絞り込んで取得する（複数CVの内訳表示用）。

    fetch_timeseries() の "conversions" はGA4標準の集計（プロパティ全体のキーイベント合計）
    のため、--key-events で指定した個々のCVの増減が読めない。粒度ごとに
    fetch_conversions_by_event() を呼び、[dim, eventName] のクロス集計を返す
    （呼び出し側が analysis_calc.kpi_group_rows() で日付/週/月ごとのKPI別件数にまとめる）。

    key_events が空、または呼び出し元でKPIが1件しか無いと判定された場合は呼ばない想定
    （単一CVのクライアントに対してこの追加リクエストを発生させない従量ガードは main() 側）。
    """
    results: dict[str, list[dict]] = {}
    for g in granularities:
        dim = GRANULARITY_DIMENSIONS[g]
        results[g] = fetch_conversions_by_event(
            client, property_id, period, [dim], key_events, limit=1000, extra_filter=extra_filter,
            label=f"CV内訳: {GRANULARITY_LABELS[g]}推移",
        )
    return results


def _format_period_label(value: str, granularity: str) -> str:
    """date/yearWeek/yearMonth の生値を表示用ラベルに整形

    weekly は「2026-W32」のようなISO週表記だと開始・終了日が分からず読みにくいという
    フィードバックを受け、calc.format_week_range() で「2026/08/10〜08/16」の日付レンジに変換する
    （GA4のyearWeekは日曜始まり・ISO週とは異なる定義。詳細は同関数のdocstring参照）。
    """
    if granularity == "daily" and len(value) == 8:
        return f"{value[:4]}-{value[4:6]}-{value[6:]}"
    if granularity == "weekly" and len(value) == 6:
        return calc.format_week_range(value)
    if granularity == "monthly" and len(value) == 6:
        return f"{value[:4]}-{value[4:]}"
    return value


def _format_report_period(period: Period) -> str:
    """表見出し用の期間。完了月だけなら月単位、それ以外は日付まで表示する。"""
    if (
        period.start.day == 1
        and period.end.day == calendar.monthrange(period.end.year, period.end.month)[1]
    ):
        return (
            f"{period.start.year}/{period.start.month}〜"
            f"{period.end.year}/{period.end.month}"
        )
    return (
        f"{period.start.year}/{period.start.month}/{period.start.day}〜"
        f"{period.end.year}/{period.end.month}/{period.end.day}"
    )


# ---------------------------------------------------------------------------
# 2. チャネル別（前期比つき）
# ---------------------------------------------------------------------------

def fetch_by_channel(client, property_id, period: Period, prev_period: Period, limit=50, extra_filter=None):
    """チャネル別: sessionDefaultChannelGroup × (sessions, conversions, totalUsers)

    当期・前期の2回クエリを叩き、チャネルごとに前期セッション数をマージする
    （前期比の計算は analysis_calc.delta_pct が担当）。
    extra_filter: 呼び出し側が渡す追加のAND絞り込み条件。省略時（None）は絞り込み無し。
    """
    dims = ["sessionDefaultChannelGroup"]
    mets = ["sessions", "conversions", "totalUsers"]
    curr_rows = _rows_to_dicts(
        _run_report(
            client, property_id, dims, mets, period, order_by_metric="sessions",
            limit=limit, filter_expression=extra_filter, label="チャネル別（当期）",
        ),
        dims, mets,
    )
    prev_rows = _rows_to_dicts(
        _run_report(
            client, property_id, dims, mets, prev_period, order_by_metric="sessions",
            limit=limit, filter_expression=extra_filter, label="チャネル別（前期）",
        ),
        dims, mets,
    )
    prev_by_channel = {r["sessionDefaultChannelGroup"]: r for r in prev_rows}
    for r in curr_rows:
        prev = prev_by_channel.get(r["sessionDefaultChannelGroup"], {})
        r["prev_sessions"] = prev.get("sessions", 0)
        r["prev_conversions"] = prev.get("conversions", 0)
    return curr_rows


# ---------------------------------------------------------------------------
# 3. ランディングページ別
# ---------------------------------------------------------------------------

def fetch_landing_pages(
    client, property_id, period: Period, fetch_limit=300,
    include_query_params=False, extra_filter=None,
):
    """ランディングページ別: landingPage(PlusQueryString) × (sessions, conversions)

    fetch_limit は表示用の上位N件より広めに取得する（既定300件）。ページ別セクション（4）の
    閲覧開始率算出にも同じ取得結果を使い回すため。

    include_query_params が False（既定）なら landingPage（クエリ文字列を含まない）を使う。
    実データで `/?renew=` のようなクエリ付き別名が別ページ扱いになる不具合があったため、
    既定でクエリを落とす。戻り値のキーはどちらの場合も従来どおり
    "landingPagePlusQueryString"（呼び出し側の互換性のため。実体の値はクエリ無しになる）。

    extra_filter: 呼び出し側が渡す追加のAND絞り込み条件。省略時（None）は絞り込み無し。
    """
    dim = calc.landing_page_dimension(include_query_params)
    dims = [dim]
    mets = ["sessions", "conversions"]
    resp = _run_report(
        client, property_id, dims, mets, period,
        order_by_metric="sessions", limit=fetch_limit, filter_expression=extra_filter,
        label="ランディングページ別",
    )
    rows = _rows_to_dicts(resp, dims, mets)
    if dim != "landingPagePlusQueryString":
        for r in rows:
            r["landingPagePlusQueryString"] = r.pop(dim)
    # landing page が定義できないセッションは GA4 が (not set) を返す。これは入口ページの
    # 比較対象ではないため、ランキング・合計・考察から除外する。計測異常としても扱わない。
    unusable = {"", "(not set)", "(data not available)"}
    return [
        r for r in rows
        if str(r.get("landingPagePlusQueryString", "")).strip().lower() not in unusable
    ]


# ---------------------------------------------------------------------------
# 4. ページ別
# ---------------------------------------------------------------------------

def fetch_pages(client, property_id, period: Period, limit=20, include_query_params=False, extra_filter=None):
    """ページ別: pagePath(PlusQueryString) × screenPageViews

    基本分析のページ表はPVだけを扱う。閲覧開始数・閲覧開始率・離脱率は表示しない。

    include_query_params が False（既定）なら pagePath（クエリ文字列を含まない）を使う
    （fetch_landing_pages() と同じ既定値。戻り値のキーは従来どおり "pagePathPlusQueryString"）。
    extra_filter: 呼び出し側が渡す追加のAND絞り込み条件。省略時（None）は絞り込み無し。
    """
    dim = calc.page_path_dimension(include_query_params)
    dims = [dim]
    mets = ["screenPageViews"]
    resp = _run_report(
        client, property_id, dims, mets, period,
        order_by_metric="screenPageViews", limit=limit, filter_expression=extra_filter,
        label="ページ別",
    )
    rows = _rows_to_dicts(resp, dims, mets)
    if dim != "pagePathPlusQueryString":
        for r in rows:
            r["pagePathPlusQueryString"] = r.pop(dim)
    return rows


# ---------------------------------------------------------------------------
# 5. デバイス別
# ---------------------------------------------------------------------------

def fetch_by_device(client, property_id, period: Period, extra_filter=None):
    """デバイス別: deviceCategory × (sessions, conversions, totalUsers)

    mobile / desktop / tablet の3カテゴリのみに絞る（地域・OS・年齢性別は対象外）。
    extra_filter: 呼び出し側が渡す追加のAND絞り込み条件（deviceCategoryの絞り込みとANDで
    組み合わせる）。省略時（None）はdeviceCategoryの絞り込みのみ。
    """
    dims = ["deviceCategory"]
    mets = ["sessions", "conversions", "totalUsers"]
    filter_expr = _and_filters(_in_list_filter("deviceCategory", DEVICE_CATEGORIES), extra_filter)
    resp = _run_report(
        client, property_id, dims, mets, period,
        order_by_metric="sessions", limit=10, filter_expression=filter_expr,
        label="デバイス別",
    )
    return _rows_to_dicts(resp, dims, mets)


# ---------------------------------------------------------------------------
# 6. 新規/リピーター別
# ---------------------------------------------------------------------------

def fetch_new_vs_returning(client, property_id, period: Period, extra_filter=None):
    """新規/リピーター別: newVsReturning × (sessions, conversions)

    extra_filter: 呼び出し側が渡す追加のAND絞り込み条件。省略時（None）は絞り込み無し。
    """
    dims = ["newVsReturning"]
    mets = ["sessions", "conversions"]
    resp = _run_report(
        client, property_id, dims, mets, period,
        order_by_metric="sessions", limit=10, filter_expression=extra_filter,
        label="新規/リピーター別",
    )
    rows = _rows_to_dicts(resp, dims, mets)
    # GA4が空文字を返すことがある（"(not set)"とは別の生値）。表示上は区別せず「(not set)」に統合する
    # （統合後に同名行が複数できる場合はセッション数・CV数を合算する）。
    merged: dict[str, dict] = {}
    for r in rows:
        label = r["newVsReturning"] or "(not set)"
        if label not in merged:
            merged[label] = {"newVsReturning": label, "sessions": 0, "conversions": 0}
        m = merged[label]
        m["sessions"] += r["sessions"]
        m["conversions"] += r["conversions"]
    out = []
    for m in merged.values():
        out.append({
            "newVsReturning": m["newVsReturning"],
            "sessions": m["sessions"],
            "conversions": m["conversions"],
        })
    out.sort(key=lambda r: r["sessions"], reverse=True)
    return out


# ---------------------------------------------------------------------------
# 複数CV（キーイベント）の内訳取得（0・1・2・3・5・6・8の共通ヘルパー）
# ---------------------------------------------------------------------------

def fetch_conversions_by_event(
    client,
    property_id,
    period: Period,
    dims: list[str],
    key_events: list[str],
    limit: int = 1000,
    extra_filter: FilterExpression | None = None,
    label: str | None = None,
) -> list[dict]:
    """dims × eventName でCVイベント発生回数を取得する。

    複数CV（キーイベント）を持つクライアントで、サマリー・推移・チャネル別・ランディング
    ページ別・デバイス別・新規/リピーター別・CVの由来にKPIごとのCV内訳を
    付けるための共通ヘルパー（analysis_calc.kpi_group_rows() / attach_kpi_breakdown() が
    この戻り値を消費する）。eventName を key_events でIN句絞り込みするため、GA4標準の
    「conversions」指標をディメンション無しでそのまま使う場合と違い、--key-events に
    指定していない他のキーイベントが合算に混入しない
    （実データで見つかった「複数CVを合算すると、どちらの施策を打つべきか決められない」
    不具合の修正の中核。単一CVのクライアントはこの関数を呼ばず、従来の集計のまま進める
    ＝多くのクライアントでは追加のGA4リクエストが発生しない）。

    key_events が空なら呼び出し側で何も内訳が作れないため、空リストを返す
    （GA4への無駄なリクエストを送らない）。
    """
    if not key_events:
        return []
    all_dims = list(dims) + ["eventName"]
    filter_expr = _and_filters(_in_list_filter("eventName", key_events), extra_filter)
    resp = _run_report(
        client, property_id, all_dims, ["eventCount"], period,
        limit=limit, filter_expression=filter_expr,
        label=label or f"CV内訳: {' × '.join(dims) if dims else '全体'}",
    )
    rows = _rows_to_dicts(resp, all_dims, ["eventCount"])
    # 既存の集計・Markdown組み立てとの互換性のため、内部キーは conversions のまま保つ。
    # 値の定義は GA4 の eventCount（イベント発生回数）であり、キーイベント設定の有無には
    # 依存しない。
    for row in rows:
        row["conversions"] = row.pop("eventCount")
    return rows


def zero_count_key_events(key_events: list[str], rows: list[dict]) -> list[str]:
    """eventName別行から、対象期間に0件（行自体が無い場合を含む）の指定CVを返す。"""
    counts = {r.get("eventName"): int(r.get("conversions", 0)) for r in rows}
    return [event for event in key_events if counts.get(event, 0) <= 0]


def fetch_channel_period_breakdown(
    client, property_id: str, period: Period, prev_period: Period, key_events: list[str],
) -> dict[str, list[dict]]:
    """チャネル別の指定CVを当期・前期のセットで取得する。

    フォーム／ECの導線分岐より前にこの関数を呼び、どちらのサイト種別でも
    前期CV・CVRを欠落させない。
    """
    return {
        "channel_rows": fetch_conversions_by_event(
            client, property_id, period, ["sessionDefaultChannelGroup"], key_events, limit=500,
            label="CV内訳: チャネル別",
        ),
        "channel_previous_rows": fetch_conversions_by_event(
            client, property_id, prev_period, ["sessionDefaultChannelGroup"], key_events, limit=500,
            label="CV内訳: チャネル別（前期）",
        ),
    }


# ---------------------------------------------------------------------------
# 7. フォームページ候補とフォーム通過率
# ---------------------------------------------------------------------------

def fetch_key_event_counts(
    client, property_id, period: Period, key_events: list[str], label: str = "キーイベント件数",
) -> dict[str, int]:
    """確認済みCVイベントごとの発生回数を取得する。

    フォーム通過率を何本作るか（CV件数の多い順に最大5本）を決める順序付けにも使う。
    基本分析のCV数はイベント発生回数とするため、GA4の eventCount を使う。
    GA4側に発火が無いイベントは0で埋める
    （呼び出し側の key_events の指定順を辞書の並び順として保つ＝件数同数時のタイブレークに使う）。
    """
    if not key_events:
        return {}
    counts: dict[str, int] = {}
    for event in key_events:
        resp = _run_report(
            client, property_id, [], ["eventCount"], period,
            limit=1, filter_expression=_exact_filter("eventName", event),
            label=f"{label}: CVイベント（{event}）",
        )
        counts[event] = int(resp.rows[0].metric_values[0].value) if resp.rows else 0
    return counts


def fetch_page_candidates_for_event(
    client, property_id, period: Period, event_name: str, limit: int = 10,
    landing_pages: list[dict] | None = None, include_query_params: bool = False,
):
    """指定したキーイベントが発火したセッションで、よく見られているページを候補として返す。

    フォームページ選定用。実データで `/contact/` 配下に、CVとして数える
    `contact_service_thanks` 用のフォームと、数えない `contact_thanks` のフォームが
    同居していたケースがあった。中間ページを人が白紙で決めるのではなく、そのキーイベントの
    発火セッションで実際によく見られているページ（＝フォームのページである可能性が高い）を
    セッション数の多い順に候補として出し、実際にサイトを読みに行って判定する運用に変える。

    実データで、完了ページ（サンクスページ）自身がこの候補の1位になる不具合があった
    （このサイトのキーイベントがサンクスページの page_view として発火する設計のため。
    GA4で最もありふれた計測方式で、他社でも同様に起こりうる）。原因はGA4がディメンションと
    指標をイベント行で結合すること。eventName でフィルタすると「そのイベントが起きた行の
    ページ」しか返らない構造上の限界で、集計方法自体を変えない限り解消しない
    （詳しくは standards/ga4-event-scoped-dimensions.md）。

    calc.rank_page_candidates() に event_name を渡し、calc.is_event_self_page() で
    「イベント自身の発火ページ」らしいと推定できた候補を除外扱いにする（黙って消さず、
    excluded_self フラグ付きで残す）。ボタンクリック等で発火する型（発火ページ＝入力前
    ページ＝正解）は影響を受けない。判定の詳細は calc.is_event_self_page() のdocstring参照。

    候補が全て除外扱い（＝サンクスページ型で、この集計方法では入力前ページを検出できない
    ケース）になった場合は、landing_pages（fetch_landing_pages() の結果。GA4への新規
    クエリを増やさず、既に取得済みのデータを使い回す）を渡すと、完了ページの親パスが
    ランディングページ一覧に実在するか照合し、実在すれば「推定候補」として先頭に追加する
    （calc.with_parent_path_guess() 参照）。landing_pages を渡さない場合はこの推定を行わない。
    """
    dim = calc.page_path_dimension(include_query_params)
    dims = [dim]
    mets = ["sessions"]
    filter_expr = _in_list_filter("eventName", [event_name])
    resp = _run_report(
        client, property_id, dims, mets, period,
        order_by_metric="sessions", limit=limit, filter_expression=filter_expr,
        label=f"フォームページ候補: {event_name}",
    )
    rows = _rows_to_dicts(resp, dims, mets)
    if dim != "pagePathPlusQueryString":
        for r in rows:
            r["pagePathPlusQueryString"] = r.pop(dim)
    candidates = calc.rank_page_candidates(rows, limit=limit, event_name=event_name)
    if landing_pages:
        candidates = calc.with_parent_path_guess(candidates, landing_pages)
    return candidates


def _build_funnel_filters(
    event: str, page: str | None, match_type: str = "contains"
) -> tuple[FilterExpression | None, FilterExpression]:
    """1本のファネル（中間ページ到達・CV達成）用のフィルタを組み立てる。

    cv_filter は必ず「このキーイベントのみ」を対象にする（in_list_filter の値は
    常に1件=[event]。複数キーイベントのORにしない。分子と分母を対応させるための変更点）。
    page が指定されていれば、CV達成の条件にも中間ページ到達条件をANDで含める
    （「中間ページに到達した上でこのキーイベントが発火したセッション」を数える）。
    """
    page_filter: FilterExpression | None = None
    if page:
        page_filter = (
            _exact_filter("pagePathPlusQueryString", page)
            if match_type == "exact"
            else _contains_filter("pagePathPlusQueryString", page)
        )
    event_filter = _in_list_filter("eventName", [event])
    cv_filter = _and_filters(page_filter, event_filter)
    return page_filter, cv_filter


def fetch_cv_funnels(
    client,
    property_id,
    period: Period,
    key_events: list[str],
    funnel_events: dict[str, dict] | None = None,
    max_funnels: int = 5,
    primary_events: set[str] | None = None,
    completion_event_counts: dict[str, int] | None = None,
):
    """CVごとにフォーム閲覧数と完了イベント数を対応させ、フォーム通過率を作る。

    旧設計（候補ページを部分一致で累積ANDし、最後にキーイベントのいずれかが発火した
    セッションを数える1本のファネル）は、分母に「CVとして数えないフォームへの到達」が
    混入し、分子からは対応しないキーイベントの完了が漏れる欠陥があった。CVごとに
    現行は分母をフォームページPV、分子を対応する完了イベント数として独立集計する。

    key_events: 対象キーイベントの全件（本数の判定・CV件数が多い順の並べ替え・
        上限を超えた分の記録に使う）。
    funnel_events: {event_name: {"page": str|None, "match_type": "contains"|"exact",
        "confirmed": bool}}。page が None のキーイベントはフォーム通過率を算出しない。
        confirmed=False は候補ページを利用者が未確認の場合に使う。
    max_funnels: CV件数が多い順に採用する本数の上限（既定5）。超えた分はファネルを
        作らず、件数だけ excluded に記録する（黙って打ち切らない）。
    primary_events: 01の kpis.yaml で優先度1と判定されたKPIに属するイベント名の集合
        （複数イベントで構成されるKPIもあり得るため集合）。指定時はCV件数の順位に関わらず
        これらのイベントを先頭に並べ、上限cutoffで黙って外れないようにする
        （analysis_calc.select_funnels() 参照）。該当ファネルの見出しにも主KPIと分かる
        印を付ける（funnel_markdown_lines）。
    completion_event_counts: 同じ実行内でサマリー用に取得済みの
        `{event_name: 完了イベント発生回数}`。渡された場合は再問い合わせせず、フォーム通過率の
        分子と対象選定に同じ値を使う。GA4の遅延反映中に別々の問い合わせ結果がずれることを防ぐ。

    戻り値: {"funnels": [{"key_event", "cv_count", "confirmed", "match_type",
             "has_intermediate", "page", "steps", "is_primary"}, ...],
             "excluded": [(event_name, cv_count), ...]}
    key_events が空なら {"funnels": [], "excluded": []} を返す。
    """
    if not key_events:
        return {"funnels": [], "excluded": []}

    funnel_events = funnel_events or {}
    if completion_event_counts is None:
        counts = fetch_key_event_counts(client, property_id, period, key_events)
    else:
        counts = {event: int(completion_event_counts.get(event, 0)) for event in key_events}
    selected, excluded = calc.select_funnels(counts, max_funnels=max_funnels, primary_events=primary_events)

    funnels = []
    for event in selected:
        spec = funnel_events.get(event, {})
        page = spec.get("page")
        match_type = spec.get("match_type", "contains")
        confirmed = spec.get("confirmed", True)

        page_views = None
        if page:
            page_filter = (
                _exact_filter("pagePath", page)
                if match_type == "exact"
                else _contains_filter("pagePath", page)
            )
            resp = _run_report(
                client, property_id, [], ["screenPageViews"], period,
                filter_expression=page_filter, limit=1,
                label=f"フォーム通過率: {event}（フォーム閲覧）",
            )
            page_views = int(resp.rows[0].metric_values[0].value) if resp.rows else 0
        completion_events = counts.get(event, 0)
        completion_rate = (
            completion_events / page_views * 100
            if page_views not in (None, 0) else None
        )

        funnels.append({
            "key_event": event,
            "cv_count": counts.get(event, 0),
            "confirmed": confirmed,
            "match_type": match_type,
            "has_intermediate": page is not None,
            "page": page,
            "form_page_views": page_views,
            "completion_events": completion_events,
            "completion_rate": completion_rate,
            "is_primary": bool(primary_events) and event in primary_events,
        })

    return {"funnels": funnels, "excluded": excluded}


# ---------------------------------------------------------------------------
# 8. CVはどこから来たか
# ---------------------------------------------------------------------------

def fetch_by_source_medium(client, property_id, period: Period, limit=50, extra_filter=None):
    """流入元別: sessionSource × sessionMedium × (sessions, conversions)

    CVはどこから来たか（8）のランキング比較専用。utm単位の詳細監査はパラメータチェック
    （既存の fetch_ga4_traffic.py）側の役割のまま変えない。
    extra_filter: 呼び出し側が渡す追加のAND絞り込み条件。省略時（None）は絞り込み無し。
    """
    dims = ["sessionSource", "sessionMedium"]
    mets = ["sessions", "conversions"]
    resp = _run_report(
        client, property_id, dims, mets, period,
        order_by_metric="sessions", limit=limit, filter_expression=extra_filter,
        label="流入元別",
    )
    return _rows_to_dicts(resp, dims, mets)


# ---------------------------------------------------------------------------
# ホスト名別（パラメータ監査: 自己参照・想定外ドメインの棚卸し用。基本分析0〜8には含まない）
# ---------------------------------------------------------------------------

def fetch_by_hostname(client, property_id, period: Period, limit=50, key_events=None):
    """ホスト名別: hostName × (sessions, conversions)

    パラメータ監査（自己参照・想定外ドメインの棚卸し）用。従来はここを共通の汎用フェッチャー
    （`common/ga4_fetch/fetch_ga4.py`）へのアドホック呼び出しで済ませ、内訳合計を全体セッション
    と突き合わせていなかった。実データで、ホスト名別の内訳合計が全体セッションを6,645件
    上回るケースが07の実測で見つかった（1セッションが複数ホスト名をまたぐ場合など、絞り込み・
    クロス集計を伴う取得は全体と一致しないことがある）。呼び出し側（hostname_markdown_lines）
    が analysis_calc.format_reconciliation_note() でこのズレを必ず注記する。
    """
    dims = ["hostName"]
    mets = ["sessions"]
    resp = _run_report(
        client, property_id, dims, mets, period, order_by_metric="sessions", limit=limit,
        label="ホスト名別",
    )
    rows = _rows_to_dicts(resp, dims, mets)
    if key_events:
        cv_rows = fetch_conversions_by_event(
            client, property_id, period, dims, key_events, limit=max(limit, 1000),
            label="ホスト名別: 指定CV内訳",
        )
        counts: dict[str, float] = {}
        for row in cv_rows:
            host = row.get("hostName", "")
            counts[host] = counts.get(host, 0) + row.get("conversions", 0)
        for row in rows:
            row["conversions"] = counts.get(row.get("hostName", ""), 0)
    return rows


def hostname_markdown_lines(rows: list[dict], overall_sessions: int, *, has_selected_cv: bool = True) -> list[str]:
    """fetch_by_hostname() の結果をMarkdownに整形する（GA4 API呼び出しなし、単体テスト可能）。

    内訳合計と全体セッションの差を analysis_calc.format_reconciliation_note() で必ず注記する
    （課題2: 絞り込み条件付きの取得で合計がずれても出力に出ない不具合の再発防止）。
    """
    lines = ["# ホスト名別セッション数（自己参照・想定外ドメインの棚卸し）", ""]
    lines.append(
        "自社ドメイン以外のホスト名（自己参照・開発/検証環境・想定外ドメイン）が"
        "混入していないかを確認する。"
    )
    lines.append("")
    if has_selected_cv:
        lines.append("| ホスト名 | セッション | 指定CV |")
        lines.append("|---|---:|---:|")
        for r in rows:
            lines.append(f"| {r['hostName']} | {r['sessions']:,} | {r.get('conversions', 0):,.0f} |")
    else:
        lines.append("| ホスト名 | セッション |")
        lines.append("|---|---:|")
        for r in rows:
            lines.append(f"| {r['hostName']} | {r['sessions']:,} |")
    lines.append("")
    note = calc.format_reconciliation_note(
        overall_sessions, rows, reference_label="全体セッション（絞り込み無し）",
        subtotal_label="ホスト名別の内訳合計",
    )
    if note:
        lines.append(note)
        lines.append("")
    return lines


# ---------------------------------------------------------------------------
# サイトセグメント: サマリーに並べるセグメント別内訳（site_segments が定義されている
# クライアントのみ）
# ---------------------------------------------------------------------------

def fetch_overall_totals(client, property_id, period: Period):
    """絞り込み無しの全体セッション・CV件数を取得する（セグメント別内訳の合計=全体、の
    突き合わせに使う権威値。1リクエスト、limit=1）。
    """
    resp = _run_report(
        client, property_id, [], ["sessions", "conversions"], period, limit=1,
        label="セグメント別内訳: 全体件数",
    )
    if not resp.rows:
        return {"sessions": 0, "conversions": 0}
    return {
        "sessions": int(float(resp.rows[0].metric_values[0].value)),
        "conversions": float(resp.rows[0].metric_values[1].value),
    }


def fetch_landing_pages_for_segmentation(
    client, property_id, period: Period, include_query_params=False, limit=500,
):
    """サマリーに並べる「セグメント別内訳」専用の、landingPage × hostName 取得。

    本文（0〜8）はどのセグメントでも絞り込まずサイト全体のまま取得する（どのセグメントを
    CVR分母とみなすかは02側では決めない）。この関数は別途 landingPage(PlusQueryString) ×
    hostName の全量を取得し、呼び出し側が analysis_calc.classify_segment_rows() で
    セグメント別に再集計してサマリーの内訳表に使う（fetch_landing_pages() はhostName
    ディメンションを含まないため、host_nameでのセグメント判定にはこちらが要る）。

    site_segments が定義されているクライアントでのみ main() が呼ぶ。未定義なら1件も
    追加リクエストは発生しない（従量への配慮）。

    戻り値: (rows, truncated)。truncated は limit に達し、併読ページと同様に
    取りこぼしがあった可能性があるかを示す（GA4のrow_countとの比較）。
    """
    dim = calc.landing_page_dimension(include_query_params)
    dims = [dim, "hostName"]
    mets = ["sessions"]
    resp = _run_report(
        client, property_id, dims, mets, period, order_by_metric="sessions", limit=limit,
        label="セグメント別内訳: ランディングページ×ホスト名",
    )
    rows = _rows_to_dicts(resp, dims, mets)
    for row in rows:
        row["conversions"] = 0
    if dim != "landingPagePlusQueryString":
        for r in rows:
            r["landingPagePlusQueryString"] = r.pop(dim)
    truncated = len(resp.rows) < resp.row_count
    return rows, truncated


def fetch_landing_event_counts_for_segmentation(
    client, property_id, period: Period, key_events: list[str], include_query_params=False, limit=10000,
):
    """セグメント別CV数を、ユーザー確認済みイベントのeventCountだけで取得する。"""
    dim = calc.landing_page_dimension(include_query_params)
    dims = [dim, "hostName", "eventName"]
    resp = _run_report(
        client, property_id, dims, ["eventCount"], period,
        order_by_metric="eventCount", limit=limit,
        filter_expression=_in_list_filter("eventName", key_events),
        label="セグメント別内訳: CVイベント×ランディングページ×ホスト名",
    )
    rows = _rows_to_dicts(resp, dims, ["eventCount"])
    if dim != "landingPagePlusQueryString":
        for row in rows:
            row["landingPagePlusQueryString"] = row.pop(dim)
    return rows, len(resp.rows) < resp.row_count


# ---------------------------------------------------------------------------
# Markdown 整形
# ---------------------------------------------------------------------------

def funnel_markdown_lines(funnel_data: dict, event_names: dict[str, str] | None = None) -> list[str]:
    """フォーム通過率（7）のMarkdown行を組み立てる。

    funnel_data: fetch_cv_funnels() の戻り値 {"funnels": [...], "excluded": [...]}。
    キーイベント1件=フォームページ1件の対で、通過率をサブセクションとして並べる。

    event_names: 01の kpis.yaml 由来の {event_name: KPI名} 対応表（省略時は空扱い）。
    渡された場合、見出しは calc.format_funnel_title() で「KPI名（event名）」にする。
    未登録のイベントは従来どおり event 名のみ（フォールバック。イベント名は必ず残る）。

    to_markdown() からも、`--funnel-only`（利用者にフォームページを確認した後の
    追い取得）からも同じ関数を使う。GA4 API呼び出しを含まないため、fetch_cv_funnels()の
    戻り値と同じ形の辞書を手作りすれば、API無しで単体テストできる。
    """
    lines: list[str] = []
    if (funnel_data or {}).get("journey_type") == "ecommerce":
        lines.append("## 7. ECサイト購入プロセス")
        lines.append("")
        lines.append(
            "GA4の推奨eコマースイベントが実際に取得できている段階だけを使う。"
            "未取得イベントを0件の行として補完せず、計測有無を先に確認する。"
        )
        lines.append("")
        lines.append("| 段階 | GA4イベント | イベント数 | 前段比 |")
        lines.append("|---|---|---:|---:|")
        previous = None
        for stage in funnel_data.get("stages", []):
            count = stage["event_count"]
            rate = "-" if previous in (None, 0) else f"{count / previous * 100:.1f}%"
            lines.append(f"| {stage['label']} | `{stage['event_name']}` | {count:,} | {rate} |")
            previous = count
        lines.append("")
        missing = funnel_data.get("missing_events", [])
        if missing:
            lines.append("未取得の推奨イベント: " + "、".join(f"`{event}`" for event in missing))
            lines.append("")
        return lines
    lines.append("## 7. フォーム通過率")
    lines.append("")
    funnels = funnel_data.get("funnels", []) if funnel_data else []
    excluded = funnel_data.get("excluded", []) if funnel_data else []

    if not funnels:
        lines.append(
            "フォームページが未確認のため算出していない。利用者に、各CVに対応する"
            "フォームページを確認してから再取得する。"
        )
        lines.append("")
        return lines

    lines.append(
        "フォームページの閲覧数（ページビュー）を分母、対応する完了イベントの発生回数を"
        "分子にして通過率を算出する。入力開始イベントの実装有無に依存しないため、"
        "一般的なGA4計測だけで継続比較できる。"
    )
    lines.append("")

    for f in funnels:
        title = calc.format_funnel_title(f["key_event"], event_names)
        if f.get("is_primary"):
            title = f"★{title}"
        if not f.get("confirmed", True):
            title += "（フォームページ未確認）"
        lines.append(f"### {title}")
        lines.append("")

        if not f.get("has_intermediate"):
            lines.append("フォームページが未確認のため、通過率は算出していない。")
            lines.append("")
            continue
        match_label = "完全一致" if f.get("match_type") == "exact" else "部分一致"
        rate = f["completion_rate"]
        rate_text = f"{rate:.2f}%" if rate is not None else "-"
        lines.append("| フォームページ | フォーム閲覧数（PV） | CV数（完了イベント） | フォーム通過率 |")
        lines.append("|---|---:|---:|---:|")
        lines.append(
            f"| `{f['page']}`（{match_label}） | {f['form_page_views']:,} | "
            f"{f['completion_events']:,} | {rate_text} |"
        )
        lines.append("")

    if excluded:
        excluded_str = "、".join(
            f"{calc.format_funnel_title(event, event_names)}（{count:,}件）" for event, count in excluded
        )
        lines.append(
            f"※ 以下のキーイベントはCV数が少なく、フォーム通過率の対象外にした"
            f"（本数の上限は既定5本。件数のみ記録し、黙って打ち切らない）: {excluded_str}"
        )
        lines.append("")

    return lines


def fetch_ecommerce_progress(client, property_id, period: Period) -> dict:
    """GA4推奨eコマースイベントの取得有無を確認し、観測された段階だけを返す。"""
    event_names = [event for _, event in ECOMMERCE_STAGES]
    counts = fetch_key_event_counts(
        client, property_id, period, event_names, label="eコマースイベント確認"
    )
    stages = [
        {"label": label, "event_name": event, "event_count": counts[event]}
        for label, event in ECOMMERCE_STAGES
        if counts.get(event, 0) > 0
    ]
    missing = [event for _, event in ECOMMERCE_STAGES if counts.get(event, 0) == 0]
    return {"journey_type": "ecommerce", "stages": stages, "missing_events": missing}


def to_markdown(
    summary, timeseries, channel, landing_pages, pages, device, new_vs_returning,
    funnel_data, source_medium,
    period: Period, prev_period: Period, key_events: list[str],
    lp_display_limit: int, page_display_limit: int,
    weekly_display_weeks: int = 12,
    event_names: dict[str, str] | None = None,
    primary_kpi_name: str | None = None,
    kpi_breakdown: dict | None = None,
    segments: list | None = None,
    segment_classification: dict | None = None,
    segment_truncated: bool = False,
    trailing_slash_dupes: list[tuple[str, str]] | None = None,
) -> str:
    """基本分析の数値セクションをMarkdownにまとめる。
    CVの経路（旧項目9「CVパス簡易近似」）は、着地ページでしか絞り込めずCVしたセッションに
    絞り込めていなかったため削除済み。BigQuery連携があるクライアントのみ、この関数の外側
    ＝bq_cv_paths.py のページ遷移で見る）

    event_names: 01の kpis.yaml 由来の {event_name: KPI名} 対応表（省略時は空扱い）。
    ヘッダーの「指定キーイベント」表示とフォーム通過率の見出しに使う。未登録のイベントは
    event 名のみで表示するフォールバックのため、渡さなくてもエラーにはならない。

    primary_kpi_name: 01の kpis.yaml で優先度1（`ClientContext.primary_kpi`）と判定された
    KPIの表示名。指定されたKPIは各セクションで先頭に並び、★印で示す（「主KPIを主として
    扱う」の実装）。KPIが1件しか無い、または優先度が未設定（`primary_kpi`がNone）の
    クライアントでは None のまま渡す（順序・印付けを変えない）。

    kpi_breakdown: 複数CV（キーイベントが2件以上でKPI名または生イベント名でグループが
    2件以上に分かれる場合のみ）の内訳データをまとめた辞書。None または該当データが
    無いキーは、そのセクションを従来どおり合算CVのまま出力する（単一CVのクライアントは
    通常このデータ自体を取得しないため、常に従来どおりの1本のCV列になる）。想定するキー:
      - "summary_rows": {"current": [...], "previous": [...]}（0）
      - "timeseries": {granularity: [{dim, eventName, conversions}, ...]}（1）
      - "channel_rows" / "device_rows" / "nvr_rows" / "lp_rows":
        fetch_conversions_by_event() の戻り値

    segments: 01の site-segments.yaml 由来の site_segments リスト。どのセグメントを
    CVR分母とみなすかは02側では決めない（本文はサイト全体のまま、絞り込みはしない）。
    segment_classification が渡された場合のみ、「0. 全体サマリ数値」にセグメント別の
    セッション・CV・CVRの内訳表を追加する（メディアの流入が多いので当たり前なのに
    「新規に弱い」と早合点するのを防ぐため。判断根拠は run.md 参照）。

    segment_classification: analysis_calc.classify_segment_rows() の戻り値。渡された
    場合のみ内訳表を追加する（渡さない・segmentsが空なら従来どおり内訳無し）。
    segment_truncated はその分類に使った取得が上限に達したか（取りこぼしの可能性が
    あるか）を示す。

    trailing_slash_dupes: analysis_calc.detect_trailing_slash_dupes() の戻り値。
    ランディングページ別（3）に末尾スラッシュ違いのペアがあれば、表の下に注記する
    （自動マージはしない。判断根拠は同関数のdocstring参照）。
    """
    kpi_breakdown = kpi_breakdown or {}
    # KPIグループの並び順・表示名はカウントに依存しない（kpi_group_rows は counts_current に
    # 何を渡しても同じ順序・ラベルを返す）ため、見出し用に空カウントで1回だけ確定させ、
    # 各セクションのテーブルの列順を揃える基準にする。
    kpi_template = calc.kpi_group_rows(key_events, {}, None, event_names, primary_kpi_name)
    has_kpi = bool(kpi_template)
    multi_kpi = len(kpi_template) >= 2
    kpi_labels = [calc.kpi_display_label(g) for g in kpi_template]

    lines: list[str] = []
    # 比較期間は直前の同日数とする。
    # 短い期間（目安: 300日未満）では従来どおり「前期」を使う。
    prev_label = "前年同期" if period.days >= 300 else "前期"
    lines.append(f"# GA4 基本分析データ ({period.start} ～ {period.end})")
    lines.append("")
    lines.append(f"{prev_label}比較: {prev_period.start} ～ {prev_period.end}")
    lines.append(f"指定キーイベント: {calc.format_key_events_header(key_events, event_names)}")
    if multi_kpi:
        if primary_kpi_name:
            lines.append(f"優先KPI: ★{primary_kpi_name}（以降、★は本文中でこのKPIを示す）")
        else:
            lines.append("※ 複数のCV（キーイベント）があるが、優先度は未設定（09未登録、または`priority`未設定）。各表でCVを内訳表示するが、優先順位は付けていない。")
    lines.append("")
    if _data_quality_warnings:
        lines.append("データ品質に関する注意:")
        for warning in sorted(_data_quality_warnings):
            lines.append(f"- {warning}")
        lines.append("")

    # 0. 全体サマリ数値
    c, p = summary["current"], summary["previous"]
    lines.append("## 0. 全体サマリ数値（レポート冒頭のサマリ作成に使う）")
    lines.append("")
    current_period_label = _format_report_period(period)
    previous_period_label = _format_report_period(prev_period)
    lines.append(
        f"| 指標 | 当期（{current_period_label}） | "
        f"{prev_label}（{previous_period_label}） | 増減 |"
    )
    lines.append("|---|---:|---:|---:|")
    lines.append(f"| セッション | {c['sessions']:,} | {p['sessions']:,} | {calc.delta_pct(c['sessions'], p['sessions'])} |")
    lines.append(f"| ユーザー | {c['totalUsers']:,} | {p['totalUsers']:,} | {calc.delta_pct(c['totalUsers'], p['totalUsers'])} |")
    lines.append(f"| 新規ユーザー | {c['newUsers']:,} | {p['newUsers']:,} | {calc.delta_pct(c['newUsers'], p['newUsers'])} |")
    summary_rows = kpi_breakdown.get("summary_rows") if has_kpi else None
    if summary_rows:
        current_rows = summary_rows.get("current", [])
        previous_rows = summary_rows.get("previous", [])
        current_counts = {r["eventName"]: r.get("conversions", 0) for r in current_rows}
        previous_counts = {r["eventName"]: r.get("conversions", 0) for r in previous_rows}
        kpi_rows0 = calc.kpi_group_rows(
            key_events, current_counts, previous_counts, event_names, primary_kpi_name,
        )
        for g in kpi_rows0:
            label = calc.kpi_display_label(g)
            cvr_c = g["current"] / c["sessions"] * 100 if c["sessions"] else 0.0
            cvr_p = g["previous"] / p["sessions"] * 100 if p["sessions"] else 0.0
            lines.append(
                f"| CV数: {label} | {g['current']:,} | {g['previous']:,} | "
                f"{calc.delta_pct(g['current'], g['previous'])} |"
            )
            # セッション・CVに続けてCVRも必ずセットで出す（CVだけでは「率として良いのか」が
            # 読めないため。分母は同じ表内のセッション行と揃える）。
            lines.append(
                f"| CVR: {label} | {cvr_c:.2f}% | {cvr_p:.2f}% | "
                f"{calc.delta_pt(g['current'] / c['sessions'] if c['sessions'] else 0.0, g['previous'] / p['sessions'] if p['sessions'] else 0.0)} |"
            )
        lines.append("")
        lines.append(
            "※ CV数は確認済みのCVイベント発生回数。CVRはCV数÷セッション数。"
            "同じセッションで複数回発火する場合は100%を超えることがある。"
        )
    else:
        lines.append("| CV | - | - | CVイベント未指定 |")
    lines.append("")

    # サイトセグメント別内訳（01の site_segments が定義されているクライアントのみ）。
    # 「メディアの流入が多いので当たり前なのに『新規に弱い』と解釈してしまう」ような
    # 早合点を防ぐため、本文0〜8の分母（サイト全体）はそのままに、内訳だけをここで見せる
    # （表をセグメントで分けるとCVごとの列分けと掛け算になり表が倍増するため、内訳は
    # ここ1箇所のみ。他の表(2〜9)はセグメントで分けない。判断根拠は run.md 参照）。
    if segments and segment_classification:
        lines.append("### サイトセグメント別内訳")
        lines.append("")
        lines.append(
            "セグメントは「そのセクションが何であるか」の定義であり、CVを狙っているかの"
            "判断はしていない。上記0〜8はサイト全体を分母にしたまま（絞り込んでいない）。"
        )
        lines.append("")
        lines.extend(calc.segment_breakdown_table_lines(segment_classification))
        lines.append("")
        if segment_truncated:
            lines.append(
                "※ この内訳はランディングページ取得の上限に達しており、ロングテールの"
                "ページが一部集計に反映しきれていない可能性がある。"
            )
            lines.append("")

    # 新規率（newUsers/totalUsers）はここには出さない。取得期間が長くなると
    # ほぼ全ユーザーの初回接触が窓内に入り100%近くに張り付くため、指標として意味を失う。
    # 新規/リピーターの内訳は項目6（セッションベース、newVsReturning）で読めるため重複させない。

    # 1. 月次推移。週次・日次は調査用に取得してもクライアント向け本文へは出さない。
    lines.append("## 1. 月次推移")
    lines.append("")
    lines.append("月次で季節性と中長期の変化を確認する。週次・日次は本文には掲載しない。")
    if period.days < 60 and "monthly" in timeseries:
        lines.append("")
        lines.append(
            f"※ 取得期間が{period.days}日と短いため、月次は端の月が不完全な場合がある"
            "（参考値）。長期の月次比較をしたい場合は取得期間を延ばして再取得する。"
        )
    lines.append("")
    for g in ("monthly",):
        rows = timeseries.get(g)
        if rows is None:
            continue
        dim = GRANULARITY_DIMENSIONS[g]
        lines.append(f"### {GRANULARITY_LABELS[g]}")
        lines.append("")

        display_rows = rows
        incomplete_flags: dict[int, bool] = {}
        if g == "monthly":
            marked = calc.mark_incomplete_months(rows, dim, period.start, period.end)
            display_rows = marked
            incomplete_flags = {i: r["incomplete"] for i, r in enumerate(marked)}
        header = "月"
        ts_by_event = (kpi_breakdown.get("timeseries") or {}).get(g) if has_kpi else None
        lines.append("<!-- chart: combo; title: 月次のセッション・CV数・CVR -->")
        if ts_by_event:
            counts_by_period: dict[str, dict[str, int]] = defaultdict(dict)
            for er in ts_by_event:
                counts_by_period[er[dim]][er["eventName"]] = er.get("conversions", 0)
            lines.append(
                f"| {header} | セッション | ユーザー | "
                + " | ".join(calc.kpi_column_headers(kpi_labels)) + " |"
            )
            lines.append("|---|---:|---:|" + "---:|" * (len(kpi_labels) * 2))
            for i, r in enumerate(display_rows):
                label = _format_period_label(r[dim], g)
                if incomplete_flags.get(i):
                    label += "※"
                kpi_rows_g = calc.kpi_group_rows(
                    key_events, counts_by_period.get(r[dim], {}), None, event_names, primary_kpi_name,
                )
                # CVセッション数だけでなくCVRも列として並べる（セッション・CV・CVRをセットで出す。
                # 他の表(2〜6)は既にKPIごとにCV:X/CVR:Xの列を持っており、ここだけ揃っていなかった）。
                kpi_cells = " | ".join(calc.kpi_column_cells(kpi_rows_g, r["sessions"]))
                lines.append(
                    f"| {label} | {r['sessions']:,} | {r['totalUsers']:,} | {kpi_cells} |"
                )
            total_sessions = sum(r["sessions"] for r in display_rows)
            total_counts: dict[str, int] = defaultdict(int)
            displayed_periods = {r[dim] for r in display_rows}
            for er in ts_by_event:
                if er[dim] in displayed_periods:
                    total_counts[er["eventName"]] += er.get("conversions", 0)
            total_kpis = calc.kpi_group_rows(
                key_events, total_counts, None, event_names, primary_kpi_name,
            )
            total_cells = " | ".join(calc.kpi_column_cells(total_kpis, total_sessions))
            lines.append(f"| **合計** | **{total_sessions:,}** | - | {total_cells} |")
        else:
            lines.append(f"| {header} | セッション | ユーザー | CV数 | CVR |")
            lines.append("|---|---:|---:|---:|---:|")
            for i, r in enumerate(display_rows):
                label = _format_period_label(r[dim], g)
                if incomplete_flags.get(i):
                    label += "※"
                cvr = r["conversions"] / r["sessions"] * 100 if r["sessions"] else 0.0
                lines.append(
                    f"| {label} | {r['sessions']:,} | {r['totalUsers']:,} | {r['conversions']:,.0f} | {cvr:.2f}% |"
                )
            total_sessions = sum(r["sessions"] for r in display_rows)
            total_cv = sum(r["conversions"] for r in display_rows)
            total_cvr = total_cv / total_sessions * 100 if total_sessions else 0.0
            lines.append(f"| **合計** | **{total_sessions:,}** | - | **{total_cv:,.0f}** | **{total_cvr:.2f}%** |")
        if g == "monthly" and any(incomplete_flags.values()):
            lines.append("")
            lines.append("※ 対象期間の端にあたるため、その月の一部のみを集計")
        lines.append("")

    # 2. チャネル別（前期比つき）
    lines.append(f"## 2. チャネル別パフォーマンス（{prev_label}比つき）")
    lines.append("")
    # 月次・週次が取得できない場合でも、HTMLに独立したグラフが最低1つ残るよう
    # チャネルは棒グラフにする。元表はreport_exportがそのまま直下へ残す。
    lines.append("<!-- chart: bar; title: チャネル別セッション比較 -->")
    channel_rows = kpi_breakdown.get("channel_rows") if has_kpi else None
    if channel_rows is not None:
        channel_with_kpi = calc.attach_kpi_breakdown(
            channel, "sessionDefaultChannelGroup", channel_rows, key_events, event_names, primary_kpi_name
        )
        previous_base = [
            {"sessionDefaultChannelGroup": r["sessionDefaultChannelGroup"], "sessions": r["prev_sessions"]}
            for r in channel
        ]
        previous_with_kpi = calc.attach_kpi_breakdown(
            previous_base, "sessionDefaultChannelGroup",
            kpi_breakdown.get("channel_previous_rows") or [], key_events, event_names, primary_kpi_name,
        )
        previous_by_channel = {
            r["sessionDefaultChannelGroup"]: r for r in previous_with_kpi
        }
        current_headers = [f"当期 {h}" for h in calc.kpi_column_headers(kpi_labels)]
        previous_headers = [f"{prev_label} {h}" for h in calc.kpi_column_headers(kpi_labels)]
        lines.append(
            f"| チャネル | 当期セッション | {prev_label}セッション | シェア | 増減率 | "
            + " | ".join(current_headers + previous_headers) + " |"
        )
        lines.append("|---|---:|---:|---:|---:|" + "---:|" * (len(kpi_labels) * 4))
        total_sessions = c["sessions"]
        for r in channel_with_kpi:
            share = r["sessions"] / total_sessions * 100 if total_sessions else 0
            prev_row = previous_by_channel.get(r["sessionDefaultChannelGroup"], {})
            kpi_cells = " | ".join(
                calc.kpi_column_cells(r["kpi_breakdown"], r["sessions"])
                + calc.kpi_column_cells(prev_row.get("kpi_breakdown", []), r["prev_sessions"])
            )
            lines.append(
                f"| {r['sessionDefaultChannelGroup']} | {r['sessions']:,} | {r['prev_sessions']:,} | {share:.1f}% "
                f"| {calc.delta_pct(r['sessions'], r['prev_sessions'])} | {kpi_cells} |"
            )
        summary_current = {
            r["eventName"]: r.get("conversions", 0)
            for r in (kpi_breakdown.get("summary_rows") or {}).get("current", [])
        }
        summary_previous = {
            r["eventName"]: r.get("conversions", 0)
            for r in (kpi_breakdown.get("summary_rows") or {}).get("previous", [])
        }
        total_kpis = calc.kpi_group_rows(
            key_events, summary_current, None, event_names, primary_kpi_name,
        )
        previous_total_kpis = calc.kpi_group_rows(
            key_events, summary_previous, None, event_names, primary_kpi_name,
        )
        total_cells = " | ".join(
            calc.kpi_column_cells(total_kpis, c["sessions"])
            + calc.kpi_column_cells(previous_total_kpis, p["sessions"])
        )
        lines.append(
            f"| **合計** | **{c['sessions']:,}** | **{p['sessions']:,}** | **100.0%** | "
            f"**{calc.delta_pct(c['sessions'], p['sessions'])}** | {total_cells} |"
        )
    else:
        lines.append(f"| チャネル | 当期セッション | {prev_label}セッション | シェア | 増減率 | 当期CV数 | 当期CVR | {prev_label}CV数 | {prev_label}CVR |")
        lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
        total_sessions = c["sessions"]
        for r in channel:
            share = r["sessions"] / total_sessions * 100 if total_sessions else 0
            cvr = r["conversions"] / r["sessions"] * 100 if r["sessions"] else 0.0
            prev_cvr = r.get("prev_conversions", 0) / r["prev_sessions"] * 100 if r["prev_sessions"] else 0.0
            lines.append(
                f"| {r['sessionDefaultChannelGroup']} | {r['sessions']:,} | {r['prev_sessions']:,} | {share:.1f}% "
                f"| {calc.delta_pct(r['sessions'], r['prev_sessions'])} | {r['conversions']:,.0f} | {cvr:.2f}% "
                f"| {r.get('prev_conversions', 0):,.0f} | {prev_cvr:.2f}% |"
            )
        total_cv = sum(r["conversions"] for r in channel)
        previous_total_cv = sum(r.get("prev_conversions", 0) for r in channel)
        total_cvr = total_cv / c["sessions"] * 100 if c["sessions"] else 0.0
        previous_total_cvr = previous_total_cv / p["sessions"] * 100 if p["sessions"] else 0.0
        lines.append(
            f"| **合計** | **{c['sessions']:,}** | **{p['sessions']:,}** | **100.0%** | "
            f"**{calc.delta_pct(c['sessions'], p['sessions'])}** | **{total_cv:,.0f}** | **{total_cvr:.2f}%** "
            f"| **{previous_total_cv:,.0f}** | **{previous_total_cvr:.2f}%** |"
        )
    lines.append("")

    # 3. ランディングページ別: 入口の量（セッション順）と成果（CV順）を分けて見る。
    # (not set) 等は fetch_landing_pages() で除外済み。
    lines.append("## 3. ランディングページ別（入口として機能しているページ）")
    lines.append("")
    lp_rows = kpi_breakdown.get("lp_rows") if has_kpi else None
    if lp_rows is not None:
        lp_all_with_kpi = calc.attach_kpi_breakdown(
            landing_pages, "landingPagePlusQueryString", lp_rows, key_events, event_names, primary_kpi_name
        )
        lp_by_sessions = lp_all_with_kpi[:lp_display_limit]
        has_primary = bool(kpi_template) and kpi_template[0]["is_primary"]
        def _lp_cv_count(row):
            parts = row["kpi_breakdown"]
            return parts[0]["current"] if has_primary else sum(v["current"] for v in parts)
        lp_by_cv = sorted(lp_all_with_kpi, key=_lp_cv_count, reverse=True)[:lp_display_limit]

        for subtitle, display_rows in (
            (f"セッション上位{len(lp_by_sessions)}件", lp_by_sessions),
            (f"CV数上位{len(lp_by_cv)}件", lp_by_cv),
        ):
            lines.append(f"### {subtitle}")
            lines.append("")
            lines.append("<!-- chart: table-bars; title: ランディングページのセッション・CV数・CVR比較 -->")
            lines.append(
                "| ランディングページ | セッション | "
                + " | ".join(calc.kpi_column_headers(kpi_labels)) + " |"
            )
            lines.append("|---|---:|" + "---:|" * (len(kpi_labels) * 2))
            for r in display_rows:
                kpi_cells = " | ".join(calc.kpi_column_cells(r["kpi_breakdown"], r["sessions"]))
                lines.append(f"| {r['landingPagePlusQueryString']} | {r['sessions']:,} | {kpi_cells} |")
            subtotal_sessions = sum(r["sessions"] for r in display_rows)
            subtotal_counts = [
                sum(r["kpi_breakdown"][i]["current"] for r in display_rows)
                for i in range(len(kpi_labels))
            ]
            subtotal_parts = []
            for count in subtotal_counts:
                subtotal_parts.extend([
                    f"**{count:,}**",
                    f"**{(count / subtotal_sessions * 100 if subtotal_sessions else 0):.2f}%**",
                ])
            lines.append(
                f"| **表示合計** | **{subtotal_sessions:,}** | "
                + " | ".join(subtotal_parts) + " |"
            )
            lines.append("")
    else:
        for subtitle, display_rows in (
            ("セッション上位", landing_pages[:lp_display_limit]),
            ("CV数上位", sorted(landing_pages, key=lambda r: r["conversions"], reverse=True)[:lp_display_limit]),
        ):
            lines.append(f"### {subtitle}{len(display_rows)}件")
            lines.append("")
            lines.append("<!-- chart: table-bars; title: ランディングページのセッション・CV数・CVR比較 -->")
            lines.append("| ランディングページ | セッション | CV数 | CVR |")
            lines.append("|---|---:|---:|---:|")
            for r in display_rows:
                cvr = r["conversions"] / r["sessions"] * 100 if r["sessions"] else 0.0
                lines.append(f"| {r['landingPagePlusQueryString']} | {r['sessions']:,} | {r['conversions']:,.0f} | {cvr:.2f}% |")
            subtotal_sessions = sum(r["sessions"] for r in display_rows)
            subtotal_cv = sum(r["conversions"] for r in display_rows)
            subtotal_cvr = subtotal_cv / subtotal_sessions * 100 if subtotal_sessions else 0.0
            lines.append(f"| **表示合計** | **{subtotal_sessions:,}** | **{subtotal_cv:,.0f}** | **{subtotal_cvr:.2f}%** |")
            lines.append("")
    if trailing_slash_dupes:
        lines.append("")
        pairs_str = "、".join(f"`{a}` と `{b}`" for a, b in trailing_slash_dupes)
        lines.append(
            f"※ 末尾スラッシュ違いで別行になっているパスがある: {pairs_str}。"
            "サーバー側のリダイレクト設定次第で別ページを指すこともあるため自動では"
            "統合していない（同一ページなら合算して読む）。"
        )
    lines.append("")

    # 4. ページ別: 閲覧開始数・閲覧開始率は入口分析と重複するため出さない。
    page_display = pages[:page_display_limit]
    lines.append(f"## 4. ページ別（PV上位{len(page_display)}件）")
    lines.append("")
    lines.append("| ページ | PV |")
    lines.append("|---|---:|")
    for r in page_display:
        lines.append(f"| {r['pagePathPlusQueryString']} | {r['screenPageViews']:,} |")
    lines.append(f"| **表示合計** | **{sum(r['screenPageViews'] for r in page_display):,}** |")
    lines.append("")

    # 5. デバイス別
    # シェアの分母は全体セッション（切り口なしのクエリ、c['sessions']）に固定する。
    # 実データで、mobile/desktop/tabletの3カテゴリの合計が全体セッションと4,009件（1.2%）
    # ずれた（GA4がこの3カテゴリに分類できないセッションを除外するため）。内訳の合計を
    # 分母にするとシェアが実態より高く出てしまうので、全体を分母に固定した上で、
    # ズレがあれば「(不明・分類外)」の行として明示する（読み手が分母の違いに気づける形にする）。
    overall_sessions = c["sessions"]
    lines.append("## 5. デバイス別（mobile / desktop / tablet）")
    lines.append("")
    lines.append(
        "シェアの分母は全体セッション（切り口なしの値）。mobile/desktop/tabletの3カテゴリに"
        "分類できないセッションがある場合は「(不明・分類外)」の行で差分を明示する。"
    )
    lines.append("")
    device_rows = kpi_breakdown.get("device_rows") if has_kpi else None
    if device_rows is not None:
        device_with_kpi = calc.attach_kpi_breakdown(
            device, "deviceCategory", device_rows, key_events, event_names, primary_kpi_name
        )
        lines.append(
            "| デバイス | セッション | シェア | " + " | ".join(calc.kpi_column_headers(kpi_labels)) + " |"
        )
        lines.append("|---|---:|---:|" + "---:|" * (len(kpi_labels) * 2))
        for r in device_with_kpi:
            share = r["sessions"] / overall_sessions * 100 if overall_sessions else 0
            kpi_cells = " | ".join(calc.kpi_column_cells(r["kpi_breakdown"], r["sessions"]))
            lines.append(
                f"| {r['deviceCategory']} | {r['sessions']:,} | {share:.1f}% | {kpi_cells} |"
            )
        device_diff = calc.unclassified_diff(overall_sessions, device)
        if device_diff:
            diff_share = device_diff / overall_sessions * 100 if overall_sessions else 0
            dashes = " | ".join(["-"] * (len(kpi_labels) * 2))
            lines.append(f"| (不明・分類外) | {device_diff:,} | {diff_share:.1f}% | {dashes} |")
        summary_current = {
            r["eventName"]: r.get("conversions", 0)
            for r in (kpi_breakdown.get("summary_rows") or {}).get("current", [])
        }
        total_kpis = calc.kpi_group_rows(key_events, summary_current, None, event_names, primary_kpi_name)
        total_cells = " | ".join(calc.kpi_column_cells(total_kpis, overall_sessions))
        lines.append(f"| **合計** | **{overall_sessions:,}** | **100.0%** | {total_cells} |")
    else:
        lines.append("| デバイス | セッション | シェア | CV数 | CVR |")
        lines.append("|---|---:|---:|---:|---:|")
        for r in device:
            share = r["sessions"] / overall_sessions * 100 if overall_sessions else 0
            cvr = r["conversions"] / r["sessions"] * 100 if r["sessions"] else 0.0
            lines.append(f"| {r['deviceCategory']} | {r['sessions']:,} | {share:.1f}% | {r['conversions']:,.0f} | {cvr:.2f}% |")
        device_diff = calc.unclassified_diff(overall_sessions, device)
        if device_diff:
            diff_share = device_diff / overall_sessions * 100 if overall_sessions else 0
            lines.append(f"| (不明・分類外) | {device_diff:,} | {diff_share:.1f}% | - | - |")
        total_cv = sum(r["conversions"] for r in device)
        total_cvr = total_cv / overall_sessions * 100 if overall_sessions else 0.0
        lines.append(f"| **合計** | **{overall_sessions:,}** | **100.0%** | **{total_cv:,.0f}** | **{total_cvr:.2f}%** |")
    lines.append("")

    # 6. 新規/リピーター別（分母の考え方は5と同じ。newVsReturningにもGA4が分類しない
    # セッションが存在し、実データで+98件のズレがあった）
    lines.append("## 6. 新規/リピーター別")
    lines.append("")
    lines.append(
        "シェアの分母は全体セッション（切り口なしの値）。new/returningに分類できない"
        "セッションがある場合は「(不明・分類外)」の行で差分を明示する。"
    )
    lines.append("")
    nvr_rows = kpi_breakdown.get("nvr_rows") if has_kpi else None
    if nvr_rows is not None:
        nvr_with_kpi = calc.attach_kpi_breakdown(
            new_vs_returning, "newVsReturning", nvr_rows, key_events, event_names, primary_kpi_name
        )
        lines.append(
            "| ユーザー種別 | セッション | シェア | " + " | ".join(calc.kpi_column_headers(kpi_labels)) + " |"
        )
        lines.append("|---|---:|---:|" + "---:|" * (len(kpi_labels) * 2))
        for r in nvr_with_kpi:
            share = r["sessions"] / overall_sessions * 100 if overall_sessions else 0
            kpi_cells = " | ".join(calc.kpi_column_cells(r["kpi_breakdown"], r["sessions"]))
            lines.append(
                f"| {r['newVsReturning']} | {r['sessions']:,} | {share:.1f}% | {kpi_cells} |"
            )
        nvr_diff = calc.unclassified_diff(overall_sessions, new_vs_returning)
        if nvr_diff:
            diff_share = nvr_diff / overall_sessions * 100 if overall_sessions else 0
            dashes = " | ".join(["-"] * (len(kpi_labels) * 2))
            lines.append(f"| (不明・分類外) | {nvr_diff:,} | {diff_share:.1f}% | {dashes} |")
        summary_current = {
            r["eventName"]: r.get("conversions", 0)
            for r in (kpi_breakdown.get("summary_rows") or {}).get("current", [])
        }
        total_kpis = calc.kpi_group_rows(key_events, summary_current, None, event_names, primary_kpi_name)
        total_cells = " | ".join(calc.kpi_column_cells(total_kpis, overall_sessions))
        lines.append(f"| **合計** | **{overall_sessions:,}** | **100.0%** | {total_cells} |")
    else:
        lines.append("| ユーザー種別 | セッション | シェア | CV数 | CVR |")
        lines.append("|---|---:|---:|---:|---:|")
        for r in new_vs_returning:
            share = r["sessions"] / overall_sessions * 100 if overall_sessions else 0
            cvr = r["conversions"] / r["sessions"] * 100 if r["sessions"] else 0.0
            lines.append(f"| {r['newVsReturning']} | {r['sessions']:,} | {share:.1f}% | {r['conversions']:,.0f} | {cvr:.2f}% |")
        nvr_diff = calc.unclassified_diff(overall_sessions, new_vs_returning)
        if nvr_diff:
            diff_share = nvr_diff / overall_sessions * 100 if overall_sessions else 0
            lines.append(f"| (不明・分類外) | {nvr_diff:,} | {diff_share:.1f}% | - | - |")
        total_cv = sum(r["conversions"] for r in new_vs_returning)
        total_cvr = total_cv / overall_sessions * 100 if overall_sessions else 0.0
        lines.append(f"| **合計** | **{overall_sessions:,}** | **100.0%** | **{total_cv:,.0f}** | **{total_cvr:.2f}%** |")
    # デバイス別と違い、new/returningは内訳合計が全体セッションを「上回る」ことがある
    # （実データで339,234 vs 338,815の419件超過、他の期間でも419〜472件の超過を確認）。
    # 原因はクライアントへの確認により確定済み（GA4の仕様、不具合ではない）: 新規ユーザーが
    # 対象期間内に再度訪問すると、そのユーザーの一連の訪問が新規（newVsReturning=new）にも
    # リピーター（newVsReturning=returning）にも計上される。newVsReturningはユーザーの
    # 状態を都度判定するイベント単位の値のため、1人のユーザーが期間内に複数回カウントされる
    # 形でこの超過が生まれる。全体セッション数（分母。切り口なしの実測値）には影響しないため、
    # 負の行は作らず注記のみで説明する。原因調査はこれ以上不要（追加調査対象ではない）。
    nvr_subtotal = sum(r.get("sessions", 0) for r in new_vs_returning)
    nvr_excess = nvr_subtotal - overall_sessions
    if nvr_excess > 0:
        excess_share = nvr_excess / overall_sessions * 100 if overall_sessions else 0
        lines.append(
            f"※ 内訳合計（{nvr_subtotal:,}）が全体セッション（{overall_sessions:,}）を"
            f"{nvr_excess:,}件（{excess_share:.1f}%）上回っている。原因はGA4の仕様として確定"
            "している（不具合ではない）: 新規ユーザーが対象期間内にもう一度訪問すると、"
            "そのユーザーの訪問が新規（new）にもリピーター（returning）にも計上される。"
            "全体セッション数（分母）には影響しない。"
        )
    lines.append("")

    # 7. フォーム通過率 / ECサイト購入プロセス
    lines.extend(funnel_markdown_lines(funnel_data, event_names))

    # 旧「CVはどこから来たか」は、項目3のランディングページCV順と内容が重複し、
    # 読み手の判断を増やさなかったため廃止。流入チャネル比較は項目2、入口ページは項目3、
    # フォームの歩留まりは項目7、BigQueryがある場合の実遷移は別取得に役割を分ける。
    return "\n".join(lines) + "\n"


def _parse_funnel_events(spec: str) -> dict[str, dict]:
    """--funnel-events の "event:page:match_type:status" 形式（; 区切りで複数）をパースする。

    event のみ必須。page/match_type/status は省略可（空欄扱い）:
    - page省略時: フォームページ未確定として扱い、通過率は算出しない
    - match_type省略時: "contains"（部分一致、既定）
    - status省略時: "confirmed"（既定。無人実行等で候補の1位を仮採用した場合のみ
      "unconfirmed" を指定し、Markdown側で「フォームページ未確認」と明記する）
    """
    result: dict[str, dict] = {}
    if not spec:
        return result
    for entry in spec.split(";"):
        entry = entry.strip()
        if not entry:
            continue
        parts = entry.split(":")
        event = parts[0].strip()
        if not event:
            continue
        page = parts[1].strip() if len(parts) > 1 and parts[1].strip() else None
        match_type = parts[2].strip() if len(parts) > 2 and parts[2].strip() else "contains"
        status = parts[3].strip() if len(parts) > 3 and parts[3].strip() else "confirmed"
        if match_type not in ("contains", "exact"):
            raise ValueError(f"不正な match_type: {match_type!r}（contains/exact のいずれか）")
        if status not in ("confirmed", "unconfirmed"):
            raise ValueError(f"不正な status: {status!r}（confirmed/unconfirmed のいずれか）")
        result[event] = {"page": page, "match_type": match_type, "confirmed": status == "confirmed"}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--property-id", required=True)
    parser.add_argument(
        "--days", type=int,
        help="互換用の取得日数。省略時は直近の完了した12か月。開始日・終了日の指定を優先する",
    )
    parser.add_argument("--start-date", type=date.fromisoformat, help="取得開始日（YYYY-MM-DD）")
    parser.add_argument("--end-date", type=date.fromisoformat, help="取得終了日（YYYY-MM-DD）")
    parser.add_argument(
        "--key-events",
        default="",
        help="カンマ区切りのキーイベント名（例: form_submit,file_download）",
    )
    parser.add_argument(
        "--event-names-json",
        default="",
        help="01の kpis.yaml 由来の {event_name: KPI名} をJSON文字列で渡す（例: "
        '\'{"form_submit": "お問い合わせ完了数"}\'）。レポート冒頭の「指定キーイベント」表示と'
        "フォーム通過率の見出しに使い、対応する名前が見つかったイベントだけ"
        "「KPI名（event名）」の形式で表示する。省略時・空文字・不正なJSONは無視され、"
        "全イベントが従来どおりevent名のみで表示される（09未登録のクライアントでもエラーにしない）",
    )
    parser.add_argument(
        "--primary-kpi-name",
        default="",
        help="01の kpis.yaml で優先度1（`ClientContext.primary_kpi`）と判定されたKPIの表示名。"
        "複数のCV（キーイベント）を業務名またはイベント名で2グループ以上に分けられる場合、"
        "各セクションでこのKPIを先頭に並べ★印を付ける。フォーム通過率も完了イベント数の"
        "順位に関わらずこのKPIを先頭に並べる。省略時・空文字（優先度が"
        "未設定、またはKPIが1件のみ）は全KPIを対等に扱い、`--key-events` の指定順のまま表示する"
        "（優先順位を付けない）。KPIが1件のみ、またはグループが1つしかできない場合はこの引数を"
        "渡してもCVは合算表示のままになる（分ける対象が無いため）。ただし単一CVで"
        "`--event-names-json` に業務名が無い場合は、この値を表・見出しの表示名に使う",
    )
    parser.add_argument(
        "--granularity",
        default="monthly",
        help="時系列トレンドの粒度をカンマ区切りで指定（daily/weekly/monthly、既定は月次のみ。"
        "日次は行数が増え、変化点の確認時だけ必要なため既定から外している。"
        "変化点を日次で追いたい場合のみ daily を明示指定する",
    )
    parser.add_argument(
        "--weekly-weeks", type=int, default=12,
        help="週次推移の表示件数（既定12週。取得自体は期間全体に対して行い、表示のみ直近N週に絞る）",
    )
    parser.add_argument(
        "--funnel-events",
        default="",
        help="フォーム通過率（キーイベント1件=フォームページ1件）を \"event:page:match_type:status\" の"
        "形式で ; 区切りで指定する。page省略時は通過率を算出しない。match_typeはcontains/exact。"
        "statusはconfirmed/unconfirmed。"
        "例: \"contact_service_thanks:/contact/service/:contains:confirmed;"
        "download_thanks:/download/:contains:confirmed\"",
    )
    parser.add_argument(
        "--journey-type", choices=("lead", "ecommerce"), default="lead",
        help="成果到達の分析形式。lead はフォームページPVと完了イベントから通過率を算出し、"
        "ecommerce はGA4推奨eコマースイベントを確認して購入プロセスを表示する（既定lead）",
    )
    parser.add_argument(
        "--funnel-max", type=int, default=5,
        help="フォーム通過率を作る本数の上限（既定5）。完了イベント数が多い順に採用する",
    )
    parser.add_argument(
        "--candidates-for",
        default="",
        help="指定したキーイベント（カンマ区切り）が発火したセッションでよく見られているページを、"
        "セッション数の多い順に候補として出力する（フォームページ確認用。実際にサイトを"
        "読みに行って何のフォームかを判定する前段）。指定時はこの候補一覧だけを出力し、"
        "他のセクションは取得しない",
    )
    parser.add_argument(
        "--candidates-limit", type=int, default=10,
        help="フォームページ候補の表示件数（既定10、キーイベントごと）",
    )
    parser.add_argument("--lp-limit", type=int, default=10, help="ランディングページ別の表示件数（既定10）")
    parser.add_argument("--page-limit", type=int, default=10, help="ページ別の表示件数（既定10）")
    parser.add_argument(
        "--funnel-only", action="store_true",
        help="フォーム通過率だけを取得する。利用者がフォームページを確認した後の追い取得用",
    )
    parser.add_argument(
        "--hostnames", action="store_true",
        help="ホスト名別セッション数だけを取得して出力する（自己参照・想定外ドメインの棚卸し用。"
        "パラメータ監査で使う。内訳合計と全体セッションの差を自動で注記する）。"
        "指定時は他のセクションは取得しない",
    )
    parser.add_argument(
        "--hostnames-limit", type=int, default=50,
        help="ホスト名別の表示件数上限（既定50）",
    )
    parser.add_argument(
        "--site-segments-json",
        default="",
        help="01の site-segments.yaml 由来の site_segments リストをJSON文字列で渡す"
        "（例: '[{\"segment_id\": \"seg_001\", \"name\": \"本体サイト\", \"default\": true}, "
        "{\"segment_id\": \"seg_002\", \"name\": \"オウンドメディア\", "
        "\"match\": {\"path_prefix\": \"/media/\"}}]'）。指定時も基本分析の分母は"
        "サイト全体のまま変えず（どのセグメントをCVR分母とみなすかは絞り込まない）、"
        "「0. 全体サマリ数値」にセグメント別のセッション・CV・CVRの内訳表を追加する。"
        "どの match にも一致しないページは、`default: true` のセグメントがあればそこに、"
        "無ければ「その他（分類外）」に入る。省略時・空文字・不正なJSONはこの内訳を出さず"
        "サイト全体のまま進む（エラーにはしない）",
    )
    parser.add_argument(
        "--include-query-params",
        action="store_true",
        help="ランディングページ別・ページ別・フォームページ候補で"
        "クエリ文字列を含めるかどうか（既定はパスのみ=このフラグを付けない）。実データで"
        "`/?renew=` のようなクエリ付き別名が別ページとして計上されたり、完了ページのクエリ違い"
        "（`?submissionGuid=...`）で中間ページ候補が埋まったりする不具合があったため、既定で"
        "クエリを落とす。ECサイト・ブログのようにクエリ文字列そのものが別ページを表す"
        "サイトだけ、このフラグを明示指定する（01の ClientContext.include_query_params と"
        "同じ既定値）",
    )
    parser.add_argument("--output", default="-")
    args = parser.parse_args()

    granularities = [g.strip() for g in args.granularity.split(",") if g.strip()]
    invalid = [g for g in granularities if g not in GRANULARITY_DIMENSIONS]
    if invalid:
        parser.error(
            f"不正な --granularity 値: {invalid}（使用可能: {list(GRANULARITY_DIMENSIONS)}）"
        )

    creds = get_credentials()
    client = BetaAnalyticsDataClient(credentials=creds)
    _reset_progress()

    try:
        resolved, resolved_previous = resolve_analysis_periods(
            today=date.today(), days=args.days,
            start_date=args.start_date, end_date=args.end_date,
        )
    except ValueError as exc:
        parser.error(str(exc))
    period = Period(resolved.start, resolved.end)
    prev_period = Period(resolved_previous.start, resolved_previous.end)

    key_events = [e.strip() for e in args.key_events.split(",") if e.strip()]
    event_names = calc.parse_event_names_json(args.event_names_json)
    funnel_events = _parse_funnel_events(args.funnel_events)
    candidate_events = [e.strip() for e in args.candidates_for.split(",") if e.strip()]

    # サイトセグメント（そのセクションが何であるか、の定義）。未設定・不正なJSONでも
    # 空リストにしてサイト全体で進める。GA4クエリ自体は絞り込まず（どのセグメントを
    # CVR分母とみなすかは02側では決めない）、サマリーにセグメント別内訳を追加するだけに使う
    # （判断根拠は run.md 参照）。
    site_segments = calc.parse_site_segments_json(args.site_segments_json)
    include_query_params = args.include_query_params
    landing_dim_name = calc.landing_page_dimension(include_query_params)

    # 複数CV（キーイベント）の内訳表示: KPI名/イベント名で2グループ以上に分かれる場合のみ
    # 有効にする（単一CVのクライアントには影響を与えず、追加のGA4リクエストも発生させない）。
    primary_kpi_name = args.primary_kpi_name.strip() or None
    event_names = calc.apply_primary_name_fallback(key_events, event_names, primary_kpi_name)
    kpi_groups = calc.kpi_labels_and_events(key_events, event_names)
    multi_kpi = len(kpi_groups) >= 2
    ambiguous_groups = [label for label, events in kpi_groups if len(events) > 1]
    if ambiguous_groups:
        parser.error(
            "1つのKPIに複数イベントが割り当てられています。セッションの重複を避けるため、"
            "CV完了を表すイベントをKPIごとに1つ選び直してください: "
            + ", ".join(ambiguous_groups)
        )
    # 主KPIに属するイベント名の集合（フォーム通過率の上限で主KPIを守るために使う）。
    # primary_kpi_name がどのグループの表示名とも一致しなければ None のまま（黙って先頭グループを
    # 代用しない＝09で優先度が未設定の場合と同じ扱いにする）。
    primary_events = None
    if primary_kpi_name:
        matched = [events for label, events in kpi_groups if label == primary_kpi_name]
        if matched:
            primary_events = set(matched[0])

    if candidate_events:
        # 候補が全てキーイベント自身の発火ページ（サンクスページ等）だった場合の推定に使う
        # ランディングページ一覧を先に1回だけ取得する（GA4への新規クエリを増やさず、
        # 既存の fetch_landing_pages() を使い回す。詳しくは
        # standards/ga4-event-scoped-dimensions.md）。
        landing_pages_for_guess = fetch_landing_pages(
            client, args.property_id, period, include_query_params=include_query_params,
        )
        lines = ["# フォームページ候補", ""]
        lines.append(
            "キーイベントが発火したセッションでよく見られているページを、セッション数の多い順に"
            "列挙する。上位ページを実際にサイトで確認し、何のフォーム・ページかを判定してから、"
            "`--funnel-events` でフォームページとして対にする。"
        )
        lines.append("")
        lines.append(
            "※ 「セッション」列は、そのページを見て、かつ同じセッション内でこのキーイベントも"
            "発火したセッションの数（=候補ページとキーイベントの共起セッション数）。このレポート"
            "内の他の箇所に出てくる「キーイベントの発生件数（イベント発生回数）」とは数えている"
            "対象が異なるため、両者は一致しない（1セッション内でイベントが複数回発火しても"
            "セッションとしては1件、同じページを何度見てもセッションとしては1件に数える）。"
            "一致しないこと自体は不具合ではない。"
        )
        lines.append("")
        for event in candidate_events:
            rows = fetch_page_candidates_for_event(
                client, args.property_id, period, event, limit=args.candidates_limit,
                landing_pages=landing_pages_for_guess, include_query_params=include_query_params,
            )
            lines.append(f"## {event}")
            lines.append("")
            if not rows:
                lines.append("※ このキーイベントが発火したセッションでのページ閲覧データが見つからなかった。")
                lines.append("")
                continue
            lines.append("| ページ（候補） | セッション（このキーイベントが発火したセッションでの閲覧） | 判定 |")
            lines.append("|---|---:|---|")
            for r in rows:
                if r.get("estimated_from_parent"):
                    note = "推定（完了ページの親パスから推定。ランディングページ一覧との照合。要目視確認）"
                elif r.get("excluded_self"):
                    note = "除外候補（このキーイベント自身の発火ページ＝サンクスページ等と推定）"
                else:
                    note = ""
                lines.append(f"| {r['pagePathPlusQueryString']} | {r['sessions']:,} | {note} |")
            if rows and all(r.get("excluded_self") for r in rows):
                lines.append("")
                lines.append(
                    "※ 候補が全てこのキーイベント自身の発火ページ（サンクスページ等）と推定され、"
                    "入力前のフォームページが見つからなかった。このキーイベントはサンクスページの "
                    "page_view として発火する設計の可能性が高く、この集計方法では入力前ページを"
                    "検出できない。親パスをランディングページ一覧と照合したが該当も無かった。"
                    "ランディングページと実サイトを参照し、利用者にフォームページを確認すること。"
                )
            lines.append("")
        md = "\n".join(lines)
        _progress_summary()
        if args.output == "-":
            print(md)
        else:
            path = Path(args.output)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(md, encoding="utf-8")
            print(f"Written {len(md):,} bytes to {path}")
        return

    if args.funnel_only:
        funnel_data = (
            fetch_ecommerce_progress(client, args.property_id, period)
            if args.journey_type == "ecommerce"
            else fetch_cv_funnels(
                client, args.property_id, period, key_events, funnel_events,
                max_funnels=args.funnel_max, primary_events=primary_events,
            )
        )
        md = "\n".join(funnel_markdown_lines(funnel_data, event_names))
        _progress_summary()
        if args.output == "-":
            print(md)
        else:
            path = Path(args.output)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(md, encoding="utf-8")
            print(f"Written {len(md):,} bytes to {path}")
        return

    if args.hostnames:
        hostname_rows = fetch_by_hostname(
            client, args.property_id, period, limit=args.hostnames_limit, key_events=key_events,
        )
        base = _run_report(
            client, args.property_id, [], ["sessions"], period, limit=1,
            label="ホスト名別: 全体セッション",
        )
        overall_sessions = int(base.rows[0].metric_values[0].value) if base.rows else 0
        md = "\n".join(hostname_markdown_lines(
            hostname_rows, overall_sessions, has_selected_cv=bool(key_events),
        ))
        _progress_summary()
        if args.output == "-":
            print(md)
        else:
            path = Path(args.output)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(md, encoding="utf-8")
            print(f"Written {len(md):,} bytes to {path}")
        return

    if not key_events:
        parser.error(
            "基本分析には --key-events が必要です。ユーザーにCVの業務上の意味と、"
            "その完了を表すGA4イベント名を確認してから再実行してください。"
        )

    # 本文を作り始める前に、確認済みCVが対象期間に実在するかを1回で検証する。
    # 0件のまま全キーイベントの合計を代用してレポートを進めない。
    validated_current_summary_rows = fetch_conversions_by_event(
        client, args.property_id, period, [], key_events, label="CV内訳: 事前検査（当期）",
    )
    zero_events = zero_count_key_events(key_events, validated_current_summary_rows)
    if zero_events:
        parser.error(
            "指定したCVイベントが取得期間内に0件です: " + ", ".join(zero_events)
            + "。CV定義または取得期間を確認してから再実行してください。"
        )

    # 基本分析はサイト全体のまま取得する（01の site_segments が定義されていても、
    # どのセグメントをCVR分母とみなすかは02側では絞り込まない。判断根拠は run.md 参照）。
    summary = fetch_summary(client, args.property_id, period, prev_period)
    timeseries = fetch_timeseries(client, args.property_id, period, granularities)
    channel = fetch_by_channel(client, args.property_id, period, prev_period)
    landing_pages = fetch_landing_pages(
        client, args.property_id, period, include_query_params=include_query_params,
    )
    pages = fetch_pages(
        client, args.property_id, period, limit=args.page_limit,
        include_query_params=include_query_params,
    )
    device = fetch_by_device(client, args.property_id, period)
    new_vs_returning = fetch_new_vs_returning(client, args.property_id, period)
    # source / medium の詳細はパラメータ監査側で取得する。基本分析ではチャネル別と
    # ランディングページ別に役割を分け、重複していた「CVはどこから来たか」は作らない。
    source_medium = []

    # サイトセグメント別内訳（サマリー用。site_segments が定義されているクライアントのみ）。
    # 未設定なら1件も追加リクエストは発生しない（従量への配慮）。
    segment_classification = None
    segment_truncated = False
    dict_site_segments = [s for s in site_segments if isinstance(s, dict) and s.get("segment_id")]
    if dict_site_segments:
        overall_totals = fetch_overall_totals(client, args.property_id, period)
        segmentation_rows, segment_truncated = fetch_landing_pages_for_segmentation(
            client, args.property_id, period, include_query_params=include_query_params,
        )
        segment_event_rows, event_rows_truncated = fetch_landing_event_counts_for_segmentation(
            client, args.property_id, period, key_events,
            include_query_params=include_query_params,
        )
        event_count_by_landing: dict[tuple[str, str], float] = {}
        for row in segment_event_rows:
            key = (row["landingPagePlusQueryString"], row["hostName"])
            event_count_by_landing[key] = event_count_by_landing.get(key, 0) + row["eventCount"]
        for row in segmentation_rows:
            key = (row["landingPagePlusQueryString"], row["hostName"])
            row["conversions"] = event_count_by_landing.get(key, 0)
        segment_truncated = segment_truncated or event_rows_truncated
        segment_classification = calc.classify_segment_rows(
            segmentation_rows, site_segments,
            path_key="landingPagePlusQueryString", host_key="hostName",
        )
        recon_note = calc.format_reconciliation_note(
            overall_totals["sessions"],
            [{"sessions": segment_classification["total"]["sessions"]}],
            reference_label="全体セッション（絞り込み無し）",
            subtotal_label="セグメント別内訳の合計",
        )
        if recon_note:
            print(f"[fetch_ga4_analytics] {recon_note}", file=sys.stderr)

    trailing_slash_dupes = calc.detect_trailing_slash_dupes(landing_pages, "landingPagePlusQueryString")

    # 指定CVの内訳。単一CVでも、CVRを「CVしたセッション / 全セッション」で正しく
    # 算出するため必ず取得する。
    kpi_breakdown: dict = {}
    if key_events:
        kpi_breakdown["summary_rows"] = {
            "current": validated_current_summary_rows,
            "previous": fetch_conversions_by_event(
                client, args.property_id, prev_period, [], key_events, label="CV内訳: サマリー（前期）",
            ),
        }
        kpi_breakdown["timeseries"] = fetch_timeseries_by_event(
            client, args.property_id, period, granularities, key_events,
        )
        kpi_breakdown.update(fetch_channel_period_breakdown(
            client, args.property_id, period, prev_period, key_events,
        ))
        kpi_breakdown["device_rows"] = fetch_conversions_by_event(
            client, args.property_id, period, ["deviceCategory"], key_events, limit=50,
            extra_filter=_in_list_filter("deviceCategory", DEVICE_CATEGORIES),
            label="CV内訳: デバイス別",
        )
        kpi_breakdown["nvr_rows"] = fetch_conversions_by_event(
            client, args.property_id, period, ["newVsReturning"], key_events, limit=20,
            label="CV内訳: 新規/リピーター別",
        )
        # ランディングページ別のKPI内訳は、項目3（セッション順・CV順の両方）で
        # 使う。ディメンションは本文の
        # landing_pages と同じ landing_dim_name を使い、結果のキーは呼び出し側
        # （attach_kpi_breakdown 等）との互換性のため "landingPagePlusQueryString" に統一する
        # （fetch_landing_pages() と同じ、実体の値はクエリ含む/含まないが切り替わるだけ）。
        lp_kpi_rows = fetch_conversions_by_event(
            client, args.property_id, period, [landing_dim_name], key_events, limit=1000,
            label="CV内訳: ランディングページ別",
        )
        if landing_dim_name != "landingPagePlusQueryString":
            for r in lp_kpi_rows:
                r["landingPagePlusQueryString"] = r.pop(landing_dim_name)
        kpi_breakdown["lp_rows"] = lp_kpi_rows

    # フォーム通過率の分子は、当期サマリーで取得済みの完了イベント発生回数を再利用する。
    # 別々にAPIへ問い合わせるとGA4の遅延反映中に数値が動くため、レポート内の基準を固定する。
    current_summary_rows = (kpi_breakdown.get("summary_rows") or {}).get("current", [])
    completion_event_counts = {
        row["eventName"]: int(row.get("conversions", 0)) for row in current_summary_rows
    }
    if args.journey_type == "ecommerce":
        funnel_data = fetch_ecommerce_progress(client, args.property_id, period)
    else:
        funnel_data = fetch_cv_funnels(
            client, args.property_id, period, key_events, funnel_events,
            max_funnels=args.funnel_max, primary_events=primary_events,
            completion_event_counts=completion_event_counts,
        )
    md = to_markdown(
        summary, timeseries, channel, landing_pages, pages, device, new_vs_returning,
        funnel_data, source_medium,
        period, prev_period, key_events,
        lp_display_limit=args.lp_limit, page_display_limit=args.page_limit,
        weekly_display_weeks=args.weekly_weeks,
        event_names=event_names,
        primary_kpi_name=primary_kpi_name,
        kpi_breakdown=kpi_breakdown,
        segments=site_segments,
        segment_classification=segment_classification,
        segment_truncated=segment_truncated,
        trailing_slash_dupes=trailing_slash_dupes,
    )
    _progress_summary()

    if args.output == "-":
        print(md)
    else:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(md, encoding="utf-8")
        print(f"Written {len(md):,} bytes to {path}")


if __name__ == "__main__":
    main()
