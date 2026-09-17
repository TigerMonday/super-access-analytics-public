"""auth.py のユニットテスト

鍵パスの解決順（GA4: 引数 → GA4_SA_KEY_PATH → 既定パス、Search Console:
引数 → SC_SA_KEY_PATH → GA4側、BigQuery: 引数 → BQ_SA_KEY_PATH → GA4側）と、
エラーメッセージが各ツールの
どちらの鍵を探して失敗したかを区別できることを検証する。
実際のGoogle APIには接続せず、実在しないパスに対するFileNotFoundErrorの
メッセージだけを確認する。
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import auth  # noqa: E402

# 実機の既定パスに実物の鍵が置かれている環境（本番運用機など）でもテストが
# 環境に依存しないよう、既定パスの参照先を実在しないダミーパスに差し替える。
_FAKE_DEFAULT_FALLBACK = Path("/tmp/no-such-dir/credentials/google-analytics/sa-key.json")
class GetCredentialsTest(unittest.TestCase):
    """GA4側 get_credentials() の挙動が今回の変更で壊れていないことを確認する"""

    def test_uses_default_path_when_env_unset(self):
        with patch.object(auth, "_DEFAULT_SA_KEY_PATH_FALLBACK", _FAKE_DEFAULT_FALLBACK):
            with patch.dict(os.environ, {}, clear=True):
                with self.assertRaises(FileNotFoundError) as ctx:
                    auth.get_credentials()
        self.assertIn(str(_FAKE_DEFAULT_FALLBACK), str(ctx.exception))
        self.assertIn("GA4_SA_KEY_PATH", str(ctx.exception))

    def test_uses_ga4_env_var_when_set(self):
        fake_path = str(Path("/tmp/fake-ga4/sa-key.json"))
        with patch.dict(os.environ, {"GA4_SA_KEY_PATH": fake_path}, clear=True):
            with self.assertRaises(FileNotFoundError) as ctx:
                auth.get_credentials()
        self.assertIn(fake_path, str(ctx.exception))

    def test_explicit_arg_overrides_env(self):
        explicit_path = Path("/tmp/explicit/sa-key.json")
        with patch.dict(os.environ, {"GA4_SA_KEY_PATH": "/tmp/fake-ga4/sa-key.json"}, clear=True):
            with self.assertRaises(FileNotFoundError) as ctx:
                auth.get_credentials(sa_key_path=explicit_path)
        self.assertIn(str(explicit_path), str(ctx.exception))


class GetBigQueryCredentialsTest(unittest.TestCase):
    """BigQuery側 get_bigquery_credentials() の鍵パス解決とエラーメッセージを確認する"""

    def test_falls_back_to_ga4_default_when_both_unset(self):
        """BQ_SA_KEY_PATH・GA4_SA_KEY_PATHの両方が未設定なら、GA4既定パスにフォールバックする"""
        with patch.object(auth, "_DEFAULT_SA_KEY_PATH_FALLBACK", _FAKE_DEFAULT_FALLBACK):
            with patch.dict(os.environ, {}, clear=True):
                with self.assertRaises(FileNotFoundError) as ctx:
                    auth.get_bigquery_credentials()
        self.assertIn(str(_FAKE_DEFAULT_FALLBACK), str(ctx.exception))
        # GA4/BigQueryの両方の環境変数を案内する（共用フォールバックのメッセージ）
        self.assertIn("GA4_SA_KEY_PATH", str(ctx.exception))
        self.assertIn("BQ_SA_KEY_PATH", str(ctx.exception))

    def test_falls_back_to_ga4_env_var_when_bq_unset(self):
        """BQ_SA_KEY_PATHが未設定でGA4_SA_KEY_PATHが設定済みなら、GA4側の鍵を使う（既存利用者の動作を維持）"""
        ga4_path = str(Path("/tmp/fake-ga4/sa-key.json"))
        with patch.dict(os.environ, {"GA4_SA_KEY_PATH": ga4_path}, clear=True):
            with self.assertRaises(FileNotFoundError) as ctx:
                auth.get_bigquery_credentials()
        self.assertIn(ga4_path, str(ctx.exception))

    def test_uses_bq_env_var_when_set(self):
        """BQ_SA_KEY_PATHが設定されていれば、GA4_SA_KEY_PATHより優先してBigQuery用の鍵を使う"""
        bq_path = str(Path("/tmp/fake-bq/sa-key.json"))
        ga4_path = str(Path("/tmp/fake-ga4/sa-key.json"))
        with patch.dict(
            os.environ, {"BQ_SA_KEY_PATH": bq_path, "GA4_SA_KEY_PATH": ga4_path}, clear=True
        ):
            with self.assertRaises(FileNotFoundError) as ctx:
                auth.get_bigquery_credentials()
        self.assertIn(bq_path, str(ctx.exception))
        self.assertNotIn(ga4_path, str(ctx.exception))

    def test_error_message_distinguishes_bq_env_failure(self):
        """BQ_SA_KEY_PATHを指定して失敗した場合は、BigQuery用の鍵を探したと分かるメッセージになる
        （GA4_SA_KEY_PATHの案内だけを返す誤誘導を避ける）"""
        bq_path = str(Path("/tmp/fake-bq/sa-key.json"))
        with patch.dict(os.environ, {"BQ_SA_KEY_PATH": bq_path}, clear=True):
            with self.assertRaises(FileNotFoundError) as ctx:
                auth.get_bigquery_credentials()
        message = str(ctx.exception)
        self.assertIn("BigQuery", message)
        self.assertIn("BQ_SA_KEY_PATH", message)
        self.assertNotIn("GA4_SA_KEY_PATH", message)

    def test_explicit_arg_overrides_env(self):
        explicit_path = Path("/tmp/explicit-bq/sa-key.json")
        with patch.dict(os.environ, {"BQ_SA_KEY_PATH": "/tmp/fake-bq/sa-key.json"}, clear=True):
            with self.assertRaises(FileNotFoundError) as ctx:
                auth.get_bigquery_credentials(sa_key_path=explicit_path)
        self.assertIn(str(explicit_path), str(ctx.exception))


class GetSearchConsoleCredentialsTest(unittest.TestCase):
    """Search Consoleが既定ではGA4鍵を共用し、個別指定もできることを確認する"""

    def test_falls_back_to_ga4_default_when_env_unset(self):
        with patch.object(auth, "_DEFAULT_SA_KEY_PATH_FALLBACK", _FAKE_DEFAULT_FALLBACK):
            with patch.dict(os.environ, {}, clear=True):
                with self.assertRaises(FileNotFoundError) as ctx:
                    auth.get_search_console_credentials()
        message = str(ctx.exception)
        self.assertIn(str(_FAKE_DEFAULT_FALLBACK), message)
        self.assertIn("SC_SA_KEY_PATH", message)

    def test_falls_back_to_ga4_env_var_when_sc_unset(self):
        ga4_path = str(Path("/tmp/fake-ga4/sa-key.json"))
        with patch.dict(os.environ, {"GA4_SA_KEY_PATH": ga4_path}, clear=True):
            with self.assertRaises(FileNotFoundError) as ctx:
                auth.get_search_console_credentials()
        self.assertIn(ga4_path, str(ctx.exception))

    def test_uses_sc_env_var_when_set(self):
        sc_path = str(Path("/tmp/fake-search-console/sa-key.json"))
        with patch.dict(
            os.environ,
            {"SC_SA_KEY_PATH": sc_path, "GA4_SA_KEY_PATH": "/tmp/fake-ga4/sa-key.json"},
            clear=True,
        ):
            with self.assertRaises(FileNotFoundError) as ctx:
                auth.get_search_console_credentials()
        message = str(ctx.exception)
        self.assertIn(sc_path, message)
        self.assertNotIn("fake-ga4", message)

    def test_explicit_arg_overrides_sc_env(self):
        explicit_path = Path("/tmp/explicit-search-console/sa-key.json")
        with patch.dict(
            os.environ,
            {"SC_SA_KEY_PATH": "/tmp/fake-search-console/sa-key.json"},
            clear=True,
        ):
            with self.assertRaises(FileNotFoundError) as ctx:
                auth.get_search_console_credentials(sa_key_path=explicit_path)
        self.assertIn(str(explicit_path), str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
