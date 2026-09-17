"""bq_cv_paths.py（CVパス精度版・BigQuery）のユニットテスト

実際のBigQueryには接続しない。SQL組み立て・識別子検証・Markdown整形のみを検証する
（google-cloud-bigquery はクエリパラメータの型オブジェクト生成のためインストールが必要）。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import bq_cv_paths as bq  # noqa: E402


class ValidateIdentifierTest(unittest.TestCase):
    def test_valid_project_id(self):
        self.assertEqual(bq.validate_identifier("my-gcp-project", "project_id"), "my-gcp-project")

    def test_valid_dataset(self):
        self.assertEqual(bq.validate_identifier("analytics_123456789", "dataset"), "analytics_123456789")

    def test_rejects_injection_attempt_in_project_id(self):
        with self.assertRaises(ValueError):
            bq.validate_identifier("proj`; DROP TABLE x; --", "project_id")

    def test_rejects_backtick_in_dataset(self):
        with self.assertRaises(ValueError):
            bq.validate_identifier("ds`.other_table` -- ", "dataset")

    def test_rejects_empty(self):
        with self.assertRaises(ValueError):
            bq.validate_identifier("", "project_id")

    def test_rejects_too_short_project_id(self):
        with self.assertRaises(ValueError):
            bq.validate_identifier("ab", "project_id")


class BuildQueryTest(unittest.TestCase):
    def test_basic_query_contains_expected_clauses(self):
        sql, params = bq.build_query(
            "my-project", "analytics_123", "2026-07-01", "2026-07-28",
            ["form_submit"], max_steps=5, limit=20,
        )
        self.assertIn("`my-project.analytics_123.events_*`", sql)
        self.assertIn("_TABLE_SUFFIX BETWEEN @start_suffix AND @end_suffix", sql)
        self.assertIn("LIMIT 5", sql)  # max_steps はSTRING_AGG内のLIMIT
        self.assertIn("<= 20", sql)  # CVごとの上位件数
        self.assertIn("UNNEST(@key_events)", sql)
        self.assertIn("e.event_timestamp < s.cv_time", sql)
        self.assertIn("SELECT DISTINCT user_pseudo_id,session_id,key_event,page", sql)
        self.assertIn("user_pseudo_id IS NOT NULL AND session_id IS NOT NULL", sql)

        param_names = {p.name for p in params}
        self.assertEqual(param_names, {"start_suffix", "end_suffix", "key_events"})

    def test_date_suffix_conversion(self):
        sql, params = bq.build_query(
            "my-project", "analytics_123", "2026-07-01", "2026-07-28", ["form_submit"]
        )
        by_name = {p.name: p for p in params}
        self.assertEqual(by_name["start_suffix"].value, "20260701")
        self.assertEqual(by_name["end_suffix"].value, "20260728")

    def test_rejects_invalid_project_id(self):
        with self.assertRaises(ValueError):
            bq.build_query("BAD_PROJECT!", "analytics_123", "2026-07-01", "2026-07-28", ["ev"])

    def test_rejects_empty_key_events(self):
        with self.assertRaises(ValueError):
            bq.build_query("my-project", "analytics_123", "2026-07-01", "2026-07-28", [])

    def test_rejects_out_of_range_max_steps(self):
        with self.assertRaises(ValueError):
            bq.build_query(
                "my-project", "analytics_123", "2026-07-01", "2026-07-28",
                ["ev"], max_steps=999,
            )

    def test_rejects_out_of_range_limit(self):
        with self.assertRaises(ValueError):
            bq.build_query(
                "my-project", "analytics_123", "2026-07-01", "2026-07-28",
                ["ev"], limit=100000,
            )


class RunQueryScanGuardTest(unittest.TestCase):
    """dry run の見積もりバイト数が上限を超えたら実クエリを実行せず止まることを確認する"""

    def test_raising_limit_does_not_bypass_consent(self):
        client = MagicMock()
        client.query.return_value.total_bytes_processed = 10 * 1024**3
        with self.assertRaisesRegex(RuntimeError, "事前同意"):
            bq.run_query(client, "SELECT 1", [], max_scan_gb=20)
        self.assertEqual(client.query.call_count, 1)

    def test_unknown_estimate_fails_closed(self):
        client = MagicMock()
        client.query.return_value.total_bytes_processed = None
        with self.assertRaisesRegex(RuntimeError, "見積もれない"):
            bq.run_query(client, "SELECT 1", [])
        self.assertEqual(client.query.call_count, 1)

    def test_approved_query_keeps_billing_cap(self):
        client = MagicMock()
        client.project = "billing-project"
        dry = MagicMock(total_bytes_processed=10 * 1024**3)
        real = MagicMock()
        real.result.return_value = []
        client.query.side_effect = [dry, dry, real]
        estimate = bq.cost_estimate(client, "SELECT 1", [], 20)
        bq.run_query(client, "SELECT 1", [], 20,
                     approval_fingerprint=estimate['approval_fingerprint'],
                     approval_reference="会話で当該クエリ1回・20GiB上限の同意済み")
        self.assertEqual(client.query.call_args.kwargs['job_config'].maximum_bytes_billed, 20 * 1024**3)

    def test_changed_query_cannot_reuse_approval(self):
        client = MagicMock()
        client.project = "billing-project"
        client.query.return_value.total_bytes_processed = 10 * 1024**3
        estimate = bq.cost_estimate(client, "SELECT 1", [], 20)
        with self.assertRaisesRegex(RuntimeError, "事前同意"):
            bq.run_query(client, "SELECT 2", [], 20,
                         approval_fingerprint=estimate['approval_fingerprint'],
                         approval_reference="original consent")
        self.assertEqual(client.query.call_count, 2)

    def test_aborts_when_estimate_exceeds_limit(self):
        fake_client = MagicMock()
        dry_run_job = MagicMock()
        dry_run_job.total_bytes_processed = 10 * (1024**3)  # 10GB
        fake_client.query.return_value = dry_run_job

        with self.assertRaises(RuntimeError) as ctx:
            bq.run_query(fake_client, "SELECT 1", [], max_scan_gb=5.0)
        self.assertIn("5.0GB", str(ctx.exception) + "")
        # dry run 用の1回だけ呼ばれ、実クエリ（2回目のquery呼び出し）は行われない
        self.assertEqual(fake_client.query.call_count, 1)

    def test_runs_when_within_limit(self):
        fake_client = MagicMock()
        dry_run_job = MagicMock()
        dry_run_job.total_bytes_processed = 1 * (1024**3)  # 1GB

        real_job = MagicMock()
        real_job.result.return_value = [
            {"path": "/a/ -> /b/", "converted_sessions": 2},
        ]
        # 1回目呼び出し(dry run)ではdry_run_job、2回目(実行)ではreal_jobを返す
        fake_client.query.side_effect = [dry_run_job, real_job]

        rows, estimated_gb = bq.run_query(fake_client, "SELECT 1", [], max_scan_gb=5.0)
        self.assertAlmostEqual(estimated_gb, 1.0)
        self.assertEqual(rows[0]["converted_sessions"], 2)
        self.assertEqual(fake_client.query.call_count, 2)
        self.assertEqual(fake_client.query.call_args.kwargs['job_config'].maximum_bytes_billed, 5 * 1024**3)


class ToMarkdownTest(unittest.TestCase):
    def test_two_metrics_and_denominators(self):
        rows = [dict(record_type='path', key_event='lead', path='/a', converted_sessions=2, viewed_sessions=0, total_cv_sessions=10, truncated=True),
                dict(record_type='page', key_event='lead', path='/a', converted_sessions=2, viewed_sessions=50, total_cv_sessions=10, truncated=False)]
        md = bq.to_markdown(rows, '2026-07-01', '2026-07-28', ['lead'], 5)
        self.assertEqual(md.count('### '), 2)
        self.assertIn('20.00%', md)
        self.assertIn('4.00%', md)
        self.assertIn('後続省略', md)

    def test_empty_rows(self):
        md = bq.to_markdown([], "2026-07-01", "2026-07-28", ["form_submit"], max_steps=5)
        self.assertIn("見つからなかった", md)

    def test_rows_rendered_as_converted_sessions(self):
        rows = [{"path": "/ -> /lp/ -> /form/", "converted_sessions": 10}]
        md = bq.to_markdown(rows, "2026-07-01", "2026-07-28", ["form_submit"], max_steps=5, estimated_gb=0.5)
        self.assertIn("/ -> /lp/ -> /form/", md)
        self.assertIn("CVセッション数", md)
        self.assertIn("0.50GB", md)


class GroupPathsTest(unittest.TestCase):
    def test_groups_urls_collapses_consecutive_steps_and_aggregates(self):
        rows = [
            {"path": "https://example.invalid/ -> https://example.invalid/service/a -> https://example.invalid/service/b -> https://example.invalid/contact/", "converted_sessions": 3},
            {"path": "https://example.invalid/ -> https://example.invalid/service/c -> https://example.invalid/contact/", "converted_sessions": 2},
        ]
        groups = [
            {"name": "トップ", "path_prefix": ["/"]},
            {"name": "サービス", "path_prefix": ["/service/"]},
            {"name": "フォーム", "path_prefix": ["/contact/"]},
        ]
        # より具体的なprefixを先に評価する契約なので、汎用のトップは最後に置く。
        groups = [groups[1], groups[2], groups[0]]
        out = bq.group_paths(rows, groups)
        self.assertEqual(out, [{"path": "トップ → サービス → フォーム", "converted_sessions": 5}])


if __name__ == "__main__":
    unittest.main()
