"""GA4 から柔軟にデータを取得する汎用フェッチャー

アドホック分析用に dimensions / metrics / filter を CLI 引数で指定可能。
エージェントが分析設計に応じて任意のクエリを組み立てる前提。

Usage:
    # 基本: モバイル vs PC の母数（全セッション）を取る
    uv run python scripts/fetch_ga4.py \
        --property-id <GA4_PROPERTY_ID> \
        --dimensions deviceCategory \
        --metrics sessions \
        --days 28 \
        --output samples/_data_device.md

    # CVしたセッション: ユーザー確認済みの完了イベントで絞る
    uv run python scripts/fetch_ga4.py \
        --property-id <GA4_PROPERTY_ID> \
        --dimensions deviceCategory \
        --metrics sessions,keyEvents \
        --filter "eventName=complete_seminar" \
        --days 28

    # キーイベント指定: complete_seminar のみ
    uv run python scripts/fetch_ga4.py \
        --property-id <GA4_PROPERTY_ID> \
        --dimensions sessionDefaultChannelGroup,date \
        --metrics eventCount \
        --filter "eventName=complete_seminar" \
        --days 90

GA4 で利用可能な dimensions / metrics の一覧:
https://developers.google.com/analytics/devguides/reporting/data/v1/api-schema
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    DateRange,
    Dimension,
    FilterExpression,
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
from ssl_diagnostics import ssl_error_hint, validate_configured_roots  # noqa: E402
from query_validation import (  # noqa: E402
    QueryPlan,
    QueryValidationError,
    build_simple_dimension_filter,
    build_simple_metric_filter,
    validate_query,
    validate_response_shape,
)

_REMOVED_METRICS = {"engagedSessions", "engagementRate"}
_METRIC_ALIASES = {"conversions": "keyEvents"}


def _is_additive_metric(metric: str) -> bool:
    """率・平均・比率系を合計行へ足さない。"""
    lowered = metric.lower()
    return not any(token in lowered for token in ("rate", "average", "percent", "persession", "peruser"))


def _quota_warning_lines(quota) -> list[str]:
    """実行継続に影響する低残量だけを利用者へ知らせる。"""
    if quota is None:
        return []
    lines = []
    for attr, label in (
        ("tokens_per_hour", "1時間あたりトークン"),
        ("tokens_per_project_per_hour", "プロジェクトの1時間あたりトークン"),
        ("concurrent_requests", "同時リクエスト"),
    ):
        status = getattr(quota, attr, None)
        remaining = getattr(status, "remaining", None) if status is not None else None
        if remaining is not None and int(remaining) <= 10:
            lines.append(f"注意: GA4 Data APIの{label}残量が{int(remaining)}です")
    return lines


@dataclass
class CombinedResponse:
    """ページングしたGA4レスポンスを出力処理へ渡す最小コンテナ。"""

    rows: list
    row_count: int
    metadata: object | None = None
    property_quota: object | None = None


def parse_filter(filter_str: str) -> FilterExpression | None:
    """単純なフィルタ文字列を FilterExpression に変換

    対応形式:
        "fieldName=value"      → 完全一致
        "fieldName~value"      → 部分一致 (CONTAINS)
        "fieldName!=value"     → 否定

    演算子は最初に現れたものを採用する（値に = や ~ を含んでも誤解釈しない。
    例: "pagePath=/foo~bar" は pagePath の完全一致）。
    """
    return build_simple_dimension_filter(filter_str)


def fetch(
    property_id: str,
    dimensions: list[str],
    metrics: list[str],
    start_date: str,
    end_date: str,
    filter_expression: FilterExpression | None = None,
    metric_filter_expression: FilterExpression | None = None,
    order_by_metric: str | None = None,
    limit: int = 200,
    fetch_all: bool = False,
):
    removed = _REMOVED_METRICS.intersection(metrics)
    if removed:
        raise ValueError(f"本プロダクトでは取得しない指標が指定されました: {sorted(removed)}")
    validate_configured_roots()
    creds = get_credentials()
    client = BetaAnalyticsDataClient(credentials=creds)

    api_metrics = [_METRIC_ALIASES.get(m, m) for m in metrics]
    api_order_metric = _METRIC_ALIASES.get(order_by_metric, order_by_metric)
    validate_query(
        client,
        property_id=property_id,
        dimensions=dimensions,
        metrics=api_metrics,
        dimension_filter=filter_expression,
        metric_filter=metric_filter_expression,
        order_by_metric=api_order_metric,
    )
    request_kwargs = {
        "property": f"properties/{property_id}",
        "dimensions": [Dimension(name=d) for d in dimensions],
        "metrics": [Metric(name=m) for m in api_metrics],
        "date_ranges": [DateRange(start_date=start_date, end_date=end_date)],
        "limit": 10_000 if fetch_all else limit,
        "return_property_quota": True,
    }
    if api_order_metric:
        request_kwargs["order_bys"] = [
            OrderBy(metric=OrderBy.MetricOrderBy(metric_name=api_order_metric), desc=True)
        ]
    elif metrics:
        request_kwargs["order_bys"] = [
            OrderBy(metric=OrderBy.MetricOrderBy(metric_name=api_metrics[0]), desc=True)
        ]
    if filter_expression:
        request_kwargs["dimension_filter"] = filter_expression
    if metric_filter_expression:
        request_kwargs["metric_filter"] = metric_filter_expression

    first = client.run_report(RunReportRequest(**request_kwargs))
    validate_response_shape(first, dimensions, api_metrics)
    if not fetch_all:
        return first

    rows = list(first.rows)
    total = int(getattr(first, "row_count", len(rows)) or len(rows))
    while len(rows) < total:
        request_kwargs["offset"] = len(rows)
        page = client.run_report(RunReportRequest(**request_kwargs))
        validate_response_shape(page, dimensions, api_metrics)
        page_rows = list(page.rows)
        if not page_rows:
            break
        rows.extend(page_rows)
    if len(rows) != total:
        raise QueryValidationError(
            f"全行取得を指定しましたが、API上の{total:,}行中{len(rows):,}行しか取得できませんでした"
        )
    return CombinedResponse(
        rows=rows,
        row_count=total,
        metadata=getattr(first, "metadata", None),
        property_quota=getattr(first, "property_quota", None),
    )


def to_markdown(
    response,
    dimensions: list[str],
    metrics: list[str],
    start_date: str,
    end_date: str,
    title: str | None = None,
) -> str:
    """API レスポンスを Markdown 表に整形"""
    lines: list[str] = []

    if title:
        lines.append(f"### {title}")
        lines.append("")

    lines.append(f"期間: {start_date} ～ {end_date}")
    lines.append(f"取得日: {date.today().isoformat()}")
    lines.append("")

    # ヘッダ
    header = "| " + " | ".join(dimensions + metrics) + " |"
    sep = "|" + "|".join(["---"] * len(dimensions) + ["---:"] * len(metrics)) + "|"
    lines.append(header)
    lines.append(sep)

    # 行
    totals: dict[str, float] = {m: 0.0 for m in metrics if _is_additive_metric(m)}
    row_count = 0
    for row in response.rows:
        cells = []
        for i, _ in enumerate(dimensions):
            cells.append(row.dimension_values[i].value or "-")
        for i, m in enumerate(metrics):
            v = row.metric_values[i].value
            try:
                fv = float(v)
                if m in totals:
                    totals[m] += fv
                if fv == int(fv):
                    cells.append(f"{int(fv):,}")
                else:
                    cells.append(f"{fv:,.2f}")
            except ValueError:
                cells.append(v)
        lines.append("| " + " | ".join(cells) + " |")
        row_count += 1

    # 合計行（率・平均系は足すと意味が変わるため対象外）
    lines.append("")
    lines.append(f"行数: {row_count}")
    api_row_count = int(getattr(response, "row_count", row_count) or row_count)
    if api_row_count > row_count:
        lines.append(f"注意: API上は{api_row_count:,}行あり、{api_row_count - row_count:,}行は未取得")
    metadata = getattr(response, "metadata", None)
    if metadata and getattr(metadata, "subject_to_thresholding", False):
        lines.append("注意: Googleのしきい値適用により一部データが省略されている可能性があります")
    if metadata and getattr(metadata, "data_loss_from_other_row", False):
        lines.append("注意: 高カーディナリティにより(other)行へ集約されたデータがあります")
    lines.extend(_quota_warning_lines(getattr(response, "property_quota", None)))
    if totals:
        totals_str = " / ".join(
            f"{m}={int(v):,}" if v == int(v) else f"{m}={v:,.2f}"
            for m, v in totals.items()
        )
        lines.append(f"合計: {totals_str}")

    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--query-plan", help="自然言語から作成した取得計画JSON。指定時は取得条件のCLI引数より優先")
    parser.add_argument("--write-query-plan", help="実行した正規化済み取得計画JSONの保存先")
    parser.add_argument("--property-id", help="GA4プロパティID")
    parser.add_argument("--dimensions", help="ディメンション（カンマ区切り）例: deviceCategory,sessionSource")
    parser.add_argument("--metrics", help="メトリクス（カンマ区切り）例: sessions,keyEvents")
    parser.add_argument("--days", type=int, default=28, help="過去N日（前日までの完全なN日間。当日は含まない。デフォルト28）")
    parser.add_argument("--start-date", help="開始日 YYYY-MM-DD（--days より優先）")
    parser.add_argument("--end-date", default=None, help="終了日 YYYY-MM-DD（デフォルト 昨日。当日は部分データのため含めない）")
    parser.add_argument("--filter", default="", help="フィルタ。例: 'eventName=complete_seminar' / 'sessionMedium~paid'")
    parser.add_argument("--metric-filter", default="", help="指標フィルタ。例: 'sessions>=10'")
    parser.add_argument("--order-by", help="ソート対象メトリクス（デフォルトは最初のメトリクス）")
    parser.add_argument("--limit", type=int, default=200, help="最大行数")
    parser.add_argument("--all-rows", action="store_true", help="APIの全行をページングして取得")
    parser.add_argument("--title", help="出力に付ける見出し")
    parser.add_argument("--output", default="-", help="出力ファイル（- で標準出力）")
    args = parser.parse_args()

    if args.query_plan:
        plan = QueryPlan.from_file(args.query_plan)
        property_id = plan.property_id
        start = date.fromisoformat(plan.start_date)
        end = date.fromisoformat(plan.end_date)
        dimensions = list(plan.dimensions)
        metrics = list(plan.metrics)
        filter_text = plan.filter_text
        metric_filter_text = plan.metric_filter_text
        order_by_metric = plan.order_by_metric
        limit = plan.limit
        fetch_all = plan.fetch_all
    else:
        if not args.property_id or not args.dimensions or not args.metrics:
            parser.error("--query-planを使わない場合は--property-id、--dimensions、--metricsが必要です")
        property_id = args.property_id
        end = date.fromisoformat(args.end_date) if args.end_date else date.today() - timedelta(days=1)
        start = date.fromisoformat(args.start_date) if args.start_date else end - timedelta(days=args.days - 1)
        dimensions = [d.strip() for d in args.dimensions.split(",") if d.strip()]
        metrics = [m.strip() for m in args.metrics.split(",") if m.strip()]
        filter_text = args.filter
        metric_filter_text = args.metric_filter
        order_by_metric = args.order_by
        limit = args.limit
        fetch_all = args.all_rows

    if start > end:
        parser.error("開始日は終了日以前にしてください")
    filter_expr = parse_filter(filter_text) if filter_text else None
    metric_filter_expr = build_simple_metric_filter(metric_filter_text) if metric_filter_text else None

    normalized_plan = QueryPlan(
        property_id=property_id,
        start_date=start.isoformat(),
        end_date=end.isoformat(),
        dimensions=tuple(dimensions),
        metrics=tuple(metrics),
        filter_text=filter_text,
        metric_filter_text=metric_filter_text,
        order_by_metric=order_by_metric,
        limit=limit,
        fetch_all=fetch_all,
    )
    try:
        response = fetch(
            property_id=property_id,
            dimensions=dimensions,
            metrics=metrics,
            start_date=start.isoformat(),
            end_date=end.isoformat(),
            filter_expression=filter_expr,
            metric_filter_expression=metric_filter_expr,
            order_by_metric=order_by_metric,
            limit=limit,
            fetch_all=fetch_all,
        )
    except Exception as exc:
        hint = ssl_error_hint(exc)
        if hint:
            raise SystemExit(f"GA4への接続で証明書エラーが発生しました。\n{hint}") from exc
        raise

    if args.write_query_plan:
        plan_path = Path(args.write_query_plan)
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        plan_path.write_text(
            json.dumps(normalized_plan.as_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    md = to_markdown(response, dimensions, metrics, start.isoformat(), end.isoformat(), args.title)

    if args.output == "-":
        print(md)
    else:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(md, encoding="utf-8")
        print(f"Written {len(md):,} bytes to {path}", file=sys.stderr)


if __name__ == "__main__":
    main()
