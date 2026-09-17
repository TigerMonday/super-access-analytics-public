"""GA4 設定確認パック — Data API モジュール

Phase 2 / Phase 5〜8 で使用する Data API ラッパー。
レポートの実行とデータ整形を行う。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    DateRange,
    Dimension,
    DimensionExpression,
    Filter,
    FilterExpression,
    Metric,
    OrderBy,
    RunReportRequest,
    RunRealtimeReportRequest,
)

# ネストされた型
StringFilter = Filter.StringFilter
InListFilter = Filter.InListFilter
MetricOrderBy = OrderBy.MetricOrderBy
DimensionOrderBy = OrderBy.DimensionOrderBy

from auth import get_credentials
from config import AuditConfig


def _client(config: AuditConfig) -> BetaAnalyticsDataClient:
    return BetaAnalyticsDataClient(credentials=get_credentials(config))


def run_report(
    config: AuditConfig,
    dimensions: list[str],
    metrics: list[str],
    start_date: str = "30daysAgo",
    end_date: str = "yesterday",
    dimension_filter: dict | None = None,
    order_by_metric: str | None = None,
    order_by_dimension: str | None = None,
    desc: bool = True,
    limit: int = 0,
    return_quota: bool = False,
) -> list[dict]:
    """Data API レポート実行

    Args:
        config: 監査設定
        dimensions: ディメンション名のリスト
        metrics: 指標名のリスト（最大10）
        start_date: 開始日（"30daysAgo", "2025-01-01" 等）
        end_date: 終了日
        dimension_filter: フィルタ辞書（後述のヘルパー関数で生成）
        order_by_metric: ソートする指標名
        order_by_dimension: ソートするディメンション名
        desc: 降順ソート
        limit: 行数上限（0=無制限）
        return_quota: クォータ情報を返すか

    Returns:
        行データのリスト。各行は {dim1: val1, dim2: val2, metric1: val1, ...} 形式
    """
    if len(metrics) > 10:
        raise ValueError(f"Data API は1リクエスト最大10指標。{len(metrics)}個指定されています。split_metrics() で分割してください。")

    client = _client(config)

    request = RunReportRequest(
        property=config.property_resource,
        date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
        dimensions=[Dimension(name=d) for d in dimensions],
        metrics=[Metric(name=m) for m in metrics],
        return_property_quota=return_quota,
    )

    if dimension_filter:
        request.dimension_filter = _build_filter_expression(dimension_filter)

    if order_by_metric:
        request.order_bys = [
            OrderBy(metric=MetricOrderBy(metric_name=order_by_metric), desc=desc)
        ]
    elif order_by_dimension:
        request.order_bys = [
            OrderBy(dimension=DimensionOrderBy(dimension_name=order_by_dimension), desc=desc)
        ]

    if limit > 0:
        request.limit = limit

    response = client.run_report(request)

    rows = []
    for row in response.rows:
        entry = {}
        for i, dim in enumerate(dimensions):
            entry[dim] = row.dimension_values[i].value
        for i, met in enumerate(metrics):
            entry[met] = row.metric_values[i].value
        rows.append(entry)

    return rows


def run_report_dual_date(
    config: AuditConfig,
    dimensions: list[str],
    metrics: list[str],
    date_range_1: tuple[str, str],
    date_range_2: tuple[str, str],
    **kwargs,
) -> dict:
    """2つの日付範囲でレポートを実行（YoY比較用）

    Returns:
        {"current": [...], "previous": [...]}
    """
    client = _client(config)

    request = RunReportRequest(
        property=config.property_resource,
        date_ranges=[
            DateRange(start_date=date_range_1[0], end_date=date_range_1[1], name="current"),
            DateRange(start_date=date_range_2[0], end_date=date_range_2[1], name="previous"),
        ],
        dimensions=[Dimension(name=d) for d in dimensions],
        metrics=[Metric(name=m) for m in metrics],
    )

    if kwargs.get("order_by_metric"):
        request.order_bys = [
            OrderBy(metric=MetricOrderBy(metric_name=kwargs["order_by_metric"]), desc=kwargs.get("desc", True))
        ]
    if kwargs.get("limit"):
        request.limit = kwargs["limit"]

    response = client.run_report(request)

    # 2つの date_range のデータを分離
    # response.rows には各 date_range の結果が metric_values に連続して入る
    current = []
    previous = []
    num_metrics = len(metrics)

    for row in response.rows:
        entry_current = {}
        entry_previous = {}
        for i, dim in enumerate(dimensions):
            entry_current[dim] = row.dimension_values[i].value
            entry_previous[dim] = row.dimension_values[i].value
        for i, met in enumerate(metrics):
            entry_current[met] = row.metric_values[i].value
            entry_previous[met] = row.metric_values[num_metrics + i].value
        current.append(entry_current)
        previous.append(entry_previous)

    return {"current": current, "previous": previous}


def split_metrics_report(
    config: AuditConfig,
    dimensions: list[str],
    metrics: list[str],
    join_key: str | None = None,
    **kwargs,
) -> list[dict]:
    """10指標超のレポートを自動分割して結合

    Args:
        join_key: 結合キーのディメンション名（デフォルト: 最初のディメンション）
    """
    if len(metrics) <= 10:
        return run_report(config, dimensions, metrics, **kwargs)

    join_key = join_key or dimensions[0]

    # 10指標ずつ分割
    batches = [metrics[i:i + 10] for i in range(0, len(metrics), 10)]
    all_results = {}

    for batch in batches:
        rows = run_report(config, dimensions, batch, **kwargs)
        for row in rows:
            key_parts = tuple(row[d] for d in dimensions)
            if key_parts not in all_results:
                all_results[key_parts] = {d: row[d] for d in dimensions}
            all_results[key_parts].update({m: row[m] for m in batch})

    return list(all_results.values())


# ──────────────────────────────────────
# フィルタヘルパー
# ──────────────────────────────────────

def filter_exact(field_name: str, value: str, case_sensitive: bool = False) -> dict:
    """完全一致フィルタ"""
    return {
        "type": "filter",
        "field_name": field_name,
        "string_filter": {"match_type": "EXACT", "value": value, "case_sensitive": case_sensitive},
    }


def filter_contains(field_name: str, value: str) -> dict:
    """部分一致フィルタ"""
    return {
        "type": "filter",
        "field_name": field_name,
        "string_filter": {"match_type": "CONTAINS", "value": value},
    }


def filter_begins_with(field_name: str, value: str, case_sensitive: bool = False) -> dict:
    """前方一致フィルタ。ページパスの配下（`/blogs` 以下）を切るのに使う。

    `filter_contains` で代用すると `/x/blogs` のような別階層まで拾うので分けている。
    """
    return {
        "type": "filter",
        "field_name": field_name,
        "string_filter": {
            "match_type": "BEGINS_WITH", "value": value, "case_sensitive": case_sensitive
        },
    }


def filter_in_list(field_name: str, values: list[str], case_sensitive: bool = False) -> dict:
    """リスト内一致フィルタ"""
    return {
        "type": "filter",
        "field_name": field_name,
        "in_list_filter": {"values": values, "case_sensitive": case_sensitive},
    }


def filter_not(inner_filter: dict) -> dict:
    """NOT フィルタ"""
    return {"type": "not", "inner": inner_filter}


def filter_and(filters: list[dict]) -> dict:
    """AND フィルタ"""
    return {"type": "and", "filters": filters}


def filter_or(filters: list[dict]) -> dict:
    """OR フィルタ"""
    return {"type": "or", "filters": filters}


def _build_filter_expression(f: dict) -> FilterExpression:
    """dict フィルタ定義を FilterExpression に変換"""
    ftype = f.get("type", "filter")

    if ftype == "not":
        return FilterExpression(
            not_expression=_build_filter_expression(f["inner"])
        )
    elif ftype == "and":
        return FilterExpression(
            and_group={"expressions": [_build_filter_expression(x) for x in f["filters"]]}
        )
    elif ftype == "or":
        return FilterExpression(
            or_group={"expressions": [_build_filter_expression(x) for x in f["filters"]]}
        )
    elif ftype == "filter":
        field_name = f["field_name"]
        if "string_filter" in f:
            sf = f["string_filter"]
            match_type_map = {
                "EXACT": StringFilter.MatchType.EXACT,
                "BEGINS_WITH": StringFilter.MatchType.BEGINS_WITH,
                "ENDS_WITH": StringFilter.MatchType.ENDS_WITH,
                "CONTAINS": StringFilter.MatchType.CONTAINS,
                "FULL_REGEXP": StringFilter.MatchType.FULL_REGEXP,
                "PARTIAL_REGEXP": StringFilter.MatchType.PARTIAL_REGEXP,
                1: StringFilter.MatchType.EXACT,
            }
            return FilterExpression(
                filter=Filter(
                    field_name=field_name,
                    string_filter=StringFilter(
                        match_type=match_type_map.get(sf["match_type"], sf["match_type"]),
                        value=sf["value"],
                        case_sensitive=sf.get("case_sensitive", False),
                    ),
                )
            )
        elif "in_list_filter" in f:
            ilf = f["in_list_filter"]
            return FilterExpression(
                filter=Filter(
                    field_name=field_name,
                    in_list_filter=InListFilter(
                        values=ilf["values"],
                        case_sensitive=ilf.get("case_sensitive", False),
                    ),
                )
            )
    raise ValueError(f"Unknown filter type: {f}")


# ──────────────────────────────────────
# 日付ヘルパー
# ──────────────────────────────────────

def get_last_month_range() -> tuple[str, str]:
    """直近月の開始日・終了日を返す"""
    today = datetime.today()
    first_of_this_month = today.replace(day=1)
    last_of_prev_month = first_of_this_month - timedelta(days=1)
    first_of_prev_month = last_of_prev_month.replace(day=1)
    return first_of_prev_month.strftime("%Y-%m-%d"), last_of_prev_month.strftime("%Y-%m-%d")


def get_yoy_ranges() -> tuple[tuple[str, str], tuple[str, str]]:
    """直近月と前年同月の日付範囲を返す"""
    current_start, current_end = get_last_month_range()
    from datetime import datetime as dt

    cs = dt.strptime(current_start, "%Y-%m-%d")
    ce = dt.strptime(current_end, "%Y-%m-%d")
    prev_start = cs.replace(year=cs.year - 1).strftime("%Y-%m-%d")
    prev_end = ce.replace(year=ce.year - 1).strftime("%Y-%m-%d")
    return (current_start, current_end), (prev_start, prev_end)


# ──────────────────────────────────────
# よく使うレポートパターン
# ──────────────────────────────────────

def get_event_list(config: AuditConfig, days: int = 30, limit: int = 100) -> list[dict]:
    """イベント一覧（Phase 2）"""
    return run_report(
        config,
        dimensions=["eventName"],
        metrics=["eventCount", "totalUsers"],
        start_date=f"{days}daysAgo",
        order_by_metric="eventCount",
        limit=limit,
    )


def get_monthly_overview(config: AuditConfig) -> list[dict]:
    """月次推移 13ヶ月（Phase 8-A）— 自動分割"""
    return split_metrics_report(
        config,
        dimensions=["yearMonth"],
        metrics=[
            "sessions", "totalUsers", "newUsers", "screenPageViews",
            "screenPageViewsPerSession", "bounceRate",
            "averageSessionDuration", "keyEvents", "userKeyEventRate",
            "eventCount", "userEngagementDuration",
        ],
        start_date="395daysAgo",
        order_by_dimension="yearMonth",
        desc=False,
    )


def get_channel_monthly(config: AuditConfig) -> list[dict]:
    """チャネル別月次（Phase 8-B）"""
    return run_report(
        config,
        dimensions=["yearMonth", "sessionDefaultChannelGroup"],
        metrics=["sessions", "keyEvents"],
        start_date="395daysAgo",
        order_by_dimension="yearMonth",
        desc=False,
    )


def get_source_medium_top(config: AuditConfig, limit: int = 20) -> list[dict]:
    """参照元/メディア Top N（Phase 8-C）"""
    start, end = get_last_month_range()
    return run_report(
        config,
        dimensions=["sessionSourceMedium"],
        metrics=["sessions", "totalUsers", "keyEvents", "userKeyEventRate",
                 "bounceRate", "averageSessionDuration"],
        start_date=start,
        end_date=end,
        order_by_metric="sessions",
        limit=limit,
    )


def get_device_monthly(config: AuditConfig) -> list[dict]:
    """デバイス別月次（Phase 8-F）"""
    return run_report(
        config,
        dimensions=["yearMonth", "deviceCategory"],
        metrics=["sessions", "keyEvents"],
        start_date="395daysAgo",
        order_by_dimension="yearMonth",
        desc=False,
    )


def get_key_events_breakdown(config: AuditConfig) -> list[dict]:
    """キーイベント内訳（Phase 8-G）"""
    start, end = get_last_month_range()
    return run_report(
        config,
        dimensions=["eventName"],
        metrics=["eventCount", "totalUsers"],
        start_date=start,
        end_date=end,
        dimension_filter=filter_exact("isKeyEvent", "true"),
        order_by_metric="eventCount",
    )


def get_utm_sources(config: AuditConfig) -> list[dict]:
    """UTM source/medium（Phase 5-A）"""
    return run_report(
        config,
        dimensions=["sessionSource", "sessionMedium"],
        metrics=["sessions", "keyEvents"],
        start_date="90daysAgo",
        order_by_metric="sessions",
        limit=100,
    )


def get_utm_campaigns(config: AuditConfig) -> list[dict]:
    """UTM campaign（Phase 5-B）"""
    return run_report(
        config,
        dimensions=["sessionCampaignName", "sessionSource", "sessionMedium"],
        metrics=["sessions", "keyEvents"],
        start_date="90daysAgo",
        order_by_metric="sessions",
        limit=100,
    )


def get_ai_traffic(config: AuditConfig) -> list[dict]:
    """AI チャットボット流入（Phase 5-D）"""
    return run_report(
        config,
        dimensions=["sessionSource", "sessionMedium"],
        metrics=["sessions", "keyEvents"],
        start_date="90daysAgo",
        dimension_filter=filter_in_list(
            "sessionSource",
            ["chatgpt.com", "perplexity.ai", "perplexity", "gemini.google.com",
             "copilot.microsoft.com", "copilot.com"],
        ),
        order_by_metric="sessions",
    )


def get_hostnames(config: AuditConfig) -> list[dict]:
    """ホスト名一覧（Phase 6-A）"""
    return run_report(
        config,
        dimensions=["hostName"],
        metrics=["sessions", "totalUsers", "screenPageViews", "keyEvents",
                 "screenPageViewsPerSession", "bounceRate"],
        start_date="90daysAgo",
        order_by_metric="sessions",
    )


def get_event_monthly_trend(config: AuditConfig, event_names: list[str]) -> list[dict]:
    """イベント月次推移（Phase 7-A）"""
    return run_report(
        config,
        dimensions=["yearMonth", "eventName"],
        metrics=["eventCount"],
        start_date="395daysAgo",
        dimension_filter=filter_in_list("eventName", event_names, case_sensitive=True),
        order_by_dimension="yearMonth",
        desc=False,
    )


def get_event_daily(config: AuditConfig, event_name: str, start_date: str, end_date: str) -> list[dict]:
    """イベント日次データ（Phase 7-C ピンポイント分析）"""
    return run_report(
        config,
        dimensions=["date"],
        metrics=["eventCount"],
        start_date=start_date,
        end_date=end_date,
        dimension_filter=filter_exact("eventName", event_name),
        order_by_dimension="date",
        desc=False,
    )


# ──────────────────────────────────────
# CLI テスト
# ──────────────────────────────────────

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print("Usage: python ga4_data.py <property_id> <function_name> [args...]")
        print("Functions: get_event_list, get_monthly_overview, get_utm_sources, ...")
        sys.exit(1)

    config = AuditConfig(property_id=sys.argv[1], client_name="_test")
    func_name = sys.argv[2]
    func = globals().get(func_name)

    if func is None:
        print(f"Unknown function: {func_name}")
        sys.exit(1)

    result = func(config, *sys.argv[3:]) if len(sys.argv) > 3 else func(config)
    print(json.dumps(result, indent=2, ensure_ascii=False))
