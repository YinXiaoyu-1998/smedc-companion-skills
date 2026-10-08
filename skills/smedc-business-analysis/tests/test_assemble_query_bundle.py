import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(ROOT / "scripts"))
from assemble_query_bundle import BundleError, assemble_bundle, load_config  # noqa: E402


def aggregate_job(tool: str = "local_partition_aggregate") -> dict:
    return {
        "id": "business_current_store_totals",
        "tool": tool,
        "module": "coreBusiness",
        "outputFile": "query-results/business_current_store_totals.json",
        "input": {
            "dataset": "business",
            "filter": {"field": "business_date", "op": "between", "value": ["2026-07-25", "2026-07-31"]},
            "groupBy": ["store_name"],
            "aggregates": [{"op": "sum", "field": "order_revenue", "as": "order_revenue"}],
            "sort": [{"field": "store_name", "direction": "asc"}],
            "page": {"limit": 200},
        },
    }


def manifest(job: dict) -> dict:
    return {
        "schemaVersion": 1,
        "metadata": {"organization_name": "示例餐饮管理有限公司"},
        "report": {"type": "weekly", "windows": {}},
        "coverage": {},
        "notices": [],
        "extracts": [
            {
                "id": "business_extract_1",
                "tool": "download_structured_partitions",
                "input": {"dataset": "business", "enterpriseName": "示例企业", "startDate": "20260725", "endDate": "20260731"},
                "outputFile": "partition-extracts/business_1.json",
            }
        ],
        "jobs": [job],
    }


class AssembleQueryBundleTests(unittest.TestCase):
    def test_assembles_local_result_and_preserves_extract_for_finally_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            responses = Path(temporary)
            job = aggregate_job()
            result_path = responses / job["outputFile"]
            result_path.parent.mkdir(parents=True)
            result_path.write_text(
                json.dumps({"dataset": "business", "mode": "aggregate", "query": job["input"], "rows": [{"store_name": "示例一店", "order_revenue": 121}], "nextCursor": None}, ensure_ascii=False),
                encoding="utf-8",
            )
            extract_path = responses / "partition-extracts" / "business_1.json"
            extract_path.parent.mkdir(parents=True)
            extract_path.write_text(json.dumps({"localDirectory": "/tmp/smedc-partition-extracts/extract-abc"}), encoding="utf-8")

            bundle = assemble_bundle(manifest(job), responses, load_config())
            self.assertEqual(bundle["metadata"]["organization_name"], "示例餐饮管理有限公司")
            self.assertEqual(bundle["resultsByJobId"][job["id"]]["rows"][0]["order_revenue"], 121)
            self.assertEqual(bundle["partitionExtractDirectories"], ["/tmp/smedc-partition-extracts/extract-abc"])
            self.assertEqual(bundle["jobs"][0]["tool"], "local_partition_aggregate")

    def test_shared_reference_survives_assembly_and_failed_download_stops_it(self):
        import partition_download_plan as planner
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = manifest(aggregate_job())
            # Legacy extract fixtures may omit transport fields; shared references still propagate.
            index = {'schemaVersion': 1, 'reports': {'one': {'extractRefs': ['business_extract_1']}}, 'extracts': data['extracts']}
            ledger = root / 'index.json'
            planner.save_json(ledger, index)
            data['sharedDownload'] = {'indexPath': str(ledger), 'reportId': 'one'}
            bundle = assemble_bundle(data, root, load_config())
            self.assertEqual(bundle['sharedDownload'], data['sharedDownload'])
            extract_path = root / data['extracts'][0]['outputFile']
            extract_path.parent.mkdir(parents=True)
            extract_path.write_text(json.dumps({'isError': True, 'result': {'localDirectory': '/tmp/smedc-partition-extracts/extract-ignore'}}))
            with self.assertRaisesRegex(BundleError, 'failed'):
                assemble_bundle(data, root, load_config())

    def test_query_pages_still_concatenate_and_require_a_null_final_cursor(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            responses = Path(temporary)
            job = aggregate_job("query_structured_dataset")
            job["input"]["dataset"] = "dish_catalog"
            job["input"] = {
                "dataset": "dish_catalog",
                "select": ["dish_name"],
                "sort": [{"field": "dish_name", "direction": "asc"}],
                "page": {"limit": 1},
            }
            result_path = responses / job["outputFile"]
            result_path.parent.mkdir(parents=True)
            result_path.write_text(
                json.dumps(
                    [
                        {"dataset": "dish_catalog", "mode": "detail", "query": job["input"], "rows": [{"dish_name": "A"}], "nextCursor": "next"},
                        {"dataset": "dish_catalog", "mode": "detail", "query": job["input"], "rows": [{"dish_name": "B"}], "nextCursor": None},
                    ]
                ),
                encoding="utf-8",
            )
            data = manifest(job)
            data["extracts"] = []
            bundle = assemble_bundle(data, responses, load_config())
            self.assertEqual([row["dish_name"] for row in bundle["resultsByJobId"][job["id"]]["rows"]], ["A", "B"])

    def test_unknown_job_tool_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            job = aggregate_job("unknown")
            with self.assertRaisesRegex(BundleError, "unsupported tool"):
                assemble_bundle(manifest(job), Path(temporary), load_config())


if __name__ == "__main__":
    unittest.main()
