"""外部LLMが既定で自動起動されないことを確認する。"""

import pytest


def test_default_backend_is_none(monkeypatch):
    from measurement_design import llm_client

    monkeypatch.delenv("LLM_BACKEND", raising=False)
    assert llm_client.resolve_backend() == "none"
    assert llm_client.llm_available() is False


def test_none_backend_refuses_completion(monkeypatch):
    from measurement_design import llm_client

    monkeypatch.delenv("LLM_BACKEND", raising=False)
    with pytest.raises(RuntimeError, match="外部LLM補完を実行しません"):
        llm_client.complete_text("test")


def test_api_alias_is_kept_for_backward_compatibility(monkeypatch):
    from measurement_design import llm_client

    monkeypatch.setattr(llm_client, "_via_api", lambda *args: "ok")
    assert llm_client.complete_text("test", backend="api") == "ok"
    assert llm_client.complete_text("test", backend="anthropic_api") == "ok"
