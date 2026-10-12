"""Calendar-aligned revenue views derived only from saved daily MCP facts."""

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
import csv

from build_query_plan import monthly_trend_window, month_end, subtract_months, weekly_trend_window
from report_common import rows_for, write_csv


NOTES = {
    "day": "最近 365 天；同期按去年同月同日对齐，2 月 29 日无对应日；空缺表示未取得记录。",
    "week": "最近 52 个完整周；同期按指定同比周对齐；空缺表示未取得记录。",
    "month": "最近 12 个完整自然月；同期为去年同月；空缺表示未取得记录。",
}


def trend_frames(current_end, yoy_end):
    day_start = current_end - timedelta(days=364)
    days = []
    for i in range(365):
        start = day_start + timedelta(days=i)
        try:
            prior = start.replace(year=start.year - 1)
        except ValueError:
            prior = None
        days.append((start, start, prior, prior))
    current_week, prior_week = weekly_trend_window(current_end), weekly_trend_window(yoy_end)
    weeks = []
    for i in range(52):
        start = current_week.start + timedelta(days=i * 7)
        prior = prior_week.start + timedelta(days=i * 7)
        weeks.append((start, start + timedelta(days=6), prior, prior + timedelta(days=6)))
    frame = monthly_trend_window(current_end)
    months = []
    for i in range(12):
        start = subtract_months(frame.start, -i)
        prior = start.replace(year=start.year - 1)
        months.append((start, month_end(start.year, start.month), prior, month_end(prior.year, prior.month)))
    return {"day": days, "week": weeks, "month": months}


def write_revenue_views(bundle, output_dir: Path, prefix: str):
    if "business_daily_store_trend" not in bundle.get("resultsByJobId", {}):
        return []  # Durable older bundles retain their existing trend view.
    windows = bundle["report"]["windows"]
    frames = trend_frames(date.fromisoformat(windows["current"]["end"]), date.fromisoformat(windows["yoy"]["end"]))
    daily = defaultdict(dict)
    for row in rows_for(bundle, "business_daily_store_trend"):
        raw = row.get("order_revenue")
        if raw is None or str(raw).strip() == "":
            continue
        day = date.fromisoformat(str(row["business_date"])[:10].replace("/", "-"))
        store = str(row.get("store_name") or "未知门店")
        daily[store][day] = daily[store].get(day, Decimal(0)) + Decimal(str(raw))

    def amount(observations, start, end):
        values = [value for day, value in observations.items() if start is not None and start <= day <= end]
        return float(sum(values).quantize(Decimal("0.01"))) if values else None

    output = []
    for grain, periods in frames.items():
        for index, (start, end, prior, prior_end) in enumerate(periods, 1):
            for store, observations in sorted(daily.items()):
                output.append({"grain": grain, "门店名称": store, "window_index": index,
                    "week_label": start.strftime("%m/%d") if grain == "day" else start.strftime("%Y-%m") if grain == "month" else f"{start:%m/%d}-{end:%m/%d}",
                    "current_week_range": f"{start}-{end}",
                    "prior_week_range": f"{prior}-{prior_end}" if prior else "",
                    "current_net_revenue": amount(observations, start, end),
                    "prior_net_revenue": amount(observations, prior, prior_end)})
    filename = f"{prefix}_revenue_trend_metrics.csv"
    write_csv(output_dir / filename, output, list(output[0]) if output else ["grain", "门店名称", "window_index"])
    return [filename]


def read_revenue_views(path: Path):
    if not path.exists():
        return {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    views = {}
    for grain in NOTES:
        selected = [row for row in rows if row["grain"] == grain]
        if not selected:
            continue
        stores = sorted({row["门店名称"] for row in selected})

        def series(source):
            buckets = {}
            for row in source:
                index = int(row["window_index"])
                item = buckets.setdefault(index, {key: row[key] for key in ("week_label", "current_week_range", "prior_week_range")})
                item["window_index"] = index
                for field in ("current_net_revenue", "prior_net_revenue"):
                    item.setdefault(field, None)
                    if row[field] != "":
                        item[field] = float(Decimal(str(item[field] or 0)) + Decimal(row[field]))
            return [buckets[key] for key in sorted(buckets)]
        views[grain] = {"note": NOTES[grain], "entities": [
            {"key": "__all__", "label": "全体门店", "rows": series(selected)},
            *[{"key": store, "label": store, "rows": series([row for row in selected if row["门店名称"] == store])} for store in stores],
        ]}
    return views
