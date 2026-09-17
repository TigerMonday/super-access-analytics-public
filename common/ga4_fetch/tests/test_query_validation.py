from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from google.analytics.data_v1beta.types import Compatibility

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from query_validation import (  # noqa: E402
    QueryPlan,
    QueryValidationError,
    build_simple_dimension_filter,
    build_simple_metric_filter,
    validate_query,
    validate_response_shape,
)


def _item(api_name: str):
    return SimpleNamespace(api_name=api_name)


class _Client:
    def __init__(self, *, incompatible_dimension: str | None = None):
        self.compatibility_requests = []
        self.incompatible_dimension = incompatible_dimension

    def get_metadata(self, name):
        assert name == "properties/123/metadata"
        return SimpleNamespace(
            dimensions=[_item("date"), _item("eventName"), _item("deviceCategory")],
            metrics=[_item("sessions"), _item("eventCount")],
        )

    def check_compatibility(self, request):
        self.compatibility_requests.append(request)
        return SimpleNamespace(
            dimension_compatibilities=[
                SimpleNamespace(
                    dimension_metadata=_item(dimension.name),
                    compatibility=(
                        Compatibility.INCOMPATIBLE
                        if dimension.name == self.incompatible_dimension
                        else Compatibility.COMPATIBLE
                    ),
                )
                for dimension in request.dimensions
            ],
            metric_compatibilities=[
                SimpleNamespace(
                    metric_metadata=_item(metric.name),
                    compatibility=Compatibility.COMPATIBLE,
                )
                for metric in request.metrics
            ],
        )


def test_unknown_dimension_is_rejected_before_compatibility_call():
    client = _Client()
    with pytest.raises(QueryValidationError, match="使えないディメンション"):
        validate_query(client, property_id="123", dimensions=["inventedField"], metrics=["sessions"])
    assert client.compatibility_requests == []


def test_metric_cannot_be_used_as_dimension_filter():
    client = _Client()
    expression = build_simple_dimension_filter("sessions=10")
    with pytest.raises(QueryValidationError, match="dimension_filter"):
        validate_query(
            client,
            property_id="123",
            dimensions=["date"],
            metrics=["sessions"],
            dimension_filter=expression,
        )


def test_official_incompatibility_stops_query():
    client = _Client(incompatible_dimension="deviceCategory")
    with pytest.raises(QueryValidationError, match="組み合わせ不可"):
        validate_query(
            client,
            property_id="123",
            dimensions=["deviceCategory"],
            metrics=["sessions"],
        )


def test_valid_query_and_filter_are_sent_to_compatibility_api():
    client = _Client()
    expression = build_simple_dimension_filter("eventName=generate_lead")
    validate_query(
        client,
        property_id="123",
        dimensions=["date"],
        metrics=["eventCount"],
        dimension_filter=expression,
        order_by_metric="eventCount",
    )
    request = client.compatibility_requests[0]
    assert request.dimensions[0].name == "date"
    assert request.metrics[0].name == "eventCount"
    assert request.dimension_filter.filter.field_name == "eventName"


def test_unrequested_incompatible_fields_do_not_stop_query():
    class _CompatibilityClient(_Client):
        def check_compatibility(self, request):
            self.compatibility_requests.append(request)
            return SimpleNamespace(
                dimension_compatibilities=[
                    SimpleNamespace(
                        dimension_metadata=_item("date"),
                        compatibility=Compatibility.COMPATIBLE,
                    ),
                    SimpleNamespace(
                        dimension_metadata=_item("unrequestedDimension"),
                        compatibility=Compatibility.INCOMPATIBLE,
                    ),
                ],
                metric_compatibilities=[
                    SimpleNamespace(
                        metric_metadata=_item("sessions"),
                        compatibility=Compatibility.COMPATIBLE,
                    ),
                    SimpleNamespace(
                        metric_metadata=_item("unrequestedMetric"),
                        compatibility=Compatibility.INCOMPATIBLE,
                    ),
                ],
            )

    validate_query(
        _CompatibilityClient(),
        property_id="123",
        dimensions=["date"],
        metrics=["sessions"],
    )


def test_dimension_cannot_be_used_as_metric_filter():
    client = _Client()
    expression = build_simple_metric_filter("deviceCategory=1")
    with pytest.raises(QueryValidationError, match="metric_filter"):
        validate_query(
            client,
            property_id="123",
            dimensions=["date"],
            metrics=["sessions"],
            metric_filter=expression,
        )


def test_metric_filter_is_parsed_as_numeric_condition():
    expression = build_simple_metric_filter("sessions>=10")
    assert expression.filter.field_name == "sessions"
    assert expression.filter.numeric_filter.operation.name == "GREATER_THAN_OR_EQUAL"
    assert expression.filter.numeric_filter.value.int64_value == 10


def test_query_plan_rejects_unknown_keys(monkeypatch):
    content = json.dumps(
        {
            "property_id": "123",
            "start_date": "2026-01-01",
            "end_date": "2026-01-31",
            "dimensions": ["date"],
            "metrics": ["sessions"],
            "metrcis": ["eventCount"],
        }
    )
    monkeypatch.setattr(Path, "read_text", lambda self, encoding: content)
    with pytest.raises(QueryValidationError, match="未対応の項目"):
        QueryPlan.from_file("plan.json")


def test_query_plan_keeps_metric_filter(monkeypatch):
    content = json.dumps(
        {
            "property_id": "123",
            "start_date": "2026-01-01",
            "end_date": "2026-01-31",
            "dimensions": ["date"],
            "metrics": ["sessions"],
            "metric_filter": "sessions>=10",
        }
    )
    monkeypatch.setattr(Path, "read_text", lambda self, encoding: content)
    plan = QueryPlan.from_file("plan.json")
    assert plan.metric_filter_text == "sessions>=10"
    assert plan.as_dict()["metric_filter"] == "sessions>=10"


def test_response_headers_must_match_plan():
    response = SimpleNamespace(
        dimension_headers=[SimpleNamespace(name="date")],
        metric_headers=[SimpleNamespace(name="eventCount")],
        rows=[SimpleNamespace(dimension_values=[object()], metric_values=[object()])],
    )
    with pytest.raises(QueryValidationError, match="指標列"):
        validate_response_shape(response, ["date"], ["sessions"])
