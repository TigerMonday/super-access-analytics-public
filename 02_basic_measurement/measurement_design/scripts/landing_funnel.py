"""特定のページ配下に着地したセッションの CTR / CVR をセッション基準で出す。

「ブログ経由の CV を記事別に見たい」という依頼は繰り返し来る。素直に GA4 の画面で
出そうとすると数字が合わなくなる箇所が決まっているので、その落とし穴を避けた形で
機械的に算出する。

**セッション基準で出す。ユーザー基準は使わない。**

| | 使えるか | 理由 |
|---|---|---|
| セッション数 | 使える | セッションスコープなので、着地ページで分割しても意味が保たれる |
| ユーザー数 | **使えない** | ディメンションで分割すると単純合計が全体と合わない。`user_id` に既定値を送っている案件では、未ログインが全員1人に統合されてさらに壊れる |
| イベント数 | **使えない** | 1セッション内の多重発火をそのまま数えてしまう |

**`landingPage` と `pagePath` を混同しない。**

- `landingPagePlusQueryString` は**セッションスコープ**。「そのセッションがどこに着地したか」
- `pagePathPlusQueryString` は**イベントスコープ**。「そのイベントがどのページで起きたか」

CV イベント（`signup` 等）は着地ページとは別のページで発火するので、`pagePath` で
絞ると分子が 0 になる。分母は `landingPage`、分子も `landingPage` で揃えること。
`pagePath` 側は「CTA がどの記事で押されたか」を見るときに別途使う。

**分母が欠けていないか必ず確認する。** 基盤タグの発火が遅い案件では `session_start` や
最初の `page_view` が落ち、着地ページが `(not set)` になる。本スクリプトはその比率を
出力の先頭で警告する。ここが大きいと、CTR/CVR の分母がそのぶん過少になる。

使い方:

    uv run python scripts/landing_funnel.py report \
      --client sample-client-123456789 \
      --prefix /blogs \
      --events form_request,generate_lead,signup \
      --host example.com \
      --out ../outputs/sample-client-123456789/02_measurement/docs/blog-ctr-cvr.md

読み取り専用。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 記事別の比較を持ち出してよい最小の分子。これ未満は日々のブレに埋もれる。
MIN_NUMERATOR_FOR_COMPARISON = 30

# 着地ページが取れていないセッションの比率がこれを超えたら分母を信用しない。
LANDING_UNKNOWN_WARN = 0.10


def rate(numerator: int, denominator: int) -> float:
    """百分率。分母0は0を返す（表に `nan` を出さないため）。"""
    if not denominator:
        return 0.0
    return numerator / denominator * 100


def fmt_rate(numerator: int, denominator: int) -> str:
    """率の表示。0.1%を割るときは桁を増やす（0.06% と 0.0% では意味が違う）。"""
    r = rate(numerator, denominator)
    if r == 0:
        return "0%"
    return f"{r:.3f}%" if r < 0.1 else f"{r:.2f}%"


def comparable_articles(articles: list[dict], event: str) -> list[dict]:
    """記事別の比較に耐える分子を持つ記事だけ返す。"""
    return [a for a in articles if a.get("events", {}).get(event, 0) >= MIN_NUMERATOR_FOR_COMPARISON]


# ──────────────────────────────────────
# 取得
# ──────────────────────────────────────

def fetch(config, prefix: str, events: list[str], host: str = "",
          start_date: str = "30daysAgo", end_date: str = "yesterday",
          max_articles: int = 10000) -> dict:
    """算出に必要な数字を GA4 Data API から集める。

    記事一覧は**打ち切らずに取る**。上位N件だけにすると、流入は少ないが CV は多い記事が
    「比較に耐える記事」の判定から漏れて、結論が変わる。取得が上限に達した場合は
    `articles_truncated` を立てて呼び出し側に知らせる。
    """
    import ga4_data as g

    base = [g.filter_begins_with("landingPagePlusQueryString", prefix)]
    scope = [g.filter_exact("hostName", host)] if host else []

    def sessions(extra: list[dict]) -> int:
        rows = g.run_report(config, [], ["sessions"], start_date, end_date,
                            dimension_filter=g.filter_and(scope + extra) if (scope + extra) else None)
        return int(rows[0]["sessions"]) if rows else 0

    total = sessions([])
    landed = sessions(base)
    unknown = sessions([g.filter_exact("landingPagePlusQueryString", "(not set)")])

    ev_sessions: dict[str, int] = {}
    for name in events:
        ev_sessions[name] = sessions(base + [g.filter_in_list("eventName", [name])])

    rows = g.run_report(
        config, ["landingPagePlusQueryString"], ["sessions"], start_date, end_date,
        dimension_filter=g.filter_and(scope + base), order_by_metric="sessions",
        limit=max_articles,
    )
    articles = [{"path": r["landingPagePlusQueryString"], "sessions": int(r["sessions"]),
                 "events": {}} for r in rows]
    by_path = {a["path"]: a for a in articles}

    per = g.run_report(
        config, ["landingPagePlusQueryString", "eventName"], ["sessions"], start_date, end_date,
        dimension_filter=g.filter_and(scope + base + [g.filter_in_list("eventName", events)]),
        limit=max_articles,
    )
    for r in per:
        path = r["landingPagePlusQueryString"]
        a = by_path.get(path)
        if a is None:
            # 着地セッションの一覧から漏れた記事。分母が取れていないので率は出さないが、
            # 分子を捨てると「比較に耐える記事」の判定が狂うので拾っておく。
            a = {"path": path, "sessions": 0, "events": {}}
            by_path[path] = a
            articles.append(a)
        a["events"][r["eventName"]] = int(r["sessions"])

    articles.sort(key=lambda a: -a["sessions"])
    return {
        "prefix": prefix, "host": host, "events": events,
        "period": {"start": start_date, "end": end_date},
        "total_sessions": total, "landed_sessions": landed,
        "landing_unknown_sessions": unknown,
        "event_sessions": ev_sessions, "articles": articles,
        "articles_truncated": len(rows) >= max_articles,
    }


# ──────────────────────────────────────
# レポート
# ──────────────────────────────────────

def build_report(d: dict) -> str:
    landed = d["landed_sessions"]
    total = d["total_sessions"]
    unknown = d["landing_unknown_sessions"]
    lines = [
        f"# `{d['prefix']}` 配下に着地したセッションの CTR / CVR",
        "",
        f"- 集計期間: {d['period']['start']} 〜 {d['period']['end']}",
        f"- 対象ホスト: {d['host'] or '（絞り込みなし）'}",
        f"- **分母: {landed:,} セッション**（全体 {total:,} の {rate(landed, total):.1f}%）",
        "",
        "> セッション基準で算出している。ユーザー基準はディメンションで分割すると",
        "> 単純合計が全体と合わないため使わない。イベント数も1セッション内の多重発火を",
        "> そのまま数えるので使わない。**分子は「そのイベントが発生したセッション数」**。",
        "",
    ]

    if unknown and rate(unknown, total) > LANDING_UNKNOWN_WARN * 100:
        lines += [
            f"> **警告: 着地ページが `(not set)` のセッションが {unknown:,}（全体の "
            f"{rate(unknown, total):.1f}%）ある。**",
            "> 基盤タグの発火が遅く、セッション開始時の `page_view` が落ちていると起きる。",
            "> **どこに着地したか分からないセッションなので、分母にも分子にも入っていない。**",
            "> 下の率は「着地ページが取れている範囲での率」で、絶対数は確実に過少。"
            "率がどちらに動くかは、この層の中身が分かるまで確定できない。",
            "> 目標管理に使うなら先に発火タイミングを直すこと。",
            "",
        ]
    if d.get("articles_truncated"):
        lines += [
            "> **警告: 記事の取得が上限に達した。** 下の「比較に耐えるか」の判定が"
            "全記事を見ていない可能性がある。`--max-articles` を増やして取り直すこと。",
            "",
        ]

    lines += ["## 全体", "", "| 指標 | 該当セッション | 率 |", "|---|---:|---:|"]
    for name in d["events"]:
        n = d["event_sessions"].get(name, 0)
        lines.append(f"| `{name}` | {n:,} | {fmt_rate(n, landed)} |")

    lines += ["", "## 記事別（着地セッション上位）", ""]
    header = "| 記事 | 着地セッション | " + " | ".join(f"`{e}`" for e in d["events"]) + " |"
    lines += [header, "|---|---:|" + "---:|" * len(d["events"])]
    for a in d["articles"][:30]:
        cells = []
        for e in d["events"]:
            n = a["events"].get(e, 0)
            cells.append(f"{n} / {fmt_rate(n, a['sessions'])}" if n else "0")
        lines.append(f"| `{a['path']}` | {a['sessions']:,} | " + " | ".join(cells) + " |")

    lines += ["", "## 記事別の比較に耐えるか", ""]
    for e in d["events"]:
        ok = comparable_articles(d["articles"], e)
        if ok:
            names = " / ".join(f"`{a['path']}`（{a['events'][e]}）" for a in ok[:5])
            lines.append(
                f"- `{e}`: 分子が {MIN_NUMERATOR_FOR_COMPARISON} 以上の記事が {len(ok)} 本。{names}")
        else:
            lines.append(
                f"- `{e}`: **分子が {MIN_NUMERATOR_FOR_COMPARISON} 以上の記事が1本もない。**"
                " 記事間の優劣を数字で比べられる水準にない。まず分子を増やすか、"
                "集計期間を延ばすか、計測点を手前（CTAの表示・クリック）に足す")
    return "\n".join(lines) + "\n"


# ──────────────────────────────────────
# CLI
# ──────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("report", help="CTR/CVR を算出して Markdown に書き出す")
    p.add_argument("--client", required=True)
    p.add_argument("--prefix", required=True, help="着地ページの前方一致（例: /blogs）")
    p.add_argument("--events", required=True, help="カンマ区切りのイベント名")
    p.add_argument("--host", default="", help="ホスト名で絞る（検証環境を除くのに使う）")
    p.add_argument("--start", default="30daysAgo")
    p.add_argument("--end", default="yesterday")
    p.add_argument("--max-articles", type=int, default=10000,
                   help="記事一覧の取得上限。打ち切ると比較判定が狂うので大きめに")
    p.add_argument("--out", required=True)

    args = parser.parse_args(argv)
    if args.command != "report":
        return 1

    # scripts/ を直接叩かれることがあるので、src/ を自分で通す（run.py 経由なら通っている）
    root = Path(__file__).resolve().parent.parent
    for p in (root / "src", root / "scripts"):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))

    from config import AuditConfig, resolve_client_paths
    from measurement_design.id_resolver import resolve_ids

    client_dir = resolve_client_paths(args.client).output_dir
    ids = resolve_ids(argparse.Namespace(property_id="", auth=None, sa_key_path="",
                                         gtm_account="", gtm_container=""),
                      client_dir, Path(__file__).resolve().parent.parent)
    if not ids["property_id"]:
        print("エラー: GA4プロパティIDが見つかりません（inputs/ga4.local.yaml）。", file=sys.stderr)
        return 1

    config = AuditConfig(property_id=ids["property_id"], client_name=args.client,
                         auth_method=ids["auth"], sa_key_path=ids["sa_key_path"])
    data = fetch(config, args.prefix, [e.strip() for e in args.events.split(",") if e.strip()],
                 host=args.host, start_date=args.start, end_date=args.end,
                 max_articles=args.max_articles)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_report(data), encoding="utf-8")
    print(f"分母 {data['landed_sessions']:,} セッション → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
