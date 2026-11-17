"""Calculate weekly dine-in headcount and estimated table turnover from store-day extracts."""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

TRAFFIC = "orders_current_dine_in_by_day"
TURNOVER = "business_current_table_turnover_by_day"
METRICS = {
    TRAFFIC: ("in_store_orders", {
        "store_name", "business_date", "order_id", "order_status", "dining_mode", "diner_count",
    }),
    TURNOVER: ("business", {
        "store_name", "business_date", "dining_method", "table_count", "table_use_count",
    }),
}
HEADCOUNT_REVIEW_LIMIT = 1000
FACT_FIELDS = [
    "scope", "门店名称", "business_date", "dine_in_headcount", "table_uses", "configured_tables",
    "estimated_table_turnover", "excluded_orders", "excluded_registered_headcount",
    "traffic_days", "turnover_days", "expected_store_days",
]


def reviewed_exclusions(rows):
    """Validate a local ledger of explicitly reviewed orders without persisting order IDs in reports."""
    if rows is None:
        return set()
    if not isinstance(rows, list):
        raise ValueError("headcount exclusions must be a JSON array")
    keys = set()
    for row in rows:
        fields = ("store_name", "business_date", "order_id", "reason")
        if not isinstance(row, dict) or not all(isinstance(row.get(k), str) and row[k].strip() for k in fields):
            raise ValueError("each headcount exclusion needs a store, date, order ID and review reason")
        day = date.fromisoformat(row["business_date"]).isoformat()
        key = row["store_name"], day, row["order_id"]
        if key in keys:
            raise ValueError("headcount exclusions repeat an order")
        keys.add(key)
    return keys


def whole_count(value):
    return value is not None and Decimal(value).is_finite() and value >= 0 and value == int(value)


@dataclass
class DiningDay:
    orders: dict = field(default_factory=lambda: defaultdict(set))
    missing_order_ids: int = 0
    table_counts: set = field(default_factory=set)
    table_uses: int = 0
    missing_table_uses: bool = False


@dataclass
class DiningAccumulator:
    job: dict
    reviewed: set
    groups: dict = field(default_factory=lambda: defaultdict(DiningDay))
    matched: set = field(default_factory=set)

    def add(self, row):
        day = row["business_date"]
        start, end = self.job["input"]["filter"]["value"]
        if not start <= day <= end:
            return
        key = row["store_name"], day
        data = self.groups[key]
        if self.job["localMetric"] == TRAFFIC:
            if row["order_status"] != "已结账" or row["dining_mode"] != "堂食":
                return
            order_id = row["order_id"]
            if not order_id or order_id == "--":
                data.missing_order_ids += 1
                return
            data.orders[order_id].add(row["diner_count"])
            if (*key, order_id) in self.reviewed:
                self.matched.add((*key, order_id))
        else:
            tables = row["table_count"]
            if tables is not None:
                data.table_counts.add(tables)
            if row["dining_method"] == "堂食":
                uses = row["table_use_count"]
                if whole_count(uses):
                    data.table_uses += int(uses)
                else:
                    data.missing_table_uses = True

    def rows(self):
        result = []
        for (store, day), data in sorted(self.groups.items()):
            row = {"store_name": store, "business_date": day}
            if self.job["localMetric"] == TRAFFIC:
                included, headcount, excluded_people = 0, 0, 0
                excluded_orders = data.missing_order_ids
                for order_id, counts in data.orders.items():
                    count = next(iter(counts)) if len(counts) == 1 else None
                    if not whole_count(count):
                        excluded_orders += 1
                    elif count >= HEADCOUNT_REVIEW_LIMIT or (store, day, order_id) in self.reviewed:
                        excluded_orders += 1
                        excluded_people += int(count)
                    else:
                        included += 1
                        headcount += int(count)
                row.update(dine_in_headcount=headcount if included or not excluded_orders else None,
                           excluded_orders=excluded_orders, excluded_registered_headcount=excluded_people)
            else:
                tables = next(iter(data.table_counts)) if len(data.table_counts) == 1 else None
                row.update(table_uses=None if data.missing_table_uses else data.table_uses, configured_tables=tables)
            result.append(row)
        return result


def dining_facts(traffic, turnover, stores, window):
    """Build daily and weekly store/enterprise facts with coverage and weighted rates."""
    if not (traffic or turnover):
        return [], []
    start, end = (date.fromisoformat(window[k]) for k in ("start", "end"))
    days = [(start + timedelta(days=n)).isoformat() for n in range((end - start).days + 1)]
    traffic_by_day = {(r["store_name"], r["business_date"]): r for r in traffic}
    table_by_day = {(r["store_name"], r["business_date"]): r for r in turnover}

    def summarize(scope, store, day, keys):
        people = [traffic_by_day[key] for key in keys if key in traffic_by_day]
        headcounts = [r["dine_in_headcount"] for r in people if r["dine_in_headcount"] is not None]
        tables = [table_by_day[key] for key in keys if key in table_by_day
                  and table_by_day[key]["table_uses"] is not None and (table_by_day[key]["configured_tables"] or 0) > 0]
        uses = sum(r["table_uses"] for r in tables)
        capacity = sum(r["configured_tables"] for r in tables)
        return {
            "scope": scope, "门店名称": store, "business_date": day,
            "dine_in_headcount": sum(headcounts) if headcounts else None,
            "table_uses": uses if capacity else None, "configured_tables": capacity or None,
            "estimated_table_turnover": uses / capacity if capacity else None,
            "excluded_orders": sum(r["excluded_orders"] for r in people),
            "excluded_registered_headcount": sum(r["excluded_registered_headcount"] for r in people),
            "traffic_days": len(headcounts), "turnover_days": len(tables), "expected_store_days": len(keys),
        }

    scopes = [("all", "全体门店", stores)] + [("store", store, [store]) for store in stores]
    daily = [summarize(scope, label, day, [(store, day) for store in names])
             for scope, label, names in scopes for day in days]
    weekly = [summarize(scope, label, None, [(store, day) for store in names for day in days])
              for scope, label, names in scopes]
    return daily, weekly
