"""auth.py のユニットテスト.

サービスアカウント鍵パスの解決順（引数 sa_key_path → 環境変数 GA4_SA_KEY_PATH →
既定パス CREDENTIALS_DIR/sa-key.json）を検証する。鍵ファイルの中身までは
検証しないため、実在しないパスを使い FileNotFoundError のメッセージで
解決先を確認する（実APIには到達しない）。
"""
from unittest.mock import patch

import pytest

import auth as auth_module


def test_data_connection_uses_metadata_without_reading_report_data(monkeypatch):
    config = type("Config", (), {"property_id": "123456789"})()
    monkeypatch.setattr(auth_module, "get_credentials", lambda config: object())
    with patch("google.analytics.data_v1beta.BetaAnalyticsDataClient") as client_class:
        metadata = client_class.return_value.get_metadata.return_value
        metadata.dimensions = [object(), object()]
        metadata.metrics = [object()]

        result = auth_module.test_data_connection(config)

    client_class.return_value.get_metadata.assert_called_once_with(
        name="properties/123456789/metadata"
    )
    assert result["status"] == "ok"
    assert result["dimension_count"] == 2
    assert result["metric_count"] == 1


def test_sa_credentials_uses_default_path_when_no_arg_and_no_env(monkeypatch, tmp_path):
    fake_credentials_dir = tmp_path / "credentials-dir"
    monkeypatch.setattr(auth_module, "CREDENTIALS_DIR", fake_credentials_dir)
    monkeypatch.delenv("GA4_SA_KEY_PATH", raising=False)

    with pytest.raises(FileNotFoundError) as exc_info:
        auth_module._get_sa_credentials(scopes=[])

    assert str(fake_credentials_dir / "sa-key.json") in str(exc_info.value)


def test_sa_credentials_uses_env_var_when_no_arg(monkeypatch, tmp_path):
    fake_credentials_dir = tmp_path / "credentials-dir"
    monkeypatch.setattr(auth_module, "CREDENTIALS_DIR", fake_credentials_dir)
    env_path = tmp_path / "env-provided" / "sa-key.json"
    monkeypatch.setenv("GA4_SA_KEY_PATH", str(env_path))

    with pytest.raises(FileNotFoundError) as exc_info:
        auth_module._get_sa_credentials(scopes=[])

    assert str(env_path) in str(exc_info.value)
    assert str(fake_credentials_dir / "sa-key.json") not in str(exc_info.value).split("\n")[0]


def test_sa_credentials_prefers_explicit_arg_over_env(monkeypatch, tmp_path):
    monkeypatch.setenv("GA4_SA_KEY_PATH", str(tmp_path / "env-provided" / "sa-key.json"))
    explicit_path = tmp_path / "explicit" / "sa-key.json"

    with pytest.raises(FileNotFoundError) as exc_info:
        auth_module._get_sa_credentials(scopes=[], sa_key_path=str(explicit_path))

    assert str(explicit_path) in str(exc_info.value)


def test_sa_credentials_falls_back_to_default_after_env_unset(monkeypatch, tmp_path):
    """環境変数を一度立ててから外すと既定パスに戻ることを確認する。"""
    fake_credentials_dir = tmp_path / "credentials-dir"
    monkeypatch.setattr(auth_module, "CREDENTIALS_DIR", fake_credentials_dir)

    monkeypatch.setenv("GA4_SA_KEY_PATH", str(tmp_path / "env-provided" / "sa-key.json"))
    with pytest.raises(FileNotFoundError) as exc_info:
        auth_module._get_sa_credentials(scopes=[])
    assert str(tmp_path / "env-provided" / "sa-key.json") in str(exc_info.value)

    monkeypatch.delenv("GA4_SA_KEY_PATH", raising=False)
    with pytest.raises(FileNotFoundError) as exc_info:
        auth_module._get_sa_credentials(scopes=[])
    assert str(fake_credentials_dir / "sa-key.json") in str(exc_info.value)
