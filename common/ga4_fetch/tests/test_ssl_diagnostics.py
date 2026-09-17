from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ssl_diagnostics import ENV_NAME, ssl_error_hint, validate_configured_roots  # noqa: E402


def test_missing_current_process_setting_mentions_restart(monkeypatch):
    monkeypatch.delenv(ENV_NAME, raising=False)
    hint = ssl_error_hint(RuntimeError("CERTIFICATE_VERIFY_FAILED"))
    assert hint is not None
    assert "開き直す" in hint


def test_invalid_configured_path_fails_preflight(monkeypatch, tmp_path):
    missing = tmp_path / "missing.pem"
    monkeypatch.setenv(ENV_NAME, str(missing))
    with pytest.raises(RuntimeError, match="証明書ファイルが見つかりません"):
        validate_configured_roots()


def test_unrelated_error_has_no_hint():
    assert ssl_error_hint(RuntimeError("permission denied")) is None
