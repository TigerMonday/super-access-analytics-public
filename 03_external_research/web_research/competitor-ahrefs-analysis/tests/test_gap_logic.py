#!/usr/bin/env python3
"""build_keyword_gap / build_backlink_gap の回帰テスト（標準ライブラリ unittest のみ）。

2026-07-14 のユニット削減施策（organic-keywords・refdomains の select 列数削減）が
ギャップ計算のロジックに影響しないことを確認する目的で追加。

- 旧フォーマット（sum_traffic・best_position_url・first_seen を含む6列/4列）と
  新フォーマット（それらを含まない5列/4列/3列）の両方を入力として与え、
  出力が完全に一致することを検証する（＝これらの列は本当に未使用であることの裏付け）。
- あわせて、KD閾値による優先/参考の振り分け・自社順位によるアクション判定
  （新規記事/リライト/内部リンク強化）・ブランド語除外・被リンクギャップの自社ドメイン除外
  といった中核ロジックが列数に関わらず正しく動くことも確認する。
"""

from __future__ import annotations

import copy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import fetch_ahrefs as fa  # noqa: E402


class TestDataDirSafety(unittest.TestCase):
    def test_accepts_safe_client_id_under_outputs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            with patch.object(fa, "REPO_ROOT", repo_root):
                result = fa.data_dir("client-01_test")

            self.assertEqual(
                result,
                (repo_root / "outputs" / "client-01_test" / "_data" / "ahrefs").resolve(),
            )
            self.assertTrue(result.is_dir())

    def test_rejects_unsafe_client_id(self):
        unsafe_ids = ["../outside", "client/name", "client\\name", "client name", ".", "", "顧客A"]
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(fa, "REPO_ROOT", Path(temp_dir)):
                for client_id in unsafe_ids:
                    with self.subTest(client_id=client_id):
                        with self.assertRaisesRegex(ValueError, "client_id"):
                            fa.data_dir(client_id)

    def test_rejects_symlink_that_escapes_outputs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            outputs = repo_root / "outputs"
            outside = repo_root / "outside"
            outputs.mkdir()
            outside.mkdir()
            try:
                (outputs / "client").symlink_to(outside, target_is_directory=True)
            except OSError:
                self.skipTest("この環境ではディレクトリのシンボリックリンクを作成できない")

            with patch.object(fa, "REPO_ROOT", repo_root):
                with self.assertRaisesRegex(ValueError, "outputs"):
                    fa.data_dir("client")


def strip_keys(rows, keys_to_drop):
    return [{k: v for k, v in r.items() if k not in keys_to_drop} for r in rows]


class BuildKeywordGapTest(unittest.TestCase):
    def setUp(self):
        # 自社側: 旧6列相当（sum_traffic・best_position_url あり）
        self.own_rows_full = [
            {
                "keyword": "kw1",
                "best_position": 25,
                "volume": 500,
                "keyword_difficulty": 20,
                "sum_traffic": 120,
                "best_position_url": "https://example.com/kw1",
            },
            {
                "keyword": "kw2",
                "best_position": 5,
                "volume": 300,
                "keyword_difficulty": 10,
                "sum_traffic": 50,
                "best_position_url": "https://example.com/kw2",
            },
        ]
        # 自社側の新5列（sum_traffic のみ削除。best_position_url は残す仕様）
        self.own_rows_reduced = strip_keys(self.own_rows_full, {"sum_traffic"})

        # 競合側: 旧6列相当
        self.competitor_rows_full = {
            "rival-a.com": [
                {
                    "keyword": "kw1",
                    "best_position": 3,
                    "volume": 800,
                    "keyword_difficulty": 25,
                    "sum_traffic": 200,
                    "best_position_url": "https://rival-a.com/kw1",
                },
                {
                    "keyword": "kw3",
                    "best_position": 2,
                    "volume": 1000,
                    "keyword_difficulty": 60,
                    "sum_traffic": 300,
                    "best_position_url": "https://rival-a.com/kw3",
                },
                {
                    # volume が閾値未満 -> ギャップ抽出条件で弾かれるはず
                    "keyword": "kw-lowvol",
                    "best_position": 1,
                    "volume": 10,
                    "keyword_difficulty": 5,
                    "sum_traffic": 1000,
                    "best_position_url": "https://rival-a.com/kw-lowvol",
                },
            ]
        }
        # 競合側の新4列（sum_traffic・best_position_url を削除）
        self.competitor_rows_reduced = {
            comp: strip_keys(rows, {"sum_traffic", "best_position_url"})
            for comp, rows in self.competitor_rows_full.items()
        }

    def _run(self, own_rows, competitor_rows, **overrides):
        kwargs = dict(
            min_volume=100,
            max_position=10,
            own_min_position=20,
            brand_terms=[],
            kd_threshold=45,
        )
        kwargs.update(overrides)
        return fa.build_keyword_gap(own_rows, competitor_rows, **kwargs)

    def test_full_vs_reduced_columns_give_identical_output(self):
        priority_full, kd_over_full, excluded_full = self._run(
            self.own_rows_full, self.competitor_rows_full
        )
        priority_reduced, kd_over_reduced, excluded_reduced = self._run(
            self.own_rows_reduced, self.competitor_rows_reduced
        )
        self.assertEqual(priority_full, priority_reduced)
        self.assertEqual(kd_over_full, kd_over_reduced)
        self.assertEqual(excluded_full, excluded_reduced)

    def test_low_volume_competitor_keyword_excluded(self):
        priority, kd_over, _ = self._run(self.own_rows_reduced, self.competitor_rows_reduced)
        all_keywords = {r["keyword"] for r in priority} | {r["keyword"] for r in kd_over}
        self.assertNotIn("kw-lowvol", all_keywords)

    def test_action_and_kd_split(self):
        priority, kd_over, _ = self._run(self.own_rows_reduced, self.competitor_rows_reduced)
        priority_by_kw = {r["keyword"]: r for r in priority}
        kd_over_by_kw = {r["keyword"]: r for r in kd_over}

        # kw1: 自社順位25位 (>20 だが <=50) -> リライト。KD25<=45 -> priority
        self.assertIn("kw1", priority_by_kw)
        self.assertEqual(priority_by_kw["kw1"]["action"], "リライト")
        self.assertEqual(priority_by_kw["kw1"]["own_position"], 25)

        # kw3: 自社未取得 -> 新規記事。KD60>45 -> kd_over
        self.assertIn("kw3", kd_over_by_kw)
        self.assertEqual(kd_over_by_kw["kw3"]["action"], "新規記事")
        self.assertIsNone(kd_over_by_kw["kw3"]["own_position"])

    def test_own_min_position_excludes_already_ranking_keyword(self):
        # kw2 は自社順位5位（own_min_position=20 以下）なので、仮に競合側にも同名で
        # 出てきてもギャップとしては報告されないはずのロジックを検証する
        competitor_rows = copy.deepcopy(self.competitor_rows_reduced)
        competitor_rows["rival-a.com"].append(
            {"keyword": "kw2", "best_position": 4, "volume": 400, "keyword_difficulty": 15}
        )
        priority, kd_over, _ = self._run(self.own_rows_reduced, competitor_rows)
        all_keywords = {r["keyword"] for r in priority} | {r["keyword"] for r in kd_over}
        self.assertNotIn("kw2", all_keywords)

    def test_own_best_position_url_propagated(self):
        """自社順位が存在する行（リライト/内部リンク強化）には自社の best_position_url が
        own_best_position_url として伝搬され、自社未取得の行（新規記事）では None になること。"""
        priority, kd_over, _ = self._run(self.own_rows_reduced, self.competitor_rows_reduced)
        priority_by_kw = {r["keyword"]: r for r in priority}
        kd_over_by_kw = {r["keyword"]: r for r in kd_over}

        # kw1: 自社25位（リライト）-> 自社URLが乗る
        self.assertEqual(
            priority_by_kw["kw1"]["own_best_position_url"], "https://example.com/kw1"
        )
        # kw3: 自社未取得（新規記事）-> None（レポート表では空欄になる）
        self.assertIsNone(kd_over_by_kw["kw3"]["own_best_position_url"])

        # 全行にフィールド自体は存在する（gap のJSONエンベロープに欠けなく保存される）
        for r in priority + kd_over:
            self.assertIn("own_best_position_url", r)

    def test_brand_term_excluded(self):
        priority, kd_over, excluded_count = self._run(
            self.own_rows_reduced, self.competitor_rows_reduced, brand_terms=["kw3"]
        )
        all_keywords = {r["keyword"] for r in priority} | {r["keyword"] for r in kd_over}
        self.assertNotIn("kw3", all_keywords)
        self.assertEqual(excluded_count, 1)


class BuildBacklinkGapTest(unittest.TestCase):
    def setUp(self):
        # 旧4列（first_seen あり）
        self.own_rd_full = [
            {"domain": "owned1.com", "domain_rating": 40, "dofollow_links": 10, "first_seen": "2020-01-01"},
        ]
        self.competitor_rd_full = {
            "rival-a.com": [
                {"domain": "newdomain.com", "domain_rating": 55, "dofollow_links": 5, "first_seen": "2021-05-01"},
                {"domain": "owned1.com", "domain_rating": 40, "dofollow_links": 10, "first_seen": "2020-01-01"},
            ],
            "rival-b.com": [
                {"domain": "newdomain.com", "domain_rating": 58, "dofollow_links": 8, "first_seen": "2021-06-01"},
            ],
        }
        # 新3列（first_seen 削除）
        self.own_rd_reduced = strip_keys(self.own_rd_full, {"first_seen"})
        self.competitor_rd_reduced = {
            comp: strip_keys(rows, {"first_seen"}) for comp, rows in self.competitor_rd_full.items()
        }

    def test_full_vs_reduced_columns_give_identical_output(self):
        full = fa.build_backlink_gap(self.own_rd_full, self.competitor_rd_full)
        reduced = fa.build_backlink_gap(self.own_rd_reduced, self.competitor_rd_reduced)
        self.assertEqual(full, reduced)

    def test_own_domain_excluded_and_multi_competitor_counted(self):
        result = fa.build_backlink_gap(self.own_rd_reduced, self.competitor_rd_reduced)
        domains = {r["domain"] for r in result}
        self.assertNotIn("owned1.com", domains)
        self.assertIn("newdomain.com", domains)
        entry = next(r for r in result if r["domain"] == "newdomain.com")
        self.assertEqual(entry["linking_competitor_count"], 2)
        self.assertEqual(entry["domain_rating"], 58)  # 2社中DRが高い方を採用


if __name__ == "__main__":
    unittest.main()
