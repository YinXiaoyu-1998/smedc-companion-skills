#!/usr/bin/env python3
"""Derive SMEDC weekly meeting fact tables from a query bundle."""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from build_query_plan import weekly_trend_window

from identity import organization_name_from_current_user_file, organization_name_from_metadata
from report_common import (
    aggregate_rows,
    COMPARISON_METRICS,
    METRIC_FIELDS,
    channel_rows,
    classify_stores,
    comparison_rows,
    daypart_comparison_rows,
    daypart_driver_rows,
    daypart_rows,
    driver_rows,
    job_metadata,
    load_bundle,
    parse_bundle_cli,
    report_gap_messages,
    rows_for,
    stall_and_product_outputs,
    store_metric_rows,
    write_csv,
    write_json,
)


PERIOD_LABELS = {"current": "本周", "previous": "环比周", "yoy": "同比周"}


def comparison_fieldnames() -> list[str]:
    fields = ["门店名称", "store_size_bucket", "store_segment"]
    for prefix in ["current", "previous", "yoy"]:
        fields.extend([f"{prefix}_{field}" for field in METRIC_FIELDS])
    for prefix in ["wow", "yoy"]:
        for field in COMPARISON_METRICS:
            fields.extend([f"{prefix}_{field}_delta", f"{prefix}_{field}_pct"])
    fields.append("open_rate_delta")
    return fields


def trend_rows(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    """Sum daily service income into fixed requested-week positions, retaining gaps."""
    groups: dict[tuple[str, str, int], list[dict[str, Any]]] = defaultdict(list)
    windows = bundle["report"]["windows"]
    frames = {}
    for job_id, series, period in (
        ("business_16_week_prior_year_store_trend", "prior_year", "yoy"),
        ("business_16_week_store_trend", "current_year", "current"),
    ):
        frame = weekly_trend_window(date.fromisoformat(windows[period]["end"]))
        frames[series] = frame
        for source in rows_for(bundle, job_id):
            try:
                day = date.fromisoformat(str(source.get("business_date") or "")[:10].replace("/", "-"))
            except ValueError:
                continue
            if frame.start <= day <= frame.end:
                index = (day - frame.start).days // 7 + 1
                groups[(series, str(source.get("store_name") or "未知门店"), index)].append(source)
    stores = sorted({store for _, store, _ in groups})
    output = []
    for index in range(1, 17):
        for series, frame in frames.items():
            start = frame.start + timedelta(days=(index - 1) * 7)
            end = start + timedelta(days=6)
            for store in stores:
                # Only additive daily income is queried for this chart; ratios remain unknown.
                source = {"store_name": store, **aggregate_rows(groups.get((series, store, index), []))}
                output.extend(store_metric_rows([source], {
                    "series_key": series, "series_label": str(frame.end.year), "window_index": index,
                    "week_start": start.isoformat(), "week_end": end.isoformat(),
                    "week_label": f"{start:%m/%d}-{end:%m/%d}",
                }))
    return output


def profile(bundle_path: Path, output_dir: Path, organization_name: str | None = None) -> dict[str, Any]:
    bundle = load_bundle(bundle_path, "weekly")
    report_organization_name = organization_name or organization_name_from_metadata(bundle)
    output_dir.mkdir(parents=True, exist_ok=True)

    current_store = rows_for(bundle, "business_current_store_totals")
    previous_store = rows_for(bundle, "business_previous_store_totals")
    yoy_store = rows_for(bundle, "business_yoy_store_totals")

    weekly_rows = trend_rows(bundle)
    channels = [
        row
        for period, label in PERIOD_LABELS.items()
        for row in channel_rows(rows_for(bundle, f"business_{period}_channel_platform_mix"), label)
    ]
    dayparts = [
        row
        for period, label in PERIOD_LABELS.items()
        for row in daypart_rows(rows_for(bundle, f"business_{period}_daypart_mix"), label)
    ]
    daypart_comparisons = daypart_comparison_rows(dayparts, PERIOD_LABELS)
    daypart_drivers = daypart_driver_rows(daypart_comparisons)
    comparisons = comparison_rows(current_store, previous_store, yoy_store)
    store_segments = classify_stores(comparisons, "本周")
    drivers = driver_rows(comparisons)
    stall_meta = stall_and_product_outputs(
        output_dir=output_dir,
        prefix="weekly",
        period_label=PERIOD_LABELS["current"],
        current_store_rows=current_store,
        dish_rows=rows_for(bundle, "dishes_current_product_totals"),
        catalog_rows=rows_for(bundle, "dish_catalog_current_snapshot"),
        comparison_dish_rows={
            period: rows_for(bundle, f"dishes_{period}_product_totals")
            for period in PERIOD_LABELS
        },
    )

    write_csv(output_dir / "weekly_store_metrics.csv", weekly_rows, ["series_key", "series_label", "window_index", "week_start", "week_end", "week_label", "门店名称"] + METRIC_FIELDS)
    write_csv(output_dir / "weekly_store_channel_metrics.csv", channels, ["门店名称", "period", "channel"] + METRIC_FIELDS)
    write_csv(output_dir / "weekly_store_daypart_metrics.csv", dayparts, ["门店名称", "period", "餐段", "时段"] + METRIC_FIELDS)
    write_csv(output_dir / "weekly_store_daypart_comparison.csv", daypart_comparisons, list(daypart_comparisons[0]) if daypart_comparisons else ["门店名称", "餐段", "时段"])
    write_csv(output_dir / "weekly_store_daypart_driver_summary.csv", daypart_drivers, list(daypart_drivers[0]) if daypart_drivers else ["门店名称", "basis"])
    write_csv(output_dir / "weekly_trend_comparison_metrics.csv", weekly_rows, ["series_key", "series_label", "window_index", "week_start", "week_end", "week_label", "门店名称"] + METRIC_FIELDS)
    write_csv(output_dir / "weekly_store_comparison.csv", comparisons, comparison_fieldnames())
    write_csv(output_dir / "store_driver_summary.csv", drivers, list(drivers[0]) if drivers else ["门店名称", "basis"])
    write_csv(output_dir / "star_problem_stores.csv", store_segments, list(store_segments[0]) if store_segments else ["门店名称", "segment"])

    outputs = [
        "weekly_store_metrics.csv",
        "weekly_store_channel_metrics.csv",
        "weekly_store_daypart_metrics.csv",
        "weekly_store_daypart_comparison.csv",
        "weekly_store_daypart_driver_summary.csv",
        *stall_meta.get("outputs", []),
        "weekly_trend_comparison_metrics.csv",
        "weekly_store_comparison.csv",
        "store_driver_summary.csv",
        "star_problem_stores.csv",
        "weekly_meeting_summary.json",
    ]
    summary = {
        "meta": {
            "organization_name": report_organization_name,
            "report_grain": "week",
            "bundle": str(bundle_path),
            "target_windows": bundle["report"]["windows"],
            "store_name_contains": bundle["report"].get("storeNameContains", []),
            "coverage": bundle.get("coverage", {}),
            "jobs": job_metadata(bundle),
            "outputContract": bundle.get("outputContract"),
            "store_count": len({row["门店名称"] for row in comparisons}),
            "outputs": outputs,
            "stall_sales_mix": stall_meta,
            "stall_attribution": stall_meta.get("stall_attribution", {"enabled": False}),
            "daypart_attribution": {
                "enabled": bool(daypart_comparisons and daypart_drivers),
                "basis": "按门店、餐段和时段比较本周、环比周与同比周的订单营业收入。",
            },
            "product_sales_per_10k": stall_meta.get("product_sales_per_10k", {}),
            "product_sales_per_10k_order_revenue": stall_meta.get("product_sales_per_10k_order_revenue", {}),
            "product_sales_per_10k_gross_sales": stall_meta.get("product_sales_per_10k_gross_sales", {}),
        },
        "comparison": comparisons,
        "drivers": drivers,
        "store_segments": store_segments,
        "channel_current": channels,
        "daypart_current_previous": daypart_comparisons,
        "weekly_trend": weekly_rows,
        "weekly_trend_comparison": weekly_rows,
        "notices": bundle.get("notices", []),
        "data_gaps": report_gap_messages(
            bundle.get("notices", []),
            has_current=bool(current_store),
            has_previous=bool(previous_store),
            has_yoy=bool(yoy_store),
            has_trend=bool(weekly_rows),
            has_channels=any(row.get("period") == PERIOD_LABELS["current"] for row in channels),
            has_dayparts=any(row.get("period") == PERIOD_LABELS["current"] for row in dayparts),
            has_dishes=bool(rows_for(bundle, "dishes_current_product_totals")),
            has_catalog=bool(rows_for(bundle, "dish_catalog_current_snapshot")),
            store_name_contains=bundle["report"].get("storeNameContains", []),
        ),
    }
    write_json(output_dir / "weekly_meeting_summary.json", summary)
    return summary


def main() -> int:
    args = parse_bundle_cli(__doc__ or "")
    try:
        organization_name = organization_name_from_current_user_file(args.current_user) if args.current_user else None
        summary = profile(args.bundle, args.output_dir, organization_name)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"output_dir": str(args.output_dir), "notices": summary["notices"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
