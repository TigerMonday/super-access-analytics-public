"""GA4 認証モジュール

サービスアカウント認証のミニマル版。
鍵の場所は環境変数 GA4_SA_KEY_PATH で上書きできる（他社・他マシン環境向け）。
未指定時はホームフォルダ配下の `~/.saa/credentials/google-analytics/sa-key.json`
を使用する。準備手順は docs/setup-ga4.md を参照。
"""

from __future__ import annotations

import os
from pathlib import Path

from google.oauth2 import service_account

SCOPES = ["https://www.googleapis.com/auth/analytics.readonly"]

_DEFAULT_SA_KEY_PATH_FALLBACK = (
    Path.home() / ".saa" / "credentials" / "google-analytics" / "sa-key.json"
)


def _default_sa_key_path() -> Path:
    """呼び出し時点の環境変数を反映する（import時固定にしない）"""
    return Path(
        os.environ.get("GA4_SA_KEY_PATH", str(_DEFAULT_SA_KEY_PATH_FALLBACK))
    )


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
