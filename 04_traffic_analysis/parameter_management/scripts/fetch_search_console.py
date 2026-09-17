"""Search Consoleの検索実績を取得し、GA4基本分析へ渡すMarkdownを作る。"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

from auth import get_search_console_credentials


@dataclass(frozen=True)
class Period:
    start: date
    end: date

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1


def resolve_period(
    *, today: date, days: int, start_date: date | None, end_date: date | None
) -> Period:
    """明示期間、またはSearch Consoleの確定遅延を考慮した既定期間を返す。"""
    if bool(start_date) != bool(end_date):
        raise ValueError("--start-date と --end-date は両方指定してください")
    if start_date and end_date:
        if start_date > end_date:
            raise ValueError("--start-date は --end-date 以前の日付にしてください")
        return Period(start_date, end_date)
    if days < 1:
        raise ValueError("days は1以上を指定してください")
    end = today - timedelta(days=3)
    return Period(end - timedelta(days=days - 1), end)


def preceding_period(period: Period) -> Period:
    """明示日付を含め、当期と同じ日数の直前期間を返す（暦年比較ではない）。"""
    end = period.start - timedelta(days=1)
    return Period(end - timedelta(days=period.days - 1), end)


def date_coverage(period: Period, rows: list[dict]) -> dict:
    """行が無い日をゼロと推定せず、日付集合で比較の可否を保守的に判定する。"""
    expected = {period.start + timedelta(days=i) for i in range(period.days)}
    observed: set[date] = set()
    invalid = 0
    for row in rows:
        try:
            day = date.fromisoformat(row["keys"][0])
        except (KeyError, IndexError, TypeError, ValueError):
            invalid += 1
            continue
        if day in observed or day not in expected:
            invalid += 1
        observed.add(day)
    missing = expected - observed
    return {
        "requested_start": period.start.isoformat(),
        "requested_end": period.end.isoformat(),
        "expected_days": period.days,
        "observed_days": len(expected & observed),
        "first_observed": min(observed).isoformat() if observed else None,
        "last_observed": max(observed).isoformat() if observed else None,
        "missing_dates": [day.isoformat() for day in sorted(missing)],
        "invalid_rows": invalid,
        "complete": bool(expected) and not missing and not invalid,
    }


def matching_site_entries(registered_site_url: str, entries: list[dict]) -> list[dict]:
    """登録済みサイトURLに対応するSearch Consoleプロパティ候補を返す。

    APIの権限一覧に実在するURLプレフィックスまたはドメインプロパティだけを
    候補にする。文字列から架空のプロパティを推測してはならない。
    """
    parsed = urlparse(registered_site_url.strip())
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        return []

    registered = registered_site_url.strip().rstrip("/") + "/"
    ranked: list[tuple[int, str, dict]] = []
    for entry in entries:
        site_url = str(entry.get("siteUrl", "")).strip()
        if not site_url:
            continue
        if site_url.lower().startswith("sc-domain:"):
            domain = site_url.split(":", 1)[1].lower().rstrip(".")
            if host == domain or host.endswith("." + domain):
                ranked.append((1, site_url, entry))
            continue

        candidate = urlparse(site_url)
        candidate_host = (candidate.hostname or "").lower().rstrip(".")
        if candidate_host != host:
            continue
        prefix = site_url.rstrip("/") + "/"
        if registered.startswith(prefix) or prefix.startswith(registered):
            exact_origin = candidate.path in ("", "/") and parsed.path in ("", "/")
            ranked.append((0 if exact_origin else 2, site_url, entry))

    return [entry for _, _, entry in sorted(ranked, key=lambda item: (item[0], item[1]))]


def query_rows(service, site_url: str, period: Period, dimensions: list[str], limit: int = 1000) -> list[dict]:
    """Search Analytics APIを1回呼び出す。取得量は既定1000行に制限する。"""
    body = {
        "startDate": period.start.isoformat(),
        "endDate": period.end.isoformat(),
        "dimensions": dimensions,
        "rowLimit": limit,
        "dataState": "final",
    }
    response = service.searchanalytics().query(siteUrl=site_url, body=body).execute()
    return list(response.get("rows", []))


def _aggregate(rows: list[dict]) -> dict:
    clicks = sum(float(row.get("clicks", 0)) for row in rows)
    impressions = sum(float(row.get("impressions", 0)) for row in rows)
    weighted_position = sum(
        float(row.get("position", 0)) * float(row.get("impressions", 0)) for row in rows
    )
    return {
        "clicks": clicks,
        "impressions": impressions,
        "ctr": clicks / impressions if impressions else 0.0,
        "position": weighted_position / impressions if impressions else 0.0,
    }


def aggregate_monthly(rows: list[dict]) -> list[dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        key = str((row.get("keys") or [""])[0])[:7]
        if key:
            grouped[key].append(row)
    return [{"month": month, **_aggregate(grouped[month])} for month in sorted(grouped)]


def _by_key(rows: list[dict]) -> dict[str, dict]:
    return {str((row.get("keys") or [""])[0]): row for row in rows}


def _delta(curr: float, prev: float) -> str:
    if prev == 0:
        return "-" if curr == 0 else "新規"
    return f"{(curr - prev) / prev * 100:+.1f}%"


def _period_comparison_table(
    current_rows: list[dict], previous_rows: list[dict], label: str, *, comparable: bool = True,
) -> list[str]:
    current = _by_key(current_rows)
    previous = _by_key(previous_rows)
    ranked = sorted(current.items(), key=lambda item: float(item[1].get("clicks", 0)), reverse=True)[:20]
    lines = [
        f"| {label} | 当期クリック | 前期クリック | 増減 | 当期表示回数 | 前期表示回数 | 当期CTR | 当期順位 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for key, row in ranked:
        prev = previous.get(key)
        clicks = float(row.get("clicks", 0))
        impressions = float(row.get("impressions", 0))
        prev_clicks = f"{float(prev.get('clicks', 0)):,.0f}" if prev is not None and comparable else "—"
        prev_impressions = f"{float(prev.get('impressions', 0)):,.0f}" if prev is not None and comparable else "—"
        delta = _delta(clicks, float(prev.get("clicks", 0))) if prev is not None and comparable else "比較不可"
        lines.append(
            f"| {key} | {clicks:,.0f} | {prev_clicks} | {delta} | "
            f"{impressions:,.0f} | {prev_impressions} | {float(row.get('ctr', 0)):.2%} | "
            f"{float(row.get('position', 0)):.1f} |"
        )
    total_current = _aggregate([row for _, row in ranked])
    total_previous = _aggregate([previous.get(key, {}) for key, _ in ranked])
    totals_comparable = comparable and bool(ranked) and all(key in previous for key, _ in ranked)
    previous_clicks = f"{total_previous['clicks']:,.0f}" if totals_comparable else "—"
    previous_impressions = f"{total_previous['impressions']:,.0f}" if totals_comparable else "—"
    delta = _delta(total_current['clicks'], total_previous['clicks']) if totals_comparable else "比較不可"
    lines.append(
        f"| **表示合計** | **{total_current['clicks']:,.0f}** | **{previous_clicks}** | "
        f"**{delta}** | "
        f"**{total_current['impressions']:,.0f}** | **{previous_impressions}** | "
        f"**{total_current['ctr']:.2%}** | **{total_current['position']:.1f}** |"
    )
    return lines


def to_markdown(
    site_url: str,
    period: Period,
    previous_period: Period,
    daily_rows: list[dict],
    previous_daily_rows: list[dict],
    query_rows_current: list[dict],
    query_rows_previous: list[dict],
    page_rows_current: list[dict],
    page_rows_previous: list[dict],
    appearance_rows: list[dict],
) -> str:
    current_total = _aggregate(daily_rows)
    previous_total = _aggregate(previous_daily_rows)
    coverage = date_coverage(period, daily_rows)
    previous_coverage = date_coverage(previous_period, previous_daily_rows)
    comparable = (
        coverage["complete"] and previous_coverage["complete"]
        and period.days == previous_period.days and previous_period.end < period.start
    )
    deltas = {
        "clicks": _delta(current_total['clicks'], previous_total['clicks']),
        "impressions": _delta(current_total['impressions'], previous_total['impressions']),
        "ctr": f"{(current_total['ctr']-previous_total['ctr'])*100:+.2f}pt",
        "position": f"{current_total['position']-previous_total['position']:+.1f}",
    } if comparable else dict.fromkeys(("clicks", "impressions", "ctr", "position"), "比較不可")
    lines = [
        f"# Search Console 検索実績 ({period.start} ～ {period.end})",
        "",
        f"比較期間: {previous_period.start} ～ {previous_period.end}",
        "",
        "## 取得範囲の確認",
        "",
        "| 期間 | 指定日数 | 日付行のある日数 | 最初の日付 | 最後の日付 | 不正・重複行数 |",
        "|---|---:|---:|---|---|---:|",
    ]
    for name, item in (("当期", coverage), ("前期", previous_coverage)):
        lines.append(
            f"| {name} | {item['expected_days']} | {item['observed_days']} | "
            f"{item['first_observed'] or '—'} | {item['last_observed'] or '—'} | {item['invalid_rows']} |"
        )
    lines.extend([
        "",
        "期間比較: 可能（日付行と日数を確認済み）。" if comparable else
        "期間比較: 不可。日付行の不足・不正、期間日数の不一致または重複を確認してください。差分・増減率を分析の根拠に使わないでください。",
        "日付行が無い理由は、実績ゼロ・保持期間外・取得上限・確定遅延等を区別できません。ゼロ補完はしません。",
        "サマリーと月次は取得行の集計です。日付行の不足がある期間は全期間の実績ではありません。",
        "クエリ・ページは取得できた上位行です。前期に行が無い値は0件・新規と扱わず、比較不可にします。",
        "",
        "## 0. 検索実績サマリー",
        "",
        "| 指標 | 当期（取得行集計） | 前期（取得行集計） | 増減 |",
        "|---|---:|---:|---:|",
        f"| クリック | {current_total['clicks']:,.0f} | {previous_total['clicks']:,.0f} | {deltas['clicks']} |",
        f"| 表示回数 | {current_total['impressions']:,.0f} | {previous_total['impressions']:,.0f} | {deltas['impressions']} |",
        f"| CTR | {current_total['ctr']:.2%} | {previous_total['ctr']:.2%} | {deltas['ctr']} |",
        f"| 平均掲載順位 | {current_total['position']:.1f} | {previous_total['position']:.1f} | {deltas['position']} |",
        "",
        "## 1. 月次推移",
        "",
        "<!-- chart: search; title: 自然検索の表示回数・クリック・CTR・平均掲載順位 -->",
        "| 月 | 表示回数 | クリック | CTR | 平均掲載順位 |",
        "|---|---:|---:|---:|---:|",
    ])
    monthly = aggregate_monthly(daily_rows)
    for row in monthly:
        lines.append(
            f"| {row['month']} | {row['impressions']:,.0f} | {row['clicks']:,.0f} | "
            f"{row['ctr']:.2%} | {row['position']:.1f} |"
        )
    lines.append(
        f"| **合計** | **{current_total['impressions']:,.0f}** | **{current_total['clicks']:,.0f}** | "
        f"**{current_total['ctr']:.2%}** | **{current_total['position']:.1f}** |"
    )
    lines.extend(["", "## 2. 検索クエリ", "", "<!-- chart: table-bars; title: 検索クエリ別のクリック・表示回数・CTR -->"])
    lines.extend(_period_comparison_table(query_rows_current, query_rows_previous, "検索クエリ", comparable=comparable))
    lines.extend(["", "## 3. 検索流入ページ", "", "<!-- chart: table-bars; title: 検索流入ページ別のクリック・表示回数・CTR -->"])
    lines.extend(_period_comparison_table(page_rows_current, page_rows_previous, "ページ", comparable=comparable))
    lines.extend(["", "## 4. 検索での表示形式", ""])
    if appearance_rows:
        lines.extend(["| 表示形式 | クリック | 表示回数 | CTR | 平均掲載順位 |", "|---|---:|---:|---:|---:|"])
        for row in appearance_rows:
            key = str((row.get("keys") or ["不明"])[0])
            lines.append(
                f"| {key} | {float(row.get('clicks', 0)):,.0f} | {float(row.get('impressions', 0)):,.0f} | "
                f"{float(row.get('ctr', 0)):.2%} | {float(row.get('position', 0)):.1f} |"
            )
        total = _aggregate(appearance_rows)
        lines.append(
            f"| **合計** | **{total['clicks']:,.0f}** | **{total['impressions']:,.0f}** | "
            f"**{total['ctr']:.2%}** | **{total['position']:.1f}** |"
        )
    else:
        lines.append("表示形式別の行は取得できなかった。")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    # 任意連携のため、依存パッケージは実行時にだけ読み込む。
    # これによりSearch Consoleを使わない基本分析や単体テストを止めない。
    if sys.platform == "win32":
        # 企業ネットワーク等でWindowsの信頼済み証明書が必要な環境でも、
        # TLS検証を無効化せずOSの証明書ストアを利用する。
        import truststore

        truststore.inject_into_ssl()

    from googleapiclient.discovery import build

    parser = argparse.ArgumentParser(description=__doc__)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--site-url", help="Search ConsoleプロパティURL")
    target.add_argument(
        "--list-sites", action="store_true",
        help="このサービスアカウントが読めるSearch Consoleプロパティを表示する",
    )
    target.add_argument(
        "--match-site-url",
        help="登録済みサイトURLに対応する、閲覧可能なSearch Consoleプロパティ候補を表示する",
    )
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--start-date", type=date.fromisoformat, help="取得開始日（YYYY-MM-DD）")
    parser.add_argument("--end-date", type=date.fromisoformat, help="取得終了日（YYYY-MM-DD）")
    parser.add_argument("--row-limit", type=int, default=1000)
    parser.add_argument("--output", default="-")
    args = parser.parse_args()
    if not 1 <= args.row_limit <= 25000:
        parser.error("row-limit は1〜25000を指定してください")

    try:
        period = resolve_period(
            today=date.today(), days=args.days,
            start_date=args.start_date, end_date=args.end_date,
        )
    except ValueError as exc:
        parser.error(str(exc))
    previous_period = preceding_period(period)

    credentials = get_search_console_credentials()
    service = build("searchconsole", "v1", credentials=credentials, cache_discovery=False)
    if args.list_sites or args.match_site_url:
        entries = service.sites().list().execute().get("siteEntry", [])
        if args.match_site_url:
            entries = matching_site_entries(args.match_site_url, entries)
        if not entries:
            if args.match_site_url:
                print("一致するSearch Consoleプロパティはありません。")
            else:
                print("利用可能なSearch Consoleプロパティはありません。")
            return
        for entry in entries:
            print(f"{entry.get('siteUrl', '')}\t{entry.get('permissionLevel', '')}")
        return

    daily = query_rows(service, args.site_url, period, ["date"], args.row_limit)
    daily_previous = query_rows(service, args.site_url, previous_period, ["date"], args.row_limit)
    queries = query_rows(service, args.site_url, period, ["query"], args.row_limit)
    queries_previous = query_rows(service, args.site_url, previous_period, ["query"], args.row_limit)
    pages = query_rows(service, args.site_url, period, ["page"], args.row_limit)
    pages_previous = query_rows(service, args.site_url, previous_period, ["page"], args.row_limit)
    appearances = query_rows(service, args.site_url, period, ["searchAppearance"], args.row_limit)

    markdown = to_markdown(
        args.site_url, period, previous_period, daily, daily_previous,
        queries, queries_previous, pages, pages_previous, appearances,
    )
    if args.output == "-":
        print(markdown)
    else:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        snapshot = {
            "site_url": args.site_url,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "data_state": "final",
            "row_limit": args.row_limit,
            "current_coverage": date_coverage(period, daily),
            "previous_coverage": date_coverage(previous_period, daily_previous),
            "daily": daily, "daily_previous": daily_previous,
            "queries": queries, "queries_previous": queries_previous,
            "pages": pages, "pages_previous": pages_previous,
            "appearances": appearances,
        }
        # Markdownだけでは日付欠損や取得上限を後から検算できないため、取得行も保持する。
        snapshot_path = output.with_name(output.name + ".json")
        snapshot_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
        output.write_text(markdown, encoding="utf-8")
        print(f"Written {len(markdown):,} bytes to {output}")


if __name__ == "__main__":
    main()
