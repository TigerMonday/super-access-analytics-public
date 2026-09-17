"""GA4 設定確認パック — GTM API モジュール

Phase 3 で使用する GTM API ラッパー。
google-api-python-client (REST) 経由でコンテナのタグ/トリガー/変数を全量取得し、
GA4 との整合性を分析する。
"""

from __future__ import annotations

import json
import os
import re

from google_auth_httplib2 import AuthorizedHttp
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import build_http

from auth import get_credentials
from config import AuditConfig


def _service(config: AuditConfig):
    """Tag Manager API v2 サービスを構築

    通信検査ソフト（Norton等）の環境では、GTM API（google-api-python-client + httplib2 経由）が
    SSL証明書検証で失敗する（ssl.SSLCertVerificationError: unable to get local issuer certificate）。
    GA4 API（gRPC経由）は環境変数 GRPC_DEFAULT_SSL_ROOTS_FILE_PATH でCA証明書ファイルを指定すれば直るが、
    httplib2 は同名・別名を問わず環境変数を一切読まない仕様のため、それだけでは直らない
    （httplib2==0.31.2 のソースで os.environ 参照箇所を確認済み。ca_certs はコンストラクタ引数でのみ渡せる）。
    ここでは GA4 側と同じ GRPC_DEFAULT_SSL_ROOTS_FILE_PATH の値を、httplib2.Http(ca_certs=...) に
    明示的に渡すことで、利用者に環境変数を2つ設定させずに両方直す（docs/setup-ga4.md 参照）。
    """
    creds = get_credentials(config)
    http = build_http()
    ca_certs = os.environ.get("GRPC_DEFAULT_SSL_ROOTS_FILE_PATH")
    if ca_certs:
        http.ca_certs = ca_certs
    authed_http = AuthorizedHttp(creds, http=http)
    return build("tagmanager", "v2", http=authed_http)


# ──────────────────────────────────────
# アカウント・コンテナ
# ──────────────────────────────────────

def list_accounts(config: AuditConfig) -> list[dict]:
    """GTM アカウント一覧"""
    service = _service(config)
    response = service.accounts().list().execute()
    return response.get("account", [])


def list_containers(config: AuditConfig) -> list[dict]:
    """GTM コンテナ一覧"""
    service = _service(config)
    parent = f"accounts/{config.gtm_account_id}"
    response = service.accounts().containers().list(parent=parent).execute()
    return response.get("container", [])


def resolve_container_id(config: AuditConfig) -> str:
    """公開ID（GTM-XXXX）をAPI用の数値containerIdへ解決する。数値ならそのまま返す。"""
    raw = str(config.gtm_container_id or "").strip()
    if not raw.upper().startswith("GTM-"):
        return raw
    match = next(
        (c for c in list_containers(config) if str(c.get("publicId", "")).upper() == raw.upper()),
        None,
    )
    if not match or not match.get("containerId"):
        raise ValueError(
            f"GTM公開ID {raw} に対応するコンテナをアカウント {config.gtm_account_id} で見つけられません"
        )
    return str(match["containerId"])


def get_live_version(config: AuditConfig) -> dict:
    """実際に公開中（live/published）のバージョンを取得する

    GTM API v2 の `accounts.containers.versions.live`（`versions:live`）エンドポイントを使う。
    これは `version_headers().latest()` とは別物なので注意:
    - `version_headers().latest()` は「最後に保存されたワークスペース由来の最新バージョン」を返す。
      公開待ちの下書き（未公開の変更）を含みうるため、"live" ではない（旧実装のバグ。docs/code-review-0702.md B-3）。
    - `versions().live()` は `ContainerVersionHeader`（件数だけ）ではなく `ContainerVersion` 本体
      （tag/trigger/variable を含む全量）を直接返す。

    一度も公開されたことがないコンテナでは 404 (HttpError) になるため、
    その場合は空 dict ({}) を返す（＝公開バージョンなし）。
    サイレントに最新保存版へフォールバックして「公開版」と偽ることはしない。
    """
    service = _service(config)
    parent = f"accounts/{config.gtm_account_id}/containers/{config.gtm_container_id}"
    try:
        return service.accounts().containers().versions().live(parent=parent).execute()
    except HttpError as e:
        if e.resp.status == 404:
            return {}
        raise


def get_version(config: AuditConfig, version_id: str) -> dict:
    """特定バージョンの取得（タグ/トリガー/変数を含む全量）"""
    service = _service(config)
    path = f"accounts/{config.gtm_account_id}/containers/{config.gtm_container_id}/versions/{version_id}"
    return service.accounts().containers().versions().get(path=path).execute()


# ──────────────────────────────────────
# タグ/トリガー/変数（ワークスペース経由）
# ──────────────────────────────────────

def _workspace_path(config: AuditConfig) -> str:
    """デフォルトワークスペースパス"""
    return f"accounts/{config.gtm_account_id}/containers/{config.gtm_container_id}/workspaces/Default"


def list_tags(config: AuditConfig) -> list[dict]:
    """全タグの取得"""
    service = _service(config)
    response = service.accounts().containers().workspaces().tags().list(
        parent=_workspace_path(config)
    ).execute()
    return response.get("tag", [])


def list_triggers(config: AuditConfig) -> list[dict]:
    """全トリガーの取得"""
    service = _service(config)
    response = service.accounts().containers().workspaces().triggers().list(
        parent=_workspace_path(config)
    ).execute()
    return response.get("trigger", [])


def list_variables(config: AuditConfig) -> list[dict]:
    """全変数の取得"""
    service = _service(config)
    response = service.accounts().containers().workspaces().variables().list(
        parent=_workspace_path(config)
    ).execute()
    return response.get("variable", [])


def list_built_in_variables(config: AuditConfig) -> list[dict]:
    """組み込み変数の一覧"""
    service = _service(config)
    response = service.accounts().containers().workspaces().built_in_variables().list(
        parent=_workspace_path(config)
    ).execute()
    return response.get("builtInVariable", [])


def get_all_from_version(config: AuditConfig) -> dict:
    """公開バージョンからタグ/トリガー/変数を一括取得

    ワークスペースAPIより確実。公開中の構成を取得する。
    `get_live_version()` が返す `ContainerVersion` は tag/trigger/variable を
    すでに含む全量のため、`get_version()` での再取得は不要。
    """
    # 実際に公開中のバージョン（tag/trigger/variable含む全量）を取得
    version = get_live_version(config)
    version_id = version.get("containerVersionId", "")
    if not version_id:
        raise ValueError(
            "公開バージョンが見つかりません（このコンテナは一度も公開されていない可能性があります）"
        )

    return {
        "version_id": version_id,
        "name": version.get("name", ""),
        "description": version.get("description", ""),
        "tags": version.get("tag", []),
        "triggers": version.get("trigger", []),
        "variables": version.get("variable", []),
        "builtInVariables": version.get("builtInVariable", []),
    }


# ──────────────────────────────────────
# 分析ヘルパー
# ──────────────────────────────────────

TAG_TYPES = {
    "googtag": "Google タグ（基盤）",
    "gaawe": "GA4 イベントタグ",
    "html": "カスタム HTML",
    "cvt_": "コミュニティテンプレート",
}

TRIGGER_TYPES = {
    "pageview": "ページビュー",
    "customEvent": "カスタムイベント",
    "linkClick": "リンクのクリック",
    "click": "全要素のクリック",
    "historyChange": "履歴変更（SPA）",
    "elementVisibility": "要素の表示",
    "scrollDepth": "スクロール深度",
    "domReady": "DOM Ready",
    "windowLoaded": "ウィンドウ読み込み完了",
}

VARIABLE_TYPES = {
    "v": "dataLayer 変数",
    "jsm": "カスタム JavaScript",
    "c": "定数",
    "smm": "ルックアップテーブル",
    "gtes": "Google タグ イベント設定",
    "cvt_": "コミュニティテンプレート",
}


def classify_tag_type(tag: dict) -> str:
    """タグタイプの分類"""
    tag_type = tag.get("type", "")
    for key, label in TAG_TYPES.items():
        if tag_type.startswith(key):
            return label
    return f"その他（{tag_type}）"


def extract_tag_params(tag: dict) -> dict:
    """タグからパラメータを抽出"""
    params = {}
    for p in tag.get("parameter", []):
        key = p.get("key", "")
        value = p.get("value", "")
        if p.get("type") == "LIST":
            value = p.get("list", [])
        elif p.get("type") == "MAP":
            value = p.get("map", [])
        params[key] = value
    return params


def extract_ga4_event_info(tag: dict) -> dict | None:
    """GA4 イベントタグから送信情報を抽出"""
    if tag.get("type") != "gaawe":
        return None

    params = extract_tag_params(tag)
    event_name = params.get("eventName", "")
    settings_var = params.get("eventSettingsVariable", "")
    settings_table = params.get("eventSettingsTable", [])

    tag_params = {}
    if isinstance(settings_table, list):
        for item in settings_table:
            if isinstance(item, dict) and "map" in item:
                for m in item["map"]:
                    if m.get("key") == "parameter":
                        tag_params[m.get("value", "")] = ""
                    elif m.get("key") == "parameterValue":
                        pass

    return {
        "tag_name": tag.get("name", ""),
        "event_name": event_name,
        "settings_variable": settings_var,
        "tag_specific_params": tag_params,
        "firing_trigger_ids": tag.get("firingTriggerId", []),
    }


def extract_datalayer_events(tag: dict) -> list[str]:
    """カスタム HTML タグから dataLayer push イベント名を抽出"""
    if tag.get("type") != "html":
        return []

    params = extract_tag_params(tag)
    html_content = params.get("html", "")

    pattern = r"""dataLayer\.push\s*\(\s*\{[^}]*['"]event['"]\s*:\s*['"]([^'"]+)['"]"""
    return re.findall(pattern, html_content)


def build_trigger_map(triggers: list[dict]) -> dict[str, dict]:
    """トリガーID → トリガー情報のマップを構築"""
    return {t.get("triggerId", ""): t for t in triggers}


def get_measurement_ids(tags: list[dict], variables: list[dict]) -> list[str]:
    """GTM から設定されている測定 ID を全て抽出"""
    ids = set()

    for tag in tags:
        params = extract_tag_params(tag)
        if tag.get("type") == "googtag":
            tag_id = params.get("tagId", "")
            if tag_id.startswith("G-"):
                ids.add(tag_id)
            elif tag_id.startswith("{{"):
                var_name = tag_id.strip("{}")
                for v in variables:
                    if v.get("name") == var_name:
                        v_params = extract_tag_params(v)
                        val = v_params.get("value", "")
                        if val.startswith("G-"):
                            ids.add(val)
        if tag.get("type") == "gaawe":
            mid = params.get("measurementId", "")
            if mid.startswith("G-"):
                ids.add(mid)

    return sorted(ids)


# ──────────────────────────────────────
# CLI テスト
# ──────────────────────────────────────

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 4:
        print("Usage: python gtm.py <gtm_account_id> <gtm_container_id> <function_name>")
        print("Functions: list_accounts, get_all_from_version, list_tags, list_triggers, list_variables, ...")
        sys.exit(1)

    config = AuditConfig(
        property_id="0",
        client_name="_test",
        gtm_account_id=sys.argv[1],
        gtm_container_id=sys.argv[2],
    )
    func_name = sys.argv[3]
    func = globals().get(func_name)

    if func is None:
        print(f"Unknown function: {func_name}")
        sys.exit(1)

    result = func(config)
    print(json.dumps(result, indent=2, ensure_ascii=False))
