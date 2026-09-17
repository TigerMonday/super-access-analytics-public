"""gtm.py のユニットテスト（docs/code-review-0702.md B-3 の回帰テスト）.

`get_live_version()` は「実際に公開中（live/published）のバージョン」を返すべきで、
`version_headers().latest()`（最後に保存されたワークスペース由来の最新バージョン。
公開待ちの下書きを含む）を使ってはいけない。

GTM API は実機で叩けないため、`gtm._service()` を疑似サービスに差し替えて
`accounts().containers().versions().live(parent=...)` が呼ばれることと、
一度も公開されていないコンテナ（404）でのフォールバック挙動を検証する。
"""
from __future__ import annotations

import httplib2
import pytest
from googleapiclient.errors import HttpError

import config as config_module
import gtm as gtm_module
from config import AuditConfig


# ──────────────────────────────────────
# 疑似 GTM API サービス
# ──────────────────────────────────────

class _FakeExecutable:
    def __init__(self, result=None, error=None):
        self._result = result
        self._error = error

    def execute(self):
        if self._error is not None:
            raise self._error
        return self._result


class _FakeVersionsResource:
    """`versions()` に相当。`live()` の呼び出しを記録する。"""

    def __init__(self, live_result=None, live_error=None):
        self._live_result = live_result
        self._live_error = live_error
        self.live_calls: list[str] = []

    def live(self, parent: str):
        self.live_calls.append(parent)
        return _FakeExecutable(result=self._live_result, error=self._live_error)

    def version_headers(self):
        raise AssertionError(
            "version_headers() は呼ばれてはいけない（B-3: latest() は公開版ではない）"
        )


class _FakeContainersResource:
    def __init__(self, versions_resource: _FakeVersionsResource):
        self._versions_resource = versions_resource

    def versions(self):
        return self._versions_resource


class _FakeAccountsResource:
    def __init__(self, containers_resource: _FakeContainersResource):
        self._containers_resource = containers_resource

    def containers(self):
        return self._containers_resource


class _FakeService:
    def __init__(self, versions_resource: _FakeVersionsResource):
        self._accounts_resource = _FakeAccountsResource(_FakeContainersResource(versions_resource))

    def accounts(self):
        return self._accounts_resource


def _make_http_error(status: int) -> HttpError:
    resp = httplib2.Response({"status": status})
    return HttpError(resp, b'{"error": {"message": "not found"}}')


@pytest.fixture
def config(monkeypatch, tmp_path) -> AuditConfig:
    """テスト用 AuditConfig。ディレクトリ作成先をリポジトリ外の tmp_path に逃がす。"""
    monkeypatch.setattr(config_module, "PROJECT_ROOT", tmp_path / "measurement_design")
    monkeypatch.setattr(config_module, "REPO_ROOT", tmp_path)
    return AuditConfig(
        property_id="123",
        client_name="sample-client",
        gtm_account_id="1111",
        gtm_container_id="2222",
    )


LIVE_VERSION = {
    "containerVersionId": "42",
    "name": "公開バージョン",
    "description": "本番公開中",
    "tag": [{"name": "GA4 Config", "type": "googtag"}],
    "trigger": [{"name": "All Pages", "triggerId": "1"}],
    "variable": [{"name": "GA4 Measurement ID"}],
    "builtInVariable": [{"name": "Page URL"}],
}


def test_get_live_version_calls_versions_live_with_correct_parent(monkeypatch, config):
    """`version_headers().latest()` ではなく `versions().live()` を、正しい parent で呼ぶこと。"""
    versions_resource = _FakeVersionsResource(live_result=LIVE_VERSION)
    monkeypatch.setattr(
        gtm_module, "_service", lambda cfg: _FakeService(versions_resource)
    )

    result = gtm_module.get_live_version(config)

    assert versions_resource.live_calls == ["accounts/1111/containers/2222"]
    assert result == LIVE_VERSION


def test_get_live_version_returns_empty_dict_when_never_published(monkeypatch, config):
    """一度も公開されていないコンテナ（404）はサイレントに latest へフォールバックせず、
    空 dict（＝公開バージョンなし）を返すこと。"""
    versions_resource = _FakeVersionsResource(live_error=_make_http_error(404))
    monkeypatch.setattr(
        gtm_module, "_service", lambda cfg: _FakeService(versions_resource)
    )

    result = gtm_module.get_live_version(config)

    assert result == {}
    assert versions_resource.live_calls == ["accounts/1111/containers/2222"]


def test_get_live_version_reraises_non_404_http_error(monkeypatch, config):
    """404 以外（権限エラー等）は握りつぶさず、そのまま再送出すること。"""
    versions_resource = _FakeVersionsResource(live_error=_make_http_error(403))
    monkeypatch.setattr(
        gtm_module, "_service", lambda cfg: _FakeService(versions_resource)
    )

    with pytest.raises(HttpError) as exc_info:
        gtm_module.get_live_version(config)

    assert exc_info.value.resp.status == 403


def test_get_all_from_version_uses_live_tags_triggers_variables(monkeypatch, config):
    """`versions().live()` が返す ContainerVersion 全量から tags/triggers/variables を
    正しく取り出せること（get_version() の再取得なしで完結する）。"""
    versions_resource = _FakeVersionsResource(live_result=LIVE_VERSION)
    monkeypatch.setattr(
        gtm_module, "_service", lambda cfg: _FakeService(versions_resource)
    )

    result = gtm_module.get_all_from_version(config)

    assert result["version_id"] == "42"
    assert result["name"] == "公開バージョン"
    assert result["description"] == "本番公開中"
    assert result["tags"] == LIVE_VERSION["tag"]
    assert result["triggers"] == LIVE_VERSION["trigger"]
    assert result["variables"] == LIVE_VERSION["variable"]
    assert result["builtInVariables"] == LIVE_VERSION["builtInVariable"]
    # live() は一度だけ呼ばれる（version_headers 経由の二段取得は行わない）
    assert len(versions_resource.live_calls) == 1


def test_get_all_from_version_raises_value_error_when_no_live_version(monkeypatch, config):
    """公開バージョンが存在しない場合、成果物生成に進ませず明示的に ValueError で止めること。"""
    versions_resource = _FakeVersionsResource(live_error=_make_http_error(404))
    monkeypatch.setattr(
        gtm_module, "_service", lambda cfg: _FakeService(versions_resource)
    )

    with pytest.raises(ValueError, match="公開バージョンが見つかりません"):
        gtm_module.get_all_from_version(config)


def test_resolve_container_id_accepts_numeric_id_without_api_call(monkeypatch, config):
    config.gtm_container_id = "1234567"
    monkeypatch.setattr(gtm_module, "list_containers", lambda cfg: pytest.fail("API should not be called"))
    assert gtm_module.resolve_container_id(config) == "1234567"


def test_resolve_container_id_maps_public_id(monkeypatch, config):
    config.gtm_container_id = "GTM-XXXXXXX"
    monkeypatch.setattr(
        gtm_module, "list_containers",
        lambda cfg: [{"publicId": "GTM-XXXXXXX", "containerId": "7654321"}],
    )
    assert gtm_module.resolve_container_id(config) == "7654321"


def test_resolve_container_id_rejects_unknown_public_id(monkeypatch, config):
    config.gtm_container_id = "GTM-MISSING"  # leak-ok: 存在しないことを表すテスト専用ID
    monkeypatch.setattr(gtm_module, "list_containers", lambda cfg: [])
    with pytest.raises(ValueError, match="見つけられません"):
        gtm_module.resolve_container_id(config)
