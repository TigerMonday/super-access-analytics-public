"""GA4 認証モジュール

サービスアカウント認証のみ対応のミニマル版。
鍵の場所は環境変数 GA4_SA_KEY_PATH で上書きできる（他社・他マシン環境向け）。
未指定時はホームフォルダ配下の `~/.saa/credentials/google-analytics/sa-key.json`
を使用する。準備手順は docs/setup-ga4.md を参照。

BigQuery（CVパス精度版）は、GA4のBigQueryエクスポート先がサイト所有者側の別GCP
プロジェクトになっているなど、GA4用とサービスアカウントが分かれるケースがある。
その場合は環境変数 BQ_SA_KEY_PATH でBigQuery用の鍵を別に指定できる。未設定なら
従来どおりGA4と同じ鍵（GA4_SA_KEY_PATH / 既定パス）にフォールバックする。

Search Consoleも既定ではGA4と同じ読み取り用サービスアカウントを使う。組織の方針で
分ける場合だけ、環境変数 SC_SA_KEY_PATH で別の鍵を指定できる。

他の認証方式（ADC・OAuth）が必要な場合は 02_basic_measurement/measurement_design/scripts/auth.py を参照。
"""

from __future__ import annotations

import os
from pathlib import Path

from google.oauth2 import service_account

SCOPES = ["https://www.googleapis.com/auth/analytics.readonly"]
BIGQUERY_SCOPES = ["https://www.googleapis.com/auth/bigquery.readonly"]
SEARCH_CONSOLE_SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]

_DEFAULT_SA_KEY_PATH_FALLBACK = (
    Path.home() / ".saa" / "credentials" / "google-analytics" / "sa-key.json"
)
def _default_sa_key_path() -> Path:
    """呼び出し時点の環境変数を反映する（import時固定にしない）"""
    return Path(
        os.environ.get("GA4_SA_KEY_PATH", str(_DEFAULT_SA_KEY_PATH_FALLBACK))
    )


def _default_bigquery_sa_key_path() -> Path:
    """BigQuery用の鍵パスを解決する。

    BQ_SA_KEY_PATH が設定されていればそれを使う。未設定なら、GA4用サービスアカウントと
    共用する従来の動作にフォールバックする（GA4_SA_KEY_PATH → 既定パス）。
    """
    bq_path = os.environ.get("BQ_SA_KEY_PATH")
    if bq_path:
        return Path(bq_path)
    return _default_sa_key_path()


def _default_search_console_sa_key_path() -> Path:
    """Search Console用の鍵パスを解決する。

    SC_SA_KEY_PATHがあれば使い、未設定ならGA4用の鍵を共用する。
    """
    sc_path = os.environ.get("SC_SA_KEY_PATH")
    if sc_path:
        return Path(sc_path)
    return _default_sa_key_path()


DEFAULT_SA_KEY_PATH = _default_sa_key_path()  # 後方互換のため残置（参照時は関数を推奨）


def get_credentials(sa_key_path: Path | None = None):
    """サービスアカウント認証情報を返す"""
    path = sa_key_path or _default_sa_key_path()
    if not path.exists():
        raise FileNotFoundError(
            f"サービスアカウント鍵が見つかりません: {path}\n"
            f"環境変数 GA4_SA_KEY_PATH で鍵のパスを指定するか、"
            f"{_DEFAULT_SA_KEY_PATH_FALLBACK} に配置してください"
            f"（準備手順は docs/setup-ga4.md）。"
        )
    return service_account.Credentials.from_service_account_file(
        str(path), scopes=SCOPES
    )


def get_bigquery_credentials(sa_key_path: Path | None = None):
    """BigQuery読み取り用の認証情報を返す（CVパス精度版、scripts/bq_cv_paths.py 用）

    GA4用とBigQuery用でサービスアカウントが分かれている環境向けに、環境変数
    BQ_SA_KEY_PATH でBigQuery用の鍵を別に指定できる。未設定の場合は、GA4と同じ
    サービスアカウント鍵ファイルを使う従来の動作にフォールバックする（get_credentials()
    と同じ既定・環境変数 GA4_SA_KEY_PATH を参照）。

    どちらの場合も、鍵を持つサービスアカウントに、対象GCPプロジェクトでのBigQueryの
    閲覧権限が付与されている前提（01の measurement.yaml で bigquery.project_id /
    dataset が設定されているクライアントのみ使用）。
    """
    path = sa_key_path or _default_bigquery_sa_key_path()
    if not path.exists():
        using_bq_env = sa_key_path is None and bool(os.environ.get("BQ_SA_KEY_PATH"))
        if using_bq_env:
            raise FileNotFoundError(
                f"BigQuery用のサービスアカウント鍵が見つかりません: {path}\n"
                f"環境変数 BQ_SA_KEY_PATH の指定先を確認してください"
                f"（準備手順は docs/setup-ga4.md）。"
            )
        raise FileNotFoundError(
            f"サービスアカウント鍵が見つかりません: {path}\n"
            f"GA4用とBigQuery用でサービスアカウントが分かれている場合は環境変数 "
            f"BQ_SA_KEY_PATH でBigQuery用の鍵のパスを指定してください。共用する場合は"
            f"環境変数 GA4_SA_KEY_PATH で鍵のパスを指定するか、"
            f"{_DEFAULT_SA_KEY_PATH_FALLBACK} に配置してください"
            f"（準備手順は docs/setup-ga4.md）。"
        )
    return service_account.Credentials.from_service_account_file(
        str(path), scopes=BIGQUERY_SCOPES
    )


def get_search_console_credentials(sa_key_path: Path | None = None):
    """Search Console読み取り用の認証情報を返す。

    SC_SA_KEY_PATHがあれば優先し、無ければGA4用の鍵を使う。対象のSearch Console
    プロパティには、このサービスアカウントを制限付きユーザーとして追加しておく。
    """
    path = sa_key_path or _default_search_console_sa_key_path()
    if not path.exists():
        if sa_key_path is None and os.environ.get("SC_SA_KEY_PATH"):
            raise FileNotFoundError(
                f"Search Console用のサービスアカウント鍵が見つかりません: {path}\n"
                "環境変数 SC_SA_KEY_PATH の指定先を確認してください"
                "（準備手順は docs/setup-search-console.md）。"
            )
        raise FileNotFoundError(
            f"サービスアカウント鍵が見つかりません: {path}\n"
            "GA4用の鍵を準備するか、別の鍵を使う場合は環境変数 "
            "SC_SA_KEY_PATH で指定してください（準備手順は docs/setup-ga4.md と "
            "docs/setup-search-console.md）。"
        )
    return service_account.Credentials.from_service_account_file(
        str(path), scopes=SEARCH_CONSOLE_SCOPES
    )
