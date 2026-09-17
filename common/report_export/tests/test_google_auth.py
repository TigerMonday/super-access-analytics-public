"""google_auth.pyの認証・依存解決のテスト。

google-api-python-client / google-auth は gdoc/gsheet を使わない利用者に強制しない任意
依存(pyproject.tomlのoptional-dependencies "google")。依存不足を明示的に注入し、
開発環境にGoogleライブラリや認証情報があっても外部接続せず検証する。
"""

from __future__ import annotations

import pytest
import builtins

from report_export import google_auth


@pytest.mark.parametrize("function,args,module", [
    (google_auth.get_credentials, (), "google.oauth2"),
    (google_auth.build_docs_service, (None,), "googleapiclient.discovery"),
    (google_auth.build_sheets_service, (None,), "googleapiclient.discovery"),
])
def test_missing_dependency_has_install_hint(monkeypatch, function, args, module):
    original_import = builtins.__import__

    def without_optional_dependency(name, *import_args, **kwargs):
        if name == module:
            raise ImportError(f"test dependency unavailable: {module}")
        return original_import(name, *import_args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_optional_dependency)
    with pytest.raises(RuntimeError, match="uv sync --extra google"):
        function(*args)


def test_extract_doc_id_from_url():
    url = "https://docs.google.com/document/d/AbC123-xyz/edit?usp=sharing"
    assert google_auth.extract_doc_id(url) == "AbC123-xyz"


def test_extract_doc_id_passthrough_when_raw_id():
    assert google_auth.extract_doc_id("AbC123-xyz") == "AbC123-xyz"


def test_extract_sheet_id_from_url():
    url = "https://docs.google.com/spreadsheets/d/QwE456-abc/edit#gid=0"
    assert google_auth.extract_sheet_id(url) == "QwE456-abc"


def test_extract_sheet_id_passthrough_when_raw_id():
    assert google_auth.extract_sheet_id("QwE456-abc") == "QwE456-abc"


def test_google_export_uses_dedicated_key_environment(monkeypatch, tmp_path):
    """GA4閲覧用の鍵を暗黙に使い回さず、Google出力専用設定だけを読む。"""
    ga4_key = tmp_path / "ga4.json"
    export_key = tmp_path / "export.json"
    monkeypatch.setenv("GA4_SA_KEY_PATH", str(ga4_key))
    monkeypatch.setenv("SAA_GOOGLE_EXPORT_SA_KEY_PATH", str(export_key))

    assert google_auth._default_sa_key_path() == export_key


def test_google_export_does_not_fall_back_to_ga4_key(monkeypatch, tmp_path):
    """専用設定が無い場合も、GA4鍵の環境変数へフォールバックしない。"""
    monkeypatch.setenv("GA4_SA_KEY_PATH", str(tmp_path / "ga4.json"))
    monkeypatch.delenv("SAA_GOOGLE_EXPORT_SA_KEY_PATH", raising=False)

    assert google_auth._default_sa_key_path() == google_auth._DEFAULT_SA_KEY_PATH_FALLBACK
