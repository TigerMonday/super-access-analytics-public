"""GA4 設定確認パック — Admin API モジュール

Phase 1 / Phase 2 / Phase 9 で使用する Admin API ラッパー。
GA4 プロパティの設定情報を取得する。
"""

from __future__ import annotations

import json
from dataclasses import asdict

from google.analytics.admin_v1beta import AnalyticsAdminServiceClient as BetaClient
from google.analytics.admin_v1alpha import AnalyticsAdminServiceClient as AlphaClient
from google.protobuf.json_format import MessageToDict

from auth import get_credentials
from config import AuditConfig


def _client(config: AuditConfig) -> BetaClient:
    return BetaClient(credentials=get_credentials(config))


def _alpha_client(config: AuditConfig) -> AlphaClient:
    return AlphaClient(credentials=get_credentials(config))


def _to_dict(proto_msg) -> dict:
    """protobuf メッセージを dict に変換"""
    return MessageToDict(type(proto_msg).pb(proto_msg), preserving_proto_field_name=True)


# ──────────────────────────────────────
# Phase 1: プロパティ設定の取得
# ──────────────────────────────────────

def get_account_summaries(config: AuditConfig) -> list[dict]:
    """アカウント・プロパティの一覧"""
    client = _client(config)
    results = []
    for summary in client.list_account_summaries():
        results.append(_to_dict(summary))
    return results


def get_property_details(config: AuditConfig) -> dict:
    """プロパティ詳細（業種、タイムゾーン、通貨など）"""
    client = _client(config)
    prop = client.get_property(name=config.property_resource)
    return _to_dict(prop)


def list_data_streams(config: AuditConfig) -> list[dict]:
    """データストリーム一覧"""
    client = _client(config)
    return [_to_dict(s) for s in client.list_data_streams(parent=config.property_resource)]


def get_enhanced_measurement_settings(config: AuditConfig, data_stream_id: str) -> dict:
    """拡張計測の設定（v1alpha）"""
    client = _alpha_client(config)
    name = f"{config.property_resource}/dataStreams/{data_stream_id}/enhancedMeasurementSettings"
    settings = client.get_enhanced_measurement_settings(name=name)
    return _to_dict(settings)


def get_data_retention_settings(config: AuditConfig) -> dict:
    """データ保持設定"""
    client = _client(config)
    settings = client.get_data_retention_settings(name=f"{config.property_resource}/dataRetentionSettings")
    return _to_dict(settings)


def get_google_signals_settings(config: AuditConfig) -> dict:
    """Google シグナル設定（v1alpha）"""
    client = _alpha_client(config)
    settings = client.get_google_signals_settings(name=f"{config.property_resource}/googleSignalsSettings")
    return _to_dict(settings)


def get_user_provided_data_settings(config: AuditConfig) -> dict:
    """ユーザー提供データの収集設定（v1alpha）"""
    client = _alpha_client(config)
    settings = client.get_user_provided_data_settings(
        name=f"{config.property_resource}/userProvidedDataSettings"
    )
    return _to_dict(settings)


def get_reporting_identity_settings(config: AuditConfig) -> dict:
    """レポート用識別子の設定（v1alpha）"""
    client = _alpha_client(config)
    settings = client.get_reporting_identity_settings(
        name=f"{config.property_resource}/reportingIdentitySettings"
    )
    return _to_dict(settings)


def get_attribution_settings(config: AuditConfig) -> dict:
    """アトリビューション設定（v1alpha）"""
    client = _alpha_client(config)
    settings = client.get_attribution_settings(name=f"{config.property_resource}/attributionSettings")
    return _to_dict(settings)


def list_google_ads_links(config: AuditConfig) -> list[dict]:
    """Google 広告リンク一覧"""
    client = _client(config)
    return [_to_dict(link) for link in client.list_google_ads_links(parent=config.property_resource)]


def list_big_query_links(config: AuditConfig) -> list[dict]:
    """BigQuery エクスポート連携の一覧。

    BigQuery 自体の閲覧権限が無くても、この設定は GA4 の権限だけで読める。
    `excluded_events`（エクスポート対象から外したイベント）は、
    クライアント側が「使えない」と判断済みのイベントの一覧として読める。
    診断の裏付けとして価値が高いので、権限が無い案件でも必ず取得する。
    """
    client = _alpha_client(config)
    return [_to_dict(link) for link in client.list_big_query_links(parent=config.property_resource)]


def list_custom_dimensions(config: AuditConfig) -> list[dict]:
    """カスタムディメンション一覧"""
    client = _client(config)
    return [_to_dict(d) for d in client.list_custom_dimensions(parent=config.property_resource)]


def list_custom_metrics(config: AuditConfig) -> list[dict]:
    """カスタム指標一覧"""
    client = _client(config)
    return [_to_dict(m) for m in client.list_custom_metrics(parent=config.property_resource)]


# ──────────────────────────────────────
# Phase 2: キーイベント・オーディエンス
# ──────────────────────────────────────

def list_key_events(config: AuditConfig) -> list[dict]:
    """キーイベント一覧"""
    client = _client(config)
    return [_to_dict(k) for k in client.list_key_events(parent=config.property_resource)]


def list_audiences(config: AuditConfig) -> list[dict]:
    """オーディエンス一覧（v1alpha）"""
    client = _alpha_client(config)
    return [_to_dict(a) for a in client.list_audiences(parent=config.property_resource)]


# ──────────────────────────────────────
# Phase 4: Admin API alpha 拡張
# ──────────────────────────────────────

def search_change_history(config: AuditConfig, resource_types: list[str] | None = None) -> list[dict]:
    """Change History の検索（データフィルタ等の確認）"""
    from google.analytics.admin_v1alpha.types import SearchChangeHistoryEventsRequest

    client = _alpha_client(config)
    request = SearchChangeHistoryEventsRequest(
        account=config.account_resource,
        property=config.property_resource,
    )
    if resource_types:
        request.resource_type = resource_types

    results = []
    for event in client.search_change_history_events(request=request):
        results.append(_to_dict(event))
    return results


def list_event_create_rules(config: AuditConfig, data_stream_id: str) -> list[dict]:
    """イベント作成ルール一覧（v1alpha）"""
    client = _alpha_client(config)
    parent = f"{config.property_resource}/dataStreams/{data_stream_id}"
    return [_to_dict(r) for r in client.list_event_create_rules(parent=parent)]


# ──────────────────────────────────────
# CLI テスト
# ──────────────────────────────────────

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print("Usage: python ga4_admin.py <property_id> <function_name> [args...]")
        print("Functions: get_account_summaries, get_property_details, list_data_streams, ...")
        sys.exit(1)

    config = AuditConfig(property_id=sys.argv[1], client_name="_test")
    func_name = sys.argv[2]
    func = globals().get(func_name)

    if func is None:
        print(f"Unknown function: {func_name}")
        sys.exit(1)

    result = func(config, *sys.argv[3:]) if len(sys.argv) > 3 else func(config)
    print(json.dumps(result, indent=2, ensure_ascii=False))
