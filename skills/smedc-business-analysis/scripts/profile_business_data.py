#!/usr/bin/env python3
"""Derive business operating diagnosis fact tables from a query bundle."""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Any

from profile_monthly_data import normalize_business_month

from identity import organization_name_from_current_user_file, organization_name_from_metadata
from report_common import (
    aggregate_rows,
    job_metadata,
    load_bundle,
    metric_row,
    optional_dec,
    parse_bundle_cli,
    rows_for,
    rounded,
    store_metric_rows,
    store_name,
    write_csv,
    write_json,
)


COMMON_FIELDS = [
    "rows",
    "active_days",
    "store_count",
    "city_count",
    "gross_sales",
    "net_revenue",
    "discount_amount",
    "discount_rate",
    "positive_orders",
    "settled_orders",
    "reverse_orders",
    "pre_discount_aov",
    "post_discount_aov",
    "dine_in_revenue",
    "delivery_revenue",
    "pickup_revenue",
    "dine_in_revenue_share",
    "delivery_revenue_share",
    "pickup_revenue_share",
    "member_revenue",
    "member_revenue_share",
    "refund_amount_known",
    "refund_rate_known",
    "customer_count",
    "revenue_per_customer",
    "consumed_tables",
    "revenue_per_table",
    "open_rate",
    "turnover_rate",
]


def diagnosis_metric_row(source: dict[str, Any]) -> dict[str, Any]:
    row = metric_row(source)
    gross = optional_dec(source, "gross_sales")
    orders = optional_dec(source, "positive_orders")
    dine_in_revenue = optional_dec(source, "dine_in_revenue")
    pickup_revenue = optional_dec(source, "pickup_revenue")
    refund_amount = optional_dec(source, "refund_amount_known")
    if refund_amount is None:
        refund_parts = [
            optional_dec(source, "dine_in_refund_amount"),
            optional_dec(source, "delivery_refund_amount"),
            optional_dec(source, "pickup_refund_amount"),
        ]
        known_refunds = [part for part in refund_parts if part is not None]
        refund_amount = sum(known_refunds, start=Decimal("0")) if known_refunds else None
    revenue = optional_dec(source, "order_revenue")
    row.update(
        {
            "store_count": source.get("store_count"),
            "city_count": source.get("city_count"),
            "pre_discount_aov": rounded((gross / orders) if gross is not None and orders else None, 2),
            "pickup_revenue": rounded(pickup_revenue, 2),
            "dine_in_revenue_share": rounded((dine_in_revenue / revenue) if dine_in_revenue is not None and revenue else None, 4),
            "pickup_revenue_share": rounded((pickup_revenue / revenue) if pickup_revenue is not None and revenue else None, 4),
            "refund_amount_known": rounded(refund_amount, 2),
            "refund_rate_known": rounded((refund_amount / gross) if refund_amount is not None and gross else None, 4),
        }
    )
    return row


def compact_top(rows: list[dict[str, Any]], label_fields: list[str], limit: int = 12) -> list[dict[str, Any]]:
    keep = label_fields + ["net_revenue", "gross_sales", "discount_rate", "positive_orders", "post_discount_aov", "member_revenue_share"]
    return [{field: row.get(field) for field in keep} for row in rows[:limit]]


def profile(bundle_path: Path, output_dir: Path, organization_name: str | None = None) -> dict[str, Any]:
    bundle = load_bundle(bundle_path, "diagnosis")
    report_organization_name = organization_name or organization_name_from_metadata(bundle)
    output_dir.mkdir(parents=True, exist_ok=True)

    overall_source = rows_for(bundle, "business_current_kpi_totals")
    overall = diagnosis_metric_row(overall_source[0] if overall_source else aggregate_rows(rows_for(bundle, "business_current_store_totals")))
    store_rows = [
        {"门店名称": row["门店名称"], "城市": source.get("city") or "", "商户号": source.get("merchant_id") or "", **diagnosis_metric_row(source)}
        for source in rows_for(bundle, "business_current_store_totals")
        for row in [{"门店名称": store_name(source.get("store_name"))}]
    ]
    store_rows.sort(key=lambda item: (-(item.get("net_revenue") or 0), item["门店名称"], item["城市"], item["商户号"]))

    channel_groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows_for(bundle, "business_current_channel_platform_mix"):
        channel_groups[(str(row.get("order_category") or "未知订单分类"), str(row.get("order_source") or "未知订单来源"))].append(row)
    channel_rows = [
        {"订单分类": key[0], "订单来源": key[1], **diagnosis_metric_row(aggregate_rows(group))}
        for key, group in channel_groups.items()
    ]
    channel_rows.sort(key=lambda item: (-(item.get("net_revenue") or 0), item["订单分类"], item["订单来源"]))

    daypart_groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows_for(bundle, "business_current_efficiency"):
        daypart_groups[(str(row.get("meal_period") or "未知餐段"), str(row.get("time_slot") or "全部时段"))].append(row)
    daypart_rows = [
        {"餐段": key[0], "时段": key[1], **diagnosis_metric_row(aggregate_rows(group))}
        for key, group in daypart_groups.items()
    ]
    daypart_rows.sort(key=lambda item: (-(item.get("net_revenue") or 0), item["餐段"], item["时段"]))

    member_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows_for(bundle, "business_current_member_mix"):
        label = "会员" if str(row.get("is_member")) == "1" else "非会员" if str(row.get("is_member")) == "0" else "未知"
        member_groups[label].append(row)
    member_rows = [{"会员类型": key, **diagnosis_metric_row(aggregate_rows(group))} for key, group in member_groups.items()]
    member_rows.sort(key=lambda item: (-(item.get("net_revenue") or 0), item["会员类型"]))

    payment_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows_for(bundle, "business_current_payment_mix"):
        payment_groups[str(row.get("order_source") or row.get("dining_method") or "未知")].append(row)
    payment_rows = [{"支付/来源": key, **diagnosis_metric_row(aggregate_rows(group))} for key, group in payment_groups.items()]
    payment_rows.sort(key=lambda item: (-(item.get("net_revenue") or 0), item["支付/来源"]))

    store_daypart_rows = [
        {"门店名称": store_name(row.get("store_name")), "城市": "未知城市", "商户号": "未知商户号", "餐段": str(row.get("meal_period") or "未知餐段"), "时段": str(row.get("time_slot") or "全部时段"), **diagnosis_metric_row(row)}
        for row in rows_for(bundle, "business_current_efficiency")
    ]
    store_daypart_rows.sort(key=lambda item: (item["门店名称"], -(item.get("net_revenue") or 0), item["餐段"], item["时段"]))

    monthly_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows_for(bundle, "business_current_monthly_trend"):
        month, start, _ = normalize_business_month(row.get("business_month"))
        if start:
            monthly_groups[month].append(row)
    monthly_rows = []
    window = bundle["report"]["windows"]["current"]
    month = window["start"][:7]
    while monthly_groups and month <= window["end"][:7]:
        sources = monthly_groups.get(month, [])
        monthly_rows.append({"月": month, **diagnosis_metric_row(aggregate_rows(sources))})
        year, number = map(int, month.split("-"))
        month = f"{year + (number == 12):04d}-{number % 12 + 1:02d}"
    if overall.get("store_count") is None and store_rows:
        overall["store_count"] = len({row["门店名称"] for row in store_rows})
    write_csv(output_dir / "monthly_trend.csv", monthly_rows, ["月"] + COMMON_FIELDS)
    write_csv(output_dir / "store_summary.csv", store_rows, ["门店名称", "城市", "商户号"] + COMMON_FIELDS)
    write_csv(output_dir / "channel_summary.csv", channel_rows, ["订单分类", "订单来源"] + COMMON_FIELDS)
    write_csv(output_dir / "daypart_summary.csv", daypart_rows, ["餐段", "时段"] + COMMON_FIELDS)
    write_csv(output_dir / "member_summary.csv", member_rows, ["会员类型"] + COMMON_FIELDS)
    write_csv(output_dir / "payment_summary.csv", payment_rows, ["支付/来源"] + COMMON_FIELDS)
    write_csv(output_dir / "store_daypart_summary.csv", store_daypart_rows, ["门店名称", "城市", "商户号", "餐段", "时段"] + COMMON_FIELDS)

    summary = {
        "meta": {
            "organization_name": report_organization_name,
        },
        "source": {
            "bundle": str(bundle_path),
            "report_type": "diagnosis",
            "windows": bundle["report"]["windows"],
            "store_name_contains": bundle["report"].get("storeNameContains", []),
            "coverage": bundle.get("coverage", {}),
            "jobs": job_metadata(bundle),
            "outputContract": bundle.get("outputContract"),
        },
        "overall_kpis": overall,
        "top_stores_by_revenue": compact_top(store_rows, ["门店名称", "城市", "商户号"]),
        "bottom_stores_by_revenue": compact_top(list(reversed(store_rows)), ["门店名称", "城市", "商户号"]),
        "top_channels_by_revenue": compact_top(channel_rows, ["订单分类", "订单来源"]),
        "top_dayparts_by_revenue": compact_top(daypart_rows, ["餐段", "时段"]),
        "member_summary": member_rows,
        "payment_summary": payment_rows,
        "notices": bundle.get("notices", []),
        "warnings": [],
        "outputs": [
            "monthly_trend.csv",
            "store_summary.csv",
            "channel_summary.csv",
            "daypart_summary.csv",
            "member_summary.csv",
            "payment_summary.csv",
            "store_daypart_summary.csv",
            "analysis_summary.json",
        ],
    }
    write_json(output_dir / "analysis_summary.json", summary)
    return summary


def main() -> int:
    args = parse_bundle_cli(__doc__ or "")
    try:
        organization_name = organization_name_from_current_user_file(args.current_user) if args.current_user else None
        summary = profile(args.bundle, args.output_dir, organization_name)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"overall_kpis": summary["overall_kpis"], "output_dir": str(args.output_dir), "notices": summary["notices"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
