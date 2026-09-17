"""GA4 設定確認パック — 認証モジュール

3つの認証方法をサポート:
  - adc: Application Default Credentials（gcloud auth application-default login）
  - oauth: OAuth クライアント（プロファイル別 JSON）
  - sa: サービスアカウント

利用者向けの案内（README/work-procedure.md/setup-ga4.md）は sa のみを案内している。
adc/oauth は「通常のGoogleアカウントでもGCPプロジェクトの利用枠設定が結局必要になり、
サービスアカウントより楽にならない」ことを実測で確認済みのため、案内から外した
（将来使う可能性を考慮しコードの分岐自体は残す。経緯は docs/setup-ga4.md 参照）。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import google.auth
import google.auth.transport.requests
from google.oauth2 import credentials as oauth2_credentials
from google.oauth2 import service_account

from config import AuditConfig, CREDENTIALS_DIR, DEFAULT_ADC_PATH

# 必要なスコープ
SCOPES = [
    "https://www.googleapis.com/auth/analytics.readonly",
    "https://www.googleapis.com/auth/tagmanager.readonly",
]


def get_credentials(config: AuditConfig, extra_scopes: list[str] | None = None):
    """設定に基づいて認証情報を取得。extra_scopes で API 別スコープ追加可。"""
    scopes = SCOPES + list(extra_scopes or [])
    if config.auth_method == "adc":
        return _get_adc_credentials(scopes)
    elif config.auth_method == "oauth":
        return _get_oauth_credentials(config.oauth_profile, scopes)
    elif config.auth_method == "sa":
        return _get_sa_credentials(scopes, config.sa_key_path)
    else:
        raise ValueError(f"Unknown auth method: {config.auth_method}")


def _get_adc_credentials(scopes: list[str]):
    """Application Default Credentials"""
    creds, project = google.auth.default(scopes=scopes)
    return creds


def _get_oauth_credentials(profile: str, scopes: list[str]):
    """OAuth クライアント認証（プロファイル別）"""
    cred_file = CREDENTIALS_DIR / f"oauth-{profile}.json"
    if not cred_file.exists():
        raise FileNotFoundError(
            f"OAuth credentials not found: {cred_file}\n"
            f"Available profiles: {[f.stem.replace('oauth-', '') for f in CREDENTIALS_DIR.glob('oauth-*.json')]}"
        )

    with open(cred_file, encoding="utf-8") as f:
        data = json.load(f)

    creds = oauth2_credentials.Credentials(
        token=None,
        refresh_token=data["refresh_token"],
        token_uri=data.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=data["client_id"],
        client_secret=data["client_secret"],
        scopes=scopes,
    )

    # トークンをリフレッシュ
    request = google.auth.transport.requests.Request()
    creds.refresh(request)
    return creds


def _get_sa_credentials(scopes: list[str], sa_key_path: str = ""):
    """サービスアカウント認証

    sa_key_path 指定時はそのパスを優先（例: Search Console 用に別の
    鍵ファイルパスを渡す）。
    未指定時は環境変数 GA4_SA_KEY_PATH を確認し、それも無ければ
    CREDENTIALS_DIR/sa-key.json（GA4用。既定はホームフォルダ配下の
    ~/.saa/credentials/google-analytics/、準備手順は docs/setup-ga4.md）を使用する。
    """
    if sa_key_path:
        sa_file = Path(sa_key_path).expanduser()
    else:
        sa_file = Path(
            os.environ.get("GA4_SA_KEY_PATH", str(CREDENTIALS_DIR / "sa-key.json"))
        ).expanduser()
    if not sa_file.exists():
        raise FileNotFoundError(
            f"Service account key not found: {sa_file}\n"
            f"環境変数 GA4_SA_KEY_PATH で鍵のパスを指定するか、"
            f"{CREDENTIALS_DIR / 'sa-key.json'} に配置してください。"
        )

    creds = service_account.Credentials.from_service_account_file(
        str(sa_file), scopes=scopes
    )
    return creds


def test_connection(config: AuditConfig) -> dict:
    """認証テスト — アカウントサマリを取得して接続確認"""
    from google.analytics.admin_v1beta import AnalyticsAdminServiceClient

    creds = get_credentials(config)
    client = AnalyticsAdminServiceClient(credentials=creds)

    summaries = []
    for summary in client.list_account_summaries():
        account = {
            "account": summary.account,
            "display_name": summary.display_name,
            "properties": [],
        }
        for prop in summary.property_summaries:
            account["properties"].append({
                "property": prop.property,
                "display_name": prop.display_name,
            })
        summaries.append(account)

    return {"status": "ok", "accounts": summaries}


def test_data_connection(config: AuditConfig) -> dict:
    """GA4 Data APIと対象プロパティへの接続を、実データ取得なしで確認する。"""
    from google.analytics.data_v1beta import BetaAnalyticsDataClient

    creds = get_credentials(config)
    client = BetaAnalyticsDataClient(credentials=creds)
    metadata = client.get_metadata(name=f"properties/{config.property_id}/metadata")
    return {
        "status": "ok",
        "property": f"properties/{config.property_id}",
        "dimension_count": len(metadata.dimensions),
        "metric_count": len(metadata.metrics),
    }
