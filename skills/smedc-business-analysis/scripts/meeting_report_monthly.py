#!/usr/bin/env python3
"""Generate a self-contained monthly meeting HTML report."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

from identity import organization_name_from_metadata
from meeting_report_weekly import (
    HTML_TEMPLATE as WEEKLY_HTML_TEMPLATE,
    REVENUE_BASIS_NOTE,
    aggregate_dayparts,
    attach_daypart_slots,
    build_product_sales_per_10k_payload,
    build_stall_sales_mix_payload,
    compact_daypart_drivers,
    escaped_report_title,
    median,
    pct_change,
    read_csv,
    read_optional_csv,
    safe_sum,
    serialized_payload_for_html,
)


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
                    "week_label": row.get("month_label") or "",
                    "current_net_revenue": None,
                    "prior_net_revenue": None,
                    "current_week_range": "",
                    "prior_week_range": "",
                },
            )
            series_key = str(row.get("series_key") or "")
            revenue = float(row["net_revenue"]) if row.get("net_revenue") is not None else None
            month_range = f"{row.get('month_start')}-{row.get('month_end')}"
            if series_key == "current_year":
                item["week_label"] = row.get("month_label") or row.get("week_label") or ""
                if revenue is not None:
                    item["current_net_revenue"] = round((item["current_net_revenue"] or 0) + revenue, 2)
                item["current_week_range"] = month_range
            elif series_key == "prior_year":
                if revenue is not None:
                    item["prior_net_revenue"] = round((item["prior_net_revenue"] or 0) + revenue, 2)
                item["prior_week_range"] = month_range
        return [groups[index] for index in sorted(groups)]

    stores = sorted({str(row.get("门店名称") or "") for row in rows if row.get("门店名称")})
    entities = [{"key": "__all__", "label": "全体门店", "rows": build_series(rows)}]
    for store in stores:
        store_rows = [row for row in rows if row.get("门店名称") == store]
        entities.append({"key": store, "label": store, "rows": build_series(store_rows)})
    return entities


def presentation_company_override(company: str | None) -> str | None:
    if company is None:
        return None
    stripped = company.strip()
    if stripped == "":
        raise ValueError("company override must be non-blank")
    return stripped


def build_payload(input_dir: Path, company: str | None = None) -> dict[str, Any]:
    summary = json.loads((input_dir / "monthly_meeting_summary.json").read_text(encoding="utf-8"))
    organization_name = organization_name_from_metadata(summary)
    report_company = presentation_company_override(company) or organization_name
    comparison = read_csv(input_dir / "monthly_store_comparison.csv")
    segments = read_csv(input_dir / "star_problem_stores.csv")
    drivers = read_csv(input_dir / "store_driver_summary.csv")
    channels = read_csv(input_dir / "monthly_store_channel_metrics.csv")
    dayparts = read_csv(input_dir / "monthly_store_daypart_metrics.csv")
    trend_comparison_path = input_dir / "monthly_trend_comparison_metrics.csv"
    trend_comparison = read_csv(trend_comparison_path) if trend_comparison_path.exists() else []
    daypart_comparison = read_optional_csv(input_dir / "monthly_store_daypart_comparison.csv")
    daypart_drivers = read_optional_csv(input_dir / "monthly_store_daypart_driver_summary.csv")
    stall_sales_mix = read_optional_csv(input_dir / "monthly_store_stall_sales_mix.csv")
    product_sales_per_10k = read_optional_csv(input_dir / "monthly_store_product_sales_per_10k.csv")

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
        row["segment"] = segment.get("segment", "未分型")
        row["segment_reason"] = str(segment.get("reason", "")).replace("本周", "本月")
        row["top_negative_factor"] = driver.get("top_negative_factor", "")
        row["top_daypart_signal"] = daypart_driver.get("daypart_signal", "")
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
    current_orders = safe_sum(comparison, "current_positive_orders")
    current_aov = current_revenue / current_orders if current_orders else 0
    star_count = sum(1 for row in comparison if row.get("segment") == "明星门店")
    problem_count = sum(1 for row in comparison if row.get("segment") == "问题门店")
    revenue_threshold = median([float(row.get("current_net_revenue") or 0) for row in comparison])

    current_channels = [row for row in channels if row.get("period") == "本月"]
    channel_by_store: dict[str, dict[str, float]] = {}
    for row in current_channels:
        store = str(row.get("门店名称") or "")
        channel = str(row.get("channel") or "")
        channel_by_store.setdefault(store, {})[channel] = float(row.get("net_revenue") or 0)

    return {
        "meta": {
            "title": f"{report_company}月经营会报",
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
            "trend": bool(trend_comparison),
            "channels": bool(current_channels),
            "dayparts": bool(dayparts),
        },
        "segment_rules": {
            "revenue_threshold": round(revenue_threshold, 2),
            "growth_threshold": 0,
            "items": [
                {
                    "name": "明星门店",
                    "logic": "本月业务收入 >= 门店中位数，且环比增长率 >= 0%",
                    "use": "优先沉淀打法，复盘可复制动作。",
                },
                {
                    "name": "高基盘承压",
                    "logic": "本月业务收入 >= 门店中位数，但环比增长率 < 0%",
                    "use": "收入体量仍大，但要复盘短期下滑原因。",
                },
                {
                    "name": "成长观察",
                    "logic": "本月业务收入 < 门店中位数，但环比增长率 >= 0%",
                    "use": "关注增长是否可持续，寻找放大空间。",
                },
                {
                    "name": "问题门店",
                    "logic": "本月业务收入 < 门店中位数，且环比增长率 < 0%",
                    "use": "优先排查客流、开台、客单和折扣拖累。",
                },
            ],
            "warnings": "同比下滑超过 25%、环比下滑超过 8%、折扣率高于门店中位水平 20% 以上、客单价低于门店中位水平 10% 以上，会作为预警补充到门店原因中。",
        },
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
        "dayparts": aggregate_dayparts([row for row in dayparts if row.get("period") in {"本月", "上月"}]),
        "trend": [],
        "trend_entities": build_trend_comparison_entities(trend_comparison),
        "trend_note": "自然月口径；仅展示最近 6 个月，实线=本年，虚线=同期。",
        "daypart_attribution": {
            "enabled": bool(summary["meta"].get("daypart_attribution", {}).get("enabled", True)) and bool(daypart_drivers),
            "meta": summary["meta"].get("daypart_attribution", {}),
            "comparison": daypart_comparison,
            "drivers": attach_daypart_slots(compact_daypart_drivers(daypart_drivers, "环比"), daypart_comparison, "环比"),
            "yoy_drivers": attach_daypart_slots(compact_daypart_drivers(daypart_drivers, "同比"), daypart_comparison, "同比"),
        },
        "data_gaps": summary.get("data_gaps", []),
    }


def monthly_template() -> str:
    replacements = [
        ("周经营会报", "月经营会报"),
        ("Weekly Operating Review", "Monthly Operating Review"),
        ("本周", "本月"),
        ("环比周", "上月"),
        ("同比周", "去年同月"),
        ("周会", "月会"),
        ("最近一年收入趋势（52 周）", "最近 6 个月收入趋势"),
        ("完整周，整体业务收入（万元）；实线=本年，虚线=同期", "自然月，整体业务收入（万元）；实线=本年，虚线=同期"),
        ("完整周，", "自然月，"),
        ("完整周口径", "自然月口径"),
        ("每家门店本周经营", "每家门店本月经营"),
        ("基于美团营业分组表，聚焦每家门店本月经营", "基于美团营业分组表，聚焦每家门店本月经营"),
        ("补齐本月、上月、去年同月后可生成完整拖动归因", "补齐本月、上月、去年同月后可生成完整驱动归因"),
    ]
    html = WEEKLY_HTML_TEMPLATE
    for source, target in replacements:
        html = html.replace(source, target)
    return html


def generate(input_dir: Path, output: Path, company: str | None = None) -> None:
    payload = build_payload(input_dir, company)
    title = escaped_report_title(payload["meta"]["title"])
    html = monthly_template().replace("__TITLE__", title).replace("__REPORT_TITLE__", title)
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
