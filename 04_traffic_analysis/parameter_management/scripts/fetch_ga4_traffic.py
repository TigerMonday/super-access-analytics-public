"""GA4 から utm 別の流入データを取得し Markdown 表形式で出力する

Usage:
    uv run python scripts/fetch_ga4_traffic.py \
        --property-id 123456789 \
        --start-date 2025-09-01 --end-date 2026-08-31 \
        --output samples/_ga4_traffic.md

    # 標準出力に流したい場合
    uv run python scripts/fetch_ga4_traffic.py --property-id 123456789

出力は prompts/parameter-audit.md の入力セクション「4. GA4 流入データ」
そのまま貼り付けられる形式。
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    DateRange,
    Dimension,
    Filter,
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

# scripts/ ディレクトリを import パスに追加
sys.path.insert(0, str(Path(__file__).resolve().parent))
from auth import get_credentials  # noqa: E402
from analysis_period import resolve_analysis_periods  # noqa: E402


def _fetch_selected_cv_response(
    client,
    property_id: str,
    start: date,
    end: date,
    key_events: list[str],
    *,
    page_size: int,
):
    """指定CVの全行をoffsetでページングして取得する。"""
    rows = []
    offset = 0
    total_rows: int | None = None
    while True:
        request = RunReportRequest(
            property=f"properties/{property_id}",
            dimensions=[
                Dimension(name="sessionSource"), Dimension(name="sessionMedium"),
                Dimension(name="sessionCampaignName"), Dimension(name="eventName"),
            ],
            metrics=[Metric(name="eventCount")],
            date_ranges=[DateRange(start_date=start.isoformat(), end_date=end.isoformat())],
            dimension_filter=FilterExpression(filter=Filter(
                field_name="eventName",
                in_list_filter=Filter.InListFilter(values=list(key_events), case_sensitive=True),
            )),
            limit=page_size,
            offset=offset,
        )
        response = client.run_report(request)
        batch = list(response.rows)
        rows.extend(batch)
        reported_total = int(getattr(response, "row_count", 0) or 0)
        if reported_total:
            total_rows = reported_total
        offset += len(batch)
        if total_rows is not None:
            if offset >= total_rows:
                break
            if not batch:
                raise RuntimeError(
                    f"指定CVの取得が{offset}/{total_rows}行で途切れました。"
                    "未取得分を0件として扱わず、再実行してください。"
                )
            continue
        if not batch or len(batch) < page_size:
            break
    return SimpleNamespace(rows=rows, row_count=total_rows or len(rows))


def fetch_traffic(
    property_id: str,
    days: int | None = None,
    limit: int = 200,
    key_events=None,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
):
    """GA4 Data API で utm_source × utm_medium × utm_campaign 別データを取得"""
    creds = get_credentials()
    client = BetaAnalyticsDataClient(credentials=creds)

    resolved, _ = resolve_analysis_periods(
        today=date.today(), days=days, start_date=start_date, end_date=end_date,
    )
    start, end = resolved.start, resolved.end

    request = RunReportRequest(
        property=f"properties/{property_id}",
        dimensions=[
            Dimension(name="sessionSource"),
            Dimension(name="sessionMedium"),
            Dimension(name="sessionCampaignName"),
        ],
        metrics=[Metric(name="sessions")] + ([] if key_events else [Metric(name="keyEvents")]),
        date_ranges=[DateRange(start_date=start.isoformat(), end_date=end.isoformat())],
        order_bys=[
            OrderBy(metric=OrderBy.MetricOrderBy(metric_name="sessions"), desc=True)
        ],
        limit=limit,
    )
    response = client.run_report(request)
    cv_response = None
    if key_events:
        cv_response = _fetch_selected_cv_response(
            client, property_id, start, end, list(key_events), page_size=max(limit, 1000),
        )
    return response, cv_response, start, end


def to_markdown(response, start: date, end: date, cv_response=None, key_events=None) -> str:
    """API レスポンスを prompts/parameter-audit.md セクション4 形式の Markdown に変換"""
    lines: list[str] = []
    lines.append(f"## 4. GA4 流入データ（{start.isoformat()} ～ {end.isoformat()}）")
    lines.append("")
    lines.append("### utm_source × utm_medium × utm_campaign 別セッション数")
    lines.append("")
    cv_label = "指定CV" if key_events else "キーイベント（全体）"
    lines.append(f"| utm_source | utm_medium | utm_campaign | セッション | {cv_label} |")
    lines.append("|---|---|---|---:|---:|")

    total = 0
    not_set = 0
    direct = 0
    organic = 0
    row_count = 0

    selected_cv: dict[tuple[str, str, str], float] = {}
    if cv_response is not None:
        for row in cv_response.rows:
            key = tuple(v.value or "-" for v in row.dimension_values[:3])
            selected_cv[key] = selected_cv.get(key, 0) + float(row.metric_values[0].value)

    for row in response.rows:
        source = row.dimension_values[0].value or "-"
        medium = row.dimension_values[1].value or "-"
        campaign = row.dimension_values[2].value or "-"
        sessions = int(row.metric_values[0].value)
        key = (source, medium, campaign)
        conv = selected_cv.get(key, 0) if cv_response is not None else float(row.metric_values[1].value)

        lines.append(
            f"| {source} | {medium} | {campaign} "
            f"| {sessions:,} | {conv:,.0f} |"
        )

        total += sessions
        row_count += 1
        if source == "(not set)" or medium == "(not set)":
            not_set += sessions
        if source == "(direct)":
            direct += sessions
        if medium == "organic":
            organic += sessions

    pct = lambda n: f"{n / total * 100:.1f}%" if total else "0%"  # noqa: E731

    lines.append("")
    lines.append("### 補足")
    lines.append(f"- データ行数: {row_count}")
    lines.append(f"- 全体セッション: {total:,}")
    lines.append(f"- `(not set)` 合計: {not_set:,}（{pct(not_set)}）")
    lines.append(f"- `(direct)` 合計: {direct:,}（{pct(direct)}）")
    lines.append(f"- `organic` 合計: {organic:,}（{pct(organic)}）")
    lines.append("")
    lines.append(f"_GA4 Data API より {date.today().isoformat()} 取得_")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--property-id",
        required=True,
        help="GA4 プロパティID（数値のみ）",
    )
    parser.add_argument(
        "--days",
        type=int,
        help="互換用の取得日数。省略時は直近の完了した12か月。開始日・終了日の指定を優先する",
    )
    parser.add_argument("--start-date", type=date.fromisoformat, help="取得開始日（YYYY-MM-DD）")
    parser.add_argument("--end-date", type=date.fromisoformat, help="取得終了日（YYYY-MM-DD）")
    parser.add_argument(
        "--limit",
        type=int,
        default=200,
        help="最大行数（デフォルト200）",
    )
    parser.add_argument(
        "--key-events",
        default="",
        help="カンマ区切りの確認済みCVイベント名。指定時は全keyEvents合計ではなく、このイベントだけを集計",
    )
    parser.add_argument(
        "--output",
        default="-",
        help="出力ファイルパス（- で標準出力、デフォルト -）",
    )
    args = parser.parse_args()

    key_events = [e.strip() for e in args.key_events.split(",") if e.strip()]
    try:
        response, cv_response, start, end = fetch_traffic(
            args.property_id, args.days, args.limit, key_events=key_events,
            start_date=args.start_date, end_date=args.end_date,
        )
    except ValueError as exc:
        parser.error(str(exc))
    markdown = to_markdown(response, start, end, cv_response=cv_response, key_events=key_events)

    if args.output == "-":
        print(markdown)
    else:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(markdown, encoding="utf-8")
        print(f"Written {len(markdown):,} bytes to {path}")


if __name__ == "__main__":
    main()
