from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import check_bigquery_access as target  # noqa: E402


@pytest.mark.parametrize(
    ("project_id", "dataset"),
    [
        ("UPPERCASE", "analytics_1"),
        ("short", "contains-hyphen"),
        ("valid-project", "contains-hyphen"),
    ],
)
def test_invalid_identifiers_are_rejected(project_id: str, dataset: str):
    with pytest.raises(ValueError):
        target.validate_identifiers(project_id, dataset)


def test_valid_identifiers_are_accepted():
    target.validate_identifiers("valid-project", "analytics_123456789")


def test_access_check_reads_metadata_and_uses_data_free_dry_run():
    with patch.object(target, "get_bigquery_credentials", return_value=object()):
        with patch("google.cloud.bigquery.Client") as client_class:
            client = client_class.return_value
            client.get_dataset.return_value.location = "asia-northeast1"
            client.list_tables.return_value = [
                SimpleNamespace(table_id="events_20260901"),
                SimpleNamespace(table_id="events_intraday_20260903"),
                SimpleNamespace(table_id="events_20260902"),
            ]

            result = target.check_access("valid-project", "analytics_123456789")

    assert result["state"] == "ready"
    client.get_dataset.assert_called_once_with("valid-project.analytics_123456789")
    query_args, query_kwargs = client.query.call_args
    assert "valid-project.analytics_123456789.events_20260902" in query_args[0]
    assert "event_params" in query_args[0]
    assert query_kwargs["job_config"].dry_run is True
    assert query_kwargs["location"] == "asia-northeast1"


def test_permission_error_is_classified():
    from google.api_core.exceptions import Forbidden

    with patch.object(target, "get_bigquery_credentials", return_value=object()):
        with patch("google.cloud.bigquery.Client") as client_class:
            client_class.return_value.get_dataset.side_effect = Forbidden("denied")

            result = target.check_access("valid-project", "analytics_123456789")

    assert result["state"] == "permission_denied"


def test_empty_dataset_is_not_ready():
    with patch.object(target, "get_bigquery_credentials", return_value=object()):
        with patch("google.cloud.bigquery.Client") as client_class:
            client = client_class.return_value
            client.list_tables.return_value = [SimpleNamespace(table_id="events_intraday_20260903")]
            result = target.check_access("valid-project", "analytics_123456789")
    assert result["state"] == "no_ga4_tables"
    client.query.assert_not_called()


def test_table_read_permission_error_is_not_ready():
    from google.api_core.exceptions import Forbidden
    with patch.object(target, "get_bigquery_credentials", return_value=object()):
        with patch("google.cloud.bigquery.Client") as client_class:
            client = client_class.return_value
            client.list_tables.return_value = [SimpleNamespace(table_id="events_20260902")]
            client.query.side_effect = Forbidden("table denied")
            result = target.check_access("valid-project", "analytics_123456789")
    assert result["state"] == "permission_denied"
