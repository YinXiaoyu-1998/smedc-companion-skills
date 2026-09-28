#!/usr/bin/env python3
"""Build deterministic SMEDC query manifests for business reports."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from identity import ORGANIZATION_ERROR, organization_name_from_current_user_file


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "business-analysis.json"
SUPPORTED_REPORT_TYPES = ("diagnosis", "weekly", "monthly")
WINDOW_NAMES = ("current", "previous", "yoy")
NUMERIC_TYPES = {"decimal", "integer", "percent"}


class PlanError(ValueError):
    pass


@dataclass(frozen=True)
class DateWindow:
    name: str
    start: date
    end: date

    def as_json(self) -> dict[str, str]:
        return {"start": self.start.isoformat(), "end": self.end.isoformat()}

    def overlaps(self, other: "DateWindow") -> bool:
        return self.start <= other.end and other.start <= self.end

    def touches(self, other: "DateWindow") -> bool:
        return self.start <= other.end + timedelta(days=1) and other.start <= self.end + timedelta(days=1)


@dataclass(frozen=True)
class FieldRef:
    dataset: str
    alias: str
    canonical: str


def load_json(path: Path, description: str) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError as exc:
        raise PlanError(f"{description} not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise PlanError(f"{description} is not valid JSON: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise PlanError(f"{description} must be a JSON object: {path}")
    return data


def unwrap_mcp_success_envelope(value: dict[str, Any], description: str) -> dict[str, Any]:
    if value.get("isError") is True or isinstance(value.get("error"), dict):
        raise PlanError(f"{description} is an MCP error response")

    candidates: list[Any] = []
    if "result" in value:
        candidates.append(value["result"])
    if "payload" in value:
        candidates.append(value["payload"])
    if "content" in value:
        content = value["content"]
        if (
            not isinstance(content, list)
            or len(content) != 1
            or not isinstance(content[0], dict)
            or content[0].get("type") != "text"
            or not isinstance(content[0].get("text"), str)
        ):
            raise PlanError(f"{description} has malformed MCP text content")
        try:
            candidates.append(json.loads(content[0]["text"]))
        except json.JSONDecodeError as exc:
            raise PlanError(f"{description} MCP text content is not valid JSON: {exc}") from exc

    if not candidates:
        return value
    if len(candidates) > 1:
        raise PlanError(f"{description} has ambiguous MCP payload candidates")
    payload = candidates[0]
    if not isinstance(payload, dict):
        raise PlanError(f"{description} MCP payload must be a JSON object")
    return unwrap_mcp_success_envelope(payload, description)


def load_mcp_json(path: Path, description: str) -> dict[str, Any]:
    return unwrap_mcp_success_envelope(load_json(path, description), description)


def parse_date(value: str, label: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise PlanError(f"invalid date for {label}: {value}") from exc


def build_windows(args: argparse.Namespace) -> dict[str, DateWindow]:
    windows = {
        "current": DateWindow(
            "current",
            parse_date(args.current_start, "current-start"),
            parse_date(args.current_end, "current-end"),
        ),
        "previous": DateWindow(
            "previous",
            parse_date(args.previous_start, "previous-start"),
            parse_date(args.previous_end, "previous-end"),
        ),
        "yoy": DateWindow("yoy", parse_date(args.yoy_start, "yoy-start"), parse_date(args.yoy_end, "yoy-end")),
    }
    for window in windows.values():
        if window.start > window.end:
            raise PlanError(f"window start must be on or before end: {window.name}")
    pairs = (("current", "previous"), ("current", "yoy"), ("previous", "yoy"))
    for left_name, right_name in pairs:
        if windows[left_name].overlaps(windows[right_name]):
            raise PlanError(f"comparison windows must not overlap: {left_name} and {right_name}")
    for comparison_name in ("previous", "yoy"):
        if windows[comparison_name].end >= windows["current"].start:
            raise PlanError("comparison windows must end before the current window")
    return windows


def subtract_months(value: date, months: int) -> date:
    year, month = divmod(value.year * 12 + value.month - 1 - months, 12)
    return date(year, month + 1, 1)


def month_end(year: int, month: int) -> date:
    if month == 12:
        return date(year, 12, 31)
    return date(year, month + 1, 1) - timedelta(days=1)


def same_date_previous_year(value: date) -> date:
    try:
        return date(value.year - 1, value.month, value.day)
    except ValueError:
        return month_end(value.year - 1, value.month)


def weekly_trend_window(current_end: date) -> DateWindow:
    return DateWindow("trend", current_end - timedelta(days=(16 * 7) - 1), current_end)


def monthly_trend_window(current_end: date) -> DateWindow:
    current_month_end = month_end(current_end.year, current_end.month)
    end = current_end if current_end == current_month_end else date(current_end.year, current_end.month, 1) - timedelta(days=1)
    return DateWindow("trend", subtract_months(end, 5), end)


def registry_by_dataset(registry: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, int]]:
    datasets = registry.get("datasets")
    limits = registry.get("limits")
    if not isinstance(datasets, list) or not isinstance(limits, dict):
        raise PlanError("malformed registry envelope: expected datasets[] and limits")
    by_dataset: dict[str, dict[str, Any]] = {}
    for dataset in datasets:
        if not isinstance(dataset, dict):
            raise PlanError("malformed registry envelope: dataset entry must be an object")
        name = dataset.get("dataset")
        fields = dataset.get("fields")
        access_mode = dataset.get("accessMode")
        if not isinstance(name, str) or not isinstance(fields, list) or access_mode not in {"partition_extract", "row_query"}:
            raise PlanError("malformed registry envelope: dataset requires dataset, accessMode, and fields")
        if name in by_dataset:
            raise PlanError(f"malformed registry envelope: duplicate dataset {name}")
        field_map: dict[str, dict[str, Any]] = {}
        for field in fields:
            if not isinstance(field, dict):
                raise PlanError(f"malformed registry envelope: field in {name} must be an object")
            canonical = field.get("canonicalName")
            capabilities = field.get("capabilities")
            field_type = field.get("type")
            if not isinstance(canonical, str) or not isinstance(capabilities, dict) or not isinstance(field_type, str):
                raise PlanError(f"malformed registry envelope: field in {name} requires canonicalName, type, capabilities")
            field_map[canonical] = field
        by_dataset[name] = {**dataset, "_fields": field_map}
    parsed_limits: dict[str, int] = {}
    for name, value in limits.items():
        if not isinstance(value, int) or value <= 0:
            raise PlanError(f"malformed registry envelope: limits.{name} must be a positive integer")
        parsed_limits[name] = value
    for name in (
        "maxGroupByFields",
        "maxAggregates",
        "maxAggregateGroups",
        "maxRows",
        "maxSelectedFields",
        "maxSortFields",
        "maxConditions",
    ):
        if name not in parsed_limits:
            raise PlanError(f"malformed registry envelope: limits.{name} must be a positive integer")
    return by_dataset, parsed_limits


def require_field(
    config: dict[str, Any],
    registry: dict[str, dict[str, Any]],
    dotted_ref: str,
    capability: str | None = None,
) -> FieldRef:
    try:
        dataset_name, alias = dotted_ref.split(".", 1)
        canonical = config["fields"][dataset_name][alias]
    except (KeyError, ValueError) as exc:
        raise PlanError(f"unknown configured field reference: {dotted_ref}") from exc
    dataset = registry.get(dataset_name)
    if dataset is None:
        raise PlanError(f"registry is missing dataset {dataset_name}")
    field = dataset["_fields"].get(canonical)
    if field is None:
        raise PlanError(f"registry dataset {dataset_name} is missing field {canonical}")
    if capability and not field["capabilities"].get(capability):
        raise PlanError(f"field {canonical} lacks {capability} capability")
    return FieldRef(dataset_name, alias, canonical)


def validate_config_fields(config: dict[str, Any], registry: dict[str, dict[str, Any]]) -> None:
    for dataset_name, dataset_config in config["datasets"].items():
        if dataset_name not in registry:
            raise PlanError(f"registry is missing dataset {dataset_name}")
        if dataset_config.get("metadataPolicy") not in {"window", "snapshot"}:
            raise PlanError(f"dataset {dataset_name} has unsupported metadata policy")
    for dataset_name, aliases in config["fields"].items():
        for alias in aliases:
            require_field(config, registry, f"{dataset_name}.{alias}")


def coverage_path(coverage_dir: Path, dataset_name: str) -> Path:
    return coverage_dir / f"coverage_{dataset_name}.json"


def load_coverage(
    config: dict[str, Any],
    registry: dict[str, dict[str, Any]],
    coverage_dir: Path,
    enterprise_name: str,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, str]]]:
    coverage: dict[str, dict[str, Any]] = {}
    notices: list[dict[str, str]] = []
    for dataset_name, dataset_config in config["datasets"].items():
        path = coverage_path(coverage_dir, dataset_name)
        if not path.exists():
            coverage[dataset_name] = {
                "dataset": dataset_name,
                "metadataPolicy": dataset_config["metadataPolicy"],
                "sources": [],
                "readable": False,
            }
            continue
        envelope = load_mcp_json(path, "coverage response")
        if envelope.get("dataset") != dataset_name:
            raise PlanError(f"malformed coverage envelope for {dataset_name}")
        if registry[dataset_name]["accessMode"] == "partition_extract":
            enterprises = envelope.get("enterprises")
            if envelope.get("accessMode") != "partition_extract" or not isinstance(enterprises, list):
                raise PlanError(f"malformed partition coverage envelope for {dataset_name}")
            selected = [item for item in enterprises if isinstance(item, dict) and item.get("enterpriseName") == enterprise_name]
            if len(selected) > 1:
                raise PlanError(f"partition coverage repeats enterprise {enterprise_name} for {dataset_name}")
            for item in selected:
                if not isinstance(item.get("startDate"), str) or not isinstance(item.get("endDate"), str):
                    raise PlanError(f"malformed partition coverage dates for {dataset_name}")
                if parse_date(item["startDate"], f"{dataset_name}.startDate") > parse_date(item["endDate"], f"{dataset_name}.endDate"):
                    raise PlanError(f"malformed partition coverage range for {dataset_name}")
                if not isinstance(item.get("stores"), list):
                    raise PlanError(f"malformed partition coverage stores for {dataset_name}")
            coverage[dataset_name] = {
                "dataset": dataset_name,
                "accessMode": "partition_extract",
                "metadataPolicy": "window",
                "enterpriseName": enterprise_name,
                "sources": selected,
                "readable": True,
            }
            continue
        if envelope.get("metadataPolicy") != dataset_config["metadataPolicy"] or not isinstance(envelope.get("sources"), list):
            raise PlanError(f"malformed coverage envelope for {dataset_name}")
        for source in envelope["sources"]:
            if not isinstance(source, dict):
                raise PlanError(f"malformed coverage envelope for {dataset_name}: source must be object")
            if dataset_config["metadataPolicy"] == "window":
                if "snapshotDate" in source:
                    raise PlanError(f"malformed coverage envelope for {dataset_name}: window source must not include snapshotDate")
                if not isinstance(source.get("startDate"), str) or not isinstance(source.get("endDate"), str):
                    raise PlanError(f"malformed coverage envelope for {dataset_name}: window source dates missing")
                start = parse_date(source["startDate"], f"{dataset_name}.sources.startDate")
                end = parse_date(source["endDate"], f"{dataset_name}.sources.endDate")
                if start > end:
                    raise PlanError(f"malformed coverage envelope for {dataset_name}: source startDate after endDate")
            else:
                if "startDate" in source or "endDate" in source:
                    raise PlanError(f"malformed coverage envelope for {dataset_name}: snapshot source must not include startDate/endDate")
                if not isinstance(source.get("snapshotDate"), str):
                    raise PlanError(f"malformed coverage envelope for {dataset_name}: snapshotDate missing")
                parse_date(source["snapshotDate"], f"{dataset_name}.sources.snapshotDate")
        coverage[dataset_name] = {**envelope, "readable": True}
    return coverage, notices


def coverage_overlaps(coverage: dict[str, Any], window: DateWindow) -> bool:
    if not coverage.get("readable"):
        return False
    if coverage.get("metadataPolicy") == "snapshot":
        return bool(coverage.get("sources"))
    for source in coverage.get("sources", []):
        start = date.fromisoformat(source["startDate"])
        end = date.fromisoformat(source["endDate"])
        if start <= window.end and window.start <= end:
            return True
    return False


def observed_window_intersections(coverage: dict[str, Any], window: DateWindow) -> list[dict[str, Any]]:
    observed: list[dict[str, Any]] = []
    if not coverage.get("readable") or coverage.get("metadataPolicy") != "window":
        return observed
    for source in coverage.get("sources", []):
        source_start = date.fromisoformat(source["startDate"])
        source_end = date.fromisoformat(source["endDate"])
        intersection_start = max(source_start, window.start)
        intersection_end = min(source_end, window.end)
        if intersection_start > intersection_end:
            continue
        observed.append(
            {
                "startDate": intersection_start.isoformat(),
                "endDate": intersection_end.isoformat(),
                "sourceDocumentId": source.get("sourceDocumentId"),
                "importBatchId": source.get("importBatchId"),
                "rowCount": source.get("rowCount"),
            }
        )
    return sorted(observed, key=lambda item: (item["startDate"], item["endDate"], item.get("importBatchId") or ""))


def coverage_gaps(coverage: dict[str, Any], window: DateWindow) -> list[dict[str, str]]:
    if coverage.get("metadataPolicy") != "window":
        return []
    gaps: list[dict[str, str]] = []
    cursor = window.start
    for observed in observed_window_intersections(coverage, window):
        observed_start = date.fromisoformat(observed["startDate"])
        observed_end = date.fromisoformat(observed["endDate"])
        if observed_end < cursor:
            continue
        if observed_start > cursor:
            gaps.append(
                {
                    "startDate": cursor.isoformat(),
                    "endDate": (observed_start - timedelta(days=1)).isoformat(),
                }
            )
        cursor = max(cursor, observed_end + timedelta(days=1))
        if cursor > window.end:
            break
    if cursor <= window.end:
        gaps.append({"startDate": cursor.isoformat(), "endDate": window.end.isoformat()})
    return gaps


def source_summaries(coverage: dict[str, Any], windows: dict[str, DateWindow]) -> dict[str, Any]:
    dataset_name = coverage["dataset"]
    result: dict[str, Any] = {
        "dataset": dataset_name,
        "metadataPolicy": coverage["metadataPolicy"],
        "readable": bool(coverage.get("readable")),
        "sources": [],
        "windows": {},
    }
    if coverage["metadataPolicy"] == "snapshot":
        sources = []
        for source in sorted(coverage.get("sources", []), key=lambda item: item["snapshotDate"]):
            sources.append(
                {
                    "snapshotDate": source["snapshotDate"],
                    "rowCount": source.get("rowCount"),
                    "importBatchId": source.get("importBatchId"),
                    "sourceDocumentId": source.get("sourceDocumentId"),
                }
            )
        snapshots = [source["snapshotDate"] for source in sources]
        result["sources"] = sources
        result["snapshots"] = snapshots
        return result

    for source in sorted(coverage.get("sources", []), key=lambda item: (item["startDate"], item["endDate"])):
        if coverage.get("accessMode") == "partition_extract":
            result["sources"].append(
                {
                    "enterpriseName": source["enterpriseName"],
                    "startDate": source["startDate"],
                    "endDate": source["endDate"],
                    "partitionCount": source.get("partitionCount"),
                    "totalRowCount": source.get("totalRowCount"),
                    "stores": source.get("stores", []),
                }
            )
            continue
        result["sources"].append(
            {
                "startDate": source["startDate"],
                "endDate": source["endDate"],
                "rowCount": source.get("rowCount"),
                "importBatchId": source.get("importBatchId"),
                "sourceDocumentId": source.get("sourceDocumentId"),
            }
        )
    for name, window in windows.items():
        gaps = coverage_gaps(coverage, window)
        result["windows"][name] = {
            "requested": window.as_json(),
            "hasReadableOverlap": coverage_overlaps(coverage, window),
            "observed": observed_window_intersections(coverage, window),
            "isFullyCovered": not gaps,
            "gaps": gaps,
        }
    return result


def business_aggregates(config: dict[str, Any], registry: dict[str, dict[str, Any]]) -> list[dict[str, str]]:
    aggregate_specs = [
        ("sum", "business.grossSales", "gross_sales"),
        ("sum", "business.orderRevenue", "order_revenue"),
        ("sum", "business.discount", "discount"),
        ("sum", "business.validOrders", "valid_orders"),
        ("sum", "business.positiveOrders", "positive_orders"),
        ("sum", "business.reverseOrders", "reverse_orders"),
        ("sum", "business.settledOrders", "settled_orders"),
        ("sum", "business.dinerCount", "diners"),
        ("sum", "business.consumedTables", "consumed_tables"),
        ("sum", "business.memberRevenue", "member_revenue"),
    ]
    aggregates: list[dict[str, str]] = []
    for op, dotted_ref, alias in aggregate_specs:
        field = require_field(config, registry, dotted_ref, "aggregate")
        aggregates.append({"op": op, "field": field.canonical, "as": alias})
    open_rate = require_field(config, registry, "business.openRate", "aggregate")
    turnover_rate = require_field(config, registry, "business.turnoverRate", "aggregate")
    table_days = require_field(config, registry, "business.tableDayCount", "aggregate")
    aggregates.append(
        {
            "op": "weightedAvg",
            "field": open_rate.canonical,
            "weightField": table_days.canonical,
            "as": "weighted_open_rate",
        }
    )
    aggregates.append(
        {
            "op": "weightedAvg",
            "field": turnover_rate.canonical,
            "weightField": table_days.canonical,
            "as": "weighted_turnover_rate",
        }
    )
    return aggregates


def supplemental_aggregates(
    config: dict[str, Any],
    registry: dict[str, dict[str, Any]],
    specs: list[tuple[str, str]],
) -> list[dict[str, str]]:
    aggregates: list[dict[str, str]] = []
    for dotted_ref, alias in specs:
        field = require_field(config, registry, dotted_ref, "aggregate")
        aggregates.append({"op": "sum", "field": field.canonical, "as": alias})
    return aggregates


def business_supplemental_aggregate_sets(
    config: dict[str, Any],
    registry: dict[str, dict[str, Any]],
) -> list[tuple[str, list[dict[str, str]]]]:
    return [
        (
            "supplemental_channel",
            supplemental_aggregates(
                config,
                registry,
                [
                    ("business.tableDayCount", "table_days"),
                    ("business.dineInGrossSales", "dine_in_sales_amount"),
                    ("business.dineInRevenue", "dine_in_revenue"),
                    ("business.dineInDiscount", "dine_in_discount"),
                    ("business.dineInOrders", "dine_in_orders"),
                    ("business.dineInPositiveOrders", "dine_in_positive_orders"),
                    ("business.dineInRefundAmount", "dine_in_refund_amount"),
                    ("business.deliveryGrossSales", "delivery_sales_amount"),
                    ("business.deliveryRevenue", "delivery_revenue"),
                    ("business.deliveryDiscount", "delivery_discount"),
                    ("business.deliveryOrders", "delivery_orders"),
                    ("business.deliveryPositiveOrders", "delivery_positive_orders"),
                ],
            ),
        ),
        (
            "supplemental_platform",
            supplemental_aggregates(
                config,
                registry,
                [
                    ("business.deliveryRefundAmount", "delivery_refund_amount"),
                    ("business.meituanDeliveryGrossSales", "meituan_delivery_sales_amount"),
                    ("business.meituanDeliveryRevenue", "meituan_delivery_revenue"),
                    ("business.meituanDeliveryRefundAmount", "meituan_delivery_refund_amount"),
                    ("business.elemeDeliveryGrossSales", "eleme_delivery_sales_amount"),
                    ("business.elemeDeliveryRevenue", "eleme_delivery_revenue"),
                    ("business.elemeDeliveryRefundAmount", "eleme_delivery_refund_amount"),
                    ("business.jdDeliveryGrossSales", "jd_delivery_sales_amount"),
                    ("business.jdDeliveryRevenue", "jd_delivery_revenue"),
                    ("business.jdDeliveryRefundAmount", "jd_delivery_refund_amount"),
                    ("business.pickupGrossSales", "pickup_sales_amount"),
                    ("business.pickupRevenue", "pickup_revenue"),
                ],
            ),
        ),
        (
            "supplemental_pickup",
            supplemental_aggregates(
                config,
                registry,
                [
                    ("business.pickupDiscount", "pickup_discount"),
                    ("business.pickupOrders", "pickup_orders"),
                    ("business.pickupPositiveOrders", "pickup_positive_orders"),
                    ("business.pickupRefundAmount", "pickup_refund_amount"),
                ],
            ),
        ),
    ]


def dish_aggregates(config: dict[str, Any], registry: dict[str, dict[str, Any]]) -> list[dict[str, str]]:
    aggregate_specs = [
        ("sum", "dishes.quantity", "dish_quantity"),
        ("sum", "dishes.sales", "dish_sales"),
        ("sum", "dishes.revenue", "dish_revenue"),
        ("sum", "dishes.discount", "dish_discount"),
        ("sum", "dishes.totalSales", "dish_total_sales"),
        ("sum", "dishes.totalRevenue", "dish_total_revenue"),
        ("sum", "dishes.totalDiscount", "dish_total_discount"),
        ("sum", "dishes.positiveOrders", "dish_positive_orders"),
        ("sum", "dishes.returnedQuantity", "returned_quantity"),
        ("sum", "dishes.returnedAmount", "returned_amount"),
        ("sum", "dishes.servingOrders", "serving_orders"),
    ]
    aggregates: list[dict[str, str]] = []
    for op, dotted_ref, alias in aggregate_specs:
        field = require_field(config, registry, dotted_ref, "aggregate")
        aggregates.append({"op": op, "field": field.canonical, "as": alias})
    return aggregates


def ensure_numeric_weighted_avg(registry: dict[str, dict[str, Any]], dataset_name: str, aggregates: list[dict[str, str]]) -> None:
    fields = registry[dataset_name]["_fields"]
    for aggregate in aggregates:
        field = fields[aggregate["field"]]
        if aggregate["op"] == "weightedAvg":
            weight_field = fields[aggregate["weightField"]]
            if field["type"] not in NUMERIC_TYPES or weight_field["type"] not in NUMERIC_TYPES:
                raise PlanError(f"weightedAvg requires numeric fields in dataset {dataset_name}")


def validate_job(job: dict[str, Any], registry: dict[str, dict[str, Any]], limits: dict[str, int]) -> None:
    if job["tool"] not in {"query_structured_dataset", "local_partition_aggregate"}:
        raise PlanError(f"job {job['id']} uses unsupported tool {job['tool']}")
    query = job["input"]
    dataset_name = query["dataset"]
    expected_tool = "local_partition_aggregate" if registry[dataset_name]["accessMode"] == "partition_extract" else "query_structured_dataset"
    if job["tool"] != expected_tool:
        raise PlanError(f"job {job['id']} must use {expected_tool} for {dataset_name}")
    fields = registry[dataset_name]["_fields"]
    allowed_query_keys = {"dataset", "filter", "groupBy", "aggregates", "select", "sort", "page"}
    unknown_keys = set(query) - allowed_query_keys
    if unknown_keys:
        raise PlanError(f"job {job['id']} uses unsupported query keys: {', '.join(sorted(unknown_keys))}")
    page = query.get("page")
    if not isinstance(page, dict) or not isinstance(page.get("limit"), int) or page["limit"] <= 0:
        raise PlanError(f"job {job['id']} has invalid page limit")
    is_detail = "select" in query
    is_aggregate = "aggregates" in query
    if is_detail == is_aggregate:
        raise PlanError(f"job {job['id']} must declare exactly one query shape")
    if is_detail:
        if "filter" in query:
            filter_field = query["filter"].get("field")
            if filter_field not in fields or not fields[filter_field]["capabilities"].get("filter"):
                raise PlanError(f"field {filter_field} lacks filter capability")
        selected = set(query.get("select", []))
        if len(selected) > limits["maxSelectedFields"]:
            raise PlanError(f"job {job['id']} exceeds maxSelectedFields")
        if len(query.get("sort", [])) > limits["maxSortFields"]:
            raise PlanError(f"job {job['id']} exceeds maxSortFields")
        for field_name in selected:
            if field_name not in fields:
                raise PlanError(f"registry dataset {dataset_name} is missing field {field_name}")
        for order in query.get("sort", []):
            field_name = order.get("field")
            if field_name not in selected:
                raise PlanError(f"job {job['id']} sorts by unselected field {field_name}")
            if not fields[field_name]["capabilities"].get("sort"):
                raise PlanError(f"field {field_name} lacks sort capability")
        if page["limit"] > limits["maxRows"]:
            raise PlanError(f"job {job['id']} exceeds maxRows")
        return

    if len(query.get("groupBy", [])) > limits["maxGroupByFields"]:
        raise PlanError(f"job {job['id']} exceeds maxGroupByFields")
    if len(query.get("aggregates", [])) > limits["maxAggregates"]:
        raise PlanError(f"job {job['id']} exceeds maxAggregates")
    if page["limit"] > limits["maxAggregateGroups"]:
        raise PlanError(f"job {job['id']} exceeds maxAggregateGroups")
    if len(query.get("sort", [])) > limits["maxSortFields"]:
        raise PlanError(f"job {job['id']} exceeds maxSortFields")
    if "filter" in query:
        filter_field = query["filter"].get("field")
        if filter_field not in fields or not fields[filter_field]["capabilities"].get("filter"):
            raise PlanError(f"field {filter_field} lacks filter capability")
    aliases = set()
    for field_name in query.get("groupBy", []):
        if field_name not in fields or not fields[field_name]["capabilities"].get("group"):
            raise PlanError(f"field {field_name} lacks group capability")
    for aggregate in query.get("aggregates", []):
        field_name = aggregate.get("field")
        alias = aggregate.get("as")
        if not isinstance(alias, str) or not alias:
            raise PlanError(f"job {job['id']} has invalid aggregate alias")
        if alias in aliases:
            raise PlanError(f"job {job['id']} has duplicate aggregate alias {alias}")
        aliases.add(alias)
        if field_name not in fields or not fields[field_name]["capabilities"].get("aggregate"):
            raise PlanError(f"field {field_name} lacks aggregate capability")
        if aggregate.get("op") == "weightedAvg":
            weight_field = aggregate.get("weightField")
            if weight_field not in fields or not fields[weight_field]["capabilities"].get("aggregate"):
                raise PlanError(f"field {weight_field} lacks aggregate capability")
    ensure_numeric_weighted_avg(registry, dataset_name, query.get("aggregates", []))
    sortable = set(query.get("groupBy", [])) | aliases
    for order in query.get("sort", []):
        if order.get("field") not in sortable:
            raise PlanError(f"job {job['id']} sorts by undeclared field {order.get('field')}")


def aggregate_job(
    *,
    job_id: str,
    module: str,
    dataset_name: str,
    registry: dict[str, dict[str, Any]],
    window: DateWindow | None,
    date_field: str | None,
    group_by: list[str],
    aggregates: list[dict[str, str]],
    output_file: str,
    limits: dict[str, int],
    order_by: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    if order_by is None:
        order_by = [{"field": field, "direction": "asc"} for field in group_by[: limits["maxSortFields"]]]
    query: dict[str, Any] = {
        "dataset": dataset_name,
        "groupBy": group_by,
        "aggregates": aggregates,
        "sort": order_by,
        "page": {"limit": min(limits["maxAggregateGroups"], 200)},
    }
    if window and date_field:
        query["filter"] = {"field": date_field, "op": "between", "value": [window.start.isoformat(), window.end.isoformat()]}
    return {
        "id": job_id,
        "tool": "local_partition_aggregate" if registry[dataset_name]["accessMode"] == "partition_extract" else "query_structured_dataset",
        "input": query,
        "outputFile": f"query-results/{output_file}.json",
        "module": module,
    }


def catalog_job(
    config: dict[str, Any],
    registry: dict[str, dict[str, Any]],
    limits: dict[str, int],
    coverage: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    snapshot_dates = sorted(
        source["snapshotDate"]
        for source in coverage["dish_catalog"].get("sources", [])
        if isinstance(source, dict) and isinstance(source.get("snapshotDate"), str)
    )
    if not snapshot_dates:
        raise PlanError("dish_catalog coverage has no visible snapshotDate")
    latest_snapshot = snapshot_dates[-1]
    selected = [
        require_field(config, registry, "dish_catalog.snapshotDate", "sort").canonical,
        require_field(config, registry, "dish_catalog.dishName", "group").canonical,
        require_field(config, registry, "dish_catalog.baseCategory", "group").canonical,
        require_field(config, registry, "dish_catalog.alias", "group").canonical,
        require_field(config, registry, "dish_catalog.price", "aggregate").canonical,
    ]
    return {
        "id": "dish_catalog_current_snapshot",
        "tool": "query_structured_dataset",
        "input": {
            "dataset": "dish_catalog",
            "filter": {"field": "snapshot_date", "op": "eq", "value": latest_snapshot},
            "select": selected,
            "sort": [
                {"field": "snapshot_date", "direction": "desc"},
                {"field": "dish_name", "direction": "asc"},
            ],
            "page": {"limit": min(limits["maxRows"], 200)},
        },
        "outputFile": "query-results/dish_catalog_current_snapshot.json",
        "module": "stallAttribution",
    }


def make_notice(code: str, dataset: str, window: str, module: str) -> dict[str, str]:
    return {"code": code, "dataset": dataset, "window": window, "module": module}


def make_partial_notice(dataset: str, window: DateWindow, module: str, gaps: list[dict[str, str]]) -> dict[str, Any]:
    return {**make_notice("COVERAGE_WINDOW_PARTIAL", dataset, window.name, module), "gaps": gaps}


def sort_notices(notices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        notices,
        key=lambda notice: (notice["code"], notice["dataset"], notice["window"], notice["module"]),
    )


def add_if_covered(
    jobs: list[dict[str, Any]],
    notices: list[dict[str, Any]],
    coverage: dict[str, dict[str, Any]],
    *,
    job: dict[str, Any],
    datasets: list[str],
    window: DateWindow | None,
    module: str,
    notice_partial: bool = False,
) -> None:
    for dataset_name in datasets:
        dataset_coverage = coverage[dataset_name]
        covered = bool(dataset_coverage.get("sources")) if window is None else coverage_overlaps(dataset_coverage, window)
        if not covered:
            code = "COVERAGE_FILE_MISSING" if not dataset_coverage.get("readable") else "COVERAGE_WINDOW_MISSING"
            notices.append(make_notice(code, dataset_name, window.name if window else "current", module))
            return
    jobs.append(job)
    if notice_partial and window is not None:
        for dataset_name in datasets:
            gaps = coverage_gaps(coverage[dataset_name], window)
            if gaps:
                notices.append(make_partial_notice(dataset_name, window, module, gaps))


def build_extracts(jobs: list[dict[str, Any]], enterprise_name: str) -> list[dict[str, Any]]:
    by_dataset: dict[str, list[DateWindow]] = {}
    for job in jobs:
        if job["tool"] != "local_partition_aggregate":
            continue
        query = job["input"]
        filter_spec = query.get("filter")
        values = filter_spec.get("value") if isinstance(filter_spec, dict) else None
        if not isinstance(filter_spec, dict) or filter_spec.get("op") != "between" or not isinstance(values, list) or len(values) != 2:
            raise PlanError(f"local job {job['id']} must have one between date filter")
        by_dataset.setdefault(query["dataset"], []).append(
            DateWindow(job["id"], parse_date(values[0], f"{job['id']}.start"), parse_date(values[1], f"{job['id']}.end"))
        )

    extracts: list[dict[str, Any]] = []
    for dataset_name in sorted(by_dataset):
        merged: list[DateWindow] = []
        for window in sorted(by_dataset[dataset_name], key=lambda item: (item.start, item.end)):
            if merged and merged[-1].touches(window):
                previous = merged[-1]
                merged[-1] = DateWindow(previous.name, min(previous.start, window.start), max(previous.end, window.end))
            else:
                merged.append(window)
        for index, window in enumerate(merged, start=1):
            extracts.append(
                {
                    "id": f"{dataset_name}_extract_{index}",
                    "tool": "download_structured_partitions",
                    "input": {
                        "dataset": dataset_name,
                        "enterpriseName": enterprise_name,
                        "startDate": window.start.strftime("%Y%m%d"),
                        "endDate": window.end.strftime("%Y%m%d"),
                    },
                    "outputFile": f"partition-extracts/{dataset_name}_{index}.json",
                }
            )
    return extracts


def build_plan(
    config: dict[str, Any],
    registry: dict[str, dict[str, Any]],
    limits: dict[str, int],
    coverage: dict[str, dict[str, Any]],
    report_type: str,
    windows: dict[str, DateWindow],
    enterprise_name: str,
    organization_name: str | None = None,
    store_name_contains: list[str] | None = None,
) -> dict[str, Any]:
    business_date = require_field(config, registry, "business.date", "filter").canonical
    business_store = require_field(config, registry, "business.store", "group").canonical
    business_month = require_field(config, registry, "business.month", "group").canonical
    order_category = require_field(config, registry, "business.orderCategory", "group").canonical
    order_source = require_field(config, registry, "business.orderSource", "group").canonical
    dining_method = require_field(config, registry, "business.diningMethod", "group").canonical
    meal_period = require_field(config, registry, "business.mealPeriod", "group").canonical
    time_slot = require_field(config, registry, "business.timeSlot", "group").canonical
    membership = require_field(config, registry, "business.membership", "group").canonical

    dishes_date = require_field(config, registry, "dishes.date", "filter").canonical
    dishes_store = require_field(config, registry, "dishes.store", "group").canonical
    product_name = require_field(config, registry, "dishes.productName", "group").canonical
    matched_product_name = require_field(config, registry, "dishes.matchedProductName", "group").canonical
    dish_order_category = require_field(config, registry, "dishes.orderCategory", "group").canonical

    business_aggs = business_aggregates(config, registry)
    business_supplemental_sets = business_supplemental_aggregate_sets(config, registry)
    dish_aggs = dish_aggregates(config, registry)
    jobs: list[dict[str, Any]] = []
    notices: list[dict[str, Any]] = []
    trend_windows: dict[str, dict[str, str]] = {}

    def add_business_window(
        job_id: str,
        module: str,
        window: DateWindow,
        group_by: list[str],
        output_file: str,
        *,
        notice_partial: bool = False,
        daily_trend: bool = False,
    ) -> None:
        add_if_covered(
            jobs,
            notices,
            coverage,
            job=aggregate_job(
                job_id=job_id,
                module=module,
                dataset_name="business",
                registry=registry,
                window=window,
                date_field=business_date,
                group_by=group_by,
                aggregates=[{"op": "sum", "field": require_field(config, registry, "business.orderRevenue", "aggregate").canonical, "as": "order_revenue"}] if daily_trend else business_aggs,
                output_file=output_file,
                limits=limits,
            ),
            datasets=["business"],
            window=window,
            module=module,
            notice_partial=notice_partial,
        )
        if not daily_trend and jobs and jobs[-1]["id"] == job_id:
            for suffix, aggregates in business_supplemental_sets:
                jobs.append(
                    aggregate_job(
                        job_id=f"{job_id}_{suffix}",
                        module=module,
                        dataset_name="business",
                        registry=registry,
                        window=window,
                        date_field=business_date,
                        group_by=group_by,
                        aggregates=aggregates,
                        output_file=f"{output_file}_{suffix}",
                        limits=limits,
                    )
                )

    def add_business(job_id: str, module: str, window_name: str, group_by: list[str], output_file: str) -> None:
        add_business_window(job_id, module, windows[window_name], group_by, output_file)

    for window_name in WINDOW_NAMES:
        if report_type in {"weekly", "monthly"} or window_name == "current":
            add_business(
                f"business_{window_name}_store_totals",
                "coreBusiness",
                window_name,
                [business_store],
                f"business_{window_name}_store_totals",
            )

    if report_type == "diagnosis":
        diagnosis_jobs = [
            (
                "business_current_kpi_totals",
                "coreBusiness",
                [],
                "business_current_kpi_totals",
            ),
            (
                "business_current_channel_platform_mix",
                "channelMix",
                [business_store, order_category, order_source, dining_method],
                "business_current_channel_platform_mix",
            ),
            (
                "business_current_member_mix",
                "membership",
                [business_store, membership],
                "business_current_member_mix",
            ),
            (
                "business_current_payment_mix",
                "payment",
                [business_store, dining_method, order_source],
                "business_current_payment_mix",
            ),
            (
                "business_current_efficiency",
                "operatingEfficiency",
                [business_store, meal_period, time_slot],
                "business_current_efficiency",
            ),
        ]
        diagnosis_jobs.append(("business_current_monthly_trend", "monthlyTrend", [business_store, business_month], "business_current_monthly_trend"))
        for job_id, module, group_by, output_file in diagnosis_jobs:
            add_business(job_id, module, "current", group_by, output_file)
    else:
        if report_type == "weekly":
            trend_window = weekly_trend_window(windows["current"].end)
            trend_id = "business_16_week_store_trend"
            trend_group = [business_store, require_field(config, registry, "business.date", "group").canonical]
            trend_module = "weeklyTrend"
        else:
            trend_window = monthly_trend_window(windows["current"].end)
            trend_id = "business_6_month_store_trend"
            trend_group = [business_store, business_month]
            trend_module = "monthlyTrend"
        trend_windows["current"] = trend_window.as_json()
        add_business_window(trend_id, trend_module, trend_window, trend_group, trend_id, notice_partial=True, daily_trend=report_type == "weekly")

        prior_window = (
            DateWindow(
                "prior_year_trend",
                windows["yoy"].end - timedelta(days=(16 * 7) - 1),
                windows["yoy"].end,
            )
            if report_type == "weekly"
            else DateWindow(
                "prior_year_trend",
                same_date_previous_year(trend_window.start),
                same_date_previous_year(trend_window.end),
            )
        )
        prior_trend_id = (
            "business_16_week_prior_year_store_trend"
            if report_type == "weekly"
            else "business_6_month_prior_year_store_trend"
        )
        trend_windows["priorYear"] = prior_window.as_json()
        add_business_window(
            prior_trend_id,
            trend_module,
            prior_window,
            trend_group,
            prior_trend_id,
            notice_partial=True,
            daily_trend=report_type == "weekly",
        )

        for window_name in WINDOW_NAMES:
            add_business(
                f"business_{window_name}_channel_platform_mix",
                "channelMix",
                window_name,
                [business_store, order_category, order_source, dining_method],
                f"business_{window_name}_channel_platform_mix",
            )
            add_business(
                f"business_{window_name}_daypart_mix",
                "daypartAttribution",
                window_name,
                [business_store, meal_period, time_slot],
                f"business_{window_name}_daypart_mix",
            )
            add_if_covered(
                jobs,
                notices,
                coverage,
                job=aggregate_job(
                    job_id=f"dishes_{window_name}_product_totals",
                    module="stallAttribution",
                    dataset_name="dishes",
                    registry=registry,
                    window=windows[window_name],
                    date_field=dishes_date,
                    group_by=[dishes_store, product_name, matched_product_name, dish_order_category],
                    aggregates=dish_aggs,
                    output_file=f"dishes_{window_name}_product_totals",
                    limits=limits,
                    order_by=[{"field": "dish_revenue", "direction": "desc"}],
                ),
                datasets=["dishes", "dish_catalog"],
                window=windows[window_name],
                module="stallAttribution",
            )
        if coverage["dish_catalog"].get("sources"):
            add_if_covered(
                jobs,
                notices,
                coverage,
                job=catalog_job(config, registry, limits, coverage),
                datasets=["dish_catalog"],
                window=None,
                module="stallAttribution",
            )
        else:
            notices.append(
                make_notice("COVERAGE_WINDOW_MISSING", "dish_catalog", "current", "stallAttribution")
            )

    coverage_manifest = {
        dataset_name: source_summaries(dataset_coverage, windows)
        for dataset_name, dataset_coverage in sorted(coverage.items())
    }
    ordered_jobs = sorted(jobs, key=lambda job: (job["module"], job["id"]))
    if len(ordered_jobs) != len({job["id"] for job in ordered_jobs}):
        raise PlanError("duplicate job ids are not allowed")
    for job in ordered_jobs:
        validate_job(job, registry, limits)
    ordered_notices = sort_notices(notices)
    manifest = {
        "schemaVersion": config["schemaVersion"],
        "report": {
            "type": report_type,
            "windows": {name: window.as_json() for name, window in windows.items()},
            "trendWindows": trend_windows,
            "storeNameContains": store_name_contains or [],
        },
        "coverage": coverage_manifest,
        "notices": ordered_notices,
        "extracts": build_extracts(ordered_jobs, enterprise_name),
        "jobs": ordered_jobs,
    }
    if organization_name is not None:
        manifest["metadata"] = {"organization_name": organization_name}
    return manifest


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a registry-bound SMEDC query plan for business reports.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--report-type",
        required=True,
        choices=SUPPORTED_REPORT_TYPES,
        metavar="diagnosis|weekly|monthly",
        help="Report type to plan: diagnosis|weekly|monthly.",
    )
    parser.add_argument("--current-start", required=True, help="Current window start date, YYYY-MM-DD.")
    parser.add_argument("--current-end", required=True, help="Current window end date, YYYY-MM-DD.")
    parser.add_argument("--previous-start", required=True, help="Previous comparison window start date, YYYY-MM-DD.")
    parser.add_argument("--previous-end", required=True, help="Previous comparison window end date, YYYY-MM-DD.")
    parser.add_argument("--yoy-start", required=True, help="Year-over-year comparison window start date, YYYY-MM-DD.")
    parser.add_argument("--yoy-end", required=True, help="Year-over-year comparison window end date, YYYY-MM-DD.")
    parser.add_argument("--enterprise-name", required=True, help="Enterprise/source name to select and download.")
    parser.add_argument(
        "--store-name-contains",
        nargs="+",
        help="Keep business and dishes rows whose store name contains any supplied text (case-sensitive).",
    )
    parser.add_argument(
        "--current-user",
        type=Path,
        help="Saved smedc_get_current_user response used as the only report organization source.",
    )
    parser.add_argument("--registry-response", required=True, type=Path, help="Saved list_structured_datasets response.")
    parser.add_argument("--coverage-dir", required=True, type=Path, help="Directory with saved coverage_*.json envelopes.")
    parser.add_argument("--output", required=True, type=Path, help="Path for the query manifest JSON.")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    try:
        args = parse_args(argv)
        if args.current_user is None:
            raise PlanError(ORGANIZATION_ERROR)
        try:
            organization_name = organization_name_from_current_user_file(args.current_user)
        except ValueError as exc:
            raise PlanError(ORGANIZATION_ERROR) from exc
        config = load_json(CONFIG_PATH, "business-analysis config")
        if config.get("schemaVersion") != 1:
            raise PlanError("unsupported config schemaVersion")
        windows = build_windows(args)
        registry_response = load_mcp_json(args.registry_response, "registry response")
        registry, limits = registry_by_dataset(registry_response)
        validate_config_fields(config, registry)
        coverage, coverage_notices = load_coverage(config, registry, args.coverage_dir, args.enterprise_name)
        store_name_contains = []
        for value in args.store_name_contains or []:
            fragment = value.strip()
            if not fragment:
                raise PlanError("store-name-contains values must be non-blank")
            if fragment not in store_name_contains:
                store_name_contains.append(fragment)
        manifest = build_plan(
            config,
            registry,
            limits,
            coverage,
            args.report_type,
            windows,
            args.enterprise_name,
            organization_name,
            store_name_contains,
        )
        manifest["notices"] = sort_notices([*manifest["notices"], *coverage_notices])
        manifest["outputContract"] = {
            "tools": ["download_structured_partitions", "query_structured_dataset", "local_partition_aggregate"],
            "limits": limits,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except PlanError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
