"""GA4 Data API クエリを実行前に検証する共通レイヤー。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from google.analytics.data_v1beta.types import (
    CheckCompatibilityRequest,
    Compatibility,
    Dimension,
    Filter,
    FilterExpression,
    Metric,
    NumericValue,
)
from google.api_core.exceptions import InvalidArgument


class QueryValidationError(ValueError):
    """取得条件がGA4の定義または本ツールの安全条件を満たさない。"""


@dataclass(frozen=True)
class QueryPlan:
    """AIが自然言語の依頼から作る、実行前の構造化クエリ。"""

    property_id: str
    start_date: str
    end_date: str
    dimensions: tuple[str, ...]
    metrics: tuple[str, ...]
    filter_text: str = ""
    metric_filter_text: str = ""
    order_by_metric: str | None = None
    limit: int = 200
    fetch_all: bool = False

    @classmethod
    def from_file(cls, path: str | Path) -> "QueryPlan":
        source = Path(path)
        try:
            raw = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise QueryValidationError(f"取得計画JSONを読めません: {source}: {exc}") from exc
        if not isinstance(raw, dict):
            raise QueryValidationError("取得計画JSONの最上位はオブジェクトにしてください")

        allowed = {
            "property_id", "start_date", "end_date", "dimensions", "metrics",
            "filter", "metric_filter", "order_by_metric", "limit", "fetch_all",
        }
        unknown = sorted(set(raw) - allowed)
        if unknown:
            raise QueryValidationError(f"取得計画JSONに未対応の項目があります: {unknown}")

        required = {"property_id", "start_date", "end_date", "dimensions", "metrics"}
        missing = sorted(required - set(raw))
        if missing:
            raise QueryValidationError(f"取得計画JSONの必須項目がありません: {missing}")

        dimensions = raw["dimensions"]
        metrics = raw["metrics"]
        if not isinstance(dimensions, list) or not all(isinstance(v, str) and v for v in dimensions):
            raise QueryValidationError("dimensionsは空文字を含まない文字列配列にしてください")
        if not isinstance(metrics, list) or not metrics or not all(isinstance(v, str) and v for v in metrics):
            raise QueryValidationError("metricsは1件以上の文字列配列にしてください")
        if not isinstance(raw.get("filter", ""), str):
            raise QueryValidationError("filterはCLIと同じ文字列形式にしてください")
        if not isinstance(raw.get("metric_filter", ""), str):
            raise QueryValidationError("metric_filterはCLIと同じ文字列形式にしてください")
        if raw.get("order_by_metric") is not None and not isinstance(raw["order_by_metric"], str):
            raise QueryValidationError("order_by_metricは文字列またはnullにしてください")
        limit = raw.get("limit", 200)
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1 or limit > 100_000:
            raise QueryValidationError("limitは1〜100000の整数にしてください")
        fetch_all = raw.get("fetch_all", False)
        if not isinstance(fetch_all, bool):
            raise QueryValidationError("fetch_allはtrueまたはfalseにしてください")

        return cls(
            property_id=str(raw["property_id"]).strip(),
            start_date=str(raw["start_date"]).strip(),
            end_date=str(raw["end_date"]).strip(),
            dimensions=tuple(dimensions),
            metrics=tuple(metrics),
            filter_text=raw.get("filter", ""),
            metric_filter_text=raw.get("metric_filter", ""),
            order_by_metric=raw.get("order_by_metric"),
            limit=limit,
            fetch_all=fetch_all,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "property_id": self.property_id,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "dimensions": list(self.dimensions),
            "metrics": list(self.metrics),
            "filter": self.filter_text,
            "metric_filter": self.metric_filter_text,
            "order_by_metric": self.order_by_metric,
            "limit": self.limit,
            "fetch_all": self.fetch_all,
        }


def _filter_fields(expression: FilterExpression | None) -> set[str]:
    if expression is None:
        return set()
    fields: set[str] = set()
    variant = expression._pb.WhichOneof("expr")
    if variant == "filter":
        field_name = expression.filter.field_name
        if field_name:
            fields.add(field_name)
    elif variant in ("and_group", "or_group"):
        group = getattr(expression, variant)
        for child in group.expressions:
            fields.update(_filter_fields(child))
    elif variant == "not_expression":
        fields.update(_filter_fields(expression.not_expression))
    return fields


def _names(items) -> set[str]:
    return {item.api_name for item in items if getattr(item, "api_name", "")}


def validate_query(
    client,
    *,
    property_id: str,
    dimensions: list[str],
    metrics: list[str],
    dimension_filter: FilterExpression | None = None,
    metric_filter: FilterExpression | None = None,
    order_by_metric: str | None = None,
) -> None:
    """プロパティ固有MetadataとcheckCompatibilityでクエリを検証する。"""
    if not property_id or not property_id.isdigit():
        raise QueryValidationError("GA4プロパティIDは数字だけで指定してください")
    if not metrics:
        raise QueryValidationError("指標を1件以上指定してください")
    if len(dimensions) > 9:
        raise QueryValidationError("GA4 Data APIは1リクエスト最大9ディメンションです")
    if len(metrics) > 10:
        raise QueryValidationError("GA4 Data APIは1リクエスト最大10指標です")
    if len(dimensions) != len(set(dimensions)) or len(metrics) != len(set(metrics)):
        raise QueryValidationError("同じディメンションまたは指標を重複指定しないでください")

    metadata = client.get_metadata(name=f"properties/{property_id}/metadata")
    known_dimensions = _names(metadata.dimensions)
    known_metrics = _names(metadata.metrics)

    missing_dimensions = sorted(set(dimensions) - known_dimensions)
    missing_metrics = sorted(set(metrics) - known_metrics)
    if missing_dimensions:
        raise QueryValidationError(
            f"このGA4プロパティで使えないディメンションです: {missing_dimensions}"
        )
    if missing_metrics:
        raise QueryValidationError(f"このGA4プロパティで使えない指標です: {missing_metrics}")

    wrong_dimension_filters = sorted(_filter_fields(dimension_filter) - known_dimensions)
    wrong_metric_filters = sorted(_filter_fields(metric_filter) - known_metrics)
    if wrong_dimension_filters:
        raise QueryValidationError(
            "dimension_filterにはディメンションだけを指定してください: "
            f"{wrong_dimension_filters}"
        )
    if wrong_metric_filters:
        raise QueryValidationError(
            f"metric_filterには指標だけを指定してください: {wrong_metric_filters}"
        )
    if order_by_metric and order_by_metric not in metrics:
        raise QueryValidationError(
            f"並び替え指標 {order_by_metric!r} はmetricsにも含めてください"
        )

    try:
        response = client.check_compatibility(
            CheckCompatibilityRequest(
                property=f"properties/{property_id}",
                dimensions=[Dimension(name=name) for name in dimensions],
                metrics=[Metric(name=name) for name in metrics],
                dimension_filter=dimension_filter,
                metric_filter=metric_filter,
            )
        )
    except InvalidArgument as exc:
        raise QueryValidationError(
            f"GA4公式の互換性確認で取得条件が拒否されました: {exc}"
        ) from exc
    requested_dimensions = set(dimensions)
    requested_metrics = set(metrics)
    incompatible_dimensions = sorted(
        item.dimension_metadata.api_name
        for item in response.dimension_compatibilities
        if (
            item.dimension_metadata.api_name in requested_dimensions
            and item.compatibility == Compatibility.INCOMPATIBLE
        )
    )
    incompatible_metrics = sorted(
        item.metric_metadata.api_name
        for item in response.metric_compatibilities
        if (
            item.metric_metadata.api_name in requested_metrics
            and item.compatibility == Compatibility.INCOMPATIBLE
        )
    )
    if incompatible_dimensions or incompatible_metrics:
        details = []
        if incompatible_dimensions:
            details.append(f"ディメンション={incompatible_dimensions}")
        if incompatible_metrics:
            details.append(f"指標={incompatible_metrics}")
        raise QueryValidationError(
            "GA4公式の互換性確認で組み合わせ不可と判定されました: " + ", ".join(details)
        )


def validate_response_shape(response, dimensions: list[str], metrics: list[str]) -> None:
    """返却列と各行の列数が依頼したクエリと一致することを確認する。"""
    if hasattr(response, "dimension_headers"):
        actual_dimensions = [header.name for header in response.dimension_headers]
        if actual_dimensions != dimensions:
            raise QueryValidationError(
                f"GA4レスポンスのディメンション列が取得計画と一致しません: {actual_dimensions}"
            )
    if hasattr(response, "metric_headers"):
        actual_metrics = [header.name for header in response.metric_headers]
        if actual_metrics != metrics:
            raise QueryValidationError(
                f"GA4レスポンスの指標列が取得計画と一致しません: {actual_metrics}"
            )
    for index, row in enumerate(response.rows, start=1):
        if len(row.dimension_values) != len(dimensions):
            raise QueryValidationError(f"GA4レスポンス{index}行目のディメンション列数が不正です")
        if len(row.metric_values) != len(metrics):
            raise QueryValidationError(f"GA4レスポンス{index}行目の指標列数が不正です")


def build_simple_dimension_filter(filter_text: str) -> FilterExpression | None:
    """取得計画JSON向けの単一ディメンションフィルタを構築する。"""
    import re

    if not filter_text:
        return None
    match = re.match(r"^(.*?)(!=|=|~)(.*)$", filter_text)
    if not match:
        raise QueryValidationError(f"フィルタ形式が不正です: {filter_text}")
    field, operator, value = match.group(1).strip(), match.group(2), match.group(3).strip()
    if not field or not value:
        raise QueryValidationError(f"フィルタの項目名と値を指定してください: {filter_text}")
    leaf = FilterExpression(
        filter=Filter(
            field_name=field,
            string_filter=Filter.StringFilter(
                value=value,
                match_type=(
                    Filter.StringFilter.MatchType.CONTAINS
                    if operator == "~"
                    else Filter.StringFilter.MatchType.EXACT
                ),
            ),
        )
    )
    return FilterExpression(not_expression=leaf) if operator == "!=" else leaf


def build_simple_metric_filter(filter_text: str) -> FilterExpression | None:
    """単一の数値指標フィルタを構築する。例: sessions>=10"""
    import re

    if not filter_text:
        return None
    match = re.match(r"^([A-Za-z0-9_:]+)\s*(>=|<=|=|>|<)\s*(-?\d+(?:\.\d+)?)$", filter_text)
    if not match:
        raise QueryValidationError(
            f"指標フィルタ形式が不正です（例: sessions>=10）: {filter_text}"
        )
    field, operator, raw_value = match.groups()
    operation = {
        "=": Filter.NumericFilter.Operation.EQUAL,
        "<": Filter.NumericFilter.Operation.LESS_THAN,
        "<=": Filter.NumericFilter.Operation.LESS_THAN_OR_EQUAL,
        ">": Filter.NumericFilter.Operation.GREATER_THAN,
        ">=": Filter.NumericFilter.Operation.GREATER_THAN_OR_EQUAL,
    }[operator]
    value = (
        NumericValue(double_value=float(raw_value))
        if "." in raw_value
        else NumericValue(int64_value=int(raw_value))
    )
    return FilterExpression(
        filter=Filter(
            field_name=field,
            numeric_filter=Filter.NumericFilter(operation=operation, value=value),
        )
    )
