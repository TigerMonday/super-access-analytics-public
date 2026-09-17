from __future__ import annotations

import json
import subprocess
from pathlib import Path

import yaml

from tools import setup_status


def _valid_key(secret: str = "DO-NOT-PRINT") -> dict:
    return {
        "type": "service_account",
        "project_id": "sample-project",
        setup_status.PRIVATE_KEY_FIELD: secret,
        setup_status.CLIENT_EMAIL_FIELD: "reader@example.com",
        "token_uri": "https://oauth2.googleapis.com/token",
    }


def test_missing_default_key_is_reported(tmp_path: Path):
    result = setup_status.check_google_key(tmp_path, {})

    assert result["state"] == "missing"
    assert result["source"] == "default"
    assert Path(result["path"]) == tmp_path / DEFAULT_KEY_NAME


def test_environment_key_path_takes_priority(tmp_path: Path):
    key = tmp_path / "custom.json"
    key.write_text(json.dumps(_valid_key()), encoding="utf-8")

    result = setup_status.check_google_key(tmp_path / "home", {"GA4_SA_KEY_PATH": str(key)})

    assert result["state"] == "ready"
    assert result["source"] == "GA4_SA_KEY_PATH"
    assert result["service_account_email"] == "reader@example.com"


def test_optional_connection_uses_ga4_key_by_default(tmp_path: Path):
    key = tmp_path / DEFAULT_KEY_NAME
    key.parent.mkdir(parents=True)
    key.write_text(json.dumps(_valid_key()), encoding="utf-8")
    ga4_key = setup_status.check_google_key(tmp_path, {})

    result = setup_status.check_effective_optional_key(
        tmp_path, {}, variable="SC_SA_KEY_PATH", ga4_key=ga4_key
    )

    assert result["state"] == "shared"
    assert result["service_account_email"] == "reader@example.com"


def test_optional_connection_reports_separate_key(tmp_path: Path):
    ga4_path = tmp_path / DEFAULT_KEY_NAME
    ga4_path.parent.mkdir(parents=True)
    ga4_path.write_text(json.dumps(_valid_key()), encoding="utf-8")
    separate = tmp_path / "search-console.json"
    payload = _valid_key()
    payload[setup_status.CLIENT_EMAIL_FIELD] = "search-console@example.com"
    separate.write_text(json.dumps(payload), encoding="utf-8")
    ga4_key = setup_status.check_google_key(tmp_path, {})

    result = setup_status.check_effective_optional_key(
        tmp_path,
        {"SC_SA_KEY_PATH": str(separate)},
        variable="SC_SA_KEY_PATH",
        ga4_key=ga4_key,
    )

    assert result["state"] == "ready"
    assert result["source"] == "SC_SA_KEY_PATH"
    assert result["service_account_email"] == "search-console@example.com"


def test_secret_key_value_is_never_returned_or_rendered(tmp_path: Path):
    secret = "LOCAL-TEST-SECRET-THAT-MUST-NOT-BE-PRINTED"
    key = tmp_path / DEFAULT_KEY_NAME
    key.parent.mkdir(parents=True)
    key.write_text(json.dumps(_valid_key(secret)), encoding="utf-8")

    result = setup_status.check_google_key(tmp_path, {})
    rendered = json.dumps(result, ensure_ascii=False)

    assert result["state"] == "ready"
    assert secret not in rendered
    assert setup_status.PRIVATE_KEY_FIELD not in result


DEFAULT_KEY_NAME = Path(".saa/credentials/google-analytics/sa-key.json")


def test_context_reports_saved_connections(tmp_path: Path):
    client = tmp_path / "my-site"
    client.mkdir()
    (client / "profile.yaml").write_text(
        yaml.safe_dump(
            {"client": {"client_id": "my-site", "name": "自社サイト", "site_url": "https://example.com/"}},
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    (client / "measurement.yaml").write_text(
        yaml.safe_dump(
            {
                "ga4": {"property_id": "123456789"},
                "search_console": {"site_url": "sc-domain:example.com"},
                "bigquery": {"project_id": "analytics-project", "dataset": "analytics_123456789"},
            }
        ),
        encoding="utf-8",
    )
    (client / "kpis.yaml").write_text(
        yaml.safe_dump({"key_events": ["generate_lead"]}), encoding="utf-8"
    )

    result = setup_status.check_context(tmp_path)

    assert result["state"] == "ready"
    assert result["clients"] == [
        {
            "client_id": "my-site",
            "site_name": "自社サイト",
            "site_url": "https://example.com/",
            "ga4_property_id": "123456789",
            "search_console_site_url": "sc-domain:example.com",
            "bigquery_project_id": "analytics-project",
            "bigquery_dataset": "analytics_123456789",
            "key_event_count": 1,
        }
    ]


def test_next_step_skips_completed_local_steps():
    checks = {
        "repository": {"state": "ready"},
        "uv": {"state": "ready"},
        "sample": {"state": "ready"},
        "google_key": {"state": "ready"},
        "context": {"state": "ready"},
    }

    assert setup_status.choose_next_step(checks) == "verify_google_connections"


def test_local_status_never_claims_online_analysis_is_ready(monkeypatch, tmp_path: Path):
    key = tmp_path / DEFAULT_KEY_NAME
    key.parent.mkdir(parents=True)
    key.write_text(json.dumps(_valid_key()), encoding="utf-8")
    context = tmp_path / "context" / "my-site"
    context.mkdir(parents=True)
    (context / "profile.yaml").write_text(
        yaml.safe_dump({"client": {"name": "自社サイト"}}, allow_unicode=True),
        encoding="utf-8",
    )
    (context / "measurement.yaml").write_text(
        yaml.safe_dump({"ga4": {"property_id": "123456789"}}), encoding="utf-8"
    )
    monkeypatch.setattr(setup_status, "check_uv", lambda: {"state": "ready"})
    monkeypatch.setattr(
        setup_status,
        "check_sample",
        lambda root, run_check, uv_status: {"state": "ready"},
    )

    result = setup_status.collect_status(
        root=setup_status.REPO_ROOT,
        home=tmp_path,
        env={},
        context_dir=tmp_path / "context",
        run_sample_check=True,
    )

    assert result["overall"] == "needs_online_verification"
    assert result["next_step"] == "verify_google_connections"


def test_invalid_json_is_reported_without_file_contents(tmp_path: Path):
    key = tmp_path / DEFAULT_KEY_NAME
    key.parent.mkdir(parents=True)
    key.write_text("not-json SUPER-SECRET", encoding="utf-8")

    result = setup_status.check_google_key(tmp_path, {})

    assert result["state"] == "invalid"
    assert "SUPER-SECRET" not in json.dumps(result, ensure_ascii=False)


def test_sample_check_never_installs_dependencies(monkeypatch, tmp_path: Path):
    project = tmp_path / "02_basic_measurement" / "measurement_design"
    inputs = project / "sample-client" / "inputs"
    inputs.mkdir(parents=True)
    for name in ("kpis.yaml", "screen-flow.yaml", "ga4.local.yaml", "gtm.local.yaml"):
        (inputs / name).write_text("{}\n", encoding="utf-8")

    calls = []
    monkeypatch.setattr(setup_status.shutil, "which", lambda name: "uv")

    def _run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="[OK]", stderr="")

    monkeypatch.setattr(setup_status.subprocess, "run", _run)

    result = setup_status.check_sample(
        tmp_path, run_check=True, uv_status={"state": "ready"}
    )

    assert result["state"] == "ready"
    assert "--no-sync" in calls[0]
