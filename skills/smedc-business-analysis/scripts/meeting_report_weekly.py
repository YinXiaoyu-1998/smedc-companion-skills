#!/usr/bin/env python3
"""Generate a self-contained weekly meeting HTML report."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date, datetime
from html import escape
from pathlib import Path
from typing import Any

from build_query_plan import WEEKLY_TREND_WEEKS, weekly_trend_window
from identity import organization_name_from_metadata


def escaped_report_title(value: Any) -> str:
    return escape(str(value), quote=True)


def serialized_payload_for_html(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c").replace("&", "\\u0026")


def read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        for key, value in list(row.items()):
            if value is None:
                continue
            text = value.strip()
            if text == "":
                row[key] = None
                continue
            try:
                row[key] = float(text)
            except ValueError:
                row[key] = text
    return rows


def safe_sum(rows: list[dict[str, Any]], field: str) -> float:
    return round(sum(float(row.get(field) or 0) for row in rows), 2)


def read_optional_csv(path: Path) -> list[dict[str, Any]]:
    return read_csv(path) if path.exists() else []


def pct_change(current: float, baseline: float) -> float | None:
    if abs(baseline) < 1e-12:
        return None
    return round((current - baseline) / baseline, 4)


def aggregate_dayparts(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], float] = {}
    for row in rows:
        key = (str(row.get("period") or ""), str(row.get("餐段") or "未知餐段"), str(row.get("时段") or "未知时段"))
        groups[key] = groups.get(key, 0.0) + float(row.get("net_revenue") or 0)
    return [
        {"period": key[0], "餐段": key[1], "时段": key[2], "net_revenue": round(value, 2)}
        for key, value in sorted(groups.items())
    ]


def hour_text(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    if ":" in text:
        text = text.split(":", 1)[0]
    try:
        hour = int(float(text))
    except ValueError:
        return None
    if hour < 0 or hour > 23:
        return None
    return f"{hour:02d}"


def aggregate_hourly_revenue_entities(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    current_rows = [row for row in rows if row.get("period") == "本周"]
    hours = [f"{hour:02d}" for hour in range(24)]

    def build_entity(entity_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        groups = {hour: 0.0 for hour in hours}
        for row in entity_rows:
            hour = hour_text(row.get("时段"))
            if hour is None:
                continue
            groups[hour] += float(row.get("net_revenue") or 0)
        return [{"hour": hour, "net_revenue": round(groups[hour], 2)} for hour in hours]

    stores = sorted({str(row.get("门店名称") or "") for row in current_rows if row.get("门店名称")})
    entities = [{"key": "__all__", "label": "全体门店", "rows": build_entity(current_rows)}]
    for store in stores:
        store_rows = [row for row in current_rows if row.get("门店名称") == store]
        entities.append({"key": store, "label": store, "rows": build_entity(store_rows)})
    return entities


def parse_report_date(value: Any) -> date | None:
    text = str(value or "").strip().replace("-", "/")
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y/%m/%d").date()
    except ValueError:
        return None


def aggregate_trend(rows: list[dict[str, Any]], max_week_end: date | None) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, float]] = {}
    for row in rows:
        week_end = parse_report_date(row.get("week_end"))
        if max_week_end and week_end and week_end > max_week_end:
            continue
        label = str(row.get("week_label") or "")
        item = groups.setdefault(label, {"net_revenue": 0.0, "dine_in_revenue": 0.0, "delivery_revenue": 0.0})
        item["net_revenue"] += float(row.get("net_revenue") or 0)
        item["dine_in_revenue"] += float(row.get("dine_in_revenue") or 0)
        item["delivery_revenue"] += float(row.get("delivery_revenue") or 0)
    result = []
    for label, values in groups.items():
        result.append({"week_label": label, **{key: round(value, 2) for key, value in values.items()}})
    result.sort(key=lambda row: row["week_label"])
    return result[-WEEKLY_TREND_WEEKS:]


def build_trend_entities(rows: list[dict[str, Any]], max_week_end: date | None) -> list[dict[str, Any]]:
    stores = sorted({str(row.get("门店名称") or "") for row in rows if row.get("门店名称")})
    entities = [
        {"key": "__all__", "label": "全体门店", "rows": aggregate_trend(rows, max_week_end)}
    ]
    for store in stores:
        store_rows = [row for row in rows if row.get("门店名称") == store]
        entities.append({"key": store, "label": store, "rows": aggregate_trend(store_rows, max_week_end)})
    return entities


def build_trend_comparison_entities(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        return []

    def build_series(entity_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        groups: dict[int, dict[str, Any]] = {}
        for row in entity_rows:
            try:
                window_index = int(float(row.get("window_index") or 0))
            except (TypeError, ValueError):
                continue
            if window_index <= 0:
                continue
            item = groups.setdefault(
                window_index,
                {
                    "window_index": window_index,
                    "week_label": row.get("week_label") or "",
                    "current_net_revenue": None,
                    "prior_net_revenue": None,
                    "current_week_range": "",
                    "prior_week_range": "",
                },
            )
            series_key = str(row.get("series_key") or "")
            revenue = float(row["net_revenue"]) if row.get("net_revenue") is not None else None
            week_range = f"{row.get('week_start')}-{row.get('week_end')}"
            if series_key == "current_year":
                item["week_label"] = row.get("month_label") or row.get("week_label") or ""
                if revenue is not None:
                    item["current_net_revenue"] = round((item["current_net_revenue"] or 0) + revenue, 2)
                item["current_week_range"] = week_range
            elif series_key == "prior_year":
                if revenue is not None:
                    item["prior_net_revenue"] = round((item["prior_net_revenue"] or 0) + revenue, 2)
                item["prior_week_range"] = week_range
        return [groups[index] for index in sorted(groups)]

    stores = sorted({str(row.get("门店名称") or "") for row in rows if row.get("门店名称")})
    entities = [{"key": "__all__", "label": "全体门店", "rows": build_series(rows)}]
    for store in stores:
        store_rows = [row for row in rows if row.get("门店名称") == store]
        entities.append({"key": store, "label": store, "rows": build_series(store_rows)})
    return entities


def build_stall_sales_mix_payload(rows: list[dict[str, Any]], meta: dict[str, Any]) -> dict[str, Any]:
    current_rows = [
        row for row in rows
        if row.get("period_key") == "current" or row.get("period_label") in {"本周", "本月"}
    ]
    if not current_rows:
        return {"enabled": False, "meta": meta, "entities": []}

    def entity_key(label: str) -> str:
        return "__all__" if label == "全体门店" else label

    def build_entity(entity_rows: list[dict[str, Any]], label: str) -> dict[str, Any] | None:
        positive_rows = [
            row for row in entity_rows
            if float(row.get("stall_income") or 0) > 0
        ]
        if not positive_rows:
            return None
        denominator = max(float(row.get("dine_in_revenue") or 0) for row in entity_rows)
        total_income = sum(float(row.get("stall_income") or 0) for row in positive_rows)
        total = denominator if denominator > 0 else total_income
        if total <= 0:
            return None
        unmatched_rows = [row for row in positive_rows if str(row.get("档口") or "") == "未匹配"]
        matched_rows = [row for row in positive_rows if str(row.get("档口") or "") != "未匹配"]
        sorted_rows = sorted(matched_rows, key=lambda row: float(row.get("stall_income") or 0), reverse=True)
        top_rows = sorted_rows[:10]
        values = [
            {
                "name": str(row.get("档口") or "未分类"),
                "value": round(float(row.get("stall_income") or 0), 2),
                "quantity": round(float(row.get("quantity") or 0), 2),
                "share": round(float(row.get("stall_income") or 0) / total, 6),
                "is_other": False,
                "is_unmatched": False,
            }
            for row in top_rows
        ]
        unmatched_value = sum(float(row.get("stall_income") or 0) for row in unmatched_rows)
        if unmatched_value > 0.01:
            values.append({
                "name": "未匹配",
                "value": round(unmatched_value, 2),
                "quantity": round(sum(float(row.get("quantity") or 0) for row in unmatched_rows), 2),
                "share": round(unmatched_value / total, 6),
                "is_other": False,
                "is_unmatched": True,
            })
        other_rows = sorted_rows[10:]
        other_value = sum(float(row.get("stall_income") or 0) for row in other_rows)
        if other_value > 0.01:
            values.append({
                "name": "其他",
                "value": round(other_value, 2),
                "quantity": round(sum(float(row.get("quantity") or 0) for row in other_rows), 2),
                "share": round(other_value / total, 6),
                "is_other": True,
                "is_unmatched": False,
            })
        return {
            "key": entity_key(label),
            "label": label,
            "total": round(total, 2),
            "rows": values,
        }

    stores = sorted({str(row.get("门店名称") or "") for row in current_rows if row.get("门店名称")})
    ordered_stores = [store for store in ["全体门店"] if store in stores] + [store for store in stores if store != "全体门店"]
    entities = []
    for store in ordered_stores:
        entity = build_entity([row for row in current_rows if row.get("门店名称") == store], store)
        if entity:
            entities.append(entity)
    return {
        "enabled": bool(meta.get("enabled", bool(entities))) and bool(entities),
        "meta": meta,
        "entities": entities,
    }


def build_product_sales_per_10k_payload(
    rows: list[dict[str, Any]],
    meta: dict[str, Any],
    denominator_field: str = "order_revenue",
    metric_field: str = "units_per_10k",
    denominator_label: str = "订单营业收入",
) -> dict[str, Any]:
    current_rows = [row for row in rows if row.get("period_key") == "current"]
    if not current_rows:
        return {"enabled": False, "meta": meta, "entities": []}
    if not all(denominator_field in row and metric_field in row for row in current_rows):
        unavailable_meta = {
            **meta,
            "enabled": False,
            "reason": f"事实表缺少{denominator_label}口径字段，请重新运行 profiling 后生成报告。",
        }
        return {"enabled": False, "meta": unavailable_meta, "entities": []}
    if not all("销售分类" in row for row in current_rows):
        unavailable_meta = {
            **meta,
            "enabled": False,
            "reason": "事实表缺少销售分类字段，请重新运行 profiling 后生成报告。",
        }
        return {"enabled": False, "meta": unavailable_meta, "entities": []}

    stores = sorted({str(row.get("门店名称") or "") for row in current_rows if row.get("门店名称")})
    ordered_stores = [store for store in ["全体门店"] if store in stores] + [store for store in stores if store != "全体门店"]
    entities = []
    for store in ordered_stores:
        store_rows = [row for row in current_rows if row.get("门店名称") == store and float(row.get("quantity") or 0) > 0]
        store_rows.sort(key=lambda row: (-float(row.get(metric_field) or 0), str(row.get("产品名称") or "")))
        if not store_rows:
            continue
        denominator = max(float(row.get(denominator_field) or 0) for row in store_rows)
        available = denominator > 0
        entities.append({
            "key": "__all__" if store == "全体门店" else store,
            "label": store,
            "total_revenue": round(denominator, 2),
            "total_denominator": round(denominator, 2),
            "available": available,
            "unavailable_reason": "" if available else f"当前区间{denominator_label}为 0 或缺失，无法计算产品万元销量。",
            "rows": [
                {
                    "name": str(row.get("产品名称") or "未知菜品"),
                    "sales_class": str(row.get("销售分类") or "外卖"),
                    "stall": str(row.get("档口") or "未匹配"),
                    "quantity": round(float(row.get("quantity") or 0), 2),
                    "units_per_10k": (
                        round(float(row.get(metric_field)), 4)
                        if available and row.get(metric_field) not in (None, "")
                        else None
                    ),
                    "search_names": str(row.get("search_names") or row.get("产品名称") or ""),
                }
                for row in store_rows
            ],
        })
    any_available = any(entity["available"] for entity in entities)
    payload_meta = dict(meta)
    if not any_available:
        payload_meta["enabled"] = False
        payload_meta["reason"] = payload_meta.get("reason") or f"当前区间{denominator_label}为 0 或缺失，无法计算产品万元销量。"
    return {
        "enabled": bool(payload_meta.get("enabled", any_available)) and any_available,
        "meta": payload_meta,
        "entities": entities,
    }


def median(values: list[float]) -> float:
    clean = sorted(value for value in values if value is not None)
    if not clean:
        return 0
    mid = len(clean) // 2
    if len(clean) % 2:
        return clean[mid]
    return (clean[mid - 1] + clean[mid]) / 2


STORE_SIZE_ORDER = ["未分组"]
REVENUE_BASIS_NOTE = "业务收入=营业分组表「订单营业收入」；不使用「营业额(元)」。"


def build_segment_groups(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    for store_size in STORE_SIZE_ORDER:
        bucket_rows = [row for row in rows if row.get("store_size") == store_size]
        if not bucket_rows:
            continue
        segment_counts: dict[str, int] = {}
        for row in bucket_rows:
            segment = str(row.get("segment") or "未分型")
            segment_counts[segment] = segment_counts.get(segment, 0) + 1
        thresholds = [
            float(row.get("revenue_threshold") or 0)
            for row in bucket_rows
            if row.get("revenue_threshold") not in {None, ""}
        ]
        groups.append({
            "key": store_size,
            "label": store_size,
            "store_count": len(bucket_rows),
            "star_count": segment_counts.get("明星门店", 0),
            "problem_count": segment_counts.get("问题门店", 0),
            "segment_counts": segment_counts,
            "revenue_threshold": round(thresholds[0] if thresholds else median([float(row.get("current_net_revenue") or 0) for row in bucket_rows]), 2),
            "growth_threshold": 0,
            "rows": sorted(bucket_rows, key=lambda row: float(row.get("current_net_revenue") or 0), reverse=True),
        })
    return groups


def metric_lookup(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {str(row.get("metric") or ""): row.get("value") for row in rows}


def compact_daypart_drivers(rows: list[dict[str, Any]], basis: str = "环比") -> list[dict[str, Any]]:
    filtered = [row for row in rows if row.get("basis") == basis]
    filtered.sort(
        key=lambda row: abs(float(row.get("top_negative_net_revenue_delta") or 0))
        + abs(float(row.get("top_positive_net_revenue_delta") or 0)),
        reverse=True,
    )
    return filtered


def attach_daypart_slots(
    daypart_drivers: list[dict[str, Any]],
    daypart_comparison: list[dict[str, Any]],
    basis: str = "环比",
    limit: int = 3,
) -> list[dict[str, Any]]:
    prefix = "wow" if basis == "环比" else "yoy"
    by_store: dict[str, list[dict[str, Any]]] = {}
    for row in daypart_comparison:
        by_store.setdefault(str(row.get("门店名称") or ""), []).append(row)

    def slots(store: str, direction: str) -> list[dict[str, Any]]:
        candidates = []
        for row in by_store.get(store, []):
            delta = row.get(f"{prefix}_net_revenue_delta")
            if delta in {None, ""}:
                continue
            delta_value = float(delta or 0)
            if direction == "negative" and delta_value >= 0:
                continue
            if direction == "positive" and delta_value <= 0:
                continue
            candidates.append({
                "餐段": row.get("餐段") or "未知餐段",
                "时段": row.get("时段") or "未知时段",
                "current_net_revenue": row.get("current_net_revenue"),
                "baseline_net_revenue": row.get("previous_net_revenue") if prefix == "wow" else row.get("yoy_net_revenue"),
                "net_revenue_delta": row.get(f"{prefix}_net_revenue_delta"),
                "net_revenue_pct": row.get(f"{prefix}_net_revenue_pct"),
            })
        candidates.sort(key=lambda item: float(item.get("net_revenue_delta") or 0), reverse=(direction == "positive"))
        return candidates[:limit]

    enriched = []
    for row in daypart_drivers:
        item = dict(row)
        store = str(row.get("门店名称") or "")
        item["negative_slots"] = slots(store, "negative")
        item["positive_slots"] = slots(store, "positive")
        enriched.append(item)
    return enriched


def compact_stall_drivers(rows: list[dict[str, Any]], basis: str = "环比") -> list[dict[str, Any]]:
    filtered = [row for row in rows if row.get("basis") == basis]
    filtered.sort(
        key=lambda row: abs(float(row.get("top_negative_income_delta") or 0))
        + abs(float(row.get("top_positive_income_delta") or 0)),
        reverse=True,
    )
    return filtered


def attach_dish_examples(
    stall_drivers: list[dict[str, Any]],
    dish_drivers: list[dict[str, Any]],
    basis: str = "环比",
    limit: int = 3,
) -> list[dict[str, Any]]:
    by_key: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in dish_drivers:
        if row.get("basis") != basis:
            continue
        key = (
            str(row.get("门店名称") or ""),
            str(row.get("direction") or ""),
            str(row.get("档口") or ""),
        )
        by_key.setdefault(key, []).append(row)

    enriched = []
    for row in stall_drivers:
        item = dict(row)
        neg_key = (
            str(row.get("门店名称") or ""),
            "negative",
            str(row.get("top_negative_stall") or ""),
        )
        pos_key = (
            str(row.get("门店名称") or ""),
            "positive",
            str(row.get("top_positive_stall") or ""),
        )
        item["negative_dishes"] = by_key.get(neg_key, [])[:limit]
        item["positive_dishes"] = by_key.get(pos_key, [])[:limit]
        enriched.append(item)
    return enriched


def presentation_company_override(company: str | None) -> str | None:
    if company is None:
        return None
    stripped = company.strip()
    if stripped == "":
        raise ValueError("company override must be non-blank")
    return stripped


def build_payload(input_dir: Path, company: str | None = None) -> dict[str, Any]:
    summary = json.loads((input_dir / "weekly_meeting_summary.json").read_text(encoding="utf-8"))
    organization_name = organization_name_from_metadata(summary)
    report_company = presentation_company_override(company) or organization_name
    comparison = read_csv(input_dir / "weekly_store_comparison.csv")
    segments = read_csv(input_dir / "star_problem_stores.csv")
    drivers = read_csv(input_dir / "store_driver_summary.csv")
    channels = read_csv(input_dir / "weekly_store_channel_metrics.csv")
    dayparts = read_csv(input_dir / "weekly_store_daypart_metrics.csv")
    weekly = read_csv(input_dir / "weekly_store_metrics.csv")
    trend_comparison_path = input_dir / "weekly_trend_comparison_metrics.csv"
    trend_comparison = read_csv(trend_comparison_path) if trend_comparison_path.exists() else []
    daypart_comparison = read_optional_csv(input_dir / "weekly_store_daypart_comparison.csv")
    daypart_drivers = read_optional_csv(input_dir / "weekly_store_daypart_driver_summary.csv")
    stall_comparison = read_optional_csv(input_dir / "weekly_store_stall_comparison.csv")
    stall_drivers = read_optional_csv(input_dir / "weekly_store_stall_driver_summary.csv")
    dish_drivers = read_optional_csv(input_dir / "weekly_store_stall_dish_drivers.csv")
    match_summary = metric_lookup(read_optional_csv(input_dir / "dish_catalog_match_summary.csv"))
    stall_sales_mix = read_optional_csv(input_dir / "weekly_store_stall_sales_mix.csv")
    product_sales_per_10k = read_optional_csv(input_dir / "weekly_store_product_sales_per_10k.csv")

    segment_by_store = {row["门店名称"]: row for row in segments}
    driver_by_store = {
        row["门店名称"]: row
        for row in drivers
        if row.get("basis") == "环比"
    }
    for row in comparison:
        segment = segment_by_store.get(row["门店名称"], {})
        driver = driver_by_store.get(row["门店名称"], {})
        daypart_driver = next((item for item in daypart_drivers if item.get("门店名称") == row["门店名称"] and item.get("basis") == "环比"), {})
        stall_driver = next((item for item in stall_drivers if item.get("门店名称") == row["门店名称"] and item.get("basis") == "环比"), {})
        row["segment"] = segment.get("segment", "未分型")
        row["store_size"] = segment.get("store_size", "未分组")
        row["revenue_threshold"] = segment.get("revenue_threshold")
        row["growth_threshold"] = segment.get("growth_threshold")
        row["segment_reason"] = segment.get("reason", "")
        row["top_negative_factor"] = driver.get("top_negative_factor", "")
        row["top_daypart_signal"] = daypart_driver.get("daypart_signal", "")
        row["top_stall_signal"] = stall_driver.get("stall_signal", "")
        row["wow_order_volume_contribution"] = driver.get("order_volume_contribution")
        row["wow_aov_contribution"] = driver.get("aov_contribution")
        row["wow_dine_in_delta"] = driver.get("dine_in_delta")
        row["wow_delivery_delta"] = driver.get("delivery_delta")

    comparison.sort(key=lambda row: float(row.get("current_net_revenue") or 0), reverse=True)
    current_revenue = safe_sum(comparison, "current_net_revenue")
    previous_revenue = safe_sum(comparison, "previous_net_revenue")
    yoy_revenue = safe_sum(comparison, "yoy_net_revenue")
    current_customers = safe_sum(comparison, "current_customer_count")
    previous_customers = safe_sum(comparison, "previous_customer_count")
    yoy_customers = safe_sum(comparison, "yoy_customer_count")
    current_tables = safe_sum(comparison, "current_consumed_tables")
    previous_tables = safe_sum(comparison, "previous_consumed_tables")
    yoy_tables = safe_sum(comparison, "yoy_consumed_tables")
    current_aov = current_revenue / safe_sum(comparison, "current_positive_orders") if safe_sum(comparison, "current_positive_orders") else 0
    star_count = sum(1 for row in comparison if row.get("segment") == "明星门店")
    problem_count = sum(1 for row in comparison if row.get("segment") == "问题门店")
    segment_groups = build_segment_groups(comparison)
    revenue_threshold = median([float(row.get("current_net_revenue") or 0) for row in comparison])
    current_window_end = parse_report_date(summary["meta"]["target_windows"]["current"]["end"])
    yoy_window_end = parse_report_date(summary["meta"]["target_windows"]["yoy"]["end"])
    current_trend_start = weekly_trend_window(current_window_end).start if current_window_end else None
    yoy_trend_start = weekly_trend_window(yoy_window_end).start if yoy_window_end else None
    trend_note = "完整周口径；实线=本期，虚线=同期，均为最近一年（52 个完整周）。"
    def short_date(value: date) -> str:
        return value.isoformat()

    if current_window_end and yoy_window_end and current_trend_start and yoy_trend_start:
        trend_note = (
            f"完整周口径；实线=本期（{short_date(current_trend_start)}-{short_date(current_window_end)}），"
            f"虚线=同期（{short_date(yoy_trend_start)}-{short_date(yoy_window_end)}）。"
        )

    current_channels = [row for row in channels if row.get("period") == "本周"]
    channel_by_store: dict[str, dict[str, float]] = {}
    for row in current_channels:
        store = str(row.get("门店名称") or "")
        channel = str(row.get("channel") or "")
        channel_by_store.setdefault(store, {})[channel] = float(row.get("net_revenue") or 0)

    return {
        "meta": {
            "title": f"{report_company}周经营会报",
            "company": report_company,
            "generated": date.today().isoformat(),
            **summary["meta"],
            "revenue_basis": REVENUE_BASIS_NOTE,
        },
        "kpis": {
            "current_revenue": current_revenue,
            "wow_pct": pct_change(current_revenue, previous_revenue),
            "yoy_pct": pct_change(current_revenue, yoy_revenue),
            "current_customers": current_customers,
            "wow_customer_pct": pct_change(current_customers, previous_customers),
            "yoy_customer_pct": pct_change(current_customers, yoy_customers),
            "current_tables": current_tables,
            "wow_table_pct": pct_change(current_tables, previous_tables),
            "yoy_table_pct": pct_change(current_tables, yoy_tables),
            "current_aov": round(current_aov, 2),
            "star_count": star_count,
            "problem_count": problem_count,
        },
        "availability": {
            "current": any(row.get("current_rows") for row in comparison),
            "trend": bool(trend_comparison or weekly),
            "channels": bool(current_channels),
            "dayparts": bool(dayparts),
        },
        "segment_rules": {
            "revenue_threshold": round(revenue_threshold, 2),
            "growth_threshold": 0,
            "items": [
                {
                    "name": "明星门店",
                    "logic": "本周业务收入 >= 门店中位数，且环比增长率 >= 0%",
                    "use": "优先沉淀打法，复盘可复制动作。",
                },
                {
                    "name": "高基盘承压",
                    "logic": "本周业务收入 >= 门店中位数，但环比增长率 < 0%",
                    "use": "收入体量仍大，但要复盘短期下滑原因。",
                },
                {
                    "name": "成长观察",
                    "logic": "本周业务收入 < 门店中位数，但环比增长率 >= 0%",
                    "use": "关注增长是否可持续，寻找放大空间。",
                },
                {
                    "name": "问题门店",
                    "logic": "本周业务收入 < 门店中位数，且环比增长率 < 0%",
                    "use": "优先排查客流、开台、客单和折扣拖累。",
                },
            ],
            "warnings": "同比下滑超过 25%、环比下滑超过 8%、折扣率高于门店中位水平 20% 以上、客单价低于门店中位水平 10% 以上，会作为预警补充到门店原因中。",
        },
        "segment_groups": segment_groups,
        "comparison": comparison,
        "drivers": [row for row in drivers if row.get("basis") == "环比"],
        "segments": segments,
        "channel_by_store": channel_by_store,
        "stall_sales_mix": build_stall_sales_mix_payload(stall_sales_mix, summary["meta"].get("stall_sales_mix", {})),
        "product_sales_per_10k": build_product_sales_per_10k_payload(product_sales_per_10k, summary["meta"].get("product_sales_per_10k", {})),
        "product_sales_per_10k_order_revenue": build_product_sales_per_10k_payload(
            product_sales_per_10k,
            summary["meta"].get("product_sales_per_10k_order_revenue", summary["meta"].get("product_sales_per_10k", {})),
        ),
        "product_sales_per_10k_gross_sales": build_product_sales_per_10k_payload(
            product_sales_per_10k,
            summary["meta"].get("product_sales_per_10k_gross_sales", {}),
            denominator_field="gross_sales",
            metric_field="units_per_10k_gross_sales",
            denominator_label="营业额",
        ),
        "dayparts": aggregate_dayparts([row for row in dayparts if row.get("period") in {"本周", "环比周"}]),
        "hourly_revenue_entities": aggregate_hourly_revenue_entities(dayparts),
        "trend": aggregate_trend(weekly, current_window_end),
        "trend_entities": build_trend_comparison_entities(trend_comparison) or build_trend_entities(weekly, current_window_end),
        "trend_note": trend_note,
        "daypart_attribution": {
            "enabled": bool(summary["meta"].get("daypart_attribution", {}).get("enabled", True)) and bool(daypart_drivers),
            "meta": summary["meta"].get("daypart_attribution", {}),
            "comparison": daypart_comparison,
            "drivers": attach_daypart_slots(compact_daypart_drivers(daypart_drivers, "环比"), daypart_comparison, "环比"),
            "yoy_drivers": attach_daypart_slots(compact_daypart_drivers(daypart_drivers, "同比"), daypart_comparison, "同比"),
        },
        "stall_attribution": {
            "enabled": bool(summary["meta"].get("stall_attribution", {}).get("enabled")) and bool(stall_drivers),
            "meta": summary["meta"].get("stall_attribution", {}),
            "comparison": stall_comparison,
            "drivers": attach_dish_examples(compact_stall_drivers(stall_drivers, "环比"), dish_drivers, "环比"),
            "yoy_drivers": attach_dish_examples(compact_stall_drivers(stall_drivers, "同比"), dish_drivers, "同比"),
            "match_summary": match_summary,
        },
        "data_gaps": summary.get("data_gaps", []),
    }


HTML_TEMPLATE = r'''<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>__TITLE__</title>
  <style>
    :root {
      --bg: #f5f7fa;
      --surface: #fff;
      --ink: #172033;
      --muted: #657386;
      --line: #d9e2ea;
      --teal: #006d77;
      --blue: #2f5b9f;
      --green: #3a7d44;
      --amber: #b85c00;
      --red: #b23a48;
      --violet: #7557a6;
      --shadow: 0 14px 34px rgba(23, 32, 51, .07);
      --radius: 8px;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      color: var(--ink);
      background: var(--bg);
      font: 14px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      letter-spacing: 0;
    }
    .topbar {
      position: sticky;
      top: 0;
      z-index: 10;
      background: rgba(245, 247, 250, .95);
      border-bottom: 1px solid var(--line);
      backdrop-filter: blur(12px);
    }
    .topbar-inner {
      max-width: 1360px;
      margin: 0 auto;
      padding: 12px 24px;
      display: flex;
      justify-content: space-between;
      gap: 18px;
      align-items: center;
    }
    .brand { font-weight: 820; display: flex; align-items: center; gap: 10px; }
    .mark { width: 30px; height: 30px; border-radius: 8px; background: linear-gradient(135deg, var(--teal), var(--blue)); }
    .nav { display: flex; flex-wrap: wrap; gap: 6px; }
    .nav a {
      color: var(--muted);
      text-decoration: none;
      padding: 7px 10px;
      border-radius: 999px;
    }
    .nav a:hover { background: var(--surface); color: var(--ink); }
    main { max-width: 1360px; margin: 0 auto; padding: 26px 24px 64px; }
    .hero {
      display: grid;
      grid-template-columns: minmax(0, 1.3fr) minmax(320px, .7fr);
      gap: 22px;
      align-items: stretch;
      padding: 12px 0 24px;
    }
    h1 { font-size: 38px; line-height: 1.12; margin: 8px 0 12px; }
    h2 { font-size: 24px; line-height: 1.24; margin: 0; }
    h3 { font-size: 16px; margin: 0; }
    .kicker { color: var(--teal); font-size: 12px; font-weight: 800; text-transform: uppercase; }
    .lede { color: var(--muted); max-width: 780px; font-size: 16px; margin: 0; }
    .meta { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 18px; }
    .chip { border: 1px solid var(--line); background: var(--surface); color: var(--muted); padding: 7px 10px; border-radius: 999px; }
    .summary {
      background: #172033;
      color: #fff;
      border-radius: var(--radius);
      padding: 20px;
      display: grid;
      gap: 12px;
      box-shadow: var(--shadow);
    }
    .summary b { font-size: 28px; display: block; line-height: 1.1; margin-top: 6px; }
    .summary span { color: rgba(255,255,255,.72); }
    .section { border-top: 1px solid var(--line); padding: 30px 0; }
    .section-head { display: flex; justify-content: space-between; align-items: end; gap: 18px; margin-bottom: 16px; }
    .note { color: var(--muted); max-width: 620px; margin: 0; }
    .grid-4 { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px; }
    .grid-3 { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; }
    .grid-2 { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
    .full-row { margin-top: 16px; }
    .trend-controls { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; margin-top: 6px; font-size: 12px; color: var(--muted); }
    .trend-controls[hidden] { display: none; }
    .trend-controls label { display: flex; align-items: center; gap: 6px; }
    .trend-controls select { max-width: 190px; padding: 6px; border: 1px solid var(--line); border-radius: 6px; background: white; color: var(--ink); }
    .trend-presets { display: flex; flex-wrap: wrap; gap: 6px; }
    .trend-presets button { padding: 6px 10px; border: 1px solid var(--line); border-radius: 6px; background: white; color: var(--ink); cursor: pointer; }
    .trend-presets button[aria-pressed="true"] { background: #eff6ff; border-color: #2563eb; color: #1d4ed8; }
    .trend-navigator { margin: 12px 0 6px; touch-action: none; user-select: none; }
    .trend-navigator svg { display: block; width: 100%; height: 64px; }
    .trend-range-label { flex-basis: 100%; }
    .rule-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-top: 14px; }
    .rule {
      border: 1px dashed var(--line);
      background: var(--surface);
      border-radius: var(--radius);
      padding: 13px;
      min-height: 126px;
    }
    .rule-title { font-weight: 820; display: flex; align-items: center; gap: 7px; margin-bottom: 7px; }
    .dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; }
    .rule p { margin: 0; color: var(--muted); font-size: 12px; }
    .rule small { display: block; color: var(--ink); margin-top: 8px; font-size: 12px; }
    .rule-note { color: var(--muted); margin-top: 10px; font-size: 12px; }
    .card, .panel {
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      box-shadow: 0 10px 24px rgba(23, 32, 51, .045);
    }
    .card { padding: 15px; min-height: 120px; }
    .label { color: var(--muted); font-size: 12px; font-weight: 760; }
    .value { font-size: 28px; font-weight: 840; line-height: 1; margin-top: 8px; }
    .foot { color: var(--muted); font-size: 12px; margin-top: 10px; }
    .panel { padding: 17px; min-width: 0; }
    .panel-head { display: flex; justify-content: space-between; gap: 12px; align-items: center; margin-bottom: 8px; }
    .panel-title-row { display: flex; align-items: center; gap: 12px; min-width: 0; }
    .mini-select {
      height: 32px;
      min-width: 150px;
      max-width: 240px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: var(--surface);
      color: var(--ink);
      padding: 0 32px 0 10px;
      font: inherit;
      font-weight: 700;
      outline: none;
    }
    .mini-select:focus { border-color: var(--teal); box-shadow: 0 0 0 3px rgba(0, 109, 119, .12); }
    .search-input {
      height: 36px;
      min-width: 240px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: var(--surface);
      color: var(--ink);
      padding: 0 11px;
      font: inherit;
      outline: none;
    }
    .search-input:focus { border-color: var(--teal); box-shadow: 0 0 0 3px rgba(0, 109, 119, .12); }
    .product-toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; }
    .chart { width: 100%; min-height: 310px; overflow: hidden; position: relative; }
    .chart svg { display: block; width: 100%; min-height: 310px; }
    .growth-board { margin-top: 10px; border: 1px solid var(--line); border-radius: var(--radius); overflow: hidden; }
    .growth-legend { display: flex; flex-wrap: wrap; gap: 16px; align-items: center; color: var(--muted); font-size: 12px; padding: 4px 0 8px; }
    .growth-store { padding: 14px 16px; border-top: 1px solid var(--line); }
    .growth-store:first-child { border-top: 0; }
    .growth-store-head { display: grid; grid-template-columns: 132px minmax(0, 1fr) 138px; gap: 16px; align-items: center; }
    .growth-store-name { color: var(--ink); font-size: 14px; font-weight: 820; }
    .growth-primary { display: grid; gap: 5px; }
    .growth-primary-row { display: grid; grid-template-columns: 104px minmax(0, 1fr); gap: 10px; align-items: center; min-height: 30px; }
    .growth-metric-label { color: var(--muted); font-size: 12px; font-weight: 760; white-space: nowrap; }
    .growth-axis { min-width: 0; }
    .growth-axis svg { display: block; width: 100%; height: 28px; min-height: 0; }
    .growth-toggle { border: 1px solid #9bb8e8; border-radius: 6px; background: #fff; color: #1d4ed8; padding: 8px 10px; font: inherit; font-size: 12px; font-weight: 760; cursor: pointer; white-space: nowrap; }
    .growth-toggle:hover { background: #f3f7ff; border-color: #1d4ed8; }
    .growth-toggle:focus-visible { outline: 3px solid rgba(29, 78, 216, .18); outline-offset: 2px; }
    .growth-channel-detail { margin: 12px 0 0 148px; padding: 8px 12px; border: 1px solid #dce8ef; border-radius: 7px; background: #f7fbfc; }
    .growth-channel-detail[hidden] { display: none; }
    .growth-channel-row { display: grid; grid-template-columns: 62px minmax(0, 1fr) minmax(0, 1fr); gap: 18px; align-items: center; padding: 8px 0; }
    .growth-channel-row + .growth-channel-row { border-top: 1px solid #e3ebf0; }
    .growth-channel-name { color: var(--ink); font-size: 13px; font-weight: 820; }
    .growth-channel-metric { display: grid; grid-template-columns: 36px minmax(0, 1fr); gap: 8px; align-items: center; }
    .growth-channel-metric .growth-metric-label { font-size: 11px; }
    .chart-tooltip {
      position: absolute;
      display: none;
      pointer-events: none;
      z-index: 4;
      background: #111827;
      color: #fff;
      border-radius: 6px;
      padding: 7px 9px;
      font-size: 12px;
      line-height: 1.35;
      box-shadow: 0 8px 20px rgba(17, 24, 39, .18);
      max-width: min(280px, calc(100% - 16px));
      white-space: normal;
      overflow-wrap: anywhere;
    }
    .chart-tooltip strong { display: block; margin-bottom: 2px; color: #fff; }
    .legend { display: flex; gap: 12px; flex-wrap: wrap; color: var(--muted); font-size: 12px; margin-top: 8px; }
    .swatch { width: 10px; height: 10px; border-radius: 2px; display: inline-block; margin-right: 5px; }
    .table-wrap { overflow: auto; border: 1px solid var(--line); border-radius: var(--radius); background: var(--surface); }
    table { border-collapse: collapse; width: 100%; min-width: 1180px; }
    .compact-table { min-width: 520px; }
    th, td { padding: 10px 11px; border-bottom: 1px solid var(--line); text-align: left; white-space: nowrap; }
    th { background: #f0f4f7; color: var(--muted); font-size: 12px; position: sticky; top: 0; cursor: pointer; }
    td { font-size: 13px; }
    .tag { display: inline-flex; padding: 4px 8px; border-radius: 999px; background: #edf5f3; color: var(--teal); font-weight: 760; font-size: 12px; }
    .tag.problem { background: #fff0f2; color: var(--red); }
    .tag.star { background: #eef8ef; color: var(--green); }
    .tag.pressure { background: #fff5e8; color: var(--amber); }
    .tag.growth { background: #edf3ff; color: var(--blue); }
    .callout { border-left: 4px solid var(--amber); background: #fff8ef; border-radius: 0 8px 8px 0; padding: 14px 16px; color: #61420f; }
    @media (max-width: 980px) {
      .hero, .grid-2, .grid-3 { grid-template-columns: 1fr; }
      .grid-4, .rule-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .section-head { align-items: start; flex-direction: column; }
      .growth-store-head { grid-template-columns: 108px minmax(0, 1fr); }
      .growth-toggle { grid-column: 2; justify-self: start; }
      .growth-channel-detail { margin-left: 124px; }
    }
    @media (max-width: 620px) {
      main { padding: 18px 14px 48px; }
      .topbar-inner { align-items: start; flex-direction: column; }
      .grid-4, .rule-grid { grid-template-columns: 1fr; }
      h1 { font-size: 30px; }
      .growth-store-head { grid-template-columns: 1fr; }
      .growth-primary-row { grid-template-columns: 92px minmax(0, 1fr); }
      .growth-toggle { grid-column: 1; }
      .growth-channel-detail { margin-left: 0; }
      .growth-channel-row { grid-template-columns: 1fr; gap: 6px; }
    }
  </style>
</head>
<body>
  <header class="topbar">
    <div class="topbar-inner">
      <div class="brand"><span class="mark"></span><span>__REPORT_TITLE__</span></div>
      <nav class="nav">
        <a href="#summary">结论</a>
        <a href="#ranking">横向对比</a>
        <a href="#stores">门店明细</a>
        <a href="#channels">堂食外卖</a>
        <a href="#stall-mix">档口占比</a>
        <a href="#product-sales-per-10k">产品万元销量</a>
        <a href="#drivers">归因</a>
        <a href="#stall-drivers">档口归因</a>
        <a href="#daypart-drivers">时段归因</a>
        <a href="#dayparts">时段收入</a>
      </nav>
    </div>
  </header>
  <main>
    <section class="hero">
      <div>
        <div class="kicker">Weekly Operating Review</div>
        <h1>__REPORT_TITLE__</h1>
        <p class="lede">基于美团营业分组表，聚焦每家门店本周经营、同比/环比变化、堂食/外卖结构、客流/开台/客单归因，以及明星与问题门店识别。</p>
        <div class="meta" id="metaChips"></div>
      </div>
      <aside class="summary">
        <div><span>本周业务收入</span><b id="heroRevenue"></b></div>
        <div class="grid-2">
          <div><span>环比</span><b id="heroWow"></b></div>
          <div><span>同比</span><b id="heroYoy"></b></div>
        </div>
      </aside>
    </section>

    <div id="missingDataNotice" class="callout" hidden></div>

    <section class="section" id="summary">
      <div class="section-head">
        <div><div class="kicker">01 Executive Summary</div><h2>先看结论：哪些门店值得复制，哪些门店要复盘</h2></div>
        <p class="note">本页业务收入口径为营业分组表“订单营业收入”；所有指标均为聚合后重新计算，时段归因基于“时段”字段。</p>
      </div>
      <div class="grid-4" id="kpiCards"></div>
      <div id="segmentRules"></div>
    </section>

    <section class="section" id="ranking">
      <div class="section-head">
        <div><div class="kicker">02 Store Benchmark</div><h2>门店横向对比：收入规模、增长和经营效率一起看</h2></div>
      </div>
      <div class="grid-2">
        <div class="panel">
          <div class="panel-head"><h3>本周门店业务收入排名</h3><span class="label">按全体门店看</span></div>
          <div class="chart" id="revenueBar"></div>
        </div>
        <div class="panel">
          <div class="panel-head"><h3>明星与问题门店四象限</h3><span class="label">各 bucket 内收入中位数</span></div>
          <div class="chart" id="scatter"></div>
        </div>
      </div>
      <div class="panel full-row">
        <div class="panel-head"><h3>业务收入同比 / 环比增长率</h3><span class="label">默认仅看业务收入；点击门店可展开堂食与外卖</span></div>
        <div class="chart" id="growthBar"></div>
      </div>
      <div class="panel full-row">
        <div class="panel-head">
          <div class="panel-title-row"><h3>最近一年收入趋势（52 周）</h3><select id="trendStoreSelect" class="mini-select" aria-label="选择门店趋势"></select></div>
          <span class="label" id="trendMetricLabel">完整周，整体业务收入（万元）；实线=本年，虚线=同期</span>
        </div>
        <div class="chart" id="trend"></div>
        <div class="trend-navigator" id="trendNavigator" aria-label="拖动两端调整时间范围，拖动选区移动时间段"></div>
        <div class="trend-controls" id="trendControls">
          <div class="trend-presets" id="trendPresets" aria-label="快捷时间范围"></div>
          <label>开始<select id="trendStartSelect" aria-label="趋势开始时间"></select></label>
          <label>结束<select id="trendEndSelect" aria-label="趋势结束时间"></select></label>
          <span class="trend-range-label" id="trendRangeLabel" role="status" aria-live="polite"></span>
          <span>拖动总览两端可缩放，拖动选区可平移；也可选择开始和结束时间。</span>
        </div>
      </div>
    </section>

    <section class="section" id="stores">
      <div class="section-head">
        <div><div class="kicker">03 Store Detail</div><h2>门店明细：本周值、同比、环比和主要提示</h2></div>
        <p class="note">点击表头可排序。问题门店优先看“主要负向因素”。</p>
      </div>
      <div class="table-wrap">
        <table id="storeTable">
          <thead><tr>
            <th data-key="门店名称">门店</th>
            <th data-key="store_size">门店类型</th>
            <th data-key="segment">分型</th>
            <th data-key="current_net_revenue">业务收入</th>
            <th data-key="wow_net_revenue_pct">环比</th>
            <th data-key="yoy_net_revenue_pct">同比</th>
            <th data-key="current_dine_in_revenue">堂食收入</th>
            <th data-key="current_delivery_revenue">外卖收入</th>
            <th data-key="current_customer_count">客流</th>
            <th data-key="current_consumed_tables">开台/桌数</th>
            <th data-key="current_post_discount_aov">客单价</th>
            <th data-key="current_discount_rate">折扣率</th>
            <th data-key="top_stall_signal">主要档口信号</th>
            <th data-key="top_daypart_signal">主要时段信号</th>
            <th data-key="top_negative_factor">主要提示</th>
          </tr></thead>
          <tbody></tbody>
        </table>
      </div>
    </section>

    <section class="section" id="channels">
      <div class="section-head">
        <div><div class="kicker">04 Dine-in / Delivery</div><h2>堂食与外卖：收入结构和变化贡献</h2></div>
      </div>
      <div class="grid-2">
        <div class="panel">
          <div class="panel-head"><h3>本周堂食 / 外卖结构</h3><span class="label">按门店堆叠</span></div>
          <div class="chart" id="mixBar"></div>
          <div class="legend"><span><i class="swatch" style="background:#006d77"></i>堂食</span><span><i class="swatch" style="background:#2f5b9f"></i>外卖</span><span><i class="swatch" style="background:#b85c00"></i>其他</span></div>
        </div>
        <div class="panel">
          <div class="panel-head"><h3>外卖平台收入</h3><span class="label">美团 / 饿了么 / 京东</span></div>
          <div class="chart" id="platformBar"></div>
          <div class="legend"><span><i class="swatch" style="background:#3a7d44"></i>美团</span><span><i class="swatch" style="background:#7557a6"></i>饿了么</span><span><i class="swatch" style="background:#d96b3b"></i>京东</span></div>
        </div>
      </div>
    </section>

    <section class="section" id="stall-mix">
      <div class="section-head">
        <div><div class="kicker">05 Stall Sales Mix</div><h2>档口占比：店内营业收入由哪些档口构成</h2></div>
        <p class="note">只看店内销售：分母为营业分组表“店内营业收入”；分子为双名称匹配后归入各档口的“菜品收入”合计，无法匹配的收入单列为“未匹配”。</p>
      </div>
      <div class="grid-2">
        <div class="panel">
          <div class="panel-head">
            <div class="panel-title-row"><h3>Top 10 档口占比</h3><select id="stallMixStoreSelect" class="mini-select" aria-label="选择门店档口占比"></select></div>
            <span class="label" id="stallMixTotalLabel">本周店内营业收入</span>
          </div>
          <div class="chart" id="stallMixPie"></div>
        </div>
        <div class="panel">
          <div class="panel-head"><h3>档口占比明细</h3><span class="label">Top 10 + 未匹配 + 其他</span></div>
          <div class="table-wrap"><table class="compact-table" id="stallMixTable"><thead><tr><th>档口</th><th>档口收入</th><th>占比</th><th>数量</th></tr></thead><tbody></tbody></table></div>
        </div>
      </div>
    </section>

    <section class="section" id="product-sales-per-10k">
      <div class="section-head">
        <div><div class="kicker">06 Product Sales per ¥10K</div><h2>产品万元销量：双口径预测与要货参考</h2></div>
        <p class="note">菜品销量按订单分类拆分：店内销售归为“堂食”，其他值归为“外卖”；两类仍共用所选门店、当前统计区间的全渠道总分母。两个板块仅分母分别采用“订单营业收入”和“营业额(元)”。产品名优先采用“关联菜品名称”，为空时回退至“菜品名称”。</p>
      </div>
      <div class="panel">
        <div class="panel-head">
          <div><h3>产品万元销量（订单营业收入）</h3><div class="product-toolbar" style="margin-top:8px;">
            <select id="productSalesPer10kStoreSelect" class="mini-select" aria-label="选择门店产品万元销量（订单营业收入）"></select>
            <input id="productSalesPer10kSearch" class="search-input" type="search" placeholder="搜索菜品名称或关联菜品名称，例如：生蚝" aria-label="搜索产品">
          </div></div>
          <span class="label" id="productSalesPer10kStatus">默认显示 Top 10</span>
        </div>
        <div class="table-wrap"><table class="compact-table" id="productSalesPer10kTable"><thead><tr><th>产品名称</th><th>销售分类</th><th>档口</th><th>本期销量</th><th>产品万元销量</th></tr></thead><tbody></tbody></table></div>
      </div>
      <div class="panel full-row">
        <div class="panel-head">
          <div><h3>产品万元销量（营业额）</h3><div class="product-toolbar" style="margin-top:8px;">
            <select id="productSalesPer10kGrossStoreSelect" class="mini-select" aria-label="选择门店产品万元销量（营业额）"></select>
            <input id="productSalesPer10kGrossSearch" class="search-input" type="search" placeholder="搜索菜品名称或关联菜品名称，例如：生蚝" aria-label="搜索产品（营业额口径）">
          </div></div>
          <span class="label" id="productSalesPer10kGrossStatus">默认显示 Top 10</span>
        </div>
        <div class="table-wrap"><table class="compact-table" id="productSalesPer10kGrossTable"><thead><tr><th>产品名称</th><th>销售分类</th><th>档口</th><th>本期销量</th><th>产品万元销量</th></tr></thead><tbody></tbody></table></div>
      </div>
    </section>

    <section class="section" id="drivers">
      <div class="section-head">
        <div><div class="kicker">07 Drivers</div><h2>问题归因：客流/订单量与客单价谁在拖动收入</h2></div>
        <p class="note">先看订单量与单均各自贡献，再结合具体门店、餐段和出品情况，选择优先改善的环节。</p>
      </div>
      <div class="panel">
        <div class="panel-head"><h3>问题门店环比归因</h3><span class="label">按全体门店看量贡献 vs 价贡献</span></div>
        <div class="chart" id="driverBar"></div>
      </div>
      <div class="full-row">
        <div class="panel">
          <div class="panel-head"><h3>经营动作提示</h3><span class="label">按分型汇总</span></div>
          <div id="actionList"></div>
        </div>
      </div>
    </section>

    <section class="section" id="stall-drivers">
      <div class="section-head">
        <div><div class="kicker">08 Stall Attribution</div><h2>档口归因：把门店变化穿透到基础分类和代表菜品</h2></div>
        <p class="note">档口 = 菜品库「总部菜品.基础分类」。菜品表无稳定编码时使用菜品名称匹配，未匹配项单独归类。</p>
      </div>
      <div id="stallAttribution"></div>
    </section>

    <section class="section" id="daypart-drivers">
      <div class="section-head">
        <div><div class="kicker">09 Daypart Attribution</div><h2>时段归因：看门店增长和下滑发生在哪些时段</h2></div>
        <p class="note">按门店、餐段、时段汇总订单营业收入，分别比较环比和同比变化；用于定位复盘方向。</p>
      </div>
      <div id="daypartAttribution"></div>
    </section>

    <section class="section" id="dayparts">
      <div class="section-head">
        <div><div class="kicker">09 Hourly Revenue</div><h2>时段收入：看全天高峰，也看单店节奏</h2></div>
      </div>
      <div class="panel">
        <div class="panel-head">
          <div class="panel-title-row"><h3>本周 24 小时收入分布</h3><select id="hourlyStoreSelect" class="mini-select" aria-label="选择门店时段收入"></select></div>
          <span class="label" id="hourlyRevenueLabel">本周，整体业务收入（万元）</span>
        </div>
        <div id="hourlyRevenueBar" class="chart"></div>
      </div>
      <div class="callout" style="margin-top:16px;" id="dataGaps"></div>
    </section>
  </main>
  <script id="payload" type="application/json">__PAYLOAD__</script>
  <script>
    const data = JSON.parse(document.getElementById('payload').textContent);
    const stores = data.comparison;
    const fmtWan = v => {
      const raw = Number(v || 0) / 10000;
      const value = Math.abs(raw) < 0.05 ? 0 : raw;
      return `${value.toLocaleString('zh-CN', {maximumFractionDigits: 1})}万`;
    };
    const fmtNum = v => Number(v || 0).toLocaleString('zh-CN', {maximumFractionDigits: 0});
    const fmtYuan = v => `${Number(v || 0).toLocaleString('zh-CN', {maximumFractionDigits: 1})}元`;
    const fmtPct = v => v === null || v === undefined || v === '' ? 'N/A' : `${(Number(v) * 100).toFixed(1)}%`;
    const cleanName = s => String(s || '');
    const colors = { teal:'#006d77', blue:'#2f5b9f', green:'#3a7d44', amber:'#b85c00', red:'#b23a48', violet:'#7557a6', orange:'#d96b3b', yellow:'#c89b18', yellowFill:'#f2c94c', maximum:'#2f80ed', maximumStroke:'#1c5fb8', minimum:'#e5484d', minimumStroke:'#b42318' };
    const segmentGroups = data.segment_groups || [];
    let selectedTrendKey = '__all__';
    let trendStart = 0, trendEnd = null;
    let selectedHourlyKey = '__all__';
    let selectedStallMixKey = '__all__';
    const selectedProductSalesPer10kKeys = {orderRevenue:'__all__', grossSales:'__all__'};
    const productSalesPer10kPanels = [
      {
        stateKey:'orderRevenue', dataKey:'product_sales_per_10k_order_revenue',
        selectId:'productSalesPer10kStoreSelect', searchId:'productSalesPer10kSearch',
        statusId:'productSalesPer10kStatus', tableId:'productSalesPer10kTable', denominatorLabel:'订单营业收入'
      },
      {
        stateKey:'grossSales', dataKey:'product_sales_per_10k_gross_sales',
        selectId:'productSalesPer10kGrossStoreSelect', searchId:'productSalesPer10kGrossSearch',
        statusId:'productSalesPer10kGrossStatus', tableId:'productSalesPer10kGrossTable', denominatorLabel:'营业额'
      },
    ];
    const stallPalette = ['#006d77', '#2f5b9f', '#3a7d44', '#b85c00', '#7557a6', '#d96b3b', '#b23a48', '#c89b18', '#4b5563', '#0f766e', '#9aa7b5'];
    const currentTrendYear = String(data.meta?.target_windows?.current?.end || '').slice(0, 4) || '本年';
    const yoyTrendYear = String(data.meta?.target_windows?.yoy?.end || '').slice(0, 4) || '同期';

    function setText(id, value) { document.getElementById(id).textContent = value; }
    function svg(tag, attrs = {}) {
      const el = document.createElementNS('http:' + '//www.w3.org/2000/svg', tag);
      Object.entries(attrs).forEach(([k, v]) => el.setAttribute(k, v));
      return el;
    }
    function positionTooltip(tip, container, event, options = {}) {
      const bounds = container.getBoundingClientRect();
      const gap = options.gap ?? 12;
      const cursorX = Number.isFinite(event.clientX) ? event.clientX - bounds.left : bounds.width / 2;
      const cursorY = Number.isFinite(event.clientY) ? event.clientY - bounds.top : bounds.height / 2;
      tip.style.display = 'block';
      tip.style.left = '0px';
      tip.style.top = '0px';
      const tipWidth = tip.offsetWidth || 0;
      const tipHeight = tip.offsetHeight || 0;
      let x = cursorX + gap;
      let y = cursorY - tipHeight / 2;
      if (x + tipWidth + 8 > bounds.width) x = cursorX - tipWidth - gap;
      x = Math.max(8, Math.min(x, bounds.width - tipWidth - 8));
      y = Math.max(8, Math.min(y, bounds.height - tipHeight - 8));
      tip.style.left = `${x}px`;
      tip.style.top = `${y}px`;
    }
    function renderMeta() {
      const meta = data.meta;
      document.getElementById('metaChips').innerHTML = [
        `本周：${meta.target_windows.current.start}-${meta.target_windows.current.end}`,
        `环比：${meta.target_windows.previous.start}-${meta.target_windows.previous.end}`,
        `同比：${meta.target_windows.yoy.start}-${meta.target_windows.yoy.end}`,
        `门店：${meta.store_count}家`
      ].map(x => `<span class="chip">${x}</span>`).join('');
      if (meta.store_name_contains?.length) {
        const scope = document.createElement('span');
        scope.className = 'chip';
        scope.textContent = `门店名称包含：${meta.store_name_contains.join('、')}（全体门店为筛选后合计）`;
        document.getElementById('metaChips').appendChild(scope);
      }
    }
    function renderKpis() {
      const k = data.kpis;
      setText('heroRevenue', fmtWan(k.current_revenue));
      setText('heroWow', fmtPct(k.wow_pct));
      setText('heroYoy', fmtPct(k.yoy_pct));
      const cards = [
        ['业务收入', fmtWan(k.current_revenue), `环比 ${fmtPct(k.wow_pct)} / 同比 ${fmtPct(k.yoy_pct)}`],
        ['客流量', fmtNum(k.current_customers), `环比 ${fmtPct(k.wow_customer_pct)} / 同比 ${fmtPct(k.yoy_customer_pct)}`],
        ['开台数', fmtNum(k.current_tables), `环比 ${fmtPct(k.wow_table_pct)} / 同比 ${fmtPct(k.yoy_table_pct)}`],
        ['门店分型', `${k.star_count} 明星 / ${k.problem_count} 问题`, segmentGroups.map(g => `${g.label} ${g.star_count} 明星/${g.problem_count} 问题`).join('；') || '按门店类型内收入中位数与环比 0% 划分象限']
      ];
      document.getElementById('kpiCards').innerHTML = cards.map(c => `<div class="card"><div class="label">${c[0]}</div><div class="value">${c[1]}</div><div class="foot">${c[2]}</div></div>`).join('');
    }
    function ruleColor(name) {
      return name === '明星门店' ? colors.green : name === '问题门店' ? colors.red : name === '高基盘承压' ? colors.amber : colors.blue;
    }
    function renderRules() {
      const rules = data.segment_rules;
      const bucketSegmentSummary = segmentGroups.map(group => `${group.label}：收入中位数 ${fmtWan(group.revenue_threshold)}，${group.star_count} 明星 / ${group.problem_count} 问题`).join('；');
      document.getElementById('segmentRules').innerHTML = `
        <div class="rule-note" id="bucketSegmentSummary">门店分型基准：全体门店统一比较；${bucketSegmentSummary}。横轴统一使用环比增长率 ${fmtPct(rules.growth_threshold)}。四象限只定义经营位置，预警项用于补充复盘优先级。</div>
        <div class="rule-grid">
          ${rules.items.map(item => `<div class="rule">
            <div class="rule-title"><i class="dot" style="background:${ruleColor(item.name)}"></i>${item.name}</div>
            <p>${item.logic}</p>
            <small>${item.use}</small>
          </div>`).join('')}
        </div>
        <div class="rule-note">预警补充：${rules.warnings}</div>`;
    }
    function renderHorizontalBar(id, rows, field, formatter, color) {
      const el = document.getElementById(id);
      const w = 760, h = Math.max(300, rows.length * 32 + 48), left = 150, right = 80;
      const max = Math.max(...rows.map(r => Math.abs(Number(r[field] || 0))), 1);
      const root = svg('svg', {viewBox:`0 0 ${w} ${h}`});
      rows.forEach((r, i) => {
        const y = 28 + i * 32;
        const val = Number(r[field] || 0);
        const bw = Math.abs(val) / max * (w - left - right);
        root.appendChild(svg('text', {x: left - 8, y: y + 15, 'text-anchor':'end', 'font-size':'12', fill:'#344054'})).textContent = cleanName(r['门店名称']);
        root.appendChild(svg('rect', {x: left, y, width: bw, height: 18, rx: 4, fill: color}));
        root.appendChild(svg('text', {x: left + bw + 8, y: y + 14, 'font-size':'12', fill:'#657386'})).textContent = formatter(val);
      });
      el.innerHTML = '';
      el.appendChild(root);
    }
    function renderBucketedRevenueRanking() {
      const el = document.getElementById('revenueBar');
      const groups = segmentGroups.length ? segmentGroups : [{label:'全体门店', rows:stores, revenue_threshold:data.segment_rules.revenue_threshold}];
      const w = 760, left = 150, right = 80, groupGap = 40;
      const rowH = 30;
      const totalRows = groups.reduce((sum, group) => sum + (group.rows || []).length, 0);
      const h = Math.max(320, totalRows * rowH + groups.length * groupGap + 36);
      const max = Math.max(...groups.flatMap(group => (group.rows || []).map(r => Number(r.current_net_revenue || 0))), 1);
      const root = svg('svg', {viewBox:`0 0 ${w} ${h}`});
      let y = 26;
      groups.forEach(group => {
        root.appendChild(svg('text', {x:left-8, y:y, 'text-anchor':'end', 'font-size':'12', fill:'#172033', 'font-weight':'800'})).textContent = `${group.label}（${group.store_count || (group.rows || []).length}家）`;
        root.appendChild(svg('text', {x:left, y:y, 'font-size':'11', fill:'#657386'})).textContent = `中位数 ${fmtWan(group.revenue_threshold || 0)}`;
        y += 12;
        (group.rows || []).forEach(r => {
          y += rowH;
          const val = Number(r.current_net_revenue || 0);
          const bw = val / max * (w - left - right);
          root.appendChild(svg('text', {x:left-8, y:y+5, 'text-anchor':'end', 'font-size':'12', fill:'#344054'})).textContent = cleanName(r['门店名称']);
          root.appendChild(svg('rect', {x:left, y:y-11, width:bw, height:18, rx:4, fill:colors.teal}));
          root.appendChild(svg('text', {x:left + bw + 8, y:y+3, 'font-size':'12', fill:'#657386'})).textContent = fmtWan(val);
        });
        y += groupGap - 10;
      });
      el.innerHTML = '';
      el.appendChild(root);
    }
    function renderGrowthBar() {
      const el = document.getElementById('growthBar');
      const rows = stores.slice().sort((a,b)=>Number(b.wow_net_revenue_pct||0)-Number(a.wow_net_revenue_pct||0));
      const primaryMetrics = [
        {field:'wow_net_revenue_pct', label:'业务收入环比', color:'#006d77'},
        {field:'yoy_net_revenue_pct', label:'业务收入同比', color:'#1d4ed8'},
      ];
      const channelRows = [
        {label:'堂食', metrics:[
          {field:'wow_dine_in_revenue_pct', label:'堂食环比', shortLabel:'环比', color:'#2e7d32'},
          {field:'yoy_dine_in_revenue_pct', label:'堂食同比', shortLabel:'同比', color:'#7c3aed'},
        ]},
        {label:'外卖', metrics:[
          {field:'wow_delivery_revenue_pct', label:'外卖环比', shortLabel:'环比', color:'#f59e0b'},
          {field:'yoy_delivery_revenue_pct', label:'外卖同比', shortLabel:'同比', color:'#dc2626'},
        ]},
      ];
      const primaryValues = rows.flatMap(row => primaryMetrics.map(metric => Number(row[metric.field] || 0)));
      const channelValues = rows.flatMap(row => channelRows.flatMap(channel => channel.metrics.map(metric => Number(row[metric.field] || 0))));
      const primaryMax = Math.max(...primaryValues.map(value => Math.abs(value)), .01);
      const channelMax = Math.max(...channelValues.map(value => Math.abs(value)), .01);

      function signedGrowthAxis(rawValue, color, maxValue, ariaLabel) {
        const hasValue = rawValue !== null && rawValue !== undefined && rawValue !== '';
        const value = hasValue ? Number(rawValue) : null;
        const w = 420, h = 28, mid = 210, maxBar = 154;
        const root = svg('svg', {viewBox:`0 0 ${w} ${h}`, role:'img', 'aria-label':`${ariaLabel} ${fmtPct(value)}`});
        root.appendChild(svg('line', {x1:mid, y1:2, x2:mid, y2:h-2, stroke:'#cbd8e3'}));
        if (value === null || !Number.isFinite(value)) {
          root.appendChild(svg('text', {x:mid+8, y:18, 'font-size':'11', fill:'#8a97a8'})).textContent = 'N/A';
          return root;
        }
        const width = Math.abs(value) / maxValue * maxBar;
        const x = value >= 0 ? mid : mid - width;
        root.appendChild(svg('rect', {x, y:8, width:Math.max(width, value === 0 ? 1 : 2), height:12, rx:3, fill:color}));
        root.appendChild(svg('text', {
          x:value >= 0 ? x + width + 8 : x - 8,
          y:18,
          'text-anchor':value >= 0 ? 'start':'end',
          'font-size':'11',
          fill:'#657386',
          'font-weight':'700',
        })).textContent = fmtPct(value);
        return root;
      }

      const legend = document.createElement('div');
      legend.className = 'growth-legend';
      primaryMetrics.forEach(metric => {
        const item = document.createElement('span');
        item.innerHTML = `<i class="swatch" style="background:${metric.color}"></i>${metric.label}`;
        legend.appendChild(item);
      });
      const axisNote = document.createElement('span');
      axisNote.textContent = '每项独立成行；0% 为中心线';
      legend.appendChild(axisNote);

      const board = document.createElement('div');
      board.className = 'growth-board';
      rows.forEach((row, index) => {
        const store = document.createElement('section');
        store.className = 'growth-store';

        const head = document.createElement('div');
        head.className = 'growth-store-head';
        const storeName = document.createElement('div');
        storeName.className = 'growth-store-name';
        storeName.textContent = cleanName(row['门店名称']);

        const primary = document.createElement('div');
        primary.className = 'growth-primary';
        primaryMetrics.forEach(metric => {
          const metricRow = document.createElement('div');
          metricRow.className = 'growth-primary-row';
          const label = document.createElement('span');
          label.className = 'growth-metric-label';
          label.textContent = metric.label;
          const axis = document.createElement('div');
          axis.className = 'growth-axis';
          axis.appendChild(signedGrowthAxis(row[metric.field], metric.color, primaryMax, metric.label));
          metricRow.append(label, axis);
          primary.appendChild(metricRow);
        });

        const detailId = `growth-channel-detail-${index}`;
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'growth-toggle';
        button.textContent = '查看渠道明细 ▾';
        button.setAttribute('aria-expanded', 'false');
        button.setAttribute('aria-controls', detailId);
        button.setAttribute('aria-label', `${cleanName(row['门店名称'])} 查看渠道明细`);
        head.append(storeName, primary, button);

        const detail = document.createElement('div');
        detail.id = detailId;
        detail.className = 'growth-channel-detail';
        detail.hidden = true;
        channelRows.forEach(channel => {
          const channelRow = document.createElement('div');
          channelRow.className = 'growth-channel-row';
          const channelName = document.createElement('div');
          channelName.className = 'growth-channel-name';
          channelName.textContent = channel.label;
          channelRow.appendChild(channelName);
          channel.metrics.forEach(metric => {
            const metricCell = document.createElement('div');
            metricCell.className = 'growth-channel-metric';
            const label = document.createElement('span');
            label.className = 'growth-metric-label';
            label.textContent = metric.shortLabel;
            label.style.color = metric.color;
            const axis = document.createElement('div');
            axis.className = 'growth-axis';
            axis.appendChild(signedGrowthAxis(row[metric.field], metric.color, channelMax, metric.label));
            metricCell.append(label, axis);
            channelRow.appendChild(metricCell);
          });
          detail.appendChild(channelRow);
        });

        button.addEventListener('click', () => {
          const expanded = button.getAttribute('aria-expanded') !== 'true';
          button.setAttribute('aria-expanded', String(expanded));
          detail.hidden = !expanded;
          button.textContent = expanded ? '收起渠道明细 ▴' : '查看渠道明细 ▾';
          button.setAttribute('aria-label', `${cleanName(row['门店名称'])} ${expanded ? '收起渠道明细' : '查看渠道明细'}`);
        });
        store.append(head, detail);
        board.appendChild(store);
      });
      el.innerHTML = '';
      el.append(legend, board);
    }
    function renderBucketedScatter() {
      const el = document.getElementById('scatter');
      const groups = segmentGroups.length ? segmentGroups : [{label:'全体门店', rows:stores, revenue_threshold:data.segment_rules.revenue_threshold, growth_threshold:0}];
      const w = 760, panelH = 260, h = Math.max(330, groups.length * panelH + 18), left = 58, right = 28, topPad = 34, bottom = 40;
      const root = svg('svg', {viewBox:`0 0 ${w} ${h}`});
      groups.forEach((group, groupIndex) => {
        const rows = group.rows || [];
        const top = groupIndex * panelH + topPad;
        const axisBottom = (groupIndex + 1) * panelH - bottom;
        const xs = rows.map(r => Number(r.wow_net_revenue_pct || 0));
        const ys = rows.map(r => Number(r.current_net_revenue || 0));
        const minX = Math.min(...xs, -0.01), maxX = Math.max(...xs, 0.01), maxY = Math.max(...ys, 1);
        const revenueThreshold = Number(group.revenue_threshold || 0);
        const growthThreshold = Number(group.growth_threshold || 0);
        const xScale = v => left + (v - minX) / (maxX - minX || 1) * (w-left-right);
        const yScale = v => axisBottom - v / maxY * (axisBottom-top);
        root.appendChild(svg('text', {x:left, y:top-14, 'font-size':'13', fill:'#172033', 'font-weight':'800'})).textContent = `${group.label}四象限`;
        root.appendChild(svg('text', {x:w-right, y:top-14, 'text-anchor':'end', 'font-size':'11', fill:'#657386'})).textContent = `收入中位数 ${fmtWan(revenueThreshold)}`;
        root.appendChild(svg('line', {x1:left, y1:axisBottom, x2:w-right, y2:axisBottom, stroke:'#9aa7b5'}));
        root.appendChild(svg('line', {x1:left, y1:top, x2:left, y2:axisBottom, stroke:'#9aa7b5'}));
        root.appendChild(svg('line', {x1:xScale(growthThreshold), y1:top, x2:xScale(growthThreshold), y2:axisBottom, stroke:'#cfd9e3', 'stroke-dasharray':'5 5'}));
        root.appendChild(svg('line', {x1:left, y1:yScale(revenueThreshold), x2:w-right, y2:yScale(revenueThreshold), stroke:'#cfd9e3', 'stroke-dasharray':'5 5'}));
        [
          ['高基盘承压', left + 10, top + 17, colors.amber],
          ['明星门店', Math.min(w - right - 88, xScale(growthThreshold) + 10), top + 17, colors.green],
          ['问题门店', left + 10, axisBottom - 12, colors.red],
          ['成长观察', Math.min(w - right - 88, xScale(growthThreshold) + 10), axisBottom - 12, colors.blue]
        ].forEach(([label, x, y, color]) => {
          root.appendChild(svg('text', {x, y, 'font-size':'10', fill:color, 'font-weight':'800', opacity:.78})).textContent = label;
        });
        const placedLabels = [];
        rows.forEach(r => {
          const seg = r.segment;
          const fill = seg === '明星门店' ? colors.green : seg === '问题门店' ? colors.red : seg === '高基盘承压' ? colors.amber : colors.blue;
          const radius = 7 + Math.min(12, Number(r.current_discount_rate || 0) * 35);
          const cx = xScale(Number(r.wow_net_revenue_pct || 0));
          const cy = yScale(Number(r.current_net_revenue || 0));
          root.appendChild(svg('circle', {cx, cy, r:radius, fill, opacity:.82}));
          let anchor = 'start';
          let lx = cx + radius + 4;
          let ly = cy + 4;
          if (cx > w - right - 90) {
            anchor = 'end';
            lx = cx - radius - 4;
          }
          let guard = 0;
          while (placedLabels.some(p => Math.abs(p.x - lx) < 92 && Math.abs(p.y - ly) < 15) && guard < 8) {
            ly += 15;
            if (ly > axisBottom - 8) ly = cy - 12 - guard * 10;
            guard += 1;
          }
          placedLabels.push({x: lx, y: ly});
          root.appendChild(svg('text', {x:lx, y:ly, 'text-anchor':anchor, 'font-size':'11', fill:'#344054', stroke:'#fff', 'stroke-width':3, 'paint-order':'stroke'})).textContent = cleanName(r['门店名称']);
        });
      });
      root.appendChild(svg('text', {x:w/2, y:h-10, 'text-anchor':'middle', 'font-size':'12', fill:'#657386'})).textContent = '环比增长率';
      el.innerHTML = '';
      el.appendChild(root);
    }
    function currentTrendEntity() {
      const entities = data.trend_entities || [{key:'__all__', label:'全体门店', rows:data.trend}];
      return entities.find(item => item.key === selectedTrendKey) || entities[0] || {key:'__all__', label:'全体门店', rows:[]};
    }
    function setTrendRange(start, end) {
      const count = (currentTrendEntity().rows || []).length;
      if (!count) return;
      trendStart = Math.max(0, Math.min(Math.round(start), count - 1));
      trendEnd = Math.max(trendStart, Math.min(Math.round(end), count - 1));
      renderTrend();
    }
    function renderTrendControls() {
      const rows = currentTrendEntity().rows || [];
      const isMonthly = data.meta.report_grain === 'month';
      const presets = document.getElementById('trendPresets');
      (isMonthly ? [[2, '最近 2 个月'], [0, '全年']] : [[2, '最近 2 周'], [5, '最近 5 周'], [16, '最近 16 周'], [0, '全年']]).forEach(([size, label]) => {
        const button = document.createElement('button');
        button.type = 'button';
        button.textContent = label;
        button.dataset.size = size;
        button.addEventListener('click', () => {
          const count = (currentTrendEntity().rows || []).length;
          setTrendRange(size ? Math.max(0, count - size) : 0, count - 1);
        });
        presets.appendChild(button);
      });
      ['trendStartSelect', 'trendEndSelect'].forEach(id => {
        const select = document.getElementById(id);
        rows.forEach((row, index) => {
          const option = document.createElement('option');
          option.value = index;
          option.textContent = row.current_week_range || row.week_label;
          select.appendChild(option);
        });
        select.disabled = !rows.length;
        select.addEventListener('change', () => {
          const value = Number(select.value);
          if (id === 'trendStartSelect') setTrendRange(value, Math.max(value, trendEnd));
          else setTrendRange(Math.min(trendStart, value), value);
        });
      });
      const navigator = document.getElementById('trendNavigator');
      let drag = null;
      const boundary = event => {
        const bounds = navigator.getBoundingClientRect();
        const count = (currentTrendEntity().rows || []).length;
        return Math.max(0, Math.min(count, Math.round((event.clientX - bounds.left) / bounds.width * count)));
      };
      navigator.addEventListener('pointerdown', event => {
        if (event.button !== 0 || !rows.length) return;
        const mode = event.target.getAttribute('data-drag') || 'select';
        drag = {mode, anchor:boundary(event), start:trendStart, end:trendEnd};
        navigator.setPointerCapture(event.pointerId);
        event.preventDefault();
      });
      navigator.addEventListener('pointermove', event => {
        if (!drag) return;
        const value = boundary(event);
        const count = (currentTrendEntity().rows || []).length;
        if (drag.mode === 'start') setTrendRange(Math.min(value, drag.end), drag.end);
        else if (drag.mode === 'end') setTrendRange(drag.start, Math.max(drag.start, value - 1));
        else if (drag.mode === 'pan') {
          const offset = Math.max(-drag.start, Math.min(value - drag.anchor, count - 1 - drag.end));
          setTrendRange(drag.start + offset, drag.end + offset);
        } else setTrendRange(Math.min(value, drag.anchor), Math.max(value, drag.anchor) - 1);
      });
      const endDrag = () => { drag = null; };
      navigator.addEventListener('pointerup', endDrag);
      navigator.addEventListener('pointercancel', endDrag);
      navigator.addEventListener('lostpointercapture', endDrag);
    }
    function renderTrendNavigator(rows, currentField, priorField) {
      const el = document.getElementById('trendNavigator');
      const root = svg('svg', {viewBox:'0 0 1120 64', preserveAspectRatio:'none', 'aria-hidden':'true'});
      root.appendChild(svg('rect', {x:0, y:0, width:1120, height:64, rx:6, fill:'#f4f7fa', 'data-drag':'select'}));
      const max = Math.max(1, ...rows.flatMap(row => [Number(row[currentField] || 0), Number(row[priorField] || 0)]));
      [currentField, priorField].forEach((field, series) => {
        let segment = [];
        const flush = () => {
          if (segment.length) root.appendChild(svg('polyline', {points:segment.join(' '), fill:'none', stroke:colors.yellow, 'stroke-width':2, ...(series ? {'stroke-dasharray':'5 4'} : {}), 'pointer-events':'none'}));
          segment = [];
        };
        rows.forEach((row, index) => {
          const value = row[field];
          if (value === null || value === undefined || value === '') { flush(); return; }
          segment.push(`${(index + .5) / rows.length * 1120},${56 - Number(value) / max * 48}`);
        });
        flush();
      });
      const startX = trendStart / rows.length * 1120;
      const endX = (trendEnd + 1) / rows.length * 1120;
      [[0, startX], [endX, 1120 - endX]].forEach(([x, width]) => root.appendChild(svg('rect', {x, y:0, width, height:64, fill:'#dbe4ef', opacity:.65, 'data-drag':'select'})));
      root.appendChild(svg('rect', {x:startX, y:1, width:endX - startX, height:62, fill:'#2563eb', 'fill-opacity':.08, stroke:'#2563eb', 'stroke-width':2, 'data-drag':'pan', style:'cursor:grab'}));
      [[startX, 'start'], [endX, 'end']].forEach(([x, mode]) => {
        root.appendChild(svg('rect', {x:Math.max(0, Math.min(1104, x - 8)), y:0, width:16, height:64, rx:4, fill:'#2563eb', 'data-drag':mode, style:'cursor:ew-resize'}));
      });
      el.replaceChildren(root);
    }
    function renderTrendSelector() {
      const select = document.getElementById('trendStoreSelect');
      const entities = data.trend_entities || [{key:'__all__', label:'全体门店', rows:data.trend}];
      select.innerHTML = entities.map(item => `<option value="${item.key}">${cleanName(item.label)}</option>`).join('');
      select.value = selectedTrendKey;
      select.addEventListener('change', () => {
        selectedTrendKey = select.value;
        renderTrend();
      });
      renderTrendControls();
    }
    function renderTrend() {
      const el = document.getElementById('trend');
      const entity = currentTrendEntity();
      const allRows = entity.rows || [];
      if (!allRows.length) {
        el.replaceChildren();
        document.getElementById('trendNavigator').replaceChildren();
        document.getElementById('trendControls').hidden = true;
        return;
      }
      trendEnd = Math.min(trendEnd ?? allRows.length - 1, allRows.length - 1);
      trendStart = Math.min(trendStart, trendEnd);
      const rows = allRows.slice(trendStart, trendEnd + 1);
      const yearLabel = (field, fallback) => {
        const first = String(rows[0][field] || '').slice(0, 4);
        const last = String(rows[rows.length - 1][field] || '').slice(11, 15);
        return first && last ? (first === last ? first : `${first}–${last}`) : fallback;
      };
      const currentLabel = yearLabel('current_week_range', currentTrendYear);
      const priorLabel = yearLabel('prior_week_range', yoyTrendYear);
      const isAllStores = entity.key === '__all__';
      document.getElementById('trendMetricLabel').textContent = `完整周，${isAllStores ? '整体' : cleanName(entity.label)}业务收入（万元）；实线=${currentLabel}，虚线=${priorLabel}同期`;
      const w = 1120, h = 360, left = 82, right = 84, top = 34, bottom = 78;
      const hasComparisonShape = rows.some(r => Object.prototype.hasOwnProperty.call(r, 'current_net_revenue') || Object.prototype.hasOwnProperty.call(r, 'prior_net_revenue'));
      const currentField = hasComparisonShape ? 'current_net_revenue' : 'net_revenue';
      const priorField = 'prior_net_revenue';
      const allValues = rows.flatMap(r => [Number(r[currentField] || 0), Number(r[priorField] || 0)]);
      const max = Math.max(...allValues, 1);
      const yMax = Math.ceil(max / 500000) * 500000;
      const yScale = v => h - bottom - Number(v || 0) / yMax * (h-top-bottom);
      const root = svg('svg', {viewBox:`0 0 ${w} ${h}`});
      const tip = document.createElement('div');
      tip.className = 'chart-tooltip';
      const showTrendTip = (event, pointRange, value) => {
        tip.innerHTML = `${pointRange}<br>业务收入：${fmtWan(value)}`;
        positionTooltip(tip, el, event);
      };
      const hideTrendTip = () => { tip.style.display = 'none'; };
      [0, .25, .5, .75, 1].forEach(t => {
        const value = yMax * t;
        const y = yScale(value);
        root.appendChild(svg('line', {x1:left, y1:y, x2:w-right, y2:y, stroke:'#e6edf3'}));
        root.appendChild(svg('text', {x:left-10, y:y+4, 'text-anchor':'end', 'font-size':'11', fill:'#657386'})).textContent = fmtWan(value);
      });
      root.appendChild(svg('line', {x1:left, y1:top, x2:left, y2:h-bottom, stroke:'#9aa7b5'}));
      root.appendChild(svg('line', {x1:left, y1:h-bottom, x2:w-right, y2:h-bottom, stroke:'#9aa7b5'}));

      function trendPoints(field) {
        return rows.map((r,i) => {
          const raw = r[field];
          if (raw === null || raw === undefined || raw === '') return null;
          const x = rows.length === 1 ? (w+left-right)/2 : left + i / (rows.length - 1) * (w-left-right);
          const y = yScale(Number(raw || 0));
          return [x,y,r,Number(raw || 0),i];
        }).filter(Boolean);
      }
      function drawTrendLine(field, color, dash, rangeField) {
        const points = trendPoints(field);
        if (!points.length) return;
        const values = points.map(([, , , value]) => value);
        const minValue = Math.min(...values), maxValue = Math.max(...values);
        const hasDistinctExtremes = points.length > 1 && minValue !== maxValue;
        const segments = [];
        points.forEach(point => {
          const last = segments[segments.length - 1];
          if (!last || point[4] !== last[last.length - 1][4] + 1) segments.push([point]);
          else last.push(point);
        });
        segments.forEach(segment => root.appendChild(svg('polyline', {
          points: segment.map(p=>`${p[0]},${p[1]}`).join(' '),
          fill: 'none', stroke: color, 'stroke-width': 3,
          'stroke-linecap': 'round', 'stroke-linejoin': 'round',
          ...(dash ? {'stroke-dasharray': dash} : {})
        })));
        points.forEach(([x,y,r,value], i) => {
          const isMin = hasDistinctExtremes && value === minValue;
          const isMax = hasDistinctExtremes && value === maxValue;
          const point = svg('circle', {
            cx:x, cy:y, r:5,
            fill:isMin ? colors.minimum : isMax ? colors.maximum : colors.yellowFill,
            stroke:isMin ? colors.minimumStroke : isMax ? colors.maximumStroke : color,
            'stroke-width':2,
            style:'cursor:pointer'
          });
          const weekLabel = String(r.week_label || '');
          const pointRange = String(r[rangeField] || weekLabel);
          const title = svg('title', {});
          title.textContent = `${pointRange} 业务收入：${fmtWan(value)}`;
          point.appendChild(title);
          point.addEventListener('mousemove', event => showTrendTip(event, pointRange, value));
          point.addEventListener('mouseleave', hideTrendTip);
          point.addEventListener('focus', event => showTrendTip(event, pointRange, value));
          point.addEventListener('blur', hideTrendTip);
          root.appendChild(point);
          if (i === points.length - 1) {
            const labelY = field === priorField ? y + 19 : y - 9;
            root.appendChild(svg('text', {x:x-7, y:labelY, 'text-anchor':'end', 'font-size':'11', fill:color, 'font-weight':'800'})).textContent = fmtWan(value);
          }
        });
      }
      drawTrendLine(currentField, colors.yellow, '', hasComparisonShape ? 'current_week_range' : 'week_label');
      if (hasComparisonShape) drawTrendLine(priorField, colors.yellow, '7 5', 'prior_week_range');

      rows.forEach((r, i) => {
        const x = rows.length === 1 ? (w+left-right)/2 : left + i / (rows.length - 1) * (w-left-right);
        if (i % Math.max(1, Math.ceil(rows.length / 10)) === 0 || i === rows.length - 1) {
          const anchor = i === rows.length - 1 ? 'end' : 'middle';
          const tx = i === rows.length - 1 ? x - 4 : x;
          root.appendChild(svg('text', {x:tx, y:h-42, 'text-anchor':anchor, 'font-size':'10', fill:'#657386', transform:`rotate(-32 ${tx} ${h-42})`})).textContent = r.current_week_range ? String(r.current_week_range).slice(0, 10) : String(r.week_label);
        }
      });
      root.appendChild(svg('line', {x1:left+190, y1:15, x2:left+232, y2:15, stroke:colors.yellow, 'stroke-width':3, 'stroke-linecap':'round'}));
      root.appendChild(svg('text', {x:left+240, y:19, 'font-size':'11', fill:'#657386'})).textContent = currentLabel;
      if (hasComparisonShape) {
        root.appendChild(svg('line', {x1:left+362, y1:15, x2:left+404, y2:15, stroke:colors.yellow, 'stroke-width':3, 'stroke-dasharray':'7 5', 'stroke-linecap':'round'}));
        root.appendChild(svg('text', {x:left+412, y:19, 'font-size':'11', fill:'#657386'})).textContent = `${priorLabel}同期`;
      }
      root.appendChild(svg('text', {x:left, y:18, 'font-size':'12', fill:'#657386', 'font-weight':'700'})).textContent = '业务收入（万元）';
      el.innerHTML = '';
      el.appendChild(root);
      el.appendChild(tip);
      document.getElementById('trendStartSelect').value = trendStart;
      document.getElementById('trendEndSelect').value = trendEnd;
      const start = rows[0].current_week_range || rows[0].week_label;
      const end = rows[rows.length - 1].current_week_range || rows[rows.length - 1].week_label;
      const label = start.includes('-') && start.length === 21 ? `${start.slice(0, 10)} 至 ${end.slice(11)}` : `${start} 至 ${end}`;
      document.getElementById('trendRangeLabel').textContent = `当前显示：${label}（${rows.length} ${data.meta.report_grain === 'month' ? '个月' : '周'}） · ${data.trend_note || ''}`;
      document.querySelectorAll('#trendPresets button').forEach(button => {
        const size = Number(button.dataset.size) || allRows.length;
        button.disabled = !allRows.length;
        button.setAttribute('aria-pressed', String(trendEnd === allRows.length - 1 && rows.length === Math.min(size, allRows.length)));
      });
      renderTrendNavigator(allRows, currentField, priorField);
    }
    function renderMixBars() {
      const rows = stores;
      const el = document.getElementById('mixBar');
      const w = 760, h = Math.max(310, rows.length * 32 + 46), left = 150, right = 70;
      const root = svg('svg', {viewBox:`0 0 ${w} ${h}`});
      const max = Math.max(...rows.map(r => Number(r.current_net_revenue || 0)), 1);
      rows.forEach((r,i) => {
        const y = 26 + i * 32;
        const total = Number(r.current_net_revenue || 0);
        const dine = Number(r.current_dine_in_revenue || 0);
        const del = Number(r.current_delivery_revenue || 0);
        const other = Math.max(0, total - dine - del);
        let x = left;
        root.appendChild(svg('text', {x:left-8, y:y+15, 'text-anchor':'end', 'font-size':'12', fill:'#344054'})).textContent = cleanName(r['门店名称']);
        [[dine, colors.teal], [del, colors.blue], [other, colors.amber]].forEach(([v,c]) => {
          const bw = v / max * (w-left-right);
          root.appendChild(svg('rect', {x, y, width:bw, height:18, rx:2, fill:c}));
          x += bw;
        });
        root.appendChild(svg('text', {x:left + total/max*(w-left-right) + 8, y:y+14, 'font-size':'12', fill:'#657386'})).textContent = fmtWan(total);
      });
      el.innerHTML = '';
      el.appendChild(root);
    }
    function renderPlatformBars() {
      const rows = stores;
      const el = document.getElementById('platformBar');
      const w = 760, h = Math.max(310, rows.length * 32 + 46), left = 150, right = 70;
      const max = Math.max(...rows.map(r => Number(r.current_meituan_delivery_revenue||0)+Number(r.current_eleme_delivery_revenue||0)+Number(r.current_jd_delivery_revenue||0)), 1);
      const root = svg('svg', {viewBox:`0 0 ${w} ${h}`});
      rows.forEach((r,i) => {
        const y = 26 + i * 32;
        const vals = [[Number(r.current_meituan_delivery_revenue||0), colors.green], [Number(r.current_eleme_delivery_revenue||0), colors.violet], [Number(r.current_jd_delivery_revenue||0), colors.orange]];
        let x = left, total = vals.reduce((s,v)=>s+v[0],0);
        root.appendChild(svg('text', {x:left-8, y:y+15, 'text-anchor':'end', 'font-size':'12', fill:'#344054'})).textContent = cleanName(r['门店名称']);
        vals.forEach(([v,c]) => { const bw = v / max * (w-left-right); root.appendChild(svg('rect', {x, y, width:bw, height:18, rx:2, fill:c})); x += bw; });
        root.appendChild(svg('text', {x:left + total/max*(w-left-right) + 8, y:y+14, 'font-size':'12', fill:'#657386'})).textContent = fmtWan(total);
      });
      el.innerHTML = '';
      el.appendChild(root);
    }
    function currentStallMixEntity() {
      const entities = data.stall_sales_mix?.entities || [];
      return entities.find(item => item.key === selectedStallMixKey) || entities[0];
    }
    function renderStallMixSelector() {
      const select = document.getElementById('stallMixStoreSelect');
      if (!select) return;
      const entities = data.stall_sales_mix?.entities || [];
      if (!entities.length) {
        select.innerHTML = '';
        return;
      }
      select.innerHTML = entities.map(item => `<option value="${item.key}">${cleanName(item.label)}</option>`).join('');
      if (!entities.some(item => item.key === selectedStallMixKey)) selectedStallMixKey = entities[0].key;
      select.value = selectedStallMixKey;
      select.addEventListener('change', () => {
        selectedStallMixKey = select.value;
        renderStallSalesMix();
      });
    }
    function describeArc(cx, cy, rOuter, rInner, startAngle, endAngle) {
      const largeArc = endAngle - startAngle > Math.PI ? 1 : 0;
      const outerStart = [cx + rOuter * Math.cos(startAngle), cy + rOuter * Math.sin(startAngle)];
      const outerEnd = [cx + rOuter * Math.cos(endAngle), cy + rOuter * Math.sin(endAngle)];
      const innerStart = [cx + rInner * Math.cos(endAngle), cy + rInner * Math.sin(endAngle)];
      const innerEnd = [cx + rInner * Math.cos(startAngle), cy + rInner * Math.sin(startAngle)];
      return [
        `M ${outerStart[0]} ${outerStart[1]}`,
        `A ${rOuter} ${rOuter} 0 ${largeArc} 1 ${outerEnd[0]} ${outerEnd[1]}`,
        `L ${innerStart[0]} ${innerStart[1]}`,
        `A ${rInner} ${rInner} 0 ${largeArc} 0 ${innerEnd[0]} ${innerEnd[1]}`,
        'Z'
      ].join(' ');
    }
    function renderStallSalesMix() {
      const pie = document.getElementById('stallMixPie');
      const tableBody = document.querySelector('#stallMixTable tbody');
      const label = document.getElementById('stallMixTotalLabel');
      const mix = data.stall_sales_mix || {};
      if (!mix.enabled) {
        document.getElementById('stall-mix').hidden = true;
        return;
      }
      const entity = currentStallMixEntity();
      if (!entity) return;
      const rows = entity.rows || [];
      if (label) label.textContent = `${cleanName(entity.label)}店内营业收入 ${fmtWan(entity.total)}`;

      const w = 760, h = 340, cx = 218, cy = 170, rOuter = 122, rInner = 68;
      const root = svg('svg', {viewBox:`0 0 ${w} ${h}`});
      const tip = document.createElement('div');
      tip.className = 'chart-tooltip';
      let start = -Math.PI / 2;
      rows.forEach((row, index) => {
        const value = Number(row.value || 0);
        const angle = (value / Math.max(entity.total, 1)) * Math.PI * 2;
        const end = start + angle;
        const fill = stallPalette[index % stallPalette.length];
        if (angle > 0.0001) {
          const slice = svg('path', {
            d: describeArc(cx, cy, rOuter, rInner, start, end),
            fill,
            stroke:'#fff',
            'stroke-width':2,
            style:'cursor:pointer'
          });
          slice.addEventListener('mousemove', event => {
            tip.innerHTML = `<strong>${row.name}</strong>${fmtWan(value)}<br>占比：${fmtPct(row.share)}`;
            positionTooltip(tip, pie, event);
          });
          slice.addEventListener('mouseleave', () => { tip.style.display = 'none'; });
          root.appendChild(slice);
        }
        start = end;
      });
      root.appendChild(svg('text', {x:cx, y:cy-4, 'text-anchor':'middle', 'font-size':'13', fill:'#657386', 'font-weight':'760'})).textContent = cleanName(entity.label);
      root.appendChild(svg('text', {x:cx, y:cy+24, 'text-anchor':'middle', 'font-size':'24', fill:'#172033', 'font-weight':'840'})).textContent = fmtWan(entity.total);
      const legendX = 390;
      rows.forEach((row, index) => {
        const y = 42 + index * 25;
        root.appendChild(svg('rect', {x:legendX, y:y-10, width:11, height:11, rx:2, fill:stallPalette[index % stallPalette.length]}));
        const name = String(row.name || '').length > 18 ? `${String(row.name).slice(0, 18)}...` : row.name;
        root.appendChild(svg('text', {x:legendX+18, y:y, 'font-size':'12', fill:'#344054', 'font-weight':'700'})).textContent = name;
        root.appendChild(svg('text', {x:w-28, y:y, 'text-anchor':'end', 'font-size':'12', fill:'#657386'})).textContent = fmtPct(row.share);
      });
      pie.innerHTML = '';
      pie.appendChild(root);
      pie.appendChild(tip);

      if (tableBody) {
        tableBody.innerHTML = rows.map((row, index) => `
          <tr>
            <td><span class="swatch" style="background:${stallPalette[index % stallPalette.length]}"></span>${row.name}</td>
            <td>${fmtWan(row.value)}</td>
            <td>${fmtPct(row.share)}</td>
            <td>${row.quantity === null || row.quantity === undefined ? '-' : fmtNum(row.quantity)}</td>
          </tr>
        `).join('');
      }
    }
    function currentProductSalesPer10kEntity(panel) {
      const entities = data[panel.dataKey]?.entities || [];
      return entities.find(item => item.key === selectedProductSalesPer10kKeys[panel.stateKey]) || entities[0];
    }
    function renderProductSalesPer10kSelector() {
      productSalesPer10kPanels.forEach(panel => {
        const select = document.getElementById(panel.selectId);
        const input = document.getElementById(panel.searchId);
        if (!select || !input) return;
        const entities = data[panel.dataKey]?.entities || [];
        select.innerHTML = entities.map(item => `<option value="${item.key}">${cleanName(item.label)}</option>`).join('');
        if (!entities.some(item => item.key === selectedProductSalesPer10kKeys[panel.stateKey])) {
          selectedProductSalesPer10kKeys[panel.stateKey] = entities[0]?.key || '__all__';
        }
        select.value = selectedProductSalesPer10kKeys[panel.stateKey];
        select.addEventListener('change', () => {
          selectedProductSalesPer10kKeys[panel.stateKey] = select.value;
          renderProductSalesPer10kPanel(panel);
        });
        input.addEventListener('input', () => renderProductSalesPer10kPanel(panel));
      });
    }
    function renderProductSalesPer10kPanel(panel) {
      const body = document.querySelector(`#${panel.tableId} tbody`);
      const input = document.getElementById(panel.searchId);
      const status = document.getElementById(panel.statusId);
      const metric = data[panel.dataKey] || {};
      if (!body || !status) return;
      if (!metric.enabled) {
        body.innerHTML = `<tr><td colspan="5">${metric.meta?.reason || '产品万元销量需要同时提供菜品主题数据和菜品库。'}</td></tr>`;
        status.textContent = '未启用';
        return;
      }
      const entity = currentProductSalesPer10kEntity(panel);
      if (!entity || entity.available === false) {
        body.innerHTML = `<tr><td colspan="5">${entity?.unavailable_reason || `当前区间${panel.denominatorLabel}不可用，无法计算。`}</td></tr>`;
        status.textContent = '不可计算';
        return;
      }
      const query = String(input?.value || '').trim().toLocaleLowerCase('zh-CN');
      const allRows = entity?.rows || [];
      const rows = query
        ? allRows.filter(row => String(row.search_names || row.name || '').toLocaleLowerCase('zh-CN').includes(query))
        : allRows.slice(0, 10);
      status.textContent = query
        ? `找到 ${rows.length} 项 · 当前区间${panel.denominatorLabel} ${fmtWan(entity?.total_denominator || 0)}`
        : `Top 10 · 当前区间${panel.denominatorLabel} ${fmtWan(entity?.total_denominator || 0)}`;
      body.innerHTML = rows.length ? rows.map(row => `<tr>
        <td>${row.name}</td>
        <td>${row.sales_class}</td>
        <td>${row.stall}</td>
        <td>${fmtNum(row.quantity)} 份</td>
        <td>${row.units_per_10k === null || row.units_per_10k === undefined ? '<b>N/A</b>' : `<b>${fmtNum(row.units_per_10k)}</b> 份/万元`}</td>
      </tr>`).join('') : '<tr><td colspan="5">没有匹配的产品</td></tr>';
    }
    function renderProductSalesPer10k() {
      const enabled = productSalesPer10kPanels.some(panel => data[panel.dataKey]?.enabled);
      document.getElementById('product-sales-per-10k').hidden = !enabled;
      if (!enabled) return;
      productSalesPer10kPanels.forEach(renderProductSalesPer10kPanel);
    }
    function renderDriverBar() {
      const groups = segmentGroups.map(group => ({
        label: group.label,
        rows: (group.rows || []).filter(r => r.segment === '问题门店').slice(0, 4)
      })).filter(group => group.rows.length);
      const fallbackRows = stores.filter(r => r.segment === '问题门店').slice(0, 6);
      const renderGroups = groups.length ? groups : [{label:'问题门店', rows:fallbackRows.length ? fallbackRows : stores.slice(-6)}];
      const el = document.getElementById('driverBar');
      const totalRows = renderGroups.reduce((sum, group) => sum + group.rows.length, 0);
      const w = 1120, h = Math.max(430, totalRows * 76 + renderGroups.length * 42 + 70), left = 180, mid = 575, right = 120;
      const vals = renderGroups.flatMap(group => group.rows.flatMap(r => [Number(r.wow_order_volume_contribution||0), Number(r.wow_aov_contribution||0), Number(r.wow_dine_in_delta||0), Number(r.wow_delivery_delta||0)]));
      const max = Math.max(...vals.map(v=>Math.abs(v)), 1);
      const root = svg('svg', {viewBox:`0 0 ${w} ${h}`});
      [['量贡献', colors.blue, 0], ['价贡献', colors.teal, 72], ['堂食变化', colors.green, 144], ['外卖变化', colors.amber, 232]].forEach(([label, color, xOff]) => {
        root.appendChild(svg('rect', {x: left + xOff, y: 16, width: 12, height: 12, rx: 2, fill: color}));
        root.appendChild(svg('text', {x: left + xOff + 18, y: 27, 'font-size':'12', fill:'#657386'})).textContent = label;
      });
      root.appendChild(svg('line', {x1:mid, y1:46, x2:mid, y2:h-26, stroke:'#d9e2ea'}));
      let y = 58;
      renderGroups.forEach(group => {
        root.appendChild(svg('text', {x:left-8, y:y+16, 'text-anchor':'end', 'font-size':'12', fill:'#172033', 'font-weight':'800'})).textContent = `${group.label}问题`;
        y += 28;
        group.rows.forEach((r,i) => {
          if (i > 0) {
            root.appendChild(svg('line', {x1: left, y1: y - 14, x2: w - right, y2: y - 14, stroke:'#d9e2ea', 'stroke-dasharray':'5 6'}));
          }
          root.appendChild(svg('text', {x:left-8, y:y+25, 'text-anchor':'end', 'font-size':'12', fill:'#344054'})).textContent = cleanName(r['门店名称']);
          [[Number(r.wow_order_volume_contribution||0), colors.blue, 0], [Number(r.wow_aov_contribution||0), colors.teal, 16], [Number(r.wow_dine_in_delta||0), colors.green, 32], [Number(r.wow_delivery_delta||0), colors.amber, 48]].forEach(([v,c,off]) => {
            const bw = Math.abs(v) / max * 360;
            const x = v >= 0 ? mid : mid - bw;
            root.appendChild(svg('rect', {x, y:y+off, width:bw, height:12, rx:2, fill:c, opacity:.9}));
            root.appendChild(svg('text', {x: v >= 0 ? x + bw + 7 : x - 7, y:y+off+10, 'text-anchor': v >= 0 ? 'start':'end', 'font-size':'11', fill:'#657386'})).textContent = fmtWan(v);
          });
          y += 76;
        });
        y += 14;
      });
      el.innerHTML = '';
      el.appendChild(root);
    }
    function renderTable() {
      const body = document.querySelector('#storeTable tbody');
      const tagClass = segment => segment === '明星门店' ? 'star' : segment === '问题门店' ? 'problem' : segment === '高基盘承压' ? 'pressure' : segment === '成长观察' ? 'growth' : '';
      const rows = stores.map(r => `<tr>
        <td>${cleanName(r['门店名称'])}</td>
        <td>${r.store_size || '未分组'}</td>
        <td><span class="tag ${tagClass(r.segment)}">${r.segment}</span></td>
        <td>${fmtWan(r.current_net_revenue)}</td>
        <td>${fmtPct(r.wow_net_revenue_pct)}</td>
        <td>${fmtPct(r.yoy_net_revenue_pct)}</td>
        <td>${fmtWan(r.current_dine_in_revenue)}</td>
        <td>${fmtWan(r.current_delivery_revenue)}</td>
        <td>${fmtNum(r.current_customer_count)}</td>
        <td>${fmtNum(r.current_consumed_tables)}</td>
        <td>${fmtYuan(r.current_post_discount_aov)}</td>
        <td>${fmtPct(r.current_discount_rate)}</td>
        <td>${r.top_stall_signal || ''}</td>
        <td>${r.top_daypart_signal || ''}</td>
        <td>${r.top_negative_factor || r.segment_reason || ''}</td>
      </tr>`).join('');
      body.innerHTML = rows;
      document.querySelectorAll('#storeTable th[data-key]').forEach(th => {
        th.addEventListener('click', () => {
          const key = th.dataset.key;
          stores.sort((a,b) => {
            const av = a[key], bv = b[key];
            const na = Number(av), nb = Number(bv);
            if (!Number.isNaN(na) && !Number.isNaN(nb)) return nb - na;
            return String(av || '').localeCompare(String(bv || ''), 'zh-CN');
          });
          renderTable();
        });
      });
    }
    function renderActions() {
      const groups = {};
      stores.forEach(r => {
        const key = `${r.store_size || '未分组'} · ${r.segment}`;
        groups[key] = groups[key] || [];
        groups[key].push(cleanName(r['门店名称']));
      });
      const hint = k => k === '明星门店' ? '沉淀可复制打法' : k === '问题门店' ? '优先复盘负向因素' : k === '高基盘承压' ? '防止高收入门店继续滑坡' : '验证增长是否可持续';
      document.getElementById('actionList').innerHTML = Object.entries(groups).map(([k, arr]) => {
        const segment = k.split(' · ')[1] || k;
        return `<div class="card" style="margin-bottom:10px; min-height:0;"><div class="label">${k}</div><div style="margin-top:8px;">${arr.join('、')}</div><div class="foot">${hint(segment)}</div></div>`;
      }).join('');
    }
    function fmtDeltaWan(v) {
      if (v === null || v === undefined || v === '') return 'N/A';
      const value = Number(v || 0);
      if (!Number.isFinite(value)) return 'N/A';
      const sign = value > 0 ? '+' : '';
      return `${sign}${fmtWan(value)}`;
    }
    function dishList(rows) {
      if (!rows || !rows.length) return '<span class="label">暂无代表菜品</span>';
      return rows.map(row => `<span class="tag" style="margin:3px 4px 3px 0;">${row['菜品名称']} ${fmtDeltaWan(row.income_delta)}</span>`).join('');
    }
    function renderStallAttribution() {
      const root = document.getElementById('stallAttribution');
      const stall = data.stall_attribution || {};
      if (!stall.enabled) {
        document.getElementById('stall-drivers').hidden = true;
        return;
      }
      const match = stall.match_summary || {};
      const drivers = stall.drivers || [];
      const yoyDrivers = stall.yoy_drivers || [];
      const basis = (stall.meta && stall.meta.basis) || '菜品主题数据“菜品收入” × 菜品库“基础分类”。';
      const coverage = (stall.meta && stall.meta.period_coverage) || {};
      const missing = ['current', 'previous', 'yoy']
        .filter(key => !(coverage[key] && Number(coverage[key].rows || 0) > 0))
        .map(key => coverage[key]?.label || key);
      const coverageNote = missing.length
        ? `<div class="callout" style="margin:0 0 16px;">部分期间菜品数据不足，相关档口和菜品变化暂不显示。</div>`
        : '';
      const rowHtml = rows => rows.map(row => `<tr>
        <td>${cleanName(row['门店名称'])}</td>
        <td>${row.basis}</td>
        <td>${row.top_negative_stall || ''}</td>
        <td>${fmtDeltaWan(row.top_negative_income_delta)}</td>
        <td>${dishList(row.negative_dishes)}</td>
        <td>${row.top_positive_stall || ''}</td>
        <td>${fmtDeltaWan(row.top_positive_income_delta)}</td>
        <td>${dishList(row.positive_dishes)}</td>
      </tr>`).join('');
      root.innerHTML = `
        ${coverageNote}
        <div class="grid-3">
          <div class="card"><div class="label">菜品行匹配率</div><div class="value">${fmtPct(match.match_rate)}</div><div class="foot">关联名称补齐 ${fmtNum(match.linked_name_rescued_rows)} / 未匹配 ${fmtNum(match.unmatched_rows)} / 重名 ${fmtNum(match.ambiguous_rows)}</div></div>
          <div class="card"><div class="label">菜品库规模</div><div class="value">${fmtNum(match.catalog_rows)}</div><div class="foot">基础分类档口 ${fmtNum(match.catalog_stall_count)} 个</div></div>
          <div class="card"><div class="label">归因口径</div><div class="value">环比 + 同比</div><div class="foot">按菜品收入变化排序</div></div>
        </div>
        <div class="callout" style="margin-top:16px;">${basis}</div>
        <div class="panel full-row" style="margin-top:16px;">
          <div class="panel-head"><h3>环比档口归因：门店主要变化</h3><span class="label">负向档口 / 正向档口 / 代表菜品</span></div>
          <div class="table-wrap"><table><thead><tr><th>门店</th><th>口径</th><th>负向档口</th><th>负向变化</th><th>负向代表菜品</th><th>正向档口</th><th>正向变化</th><th>正向代表菜品</th></tr></thead><tbody>${rowHtml(drivers)}</tbody></table></div>
        </div>
        <div class="panel full-row" style="margin-top:16px;">
          <div class="panel-head"><h3>同比档口归因</h3><span class="label">用于识别结构性改善或退化</span></div>
          <div class="table-wrap"><table><thead><tr><th>门店</th><th>口径</th><th>负向档口</th><th>负向变化</th><th>负向代表菜品</th><th>正向档口</th><th>正向变化</th><th>正向代表菜品</th></tr></thead><tbody>${rowHtml(yoyDrivers)}</tbody></table></div>
        </div>`;
    }
    function slotList(rows) {
      if (!rows || !rows.length) return '<span class="label">无明显变化</span>';
      return rows.map(row => `<span class="tag" style="margin:3px 4px 3px 0;">${row['餐段']} ${row['时段']} ${fmtDeltaWan(row.net_revenue_delta)}</span>`).join('');
    }
    function renderDaypartAttribution() {
      const root = document.getElementById('daypartAttribution');
      const daypart = data.daypart_attribution || {};
      if (!daypart.enabled) {
        document.getElementById('daypart-drivers').hidden = true;
        return;
      }
      const drivers = daypart.drivers || [];
      const yoyDrivers = daypart.yoy_drivers || [];
      const basis = (daypart.meta && daypart.meta.basis) || '营业分组表“时段”字段。';
      const rowHtml = rows => rows.map(row => `<tr>
        <td>${cleanName(row['门店名称'])}</td>
        <td>${row.basis}</td>
        <td>${slotList(row.negative_slots)}</td>
        <td>${fmtDeltaWan(row.top_negative_net_revenue_delta)}</td>
        <td>${slotList(row.positive_slots)}</td>
        <td>${fmtDeltaWan(row.top_positive_net_revenue_delta)}</td>
      </tr>`).join('');
      root.innerHTML = `
        <div class="grid-3">
          <div class="card"><div class="label">归因维度</div><div class="value">餐段 × 时段</div><div class="foot">来自营业分组表</div></div>
          <div class="card"><div class="label">归因口径</div><div class="value">环比 + 同比</div><div class="foot">按订单营业收入变化排序</div></div>
          <div class="card"><div class="label">展示规则</div><div class="value">Top 3</div><div class="foot">每店负向 / 正向时段</div></div>
        </div>
        <div class="callout" style="margin-top:16px;">${basis}</div>
        <div class="panel full-row" style="margin-top:16px;">
          <div class="panel-head"><h3>环比时段归因：门店主要变化</h3><span class="label">负向时段 / 正向时段</span></div>
          <div class="table-wrap"><table><thead><tr><th>门店</th><th>口径</th><th>负向时段 Top 3</th><th>最大负向变化</th><th>正向时段 Top 3</th><th>最大正向变化</th></tr></thead><tbody>${rowHtml(drivers)}</tbody></table></div>
        </div>
        <div class="panel full-row" style="margin-top:16px;">
          <div class="panel-head"><h3>同比时段归因</h3><span class="label">用于识别结构性改善或退化</span></div>
          <div class="table-wrap"><table><thead><tr><th>门店</th><th>口径</th><th>负向时段 Top 3</th><th>最大负向变化</th><th>正向时段 Top 3</th><th>最大正向变化</th></tr></thead><tbody>${rowHtml(yoyDrivers)}</tbody></table></div>
        </div>`;
    }
    function hourlyEntity() {
      const entities = data.hourly_revenue_entities || [{key:'__all__', label:'全体门店', rows:[]}];
      return entities.find(item => item.key === selectedHourlyKey) || entities[0];
    }
    function renderHourlySelector() {
      const select = document.getElementById('hourlyStoreSelect');
      const entities = data.hourly_revenue_entities || [{key:'__all__', label:'全体门店', rows:[]}];
      select.innerHTML = entities.map(item => `<option value="${item.key}">${cleanName(item.label)}</option>`).join('');
      select.value = selectedHourlyKey;
      select.addEventListener('change', () => {
        selectedHourlyKey = select.value;
        renderHourlyRevenueBar();
      });
    }
    function renderHourlyRevenueBar() {
      const el = document.getElementById('hourlyRevenueBar');
      const entity = hourlyEntity();
      const rows = entity.rows || [];
      if (!rows.some(row => Number(row.net_revenue || 0))) {
        document.getElementById('dayparts').hidden = true;
        return;
      }
      const isAllStores = entity.key === '__all__';
      document.getElementById('hourlyRevenueLabel').textContent = `本周，${isAllStores ? '整体' : cleanName(entity.label)}业务收入（万元）`;
      const w = 1120, h = 350, left = 74, right = 34, top = 34, bottom = 62;
      const max = Math.max(...rows.map(r => Number(r.net_revenue || 0)), 1);
      const yMax = Math.ceil(max / 10000) * 10000 || 1;
      const yScale = v => h - bottom - Number(v || 0) / yMax * (h - top - bottom);
      const plotW = w - left - right;
      const slot = plotW / 24;
      const barW = Math.max(12, Math.min(28, slot * .64));
      const root = svg('svg', {viewBox:`0 0 ${w} ${h}`});
      const tip = document.createElement('div');
      tip.className = 'chart-tooltip';
      const showTip = (event, row) => {
        tip.innerHTML = `<strong>${Number(row.hour)}点</strong>业务收入：${fmtWan(row.net_revenue)}`;
        positionTooltip(tip, el, event);
      };
      const hideTip = () => { tip.style.display = 'none'; };
      [0, .25, .5, .75, 1].forEach(t => {
        const value = yMax * t;
        const y = yScale(value);
        root.appendChild(svg('line', {x1:left, y1:y, x2:w-right, y2:y, stroke:'#e6edf3'}));
        root.appendChild(svg('text', {x:left-10, y:y+4, 'text-anchor':'end', 'font-size':'11', fill:'#657386'})).textContent = fmtWan(value);
      });
      root.appendChild(svg('line', {x1:left, y1:top, x2:left, y2:h-bottom, stroke:'#9aa7b5'}));
      root.appendChild(svg('line', {x1:left, y1:h-bottom, x2:w-right, y2:h-bottom, stroke:'#9aa7b5'}));
      rows.forEach((row, i) => {
        const value = Number(row.net_revenue || 0);
        const x = left + i * slot + (slot - barW) / 2;
        const y = yScale(value);
        const height = h - bottom - y;
        const bar = svg('rect', {x, y, width:barW, height:Math.max(1, height), rx:4, fill:colors.teal, opacity:.9, style:'cursor:pointer'});
        const title = svg('title', {});
        title.textContent = `${Number(row.hour)}点 业务收入：${fmtWan(value)}`;
        bar.appendChild(title);
        bar.addEventListener('mousemove', event => showTip(event, row));
        bar.addEventListener('mouseleave', hideTip);
        root.appendChild(bar);
        root.appendChild(svg('text', {x:x+barW/2, y:h-38, 'text-anchor':'middle', 'font-size':'10', fill:'#657386'})).textContent = `${Number(row.hour)}点`;
      });
      const peak = rows.reduce((best, row) => Number(row.net_revenue || 0) > Number(best.net_revenue || 0) ? row : best, rows[0] || {hour:'00', net_revenue:0});
      root.appendChild(svg('text', {x:left, y:18, 'font-size':'12', fill:'#657386', 'font-weight':'700'})).textContent = '业务收入（万元）';
      root.appendChild(svg('text', {x:w-right, y:18, 'text-anchor':'end', 'font-size':'11', fill:'#657386'})).textContent = `峰值：${Number(peak.hour)}点 ${fmtWan(peak.net_revenue)}`;
      el.innerHTML = '';
      el.appendChild(root);
      el.appendChild(tip);
    }
    function renderGaps() {
      const messages = data.data_gaps || [];
      const notice = document.getElementById('missingDataNotice');
      if (messages.length) {
        notice.hidden = false;
        notice.innerHTML = `<b>数据提示：</b>${messages.join('；')}`;
      }
      document.getElementById('dataGaps').hidden = true;
      const hideSection = id => {
        const section = document.getElementById(id);
        if (section) section.hidden = true;
        const link = document.querySelector(`.nav a[href="#${id}"]`);
        if (link) link.hidden = true;
      };
      const availability = data.availability || {};
      if (!availability.current) {
        document.querySelector('.hero .summary').hidden = true;
        ['summary', 'ranking', 'stores', 'channels', 'stall-mix', 'product-sales-per-10k', 'drivers', 'stall-drivers', 'daypart-drivers', 'dayparts'].forEach(hideSection);
        return;
      }
      if (!availability.trend) document.getElementById('trend').closest('.panel').hidden = true;
      if (!availability.channels) hideSection('channels');
      if (!data.stall_sales_mix?.enabled) hideSection('stall-mix');
      if (![data.product_sales_per_10k_order_revenue, data.product_sales_per_10k_gross_sales].some(panel => panel?.enabled)) hideSection('product-sales-per-10k');
      if (!data.stall_attribution?.enabled) hideSection('stall-drivers');
      if (!data.daypart_attribution?.enabled) hideSection('daypart-drivers');
      if (!availability.dayparts) hideSection('dayparts');
    }
    renderMeta();
    renderKpis();
    renderRules();
    renderBucketedRevenueRanking();
    renderGrowthBar();
    renderBucketedScatter();
    renderTrendSelector();
    renderTrend();
    renderTable();
    renderMixBars();
    renderPlatformBars();
    renderStallMixSelector();
    renderStallSalesMix();
    renderProductSalesPer10kSelector();
    renderProductSalesPer10k();
    renderDriverBar();
    renderActions();
    renderStallAttribution();
    renderDaypartAttribution();
    renderHourlySelector();
    renderHourlyRevenueBar();
    renderGaps();
  </script>
</body>
</html>
'''


def generate(input_dir: Path, output: Path, company: str | None = None) -> None:
    payload = build_payload(input_dir, company)
    title = escaped_report_title(payload["meta"]["title"])
    html = HTML_TEMPLATE.replace("__TITLE__", title).replace("__REPORT_TITLE__", title)
    html = html.replace("__PAYLOAD__", serialized_payload_for_html(payload))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html, encoding="utf-8")
    print(output)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--company")
    args = parser.parse_args()
    try:
        generate(args.input_dir, args.output, args.company)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
