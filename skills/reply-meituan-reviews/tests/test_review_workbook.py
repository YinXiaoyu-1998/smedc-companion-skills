"""Exercise the real host workbook exporter when its bundled libraries are supplied."""
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import openpyxl

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "review_workbook.mjs"


@unittest.skipUnless(
    os.environ.get("SMEDC_WORKBOOK_NODE_MODULES"),
    "The host artifact runtime is needed for the workbook export integration check",
)
class ReviewWorkbookExportTests(unittest.TestCase):
    def test_second_precision_survives_native_date_export(self):
        times = [
            "2025-05-13T12:11:54+08:00",
            "2025-05-14T12:56:22+08:00",
            "2025-05-15T20:16:06+08:00",
            "2025-05-16T15:26:28+08:00",
        ]
        records = [
            dict(
                reviewerName="合成顾客",
                storeName="合成门店",
                enterpriseName="合成企业",
                source="美团评价",
                sheetStatus="未回复无正文",
                content=None,
                scores={"总评": 5},
                reviewedAt=value,
            )
            for value in times
        ]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            builder = root / SCRIPT.name
            shutil.copyfile(SCRIPT, builder)
            (root / "node_modules").symlink_to(
                Path(os.environ["SMEDC_WORKBOOK_NODE_MODULES"]), target_is_directory=True
            )
            inputs, output, previews = root / "records.json", root / "review.xlsx", root / "previews"
            inputs.write_text(json.dumps(records, ensure_ascii=False))
            result = subprocess.run(
                [shutil.which("node"), str(builder), str(inputs), str(output), str(previews)],
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            workbook = openpyxl.load_workbook(output)
            self.assertEqual(workbook.sheetnames, ["评价审阅表"])
            self.assertEqual(workbook.active.max_column, 9)
            for row, value in enumerate(times, 2):
                cell = workbook.active.cell(row, 5)
                self.assertIsInstance(cell.value, datetime)
                self.assertEqual(cell.value, datetime.fromisoformat(value).replace(tzinfo=None))
                self.assertIn("+08:00", cell.number_format)
                self.assertEqual(workbook.active.cell(row, 4).value, 5)
            workbook.close()
            self.assertTrue((previews / "preview-1.png").is_file())
