"""BigQueryのGA4エクスポート先を読めるか、データ取得なしで確認する。"""

from __future__ import annotations

import argparse
import json
import re

from auth import get_bigquery_credentials


PROJECT_RE = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")
DATASET_RE = re.compile(r"^[A-Za-z0-9_]{1,1024}$")


def validate_identifiers(project_id: str, dataset: str) -> None:
    if not PROJECT_RE.fullmatch(project_id):
        raise ValueError("BigQueryのプロジェクトIDの形式が正しくありません")
    if not DATASET_RE.fullmatch(dataset):
        raise ValueError("BigQueryのデータセット名の形式が正しくありません")


def check_access(project_id: str, dataset: str) -> dict[str, str]:
    validate_identifiers(project_id, dataset)

    from google.api_core.exceptions import Forbidden, GoogleAPICallError, NotFound
    from google.cloud import bigquery

    credentials = get_bigquery_credentials()
    client = bigquery.Client(project=project_id, credentials=credentials)
    target = f"{project_id}.{dataset}"
    try:
        dataset_info = client.get_dataset(target)
        # 日次GA4テーブルの存在と読み取り権限を、実データを取得せず確認する。
        daily_tables = [
            table.table_id for table in client.list_tables(target)
            if re.fullmatch(r"events_\d{8}", table.table_id)
        ]
        if not daily_tables:
            return {"state": "no_ga4_tables", "project_id": project_id, "dataset": dataset}
        latest_table = max(daily_tables)
        job_config = bigquery.QueryJobConfig(dry_run=True, use_query_cache=False)
        client.query(
            f"SELECT user_pseudo_id, event_name, event_timestamp, event_params "
            f"FROM `{target}.{latest_table}` LIMIT 0",
            job_config=job_config, location=dataset_info.location,
        )
    except Forbidden:
        return {"state": "permission_denied", "project_id": project_id, "dataset": dataset}
    except NotFound:
        return {"state": "not_found", "project_id": project_id, "dataset": dataset}
    except GoogleAPICallError as exc:
        return {
            "state": "error",
            "project_id": project_id,
            "dataset": dataset,
            "reason": str(exc),
        }
    return {"state": "ready", "project_id": project_id, "dataset": dataset}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        result = check_access(args.project_id, args.dataset)
    except (ValueError, FileNotFoundError) as exc:
        result = {"state": "error", "reason": str(exc)}

    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    elif result["state"] == "ready":
        print(f"[OK] BigQueryへ接続できました: {args.project_id}.{args.dataset}")
    elif result["state"] == "permission_denied":
        print("[NG] BigQueryの閲覧権限がありません。サービスアカウントの役割を確認してください。")
    elif result["state"] == "not_found":
        print("[NG] BigQueryのデータセットが見つかりません。プロジェクトIDとデータセット名を確認してください。")
    elif result["state"] == "no_ga4_tables":
        print("[未完了] データセットには接続できましたが、GA4の日次テーブルがありません。出力先とエクスポート状況を確認してください。")
    else:
        print(f"[NG] {result.get('reason', 'BigQueryへ接続できませんでした')}")
    return 0 if result["state"] == "ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
