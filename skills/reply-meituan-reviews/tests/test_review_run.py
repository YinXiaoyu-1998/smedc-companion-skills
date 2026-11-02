import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import openpyxl

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "review_run.py"


class ReviewRunCliTests(unittest.TestCase):
    def test_original_export_parser_preserves_existing_reply_and_pure_rating(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            run = root / "run-demo"
            run.mkdir()
            (run / "run.json").write_text(
                json.dumps(
                    {
                        "runId": "run-demo",
                        "startDate": "2026-11-01",
                        "endDate": "2026-11-02",
                        "startedAt": "2026-11-02T00:00:00+08:00",
                    }
                )
            )
            source = run / "export.xlsx"
            book = openpyxl.Workbook()
            sheet = book.active
            sheet.append(
                [
                    "评价ID",
                    "用户昵称",
                    "评分",
                    "评价",
                    "门店",
                    "评价时间",
                    "评价展示平台",
                    "商家回应",
                    "回应&盖楼内容",
                ]
            )
            sheet.append(
                [
                    "123",
                    "匿名",
                    5,
                    None,
                    "来源门店",
                    "2026-11-01 12:00:00",
                    "美团",
                    "否",
                    None,
                ]
            )
            sheet.append(
                [
                    "124",
                    "匿名二",
                    4,
                    "不错",
                    "来源门店",
                    "2026-11-01 13:00:00",
                    "美团",
                    "是",
                    "【2026-11-01 14:00:00】商家:谢谢光临",
                ]
            )
            book.save(source)
            task = root / "task.json"
            task.write_text(
                json.dumps(
                    {
                        "enterpriseName": "合成企业",
                        "mappings": [
                            {
                                "targetStoreName": "标准门店",
                                "sourceStores": [{"storeName": "来源门店"}],
                            }
                        ],
                        "replyWhitelist": [],
                        "ignoredRecords": [],
                        "sourceIdentityMappings": [
                            {
                                "source": {
                                    "product": "meituan_reviews",
                                    "accountRef": "account-demo",
                                    "channel": "meituan",
                                    "sourceStoreId": "poi-demo",
                                    "sourceStoreName": "来源门店",
                                },
                                "storeName": "标准门店",
                            }
                        ],
                    }
                )
            )
            (run / "exports.json").write_text(
                json.dumps(
                    [
                        {
                            "path": str(source),
                            "poiId": "poi-demo",
                            "source": "美团评价",
                            "sourceStoreName": "来源门店",
                            "storeName": "标准门店",
                            "snapshotAt": "2026-11-02T00:00:00+08:00",
                            "pageCount": 2,
                            "sourceIdentity": {
                                "product": "meituan_reviews",
                                "accountRef": "account-demo",
                                "channel": "meituan",
                                "sourceStoreId": "poi-demo",
                                "sourceStoreName": "来源门店",
                            },
                        }
                    ]
                )
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "parse",
                    "--run-dir",
                    str(run),
                    "--task",
                    str(task),
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            records = json.loads((run / "records.json").read_text())
            self.assertEqual(len(records), 2)
            self.assertIsNone(records[0]["content"])
            self.assertIsNone(records[0]["merchantReply"])
            self.assertEqual(records[0]["feedbackId"], "feedback-123")
            self.assertEqual(records[0]["storeName"], "标准门店")
            self.assertEqual(records[1]["merchantReply"], "谢谢光临")
            self.assertEqual(records[1]["sheetStatus"], "已回复")
            self.assertFalse(records[1]["needsDraft"])
            self.assertEqual(sum(bool(r["issues"]) for r in records), 0)

            exports = json.loads((run / "exports.json").read_text())
            exports[0]["sourceIdentity"]["accountRef"] = "another-account"
            (run / "exports.json").write_text(json.dumps(exports))
            rejected = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "parse",
                    "--run-dir",
                    str(run),
                    "--task",
                    str(task),
                ],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("namespace", rejected.stderr)
