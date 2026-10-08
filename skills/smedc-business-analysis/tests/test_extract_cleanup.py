import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import run_business_report  # noqa: E402
from report_common import cleanup_partition_extracts
import partition_download_plan as planner


class ExtractCleanupTests(unittest.TestCase):
    def test_shared_bundle_cleanup_releases_only_last_report(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory = root / "smedc-partition-extracts" / "extract-shared"
            directory.mkdir(parents=True)
            extract = planner.make_extract({"dataset": "business", "enterpriseName": "企业", "startDate": "20240201", "endDate": "20240229"})
            index = planner.merge_download_plans([{"reportId": name, "extracts": [extract]} for name in ("one", "two")])
            index["extracts"][0]["downloadState"] = {"status": "succeeded", "localDirectory": str(directory)}
            ledger = root / "index.json"
            planner.save_json(ledger, index)
            bundle = root / "bundle.json"
            for name in ("one", "two"):
                bundle.write_text(json.dumps({"sharedDownload": {"indexPath": str(ledger), "reportId": name}, "partitionExtractDirectories": [str(directory)]}))
                cleanup_partition_extracts(bundle)
                self.assertEqual(directory.exists(), name == "one")

    def test_shared_bundle_missing_or_malformed_ledger_never_deletes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory = root / "smedc-partition-extracts" / "extract-keep"
            directory.mkdir(parents=True)
            bundle = root / "bundle.json"
            ledger = root / "index.json"
            for shared in (None, {}, {"indexPath": str(ledger), "reportId": "one"}):
                bundle.write_text(json.dumps({"sharedDownload": shared, "partitionExtractDirectories": [str(directory)]}))
                cleanup_partition_extracts(bundle)
                self.assertTrue(directory.exists())
            for malformed in ([], {}, {'schemaVersion': 1, 'reports': {'one': {'extractRefs': ['missing']}}, 'extracts': []}):
                ledger.write_text(json.dumps(malformed))
                cleanup_partition_extracts(bundle)
                self.assertTrue(directory.exists())

    def test_shared_cleanup_validates_all_paths_before_deleting_any(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            valid = root / 'smedc-partition-extracts' / 'extract-valid'
            unsafe = root / 'keep'
            valid.mkdir(parents=True)
            unsafe.mkdir()
            extracts = [planner.make_extract({'dataset': 'business', 'enterpriseName': '企业', 'startDate': day, 'endDate': day}) for day in ('20240201', '20240202')]
            index = planner.merge_download_plans([{'reportId': 'one', 'extracts': extracts}])
            by_id = {extract['id']: extract for extract in index['extracts']}
            for extract_id, directory in zip(index['reports']['one']['extractRefs'], (valid, unsafe)):
                by_id[extract_id]['downloadState'] = {'status': 'succeeded', 'localDirectory': str(directory)}
            ledger = root / 'index.json'
            planner.save_json(ledger, index)
            bundle = root / 'bundle.json'
            bundle.write_text(json.dumps({'sharedDownload': {'indexPath': str(ledger), 'reportId': 'one'}, 'partitionExtractDirectories': [str(valid)]}))
            cleanup_partition_extracts(bundle)
            self.assertTrue(valid.exists())
            self.assertTrue(unsafe.exists())

    def test_runner_failure_removes_only_launcher_extract_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary) / "report-run"
            run_dir.mkdir()
            marker = run_dir / "keep.txt"
            marker.write_text("keep", encoding="utf-8")
            extract = Path(temporary) / "smedc-partition-extracts" / "extract-failure"
            extract.mkdir(parents=True)
            (extract / "partition.csv").write_text("header\nvalue\n", encoding="utf-8")
            bundle = run_dir / "bundle.json"
            bundle.write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "report": {"type": "diagnosis"},
                        "notices": [],
                        "resultsByJobId": {},
                        "partitionExtractDirectories": [str(extract)],
                    }
                ),
                encoding="utf-8",
            )

            argv = [
                "run_business_report.py",
                "--bundle",
                str(bundle),
                "--output-dir",
                str(run_dir / "facts"),
                "--report",
                str(run_dir / "report.html"),
            ]
            with patch.object(sys, "argv", argv), patch.object(run_business_report, "profile", side_effect=RuntimeError("forced")):
                self.assertEqual(run_business_report.main(), 2)

            self.assertFalse(extract.exists())
            self.assertTrue(run_dir.exists())
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep")


if __name__ == "__main__":
    unittest.main()
