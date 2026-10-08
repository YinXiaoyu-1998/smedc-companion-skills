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
sys.path.insert(0, str(ROOT / "scripts"))
import load_partition_extract as loader

REGISTRY = ROOT / "tests" / "fixtures" / "registry_response.json"


class PartitionExtractTests(unittest.TestCase):
    def save_download(self, root, responses, extract, rows, suffix, strings=False):
        directory = root / "smedc-partition-extracts" / f"extract-{suffix}"
        directory.mkdir(parents=True)
        files = []
        for day, amount in rows:
            path = directory / f"{day}.csv"
            path.write_text(f"营业日期,门店名称,订单营业收入\n{day},示例一店,{amount}\n", encoding="utf-8")
            payload = path.read_bytes()
            files.append({"fileName": path.name, "storeId": "001", "businessDate": day, "storeName": "示例一店", "rowCount": "1" if strings else 1, "byteSize": str(len(payload)) if strings else len(payload), "checksumSha256": hashlib.sha256(payload).hexdigest()})
        selector = extract["input"]
        response = {"dataset": selector["dataset"], "enterpriseName": selector["enterpriseName"], "startDate": loader.compact_to_iso(selector["startDate"]), "endDate": loader.compact_to_iso(selector["endDate"]), "partitionCount": str(len(files)) if strings else len(files), "totalRowCount": str(len(files)) if strings else len(files), "localDirectory": str(directory), "files": [f["fileName"] for f in files]}
        (directory / "manifest.json").write_text(json.dumps({**response, "files": files}), encoding="utf-8")
        output = responses / extract["outputFile"]
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(response), encoding="utf-8")
        return response

    def aggregate_manifest(self, extracts):
        return {"report": {}, "extracts": extracts, "jobs": [{"id": "total", "tool": "local_partition_aggregate", "outputFile": "query-results/total.json", "input": {"dataset": "business", "filter": {"field": "business_date", "op": "between", "value": ["2024-02-01", "2024-02-02"]}, "groupBy": [], "aggregates": [{"op": "sum", "field": "order_revenue", "as": "revenue"}]}}]}

    def test_null_id_overlapping_extracts_materialize_and_reject_conflicts(self):
        import partition_download_plan as planner
        with tempfile.TemporaryDirectory() as temporary:
            root, responses = Path(temporary), Path(temporary)/'responses'
            extracts = [planner.make_extract({'dataset': 'business', 'enterpriseName': '企业',
                'startDate': '20240201', 'endDate': end}) for end in ('20240201', '20240202')]
            manifests = []
            for i, extract in enumerate(extracts):
                response = self.save_download(root, responses, extract, [('2024-02-01', 10)], str(i))
                path = Path(response['localDirectory'])/'manifest.json'
                metadata = json.loads(path.read_text())
                metadata['files'][0]['storeId'] = None
                # Same display name, distinct stable file/store identity: keep both stores.
                second = {**metadata['files'][0], 'fileName': 'other-store.csv'}
                (path.parent/second['fileName']).write_bytes((path.parent/metadata['files'][0]['fileName']).read_bytes())
                metadata['files'].append(second)
                metadata['partitionCount'] = metadata['totalRowCount'] = 2
                response.update({'partitionCount': 2, 'totalRowCount': 2, 'files': [f['fileName'] for f in metadata['files']]})
                (responses/extract['outputFile']).write_text(json.dumps(response))
                path.write_text(json.dumps(metadata))
                manifests.append((path, metadata))
            loader.materialize(self.aggregate_manifest(extracts), json.loads(REGISTRY.read_text()), responses)
            self.assertEqual(json.loads((responses/'query-results/total.json').read_text())['rows'], [{'revenue': 20}])
            path, metadata = manifests[1]
            csv_file = path.parent/metadata['files'][0]['fileName']
            csv_file.write_text(csv_file.read_text().replace(',10', ',20'))
            metadata['files'][0]['checksumSha256'] = hashlib.sha256(csv_file.read_bytes()).hexdigest()
            path.write_text(json.dumps(metadata))
            with self.assertRaisesRegex(loader.ExtractError, 'conflicting checksums'):
                loader.materialize(self.aggregate_manifest(extracts), json.loads(REGISTRY.read_text()), responses)

    def test_split_shared_failed_parent_materializes_only_children(self):
        import partition_download_plan as planner
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            responses = root / "responses"
            parent = planner.make_extract({"dataset": "business", "enterpriseName": "企业", "startDate": "20240201", "endDate": "20240202"})
            old = self.aggregate_manifest([parent])
            old['reportId'] = 'one'
            index = planner.merge_download_plans([old, {**old, 'reportId': 'two'}])
            parent = index['extracts'][0]
            self.save_download(root, responses, parent, [('2024-02-01', 900)], 'parent')
            parent['downloadState'] = {'status': 'failed'}
            index = planner.replace_failed_extract(index, parent['id'])
            for child, day, amount in zip(sorted(index['extracts'], key=lambda extract: extract['input']['startDate']), ('2024-02-01', '2024-02-02'), (10, 20)):
                response = self.save_download(root, responses, child, [(day, amount)], day, True)
                planner.record_download_result(index, child['id'], response)
            ledger = root / 'index.json'
            planner.save_json(ledger, index)
            old['sharedDownload'] = {'indexPath': str(ledger), 'reportId': 'one'}
            loader.materialize(old, json.loads(REGISTRY.read_text()), responses)
            self.assertEqual(json.loads((responses / index['reports']['one']['jobs'][0]['outputFile']).read_text())['rows'], [{'revenue': 30}])

    def test_verified_success_reuse_materializes_without_redownload_or_new_response_file(self):
        import partition_download_plan as planner
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            responses = root / 'responses'
            extract = planner.make_extract({'dataset': 'business', 'enterpriseName': '企业', 'startDate': '20240201', 'endDate': '20240202'})
            response = self.save_download(root, responses, extract, [('2024-02-01', 10)], 'reuse')
            extract['downloadState'] = {'status': 'succeeded', 'localDirectory': response['localDirectory'], 'response': response}
            old = self.aggregate_manifest([extract])
            index = planner.merge_download_plans([{**old, 'reportId': 'one'}, {**old, 'reportId': 'two'}])
            self.assertEqual(len(index['extracts']), 1)
            (responses / extract['outputFile']).unlink()
            for report in index['reports'].values():
                loader.materialize(report, json.loads(REGISTRY.read_text()), responses)
                self.assertEqual(json.loads((responses / report['jobs'][0]['outputFile']).read_text())['rows'], [{'revenue': 10}])

    def test_partially_overlapping_plan_keeps_verified_success_and_downloads_only_tail(self):
        import partition_download_plan as planner
        with tempfile.TemporaryDirectory() as temporary:
            root, responses = Path(temporary), Path(temporary)/'responses'
            first = planner.make_extract({'dataset': 'business', 'enterpriseName': '企业', 'startDate': '20240201', 'endDate': '20240201'})
            response = self.save_download(root, responses, first, [('2024-02-01', 10)], 'success')
            first['downloadState'] = {'status': 'succeeded', 'localDirectory': response['localDirectory'], 'response': response}
            second = planner.make_extract({**first['input'], 'endDate': '20240202'})
            index = planner.merge_download_plans([{**self.aggregate_manifest([first]), 'reportId': 'one'}, {**self.aggregate_manifest([second]), 'reportId': 'two'}])
            self.assertEqual(len(index['extracts']), 2)
            kept = next(e for e in index['extracts'] if e['id'] == first['id'])
            self.assertEqual(kept['downloadState'], first['downloadState'])
            self.assertEqual(set(kept['consumers']), {'one', 'two'})
            tail = next(e for e in index['extracts'] if e['id'] != first['id'])
            self.assertEqual((tail['input']['startDate'], tail['input']['endDate']), ('20240202', '20240202'))
            planner.record_download_result(index, tail['id'], self.save_download(root, responses, tail, [('2024-02-02', 20)], 'tail'))
            for name, total in [('one', 10), ('two', 30)]:
                report = index['reports'][name]
                loader.materialize(report, json.loads(REGISTRY.read_text()), responses)
                self.assertEqual(json.loads((responses/report['jobs'][0]['outputFile']).read_text())['rows'], [{'revenue': total}])

    def test_two_shared_reports_keep_separate_results_and_assemble_independently(self):
        import partition_download_plan as planner
        from assemble_query_bundle import assemble_bundle, load_config
        with tempfile.TemporaryDirectory() as temporary:
            root, responses = Path(temporary), Path(temporary) / 'responses'
            extract = planner.make_extract({'dataset': 'business', 'enterpriseName': '企业', 'startDate': '20240201', 'endDate': '20240202'})
            response = self.save_download(root, responses, extract, [('2024-02-01', 10), ('2024-02-02', 20)], 'independent')
            first = self.aggregate_manifest([extract])
            first.update({'schemaVersion': 1, 'reportId': 'one', 'coverage': {}, 'notices': []})
            first['jobs'][0]['module'] = 'coreBusiness'
            second = json.loads(json.dumps(first))
            second['reportId'] = 'two'
            second['jobs'][0]['input']['filter']['value'][1] = '2024-02-01'
            index = planner.merge_download_plans([first, second])
            planner.record_download_result(index, index['extracts'][0]['id'], response)
            ledger = root / 'index.json'
            planner.save_json(ledger, index)
            for report_id, report in index['reports'].items():
                report['sharedDownload'] = {'indexPath': str(ledger), 'reportId': report_id}
                loader.materialize(report, json.loads(REGISTRY.read_text()), responses)
            for report_id, report in index['reports'].items():
                bundle = assemble_bundle(report, responses, load_config())
                self.assertEqual(bundle['resultsByJobId']['total']['rows'], [{'revenue': 30 if report_id == 'one' else 10}])
                self.assertEqual(bundle['sharedDownload']['reportId'], report_id)

    def test_duplicate_partition_identity_does_not_double_count(self):
        import partition_download_plan as planner
        with tempfile.TemporaryDirectory() as temporary:
            root, extracts = Path(temporary), []
            responses = root / 'responses'
            for suffix in ('one', 'two'):
                extract = planner.make_extract({'dataset': 'business', 'enterpriseName': '企业', 'startDate': '20240201', 'endDate': '20240202'}, suffix)
                self.save_download(root, responses, extract, [('2024-02-01', 10)], suffix)
                extracts.append(extract)
            loader.materialize(self.aggregate_manifest(extracts), json.loads(REGISTRY.read_text()), responses)
            self.assertEqual(json.loads((responses / 'query-results/total.json').read_text())['rows'], [{'revenue': 10}])

    def test_legal_string_counts_zero_and_row_mismatch(self):
        import partition_download_plan as planner
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            responses = root / 'responses'
            extract = planner.make_extract({'dataset': 'business', 'enterpriseName': '企业', 'startDate': '20240201', 'endDate': '20240202'})
            response = self.save_download(root, responses, extract, [], 'zero', True)
            manifest = self.aggregate_manifest([extract])
            loader.materialize(manifest, json.loads(REGISTRY.read_text()), responses)
            self.assertEqual(json.loads((responses / 'query-results/total.json').read_text())['rows'], [])
            # Non-empty string counts are consumed without requiring a new Launcher layout.
            response = self.save_download(root, responses, extract, [('2024-02-01', 10)], 'strings', True)
            loader.materialize(manifest, json.loads(REGISTRY.read_text()), responses)
            self.assertEqual(json.loads((responses / 'query-results/total.json').read_text())['rows'], [{'revenue': 10}])
            directory = Path(response['localDirectory'])
            local = json.loads((directory / 'manifest.json').read_text())
            local['files'][0]['rowCount'] = '2'
            local['totalRowCount'] = '2'
            response['totalRowCount'] = '2'
            (directory / 'manifest.json').write_text(json.dumps(local))
            (responses / extract['outputFile']).write_text(json.dumps(response))
            with self.assertRaisesRegex(ValueError, 'row count mismatch'):
                loader.materialize(manifest, json.loads(REGISTRY.read_text()), responses)

    def test_decimal_count_validation_rejects_invalid_and_accepts_strings(self):
        self.assertEqual(loader.metadata_count("12", "count"), 12)
        for value in (-1, True, "-1", "1.0", "1e3", 1.5, " 1", ""):
            with self.subTest(value=value), self.assertRaises(ValueError):
                loader.metadata_count(value, "count")

    def test_service_filtered_rows_are_validated_instead_of_hidden(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary).resolve()
            path = directory / "day.csv"
            path.write_text("营业日期,门店名称,订单营业收入\n2024-02-01,范围外,10\n", encoding="utf-8")
            payload = path.read_bytes()
            metadata = {"fileName": path.name, "businessDate": "2024-02-01", "storeId": "1", "storeName": "范围外", "rowCount": "1", "byteSize": str(len(payload)), "checksumSha256": hashlib.sha256(payload).hexdigest()}
            fields = {"business_date": {"canonicalName": "business_date", "sourceColumn": "营业日期", "type": "string"}, "store_name": {"canonicalName": "store_name", "sourceColumn": "门店名称", "type": "string"}}
            accumulator = loader.JobAccumulator({"id": "totals", "input": {"filter": {"field": "business_date", "op": "between", "value": ["2024-02-01", "2024-02-01"]}, "groupBy": [], "aggregates": []}})
            with self.assertRaisesRegex(ValueError, "storeNameContains"):
                loader.process_file("business", directory, metadata, fields, [accumulator], ["一店"], True)
            metadata["storeName"] = "一店"
            with self.assertRaisesRegex(ValueError, "storeNameContains"):
                loader.process_file("business", directory, metadata, fields, [accumulator], ["一店"], True)

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
