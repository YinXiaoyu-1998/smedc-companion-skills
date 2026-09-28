import csv
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "load_partition_extract.py"
REGISTRY = ROOT / "tests" / "fixtures" / "registry_response.json"


class PartitionExtractTests(unittest.TestCase):
    def test_store_name_filter_applies_to_business_and_dishes_before_aggregation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            responses = run_dir / "responses"
            extracts = []
            jobs = []
            cases = (
                ("business", ["营业日期", "门店名称", "订单营业收入"], "门店名称", "订单营业收入", "order_revenue"),
                ("dishes", ["营业日", "门店", "菜品收入"], "门店", "菜品收入", "dish_revenue"),
            )
            for dataset, headers, store_column, amount_column, amount_field in cases:
                directory = run_dir / "smedc-partition-extracts" / f"extract-{dataset}"
                directory.mkdir(parents=True)
                files = []
                for index, store in enumerate(("示例品牌一店", "其他品牌二店"), start=1):
                    path = directory / f"store-{index}.csv"
                    with path.open("w", encoding="utf-8", newline="") as handle:
                        writer = csv.DictWriter(handle, fieldnames=headers)
                        writer.writeheader()
                        writer.writerow({headers[0]: "2026-07-25", store_column: store, amount_column: str(index * 100)})
                    payload = path.read_bytes()
                    files.append({
                        "fileName": path.name, "businessDate": "2026-07-25", "storeId": f"00{index}",
                        "storeName": store, "rowCount": 1, "byteSize": len(payload),
                        "checksumSha256": hashlib.sha256(payload).hexdigest(),
                    })
                response = {
                    "localDirectory": str(directory), "dataset": dataset, "enterpriseName": "示例企业",
                    "startDate": "2026-07-25", "endDate": "2026-07-31", "partitionCount": 2,
                    "totalRowCount": 2, "files": [item["fileName"] for item in files],
                }
                (directory / "manifest.json").write_text(
                    json.dumps({**response, "files": files}, ensure_ascii=False), encoding="utf-8"
                )
                response_file = responses / "partition-extracts" / f"{dataset}_1.json"
                response_file.parent.mkdir(parents=True, exist_ok=True)
                response_file.write_text(json.dumps(response, ensure_ascii=False), encoding="utf-8")
                extracts.append({
                    "id": f"{dataset}_extract_1", "tool": "download_structured_partitions",
                    "input": {"dataset": dataset, "enterpriseName": "示例企业", "startDate": "20260725", "endDate": "20260731"},
                    "outputFile": f"partition-extracts/{dataset}_1.json",
                })
                jobs.append({
                    "id": f"{dataset}_totals", "tool": "local_partition_aggregate",
                    "outputFile": f"query-results/{dataset}_totals.json",
                    "input": {
                        "dataset": dataset,
                        "filter": {"field": "business_date", "op": "between", "value": ["2026-07-25", "2026-07-31"]},
                        "groupBy": ["store_name"],
                        "aggregates": [{"op": "sum", "field": amount_field, "as": amount_field}],
                    },
                })
            manifest_path = run_dir / "query_manifest.json"
            manifest_path.write_text(json.dumps({
                "schemaVersion": 1, "report": {"storeNameContains": ["示例品牌"]},
                "extracts": extracts, "jobs": jobs,
            }, ensure_ascii=False), encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, str(SCRIPT), "--manifest", str(manifest_path),
                 "--registry-response", str(REGISTRY), "--responses-dir", str(responses)],
                cwd=ROOT, text=True, capture_output=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            for dataset, _, _, _, amount_field in cases:
                rows = json.loads((responses / "query-results" / f"{dataset}_totals.json").read_text(encoding="utf-8"))["rows"]
                self.assertEqual(rows, [{"store_name": "示例品牌一店", amount_field: 100}])

    def test_loads_launcher_csv_and_materializes_local_aggregate_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            extract = run_dir / "smedc-partition-extracts" / "extract-business"
            extract.mkdir(parents=True)
            csv_path = extract / "store-day.csv"
            with csv_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["营业日期", "门店名称", "订单营业收入", "开台率", "桌台数x营业天数"])
                writer.writeheader()
                writer.writerows(
                    [
                        {"营业日期": "2026-07-25", "门店名称": "示例一店", "订单营业收入": "100.25", "开台率": "0.5", "桌台数x营业天数": "2"},
                        {"营业日期": "2026-07-25", "门店名称": "示例一店", "订单营业收入": "20.75", "开台率": "0.8", "桌台数x营业天数": "3"},
                    ]
                )
            payload = csv_path.read_bytes()
            local_manifest = {
                "dataset": "business",
                "enterpriseName": "示例企业",
                "startDate": "2026-07-25",
                "endDate": "2026-07-31",
                "partitionCount": 1,
                "totalRowCount": 2,
                "files": [
                    {
                        "fileName": csv_path.name,
                        "businessDate": "2026-07-25",
                        "storeId": "001",
                        "storeName": "示例一店",
                        "rowCount": 2,
                        "byteSize": len(payload),
                        "checksumSha256": hashlib.sha256(payload).hexdigest(),
                    }
                ],
            }
            (extract / "manifest.json").write_text(json.dumps(local_manifest, ensure_ascii=False), encoding="utf-8")

            responses = run_dir / "responses"
            response_file = responses / "partition-extracts" / "business_1.json"
            response_file.parent.mkdir(parents=True)
            response_file.write_text(
                json.dumps(
                    {
                        "localDirectory": str(extract),
                        "dataset": "business",
                        "enterpriseName": "示例企业",
                        "startDate": "2026-07-25",
                        "endDate": "2026-07-31",
                        "partitionCount": 1,
                        "totalRowCount": 2,
                        "files": [csv_path.name],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            manifest = {
                "schemaVersion": 1,
                "extracts": [
                    {
                        "id": "business_extract_1",
                        "tool": "download_structured_partitions",
                        "input": {"dataset": "business", "enterpriseName": "示例企业", "startDate": "20260725", "endDate": "20260731"},
                        "outputFile": "partition-extracts/business_1.json",
                    }
                ],
                "jobs": [
                    {
                        "id": "business_current_store_totals",
                        "tool": "local_partition_aggregate",
                        "module": "coreBusiness",
                        "outputFile": "query-results/business_current_store_totals.json",
                        "input": {
                            "dataset": "business",
                            "filter": {"field": "business_date", "op": "between", "value": ["2026-07-25", "2026-07-31"]},
                            "groupBy": ["store_name"],
                            "aggregates": [
                                {"op": "sum", "field": "order_revenue", "as": "order_revenue"},
                                {"op": "weightedAvg", "field": "open_rate", "weightField": "table_days", "as": "weighted_open_rate"},
                            ],
                            "sort": [{"field": "store_name", "direction": "asc"}],
                            "page": {"limit": 200},
                        },
                    }
                ],
            }
            manifest_path = run_dir / "query_manifest.json"
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

            completed = subprocess.run(
                [sys.executable, str(SCRIPT), "--manifest", str(manifest_path), "--registry-response", str(REGISTRY), "--responses-dir", str(responses)],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            result = json.loads((responses / "query-results" / "business_current_store_totals.json").read_text(encoding="utf-8"))
            self.assertEqual(result["rows"], [{"store_name": "示例一店", "order_revenue": 121, "weighted_open_rate": 0.68}])


if __name__ == "__main__":
    unittest.main()
