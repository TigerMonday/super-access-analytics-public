"""run_phase.save_result のユニットテスト.

`_data/phase*.json` は `dataset.split_and_save` 経由の新設3ファイルと違い、
`save_result` が素の json.dump のままだと個人情報が平文で残ってしまう
（phase2.json はカスタムディメンションの実測サンプル値を含むため特に問題）。
保存前に pii.redact_obj を通すことを確認する。
"""

import json
import sys
import types

import config as config_module
import auth as auth_module
import run_phase
from config import AuditConfig


def _make_config(tmp_path, monkeypatch):
    monkeypatch.setattr(config_module, "PROJECT_ROOT", tmp_path / "measurement_design")
    monkeypatch.setattr(config_module, "REPO_ROOT", tmp_path)
    return AuditConfig(property_id="123", client_name="sample-client")


def test_save_result_redacts_email_in_saved_file(tmp_path, monkeypatch, capsys):
    cfg = _make_config(tmp_path, monkeypatch)
    data = {
        "custom_dimensions_sample": [
            {"parameter_name": "user_email", "example_value": "taro.yamada@example.com"},
        ],
        "note": "連絡先は staff@example.org です",
    }

    run_phase.save_result(cfg, "phase2", data)

    out_file = cfg.data_dir / "phase2.json"
    raw = out_file.read_text(encoding="utf-8")
    assert "taro.yamada@example.com" not in raw
    assert "staff@example.org" not in raw

    saved = json.loads(raw)
    assert saved["custom_dimensions_sample"][0]["example_value"] == "[redacted:pii]"

    # 何件伏せたかがログに出て、利用者が気づける
    captured = capsys.readouterr()
    assert "2" in captured.out
    assert "伏せました" in captured.out


def test_save_result_keeps_clean_data_untouched(tmp_path, monkeypatch, capsys):
    cfg = _make_config(tmp_path, monkeypatch)
    data = {"event_name": "cv_reserve", "sessions": 10}

    run_phase.save_result(cfg, "phase1", data)

    out_file = cfg.data_dir / "phase1.json"
    saved = json.loads(out_file.read_text(encoding="utf-8"))
    assert saved == data

    captured = capsys.readouterr()
    assert "伏せました" not in captured.out


def test_run_phase2_saves_full_event_name_counts(monkeypatch, tmp_path):
    cfg = _make_config(tmp_path, monkeypatch)
    full_rows = [
        {"eventName": "page_view", "eventCount": "1000"},
        {"eventName": "rare_conversion", "eventCount": "1"},
    ]

    def run_report(_config, *, dimensions, metrics, **kwargs):
        if dimensions == []:
            return [{"sessions": "10", "eventCount": "100"}]
        if dimensions == ["eventName"] and kwargs.get("limit") == 0:
            return full_rows
        return []

    fake_api = types.SimpleNamespace(
        get_event_list=lambda _config, days: [full_rows[0]],
        run_report=run_report,
        filter_exact=lambda field, value: {"field": field, "value": value},
        filter_not=lambda value: {"not": value},
    )
    monkeypatch.setitem(sys.modules, "ga4_data", fake_api)
    captured = {}
    monkeypatch.setattr(run_phase, "save_result", lambda _config, _phase, data: captured.update(data))

    run_phase.run_phase2(cfg)

    assert captured["event_name_counts_30d"] == full_rows
    assert captured["event_name_counts_status"] == "complete"
    assert captured["event_name_total"]["distinct_event_names"] == 2


def test_run_phase1_collects_new_property_settings(monkeypatch, tmp_path):
    cfg = _make_config(tmp_path, monkeypatch)
    fake_admin = types.SimpleNamespace(
        get_property_details=lambda _config: {"name": "properties/123"},
        list_data_streams=lambda _config: [],
        get_data_retention_settings=lambda _config: {"event_data_retention": "FOURTEEN_MONTHS"},
        get_google_signals_settings=lambda _config: {"state": "GOOGLE_SIGNALS_ENABLED"},
        get_user_provided_data_settings=lambda _config: {"user_provided_data_collection_enabled": True},
        get_reporting_identity_settings=lambda _config: {"reporting_identity": "BLENDED"},
        get_attribution_settings=lambda _config: {"reporting_attribution_model": "DATA_DRIVEN"},
        list_google_ads_links=lambda _config: [],
        list_big_query_links=lambda _config: [],
        list_custom_dimensions=lambda _config: [],
        list_custom_metrics=lambda _config: [],
        list_key_events=lambda _config: [],
        list_audiences=lambda _config: [],
    )
    monkeypatch.setitem(sys.modules, "ga4_admin", fake_admin)
    captured = {}
    monkeypatch.setattr(run_phase, "save_result", lambda _config, _phase, data: captured.update(data))

    run_phase.run_phase1(cfg)

    assert captured["user_provided_data"]["user_provided_data_collection_enabled"] is True
    assert captured["reporting_identity"]["reporting_identity"] == "BLENDED"


def test_preflight_checks_admin_and_data_api(monkeypatch, tmp_path, capsys):
    cfg = _make_config(tmp_path, monkeypatch)
    monkeypatch.setattr(
        auth_module,
        "test_connection",
        lambda config: {
            "status": "ok",
            "accounts": [
                {
                    "account": "accounts/1",
                    "display_name": "テスト",
                    "properties": [
                        {"property": "properties/123", "display_name": "対象サイト"}
                    ],
                }
            ],
        },
    )
    called = []
    monkeypatch.setattr(
        auth_module, "test_data_connection", lambda config: called.append(config.property_id)
    )

    assert run_phase.run_preflight(cfg) == 0
    assert called == ["123"]
    assert "Data APIへ接続できました" in capsys.readouterr().out


def test_preflight_fails_when_data_api_is_unavailable(monkeypatch, tmp_path, capsys):
    cfg = _make_config(tmp_path, monkeypatch)
    monkeypatch.setattr(
        auth_module,
        "test_connection",
        lambda config: {
            "status": "ok",
            "accounts": [
                {
                    "properties": [
                        {"property": "properties/123", "display_name": "対象サイト"}
                    ]
                }
            ],
        },
    )

    def _fail(config):
        raise RuntimeError("API disabled")

    monkeypatch.setattr(auth_module, "test_data_connection", _fail)

    assert run_phase.run_preflight(cfg) == 1
    assert "Data APIへ接続できません" in capsys.readouterr().out


def test_preflight_does_not_accept_partial_property_id_match(monkeypatch, tmp_path):
    cfg = _make_config(tmp_path, monkeypatch)
    monkeypatch.setattr(
        auth_module,
        "test_connection",
        lambda config: {
            "status": "ok",
            "accounts": [
                {
                    "properties": [
                        {"property": "properties/1234", "display_name": "別サイト"}
                    ]
                }
            ],
        },
    )
    monkeypatch.setattr(
        auth_module,
        "test_data_connection",
        lambda config: (_ for _ in ()).throw(AssertionError("呼ばれてはいけません")),
    )

    assert run_phase.run_preflight(cfg) == 1
