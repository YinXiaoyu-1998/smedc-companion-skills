#!/usr/bin/env python3
"""Verify the business day, export settings, and observed stores in a Meituan workbook."""

import argparse
from datetime import date
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import re
import sys
from zipfile import BadZipFile

from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException


TITLE = "单品关联套餐销售明细"
REQUIRED_FILTERS = {
    "统计方式": "套餐明细",
    "按门店统计": "是",
    "显示菜品规格": "是",
    "同名菜品合并统计": "否",
    "菜品分类": "全部",
    "菜品名称": "全部",
    "订单分类": "全部",
    "菜品下单来源": "全部",
}
AMOUNT_HEADERS = ("销售数量", "销售额(元)", "菜品优惠(元)", "菜品收入(元)")
HEADERS = {
    "地区", "门店", "菜品编码", "套餐", "单品名称", "菜品类型", "单位", "规格", "菜品大类",
    *AMOUNT_HEADERS,
}


def nonempty_rows(sheet):
    sheet.reset_dimensions()
    for number, row in enumerate(sheet.iter_rows(values_only=True), 1):
        fields = tuple("" if value is None else str(value).strip() for value in row)
        while fields and not fields[-1]:
            fields = fields[:-1]
        if fields:
            yield number, fields


def read_filters(summary):
    filters = {}
    for part in re.split(r"[；;]", summary):
        match = re.fullmatch(r"([^：【】]+?)[:：]?【([^【】]+)】", part.strip())
        if not match or match[1] in filters:
            raise ValueError("筛选说明格式错误或包含重复条件。")
        filters[match[1]] = match[2]
    for key, expected in REQUIRED_FILTERS.items():
        if filters.get(key) != expected:
            raise ValueError(f"导出设置须为 {key}【{expected}】。")
    if set(filters) != set(REQUIRED_FILTERS) | {"营业日期", "门店"} or not filters["门店"].strip():
        raise ValueError("筛选说明缺少营业日期或门店，或含有额外条件。")
    span = re.fullmatch(r"(\d{4}[/-]\d{2}[/-]\d{2})\s*至\s*(\d{4}[/-]\d{2}[/-]\d{2})", filters["营业日期"])
    if not span:
        raise ValueError("无法从筛选说明读取营业日期。")
    days = [date.fromisoformat(value.replace("/", "-")) for value in span.groups()]
    if days[0] != days[1]:
        raise ValueError(f"工作簿汇总了 {days[0]} 至 {days[1]}，请按单营业日重新导出。")
    return days[0]


def verify(path, expected_day, requested_stores):
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        if TITLE not in workbook.sheetnames:
            raise ValueError(f"缺少「{TITLE}」工作表。")
        for sheet in workbook.worksheets:
            if sheet.title != TITLE and next(nonempty_rows(sheet), None):
                raise ValueError("工作簿含有额外的非空工作表。")
        rows = nonempty_rows(workbook[TITLE])
        title, summary, header = (next(rows, (0, ()))[1] for _ in range(3))
        if title != (TITLE,) or len(summary) != 1:
            raise ValueError("缺少原始报表标题或筛选说明。")
        business_day = read_filters(summary[0])
        if business_day != expected_day:
            raise ValueError(f"工作簿营业日为 {business_day}，目标营业日为 {expected_day}。")
        if len(header) != len(HEADERS) or set(header) != HEADERS:
            raise ValueError("表头不符合带规格的套餐子菜销售明细。")

        stores = set()
        count = 0
        saw_total = False
        for number, row in rows:
            if saw_total:
                raise ValueError(f"合计行之后仍有数据，见第 {number} 行。")
            if len(row) > len(header):
                raise ValueError(f"第 {number} 行有超出表头的字段。")
            fields = dict(zip(header, row + ("",) * (len(header) - len(row))))
            if not fields["门店"]:
                summary_labels = {"", "合计", "总计", "汇总", "小计"}
                if fields["地区"] not in summary_labels or any(
                    fields[key] for key in HEADERS - set(AMOUNT_HEADERS) - {"地区"}
                ):
                    raise ValueError(f"第 {number} 行缺少门店。")
                saw_total = True
            elif fields["套餐"] and fields["单品名称"]:
                stores.add(fields["门店"])
                count += 1
            else:
                raise ValueError(f"第 {number} 行缺少套餐名或单品名。")
            try:
                if not all(Decimal(fields[key]).is_finite() for key in AMOUNT_HEADERS):
                    raise InvalidOperation
            except InvalidOperation:
                raise ValueError(f"第 {number} 行的销量或金额无效。") from None
        if not count:
            raise ValueError("工作簿中没有子菜销售明细。")
        if requested_stores and stores - requested_stores:
            raise ValueError("工作簿包含请求范围外的门店。")
        return {"file": str(path.resolve()), "businessDate": business_day.isoformat(),
                "rowCount": count, "storeCount": len(stores), "storesObserved": sorted(stores),
                "requestedStoresWithoutRows": sorted(requested_stores - stores)}
    finally:
        workbook.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    parser.add_argument("--date", type=date.fromisoformat, required=True)
    parser.add_argument("--store", action="append", default=[])
    args = parser.parse_args()
    try:
        result = verify(args.file, args.date, set(args.store))
    except (ValueError, OSError, BadZipFile, InvalidFileException) as error:
        parser.exit(1, f"校验未通过。{error}\n")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
