"""BigQueryのGA4エクスポート生データから CVパス（精度版）を組み立てる

01の measurement.yaml に `bigquery.project_id` / `bigquery.dataset` が設定されている
クライアントのみが対象（呼び出すかどうかの判断は呼び出し側＝プロンプトの役割。
設定が無ければこのスクリプトは呼ばれない＝エラーにしない）。

GA4 Data API（標準API）では訪問順序を直接取得できない（着地ページでしか絞り込めず、
CVしたセッションに絞り込めない）ため、この項目だけは BigQuery の GA4 エクスポート生データ
（`events_*` テーブル）から セッション単位でイベントを実際の発生時刻順に並べ、正確な
ページ遷移経路を組み立てる（旧来はGA4 Data APIの着地ページ×閲覧ページの共起関係による
近似版が fetch_ga4_analytics.py 側にあったが、CVしたセッションに絞り込めていなかったため
削除済み。CVの経路はBigQuery連携があるクライアントのみ、この項目で見る）。

従量への配慮:
- 本クエリを実行する前に必ず dry run でスキャンバイト数を見積もり、既定の上限
  （`--max-scan-gb`、既定5GB）を超える場合は実行せずエラーで止める。
- `_TABLE_SUFFIX` で日付範囲を絞り込み、対象日以外の日次テーブルをスキャンしない
  （GA4のBigQueryエクスポートは日毎にテーブルが分かれるため、意図しない全期間スキャンを防げる）。
- 経路の長さ（`--max-steps`、既定5）と結果件数（`--limit`、既定10。他の一覧表（ランディングページ別・
  ページ別など）と表示件数を揃えている）を絞り、無闇に広げない。

SQL中のテーブル参照（`project_id.dataset.events_*`）はクエリパラメータにできないため、
文字列展開する前に validate_identifier() で厳格な正規表現チェックを行い、
それ以外の値（日付・イベント名・経路長・件数）はすべてバインドパラメータまたは
検証済みの整数として渡す（SQLインジェクション対策）。

Usage:
    uv run python scripts/bq_cv_paths.py \
        --project-id my-gcp-project \
        --dataset analytics_123456789 \
        --start-date 2026-07-01 --end-date 2026-07-28 \
        --key-events form_submit,file_download \
        --output samples/_cv_paths_bq.md
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse

# Windows + Git Bash等では既定の画面エンコーディングがUTF-8にならず、日本語の
# 表示だけが文字化けすることがある（ファイル自体はUTF-8で正しく書かれている）。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

sys.path.insert(0, str(Path(__file__).resolve().parent))
from auth import get_bigquery_credentials  # noqa: E402

# GCPプロジェクトIDの命名規則（英小文字始まり、英数字とハイフン、6〜30文字）
_PROJECT_ID_RE = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")
# BigQueryデータセットIDの命名規則（英数字とアンダースコアのみ、最大1024文字）
_DATASET_RE = re.compile(r"^[A-Za-z0-9_]{1,1024}$")


def validate_identifier(value: str, kind: str) -> str:
    """project_id / dataset をテーブル参照に文字列展開する前の検証。

    不正な値（SQL構文を壊しうる文字を含む等）なら ValueError を投げる。
    """
    pattern = _PROJECT_ID_RE if kind == "project_id" else _DATASET_RE
    if not value or not pattern.match(value):
        raise ValueError(
            f"不正な{kind}: {value!r}（01の measurement.yaml の bigquery.{kind} を確認してください）"
        )
    return value


def build_query(
    project_id: str,
    dataset: str,
    start_date: str,
    end_date: str,
    key_events: list[str],
    max_steps: int = 5,
    limit: int = 10,
    page_groups: list[dict] | None = None,
):
    """CVパス精度版のBigQuery SQLを組み立てる。

    戻り値: (sql文字列, bigquery.QueryJobConfig 用の query_parameters リスト)
    google-cloud-bigquery への依存を避けるため、ここでは types をインポートせず、
    呼び出し側（run_query）で bigquery.ScalarQueryParameter / ArrayQueryParameter に変換する
    形にしてもよいが、実装の単純さを優先してこの関数内で直接 bigquery 型を使う
    （テストは google-cloud-bigquery インストール前提で行う）。
    """
    from google.cloud import bigquery

    validate_identifier(project_id, "project_id")
    validate_identifier(dataset, "dataset")
    if not key_events:
        raise ValueError("key_events が空です（CVパスの判定にキーイベント名が必要）")

    max_steps = int(max_steps)
    limit = int(limit)
    if max_steps < 1 or max_steps > 20:
        raise ValueError(f"max_steps は 1〜20 の範囲で指定してください: {max_steps}")
    if limit < 1 or limit > 200:
        raise ValueError(f"limit は 1〜200 の範囲で指定してください: {limit}")

    from bq_cv_analysis import build_sql
    return build_sql(project_id, dataset, start_date, end_date, key_events, max_steps, limit, page_groups)



def estimate_bytes(client, sql: str, params) -> int:
    """dry run でスキャンバイト数を見積もる（実クエリは実行しない）"""
    from google.cloud import bigquery

    job_config = bigquery.QueryJobConfig(query_parameters=params, dry_run=True, use_query_cache=False)
    job = client.query(sql, job_config=job_config)
    value = job.total_bytes_processed
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise RuntimeError("スキャン量を見積もれないため実行を停止しました")
    return value


def cost_estimate(client, sql, params, max_scan_gb=5.0):
    """費用確認に使う情報。5GiBは料金そのものではなく同意要求の保守的な境界。"""
    if not math.isfinite(max_scan_gb) or max_scan_gb <= 0:
        raise ValueError("max_scan_gb は有限の正数で指定してください")
    estimated = estimate_bytes(client, sql, params)
    maximum = int(max_scan_gb * 1024**3)
    scope = {
        "project": str(client.project), "sql": sql,
        "parameters": [p.to_api_repr() for p in params],
        "estimated_bytes": estimated, "maximum_bytes_billed": maximum,
    }
    fingerprint = hashlib.sha256(json.dumps(scope, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return {
        "billing_project": str(client.project),
        "estimated_gib": estimated / 1024**3,
        "maximum_bytes_billed": maximum,
        "approval_required": estimated > 5 * 1024**3 or maximum > 5 * 1024**3,
        "exceeds_limit": estimated > maximum,
        "approval_fingerprint": fingerprint,
        "cost_note": "金額は課金方式・リージョン・単価に依存。無料枠やキャッシュを前提にしない。",
    }


def run_query(client, sql: str, params, max_scan_gb: float = 5.0,
              approval_fingerprint: str | None = None, approval_reference: str | None = None):
    """dry run で見積もった上で、上限内ならクエリを実行する。

    戻り値: (rows のリスト（dict化済み）, 見積もりGB)
    上限超過時は RuntimeError（呼び出し側は「エラーにせず、この項目を省略する」扱いにしてよい）。
    """
    from google.cloud import bigquery

    estimate = cost_estimate(client, sql, params, max_scan_gb)
    estimated_gb = estimate["estimated_gib"]
    if estimate["exceeds_limit"]:
        raise RuntimeError(
            f"見積もりスキャン量が上限を超えています: {estimated_gb:.2f}GB > {max_scan_gb}GB"
            "（取得期間を短くするか、見積もりと上限を提示して利用者の同意を得てください）"
        )

    if estimate["approval_required"] and (
        approval_fingerprint != estimate["approval_fingerprint"]
        or not approval_reference or not approval_reference.strip()
    ):
        raise RuntimeError(
            "費用の事前同意が必要です。--estimate-onlyで見積もりを確認し、"
            "利用者の同意後にのみ承認情報を指定してください。実クエリは未実行です。"
        )

    job_config = bigquery.QueryJobConfig(query_parameters=params, maximum_bytes_billed=estimate["maximum_bytes_billed"])
    result = client.query(sql, job_config=job_config).result()
    rows = [dict(r) for r in result]
    return rows, estimated_gb


def group_paths(rows: list[dict], page_groups: list[dict]) -> list[dict]:
    """URL列を利用者確認済みのページ群へまとめ、同じ群の連続を折りたたむ。"""
    if not page_groups:
        return rows

    def classify(url: str) -> str:
        path = urlparse(url.strip()).path or "/"
        for group in page_groups:
            name = str(group.get("name") or "").strip()
            prefixes = group.get("path_prefix") or []
            if isinstance(prefixes, str):
                prefixes = [prefixes]
            if name and any(path.startswith(str(prefix)) for prefix in prefixes if str(prefix)):
                return name
        return "その他"

    totals: dict[str, int] = defaultdict(int)
    for row in rows:
        labels: list[str] = []
        for raw in str(row.get("path") or "").split(" -> "):
            label = classify(raw)
            if not labels or labels[-1] != label:
                labels.append(label)
        if labels:
            totals[" → ".join(labels)] += int(row.get("converted_sessions", 0))
    return [
        {"path": path, "converted_sessions": count}
        for path, count in sorted(totals.items(), key=lambda item: item[1], reverse=True)
    ]


def to_markdown(
    rows: list[dict],
    start_date: str,
    end_date: str,
    key_events: list[str],
    max_steps: int,
    estimated_gb: float | None = None,
) -> str:
    """CVパス精度版のMarkdown整形（BigQuery依存なし、単体テスト可能）"""
    if rows and 'record_type' in rows[0]:
        from bq_cv_analysis import render
        return render(rows, start_date, end_date, max_steps)
    lines: list[str] = []
    lines.append(f"# 成果に至るページ遷移（BigQuery、{start_date} ～ {end_date}）")
    lines.append("")
    lines.append(f"対象キーイベント: {', '.join(key_events)}")
    lines.append(f"経路の最大ステップ数: {max_steps}")
    if estimated_gb is not None:
        lines.append(f"クエリのスキャン量（見積もり）: {estimated_gb:.2f}GB")
    lines.append("")
    lines.append(
        "GA4のBigQueryエクスポート生データから、セッションごとの実際のイベント発生順序で"
        "組み立てた経路（簡易近似ではなく、実データに基づく経路）。"
    )
    lines.append("")

    if not rows:
        lines.append("対象期間内に該当する経路が見つからなかった。")
        return "\n".join(lines) + "\n"

    lines.append("| CVしたセッションのページ群経路 | CVセッション数 |")
    lines.append("|---|---:|")
    for r in rows:
        lines.append(f"| {r['path']} | {r['converted_sessions']:,} |")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project-id", required=True, help="GCPプロジェクトID（01の bigquery.project_id）")
    parser.add_argument("--dataset", required=True, help="GA4エクスポート先データセット（01の bigquery.dataset）")
    parser.add_argument("--start-date", required=True, help="開始日 YYYY-MM-DD")
    parser.add_argument("--end-date", required=True, help="終了日 YYYY-MM-DD")
    parser.add_argument("--key-events", required=True, help="カンマ区切りのキーイベント名")
    parser.add_argument("--max-steps", type=int, default=5, help="経路の最大ステップ数（既定5）")
    parser.add_argument(
        "--page-groups-json", default="[]",
        help='ページ群のJSON。例: [{"name":"サービス","path_prefix":["/service/"]}]',
    )
    parser.add_argument(
        "--limit", type=int, default=10,
        help="表示する経路の上位件数（既定10。他の一覧表と表示件数を揃えている）",
    )
    parser.add_argument("--max-scan-gb", type=float, default=5.0, help="スキャン量の上限GB（既定5GB。超過時はエラーで停止）")
    parser.add_argument("--output", default="-")
    parser.add_argument("--estimate-only", action="store_true", help="dry runと同意用の識別情報だけを出力。実クエリは実行しない")
    parser.add_argument("--approve-cost", help="利用者が同意した見積もりのapproval_fingerprint")
    parser.add_argument("--approval-reference", help="利用者の同意を確認できる会話・内部記録の参照。AIが同意を代行しない")
    args = parser.parse_args()

    from google.cloud import bigquery

    key_events = [e.strip() for e in args.key_events.split(",") if e.strip()]

    try:
        page_groups = json.loads(args.page_groups_json)
    except json.JSONDecodeError as exc:
        parser.error(f"--page-groups-json が不正なJSONです: {exc}")
    if not isinstance(page_groups, list):
        parser.error("--page-groups-json は配列で指定してください")

    creds = get_bigquery_credentials()
    client = bigquery.Client(project=args.project_id, credentials=creds)

    sql, params = build_query(
        args.project_id, args.dataset, args.start_date, args.end_date,
        key_events, max_steps=args.max_steps, limit=args.limit, page_groups=page_groups,
    )
    if args.estimate_only:
        print(json.dumps(cost_estimate(client, sql, params, args.max_scan_gb), ensure_ascii=False, indent=2))
        return
    rows, estimated_gb = run_query(
        client, sql, params, max_scan_gb=args.max_scan_gb,
        approval_fingerprint=args.approve_cost, approval_reference=args.approval_reference,
    )
    # 分類はSQL内で上位抽出前に実施済み。

    md = to_markdown(rows, args.start_date, args.end_date, key_events, args.max_steps, estimated_gb)

    if args.output == "-":
        print(md)
    else:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(md, encoding="utf-8")
        print(f"Written {len(md):,} bytes to {path}")


if __name__ == "__main__":
    main()
