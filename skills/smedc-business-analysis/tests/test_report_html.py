import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
ORG_NAME = "示例餐饮管理有限公司"
ORG_ERROR = "SMEDC account organization"


def run_script(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )


def assert_self_contained(testcase: unittest.TestCase, html: str) -> None:
    testcase.assertNotRegex(html, r"<script[^>]+src=", "report must not load external scripts")
    testcase.assertNotRegex(html, r"<link[^>]+stylesheet", "report must not load external stylesheets")
    testcase.assertNotRegex(html, r"https?://", "report must not depend on network URLs")
    testcase.assertIn("<style>", html)
    testcase.assertIn("<script>", html)
    testcase.assertIn('type="application/json"', html)
    testcase.assertRegex(html, r"<table[^>]+aria-label=")
    testcase.assertIn('scope="col"', html)
    payload_match = re.search(r'<script type="application/json" id="report-data">(.*?)</script>', html, re.DOTALL)
    testcase.assertIsNotNone(payload_match, "report must embed its source payload as JSON")
    json.loads(payload_match.group(1))
    testcase.assertNotIn(str(ROOT), html, "report must not embed workspace-local paths")


def strip_embedded_scripts(html: str) -> str:
    return re.sub(r"<script\b.*?</script>", "", html, flags=re.IGNORECASE | re.DOTALL)


def embedded_payload(html: str) -> dict:
    match = re.search(r'<script type="application/json" id="report-data">(.*?)</script>', html, re.DOTALL)
    if match is None:
        match = re.search(r'<script id="payload" type="application/json">(.*?)</script>', html, re.DOTALL)
    if match is None:
        raise AssertionError("report payload is missing")
    return json.loads(match.group(1))


class ReportHtmlTests(unittest.TestCase):
    maxDiff = None

    def render_from_profile(self, profile_script: str, render_script: str, fixture_name: str, summary_name: str) -> tuple[Path, str, dict]:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        output_dir = Path(tmp.name)
        report_path = output_dir / "report.html"

        profile = run_script(
            f"scripts/{profile_script}",
            "--bundle",
            str(FIXTURES / fixture_name),
            "--output-dir",
            str(output_dir),
        )
        self.assertEqual(profile.returncode, 0, profile.stderr)

        rendered = run_script(
            f"scripts/{render_script}",
            "--input-dir",
            str(output_dir),
            "--report",
            str(report_path),
        )
        self.assertEqual(rendered.returncode, 0, rendered.stderr)
        result = json.loads(rendered.stdout)
        self.assertEqual(Path(result["artifacts"]["report"]), report_path)
        return report_path, report_path.read_text(encoding="utf-8"), json.loads((output_dir / summary_name).read_text(encoding="utf-8"))

    def profile_to_directory(self, profile_script: str, fixture_name: str) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        output_dir = Path(tmp.name)
        profile = run_script(
            f"scripts/{profile_script}",
            "--bundle",
            str(FIXTURES / fixture_name),
            "--output-dir",
            str(output_dir),
        )
        self.assertEqual(profile.returncode, 0, profile.stderr)
        return output_dir

    def corrupt_summary_organization(self, output_dir: Path, summary_name: str, value: object = None, *, remove: bool = False) -> None:
        summary_path = output_dir / summary_name
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        if remove:
            summary["meta"].pop("organization_name", None)
        else:
            summary["meta"]["organization_name"] = value
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    def test_diagnosis_report_renders_business_charts_without_technical_provenance(self) -> None:
        _, html, summary = self.render_from_profile(
            "profile_business_data.py",
            "generate_business_report_html.py",
            "diagnosis_bundle.json",
            "analysis_summary.json",
        )

        assert_self_contained(self, html)
        self.assertIn("示例餐饮管理有限公司经营诊断", html)
        self.assertIn("2026-07-01", html)
        self.assertIn("2026-07-07", html)
        self.assertNotIn("doc_diagnosis_business", html)
        self.assertNotIn("OPTIONAL_MODULE_MISSING", html)
        self.assertIn("订单营业收入", html)
        self.assertIn("门店组合", html)
        self.assertIn("渠道结构", html)
        self.assertIn("会员与非会员", html)
        self.assertIn("机会池", html)
        self.assertIn("餐段机会", html)
        self.assertIn("示例一店", html)
        self.assertIn("示例二店", html)
        self.assertIn("店内销售", html)
        self.assertIn("午餐", html)
        self.assertIn("8000", html)
        self.assertEqual(summary["overall_kpis"]["net_revenue"], 8000.0)

    def test_weekly_report_renders_comparison_trend_mix_and_product_panels(self) -> None:
        _, html, summary = self.render_from_profile(
            "profile_weekly_data.py",
            "generate_weekly_report_html.py",
            "weekly_bundle.json",
            "weekly_meeting_summary.json",
        )

        assert_self_contained(self, html)
        self.assertIn("<h1>示例餐饮管理有限公司周经营会报</h1>", html)
        self.assertNotIn("示例餐饮管理有限公司周会经营报告", html)
        self.assertIn("2026-07-20", html)
        self.assertIn("2026-07-26", html)
        self.assertIn("趋势", html)
        self.assertIn("门店横向对比", html)
        self.assertIn("堂食与外卖", html)
        self.assertIn("时段归因", html)
        self.assertIn("档口占比", html)
        self.assertIn("产品万元销量（订单营业收入）", html)
        self.assertIn("产品万元销量（营业额）", html)
        self.assertIn("牛肉面", html)
        self.assertIn("面档", html)
        self.assertIn("明星门店", html)
        self.assertNotIn("OPTIONAL_MODULE_MISSING", html)
        self.assertIn('id="trendStoreSelect"', html)
        self.assertIn('id="stallMixPie"', html)
        self.assertIn('id="hourlyRevenueBar"', html)
        self.assertIn('id="productSalesPer10kSearch"', html)
        self.assertIn('id="productSalesPer10kGrossSearch"', html)
        self.assertIn("查看渠道明细", html)
        self.assertEqual(summary["meta"]["report_grain"], "week")

    def test_monthly_report_renders_comparison_trend_mix_and_product_panels_without_removed_scope(self) -> None:
        _, html, summary = self.render_from_profile(
            "profile_monthly_data.py",
            "generate_monthly_report_html.py",
            "monthly_bundle.json",
            "monthly_meeting_summary.json",
        )

        assert_self_contained(self, html)
        self.assertIn("最近一年收入趋势（12 个月）", html)
        self.assertEqual(len(embedded_payload(html)["trend_entities"][0]["rows"]), 12)
        self.assertIn("<h1>示例餐饮管理有限公司月经营会报</h1>", html)
        self.assertNotIn("示例餐饮管理有限公司月会经营报告", html)
        self.assertIn("2026-07-01", html)
        self.assertIn("2026-07-31", html)
        self.assertIn("2025-07-01", html)
        self.assertIn("2025-06", html)
        self.assertIn("2026-07", html)
        self.assertIn("档口占比", html)
        self.assertIn("产品万元销量（订单营业收入）", html)
        self.assertIn("产品万元销量（营业额）", html)
        self.assertIn('id="trendStoreSelect"', html)
        self.assertIn('id="stallMixPie"', html)
        self.assertIn('id="hourlyRevenueBar"', html)
        self.assertIn('id="productSalesPer10kSearch"', html)
        forbidden = re.compile("|".join(["pro" + "fit", "monthly_" + "pro" + "fit", "利" + "润"]), re.IGNORECASE)
        self.assertNotRegex(html, forbidden)
        self.assertEqual(summary["meta"]["report_grain"], "month")

    @unittest.skipUnless(shutil.which("node"), "Node.js is needed to execute the embedded chart")
    def test_monthly_ranking_displays_the_all_store_revenue_median(self) -> None:
        _, html, _ = self.render_from_profile(
            "profile_monthly_data.py", "generate_monthly_report_html.py",
            "monthly_bundle.json", "monthly_meeting_summary.json",
        )
        # The fixture stores earn 40,000 and 20,000 yuan: median 30,000, or 3万.
        payload = embedded_payload(html)
        declarations = html.split("const data = JSON.parse", 1)[1].split("let selectedTrendKey", 1)[0]
        svg_function = html.split("function svg(", 1)[1].split("function positionTooltip", 1)[0]
        ranking = html.split("function renderBucketedRevenueRanking()", 1)[1].split("function renderGrowthBar", 1)[0]
        script = """
const chart = {appendChild(node) {this.root = node;}};
const document = {
  getElementById(id) {return id === 'report-data' ? {textContent: PAYLOAD} : chart;},
  createElementNS(_, tag) {
    return {tag, children: [], setAttribute() {}, appendChild(node) {this.children.push(node); return node;}};
  }
};
""".replace("PAYLOAD", json.dumps(json.dumps(payload, ensure_ascii=False)))
        script += "const data = JSON.parse" + declarations
        script += "function svg(" + svg_function
        script += "function renderBucketedRevenueRanking()" + ranking
        script += "renderBucketedRevenueRanking(); console.log(JSON.stringify(chart.root.children.filter(n => n.tag === 'text').map(n => n.textContent)));"
        result = subprocess.run(["node", "-e", script], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        labels = json.loads(result.stdout)
        self.assertIn("全体门店（2家）", labels)
        self.assertIn("中位数 3万", labels)

    def test_shared_trend_tooltip_keeps_dates_and_revenue_without_year_heading(self) -> None:
        for grain in ("weekly", "monthly"):
            with self.subTest(grain=grain):
                _, html, _ = self.render_from_profile(
                    f"profile_{grain}_data.py", f"generate_{grain}_report_html.py",
                    f"{grain}_bundle.json", f"{grain}_meeting_summary.json",
                )
                trend = html.split("function renderTrend() {", 1)[1].split("function ", 1)[0]
                self.assertIn("const showTrendTip = (event, pointRange, value)", trend)
                self.assertIn("tip.innerHTML = `${pointRange}<br>业务收入：${fmtWan(value)}`;", trend)
                self.assertNotIn("<strong>", trend)
                self.assertIn("title.textContent = `${pointRange} 业务收入：${fmtWan(value)}`;", html)
                self.assertIn("showTrendTip(event, pointRange, value)", html)
                self.assertIn(".textContent = currentLabel;", html)
                self.assertIn(".textContent = `${priorLabel}同期`;", html)
                self.assertIn("`${first}–${last}`", html)
                self.assertNotIn("${seriesLabel}", html.split("function renderTrend() {", 1)[1].split("function render", 1)[0])

    def test_diagnosis_renderer_rejects_company_override(self) -> None:
        output_dir = self.profile_to_directory("profile_business_data.py", "diagnosis_bundle.json")
        report_path = output_dir / "diagnosis-override.html"
        rendered = run_script(
            "scripts/generate_business_report_html.py",
            "--input-dir",
            str(output_dir),
            "--report",
            str(report_path),
            "--company",
            "伪造公司",
        )
        self.assertNotEqual(rendered.returncode, 0)
        self.assertIn("--company", rendered.stderr)
        self.assertFalse(report_path.exists())

    def test_weekly_renderer_uses_metadata_organization_title_by_default(self) -> None:
        output_dir = self.profile_to_directory("profile_weekly_data.py", "weekly_bundle.json")
        report_path = output_dir / "weekly-default.html"
        rendered = run_script("scripts/meeting_report_weekly.py", "--input-dir", str(output_dir), "--output", str(report_path))
        self.assertEqual(rendered.returncode, 0, rendered.stderr)
        html = report_path.read_text(encoding="utf-8")
        payload = embedded_payload(html)
        self.assertIn(f"<h1>{ORG_NAME}周经营会报</h1>", html)
        self.assertEqual(payload["meta"]["title"], f"{ORG_NAME}周经营会报")
        self.assertEqual(payload["meta"]["organization_name"], ORG_NAME)

    def test_weekly_renderer_accepts_nonblank_company_title_override_only_for_presentation(self) -> None:
        output_dir = self.profile_to_directory("profile_weekly_data.py", "weekly_bundle.json")
        default_report = output_dir / "weekly-default.html"
        report_path = output_dir / "weekly-override.html"
        default_rendered = run_script("scripts/meeting_report_weekly.py", "--input-dir", str(output_dir), "--output", str(default_report))
        self.assertEqual(default_rendered.returncode, 0, default_rendered.stderr)
        rendered = run_script(
            "scripts/meeting_report_weekly.py",
            "--input-dir",
            str(output_dir),
            "--output",
            str(report_path),
            "--company",
            "董事会展示名称",
        )
        self.assertEqual(rendered.returncode, 0, rendered.stderr)

        default_payload = embedded_payload(default_report.read_text(encoding="utf-8"))
        override_html = report_path.read_text(encoding="utf-8")
        override_payload = embedded_payload(override_html)

        self.assertIn("<h1>董事会展示名称周经营会报</h1>", override_html)
        self.assertEqual(override_payload["meta"]["title"], "董事会展示名称周经营会报")
        self.assertEqual(override_payload["meta"]["organization_name"], ORG_NAME)
        self.assertEqual(override_payload["meta"]["target_windows"], default_payload["meta"]["target_windows"])
        self.assertEqual(override_payload["comparison"], default_payload["comparison"])
        self.assertEqual(override_payload["trend"], default_payload["trend"])
        self.assertEqual(override_payload["availability"], default_payload["availability"])

    def test_weekly_renderer_rejects_blank_company_title_override(self) -> None:
        output_dir = self.profile_to_directory("profile_weekly_data.py", "weekly_bundle.json")
        report_path = output_dir / "weekly-blank-override.html"
        rendered = run_script(
            "scripts/meeting_report_weekly.py",
            "--input-dir",
            str(output_dir),
            "--output",
            str(report_path),
            "--company",
            "   ",
        )
        self.assertNotEqual(rendered.returncode, 0)
        self.assertIn("company", rendered.stderr.lower())
        self.assertFalse(report_path.exists())

    def test_weekly_renderer_validates_metadata_organization_even_with_company_override(self) -> None:
        invalid_values = [
            ("missing", None, True),
            ("blank", "   ", False),
            ("non_string", 123, False),
        ]
        for label, value, remove in invalid_values:
            with self.subTest(label=label):
                output_dir = self.profile_to_directory("profile_weekly_data.py", "weekly_bundle.json")
                self.corrupt_summary_organization(output_dir, "weekly_meeting_summary.json", value, remove=remove)
                report_path = output_dir / f"weekly-{label}-override.html"
                rendered = run_script(
                    "scripts/meeting_report_weekly.py",
                    "--input-dir",
                    str(output_dir),
                    "--output",
                    str(report_path),
                    "--company",
                    "董事会展示名称",
                )
                self.assertNotEqual(rendered.returncode, 0)
                self.assertIn(ORG_ERROR, rendered.stderr)
                self.assertFalse(report_path.exists())

    def test_monthly_renderer_uses_metadata_organization_title_by_default(self) -> None:
        output_dir = self.profile_to_directory("profile_monthly_data.py", "monthly_bundle.json")
        report_path = output_dir / "monthly-default.html"
        rendered = run_script("scripts/meeting_report_monthly.py", "--input-dir", str(output_dir), "--output", str(report_path))
        self.assertEqual(rendered.returncode, 0, rendered.stderr)
        html = report_path.read_text(encoding="utf-8")
        payload = embedded_payload(html)
        self.assertIn(f"<h1>{ORG_NAME}月经营会报</h1>", html)
        self.assertEqual(payload["meta"]["title"], f"{ORG_NAME}月经营会报")
        self.assertEqual(payload["meta"]["organization_name"], ORG_NAME)

    def test_monthly_renderer_accepts_nonblank_company_title_override_only_for_presentation(self) -> None:
        output_dir = self.profile_to_directory("profile_monthly_data.py", "monthly_bundle.json")
        default_report = output_dir / "monthly-default.html"
        override_report = output_dir / "monthly-override.html"
        default_rendered = run_script("scripts/meeting_report_monthly.py", "--input-dir", str(output_dir), "--output", str(default_report))
        self.assertEqual(default_rendered.returncode, 0, default_rendered.stderr)
        override_rendered = run_script(
            "scripts/meeting_report_monthly.py",
            "--input-dir",
            str(output_dir),
            "--output",
            str(override_report),
            "--company",
            "董事会展示名称",
        )
        self.assertEqual(override_rendered.returncode, 0, override_rendered.stderr)

        default_payload = embedded_payload(default_report.read_text(encoding="utf-8"))
        override_html = override_report.read_text(encoding="utf-8")
        override_payload = embedded_payload(override_html)

        self.assertIn("<h1>董事会展示名称月经营会报</h1>", override_html)
        self.assertEqual(override_payload["meta"]["title"], "董事会展示名称月经营会报")
        self.assertEqual(override_payload["meta"]["organization_name"], ORG_NAME)
        self.assertEqual(override_payload["meta"]["target_windows"], default_payload["meta"]["target_windows"])
        self.assertEqual(override_payload["comparison"], default_payload["comparison"])
        self.assertEqual(override_payload["trend"], default_payload["trend"])
        self.assertEqual(override_payload["availability"], default_payload["availability"])

    def test_monthly_renderer_rejects_blank_company_title_override(self) -> None:
        output_dir = self.profile_to_directory("profile_monthly_data.py", "monthly_bundle.json")
        report_path = output_dir / "monthly-blank-override.html"
        rendered = run_script(
            "scripts/meeting_report_monthly.py",
            "--input-dir",
            str(output_dir),
            "--output",
            str(report_path),
            "--company",
            "   ",
        )
        self.assertNotEqual(rendered.returncode, 0)
        self.assertIn("company", rendered.stderr.lower())
        self.assertFalse(report_path.exists())

    def test_monthly_renderer_validates_metadata_organization_even_with_company_override(self) -> None:
        invalid_values = [
            ("missing", None, True),
            ("blank", "   ", False),
            ("non_string", 123, False),
        ]
        for label, value, remove in invalid_values:
            with self.subTest(label=label):
                output_dir = self.profile_to_directory("profile_monthly_data.py", "monthly_bundle.json")
                self.corrupt_summary_organization(output_dir, "monthly_meeting_summary.json", value, remove=remove)
                report_path = output_dir / f"monthly-{label}-override.html"
                rendered = run_script(
                    "scripts/meeting_report_monthly.py",
                    "--input-dir",
                    str(output_dir),
                    "--output",
                    str(report_path),
                    "--company",
                    "董事会展示名称",
                )
                self.assertNotEqual(rendered.returncode, 0)
                self.assertIn(ORG_ERROR, rendered.stderr)
                self.assertFalse(report_path.exists())

    def test_weekly_report_marks_stall_and_product_panels_partial_when_data_is_missing(self) -> None:
        bundle = json.loads((FIXTURES / "weekly_bundle.json").read_text(encoding="utf-8"))
        bundle["resultsByJobId"]["dishes_current_product_totals"]["rows"] = []
        bundle["resultsByJobId"]["dish_catalog_current_snapshot"]["rows"] = []
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        output_dir = Path(tmp.name)
        bundle_path = output_dir / "bundle.json"
        bundle_path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")

        profile = run_script("scripts/profile_weekly_data.py", "--bundle", str(bundle_path), "--output-dir", str(output_dir))
        self.assertEqual(profile.returncode, 0, profile.stderr)
        report_path = output_dir / "partial.html"
        rendered = run_script("scripts/generate_weekly_report_html.py", "--input-dir", str(output_dir), "--report", str(report_path))
        self.assertEqual(rendered.returncode, 0, rendered.stderr)
        html = report_path.read_text(encoding="utf-8")

        assert_self_contained(self, html)
        payload = embedded_payload(html)
        self.assertIn("缺少菜品销售数据或菜品库，档口和产品分析未展示。", strip_embedded_scripts(html))
        self.assertFalse(payload["stall_sales_mix"]["enabled"])
        self.assertFalse(payload["product_sales_per_10k_order_revenue"]["enabled"])
        self.assertFalse(payload["product_sales_per_10k_gross_sales"]["enabled"])

    def test_weekly_report_hides_technical_coverage_details_and_uses_business_language(self) -> None:
        bundle = json.loads((FIXTURES / "weekly_bundle.json").read_text(encoding="utf-8"))
        bundle["coverage"] = {
            "business": {
                "dataset": "business",
                "metadataPolicy": "window",
                "readable": True,
                "sources": [],
                "windows": {
                    "trend": {
                        "requested": {"start": "2026-04-06", "end": "2026-07-26"},
                        "hasReadableOverlap": True,
                        "observed": [
                            {
                                "startDate": "2026-07-01",
                                "endDate": "2026-07-26",
                                "rowCount": 42,
                                "sourceDocumentId": "doc_visible_trend",
                                "importBatchId": "imp_visible_trend",
                            }
                        ],
                        "isFullyCovered": False,
                        "gaps": [{"startDate": "2026-04-06", "endDate": "2026-06-30"}],
                    }
                },
            }
        }
        bundle["notices"].append(
            {
                "code": "COVERAGE_WINDOW_PARTIAL",
                "dataset": "business",
                "window": "trend",
                "module": "weeklyTrend",
                "gaps": [{"startDate": "2026-04-06", "endDate": "2026-06-30"}],
            }
        )
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        output_dir = Path(tmp.name)
        bundle_path = output_dir / "bundle.json"
        bundle_path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")

        profile = run_script("scripts/profile_weekly_data.py", "--bundle", str(bundle_path), "--output-dir", str(output_dir))
        self.assertEqual(profile.returncode, 0, profile.stderr)
        report_path = output_dir / "coverage.html"
        rendered = run_script("scripts/generate_weekly_report_html.py", "--input-dir", str(output_dir), "--report", str(report_path))
        self.assertEqual(rendered.returncode, 0, rendered.stderr)
        visible_html = strip_embedded_scripts(report_path.read_text(encoding="utf-8"))

        self.assertNotIn("覆盖明细", visible_html)
        self.assertNotIn("doc_visible_trend", visible_html)
        self.assertNotIn("imp_visible_trend", visible_html)
        self.assertNotIn("COVERAGE_WINDOW_PARTIAL", visible_html)
        self.assertIn("历史营业数据不足，趋势图只展示当前可用区间。", visible_html)

    def test_report_does_not_render_internal_job_ids_visibly(self) -> None:
        _, html, _ = self.render_from_profile(
            "profile_weekly_data.py",
            "generate_weekly_report_html.py",
            "weekly_bundle.json",
            "weekly_meeting_summary.json",
        )
        self.assertNotIn("business_current_store_totals", html)
        self.assertNotIn("weekly_store_comparison.csv", html)

    def test_weekly_headline_additive_metrics_are_unknown_when_comparison_rows_are_incomplete(self) -> None:
        bundle = json.loads((FIXTURES / "weekly_bundle.json").read_text(encoding="utf-8"))
        bundle["resultsByJobId"]["business_previous_store_totals"]["rows"] = bundle["resultsByJobId"][
            "business_previous_store_totals"
        ]["rows"][:1]
        bundle["resultsByJobId"]["business_yoy_store_totals"]["rows"] = []
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        output_dir = Path(tmp.name)
        bundle_path = output_dir / "bundle.json"
        bundle_path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")

        profile = run_script("scripts/profile_weekly_data.py", "--bundle", str(bundle_path), "--output-dir", str(output_dir))
        self.assertEqual(profile.returncode, 0, profile.stderr)
        report_path = output_dir / "incomplete-comparison.html"
        rendered = run_script("scripts/generate_weekly_report_html.py", "--input-dir", str(output_dir), "--report", str(report_path))
        self.assertEqual(rendered.returncode, 0, rendered.stderr)
        payload = embedded_payload(report_path.read_text(encoding="utf-8"))
        by_store = {row["门店名称"]: row for row in payload["comparison"]}
        self.assertIsNone(by_store["示例二店"]["previous_net_revenue"])
        self.assertIsNone(by_store["示例二店"]["wow_net_revenue_delta"])
        self.assertTrue(all(row["yoy_net_revenue"] is None for row in payload["comparison"]))

    def test_weekly_report_can_render_when_every_query_returns_no_rows(self) -> None:
        bundle = json.loads((FIXTURES / "weekly_bundle.json").read_text(encoding="utf-8"))
        bundle["notices"] = []
        for result in bundle["resultsByJobId"].values():
            result["rows"] = []
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        output_dir = Path(tmp.name)
        bundle_path = output_dir / "empty-bundle.json"
        bundle_path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")

        profile = run_script("scripts/profile_weekly_data.py", "--bundle", str(bundle_path), "--output-dir", str(output_dir))
        self.assertEqual(profile.returncode, 0, profile.stderr)
        report_path = output_dir / "empty.html"
        rendered = run_script("scripts/generate_weekly_report_html.py", "--input-dir", str(output_dir), "--report", str(report_path))
        self.assertEqual(rendered.returncode, 0, rendered.stderr)
        html = report_path.read_text(encoding="utf-8")
        payload = embedded_payload(html)

        assert_self_contained(self, html)
        self.assertEqual(payload["availability"], {"current": False, "trend": False, "channels": False, "dayparts": False})
        self.assertFalse(payload["stall_sales_mix"]["enabled"])
        self.assertFalse(payload["product_sales_per_10k_order_revenue"]["enabled"])
        visible_html = strip_embedded_scripts(html)
        self.assertIn("本周暂无可用经营数据，经营指标与分析板块未展示。", visible_html)
        self.assertNotIn("缺少历史营业数据，趋势图未展示。", visible_html)
        self.assertNotIn("COVERAGE_", html)
        self.assertNotIn("business_current_store_totals", html)

    def test_weekly_report_hides_all_analysis_when_only_historical_data_exists(self) -> None:
        bundle = json.loads((FIXTURES / "weekly_bundle.json").read_text(encoding="utf-8"))
        for job_id, result in bundle["resultsByJobId"].items():
            if "_current_" in job_id or "_previous_" in job_id:
                result["rows"] = []
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        output_dir = Path(tmp.name)
        bundle_path = output_dir / "historical-only-bundle.json"
        bundle_path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")

        profile = run_script("scripts/profile_weekly_data.py", "--bundle", str(bundle_path), "--output-dir", str(output_dir))
        self.assertEqual(profile.returncode, 0, profile.stderr)
        report_path = output_dir / "historical-only.html"
        rendered = run_script("scripts/generate_weekly_report_html.py", "--input-dir", str(output_dir), "--report", str(report_path))
        self.assertEqual(rendered.returncode, 0, rendered.stderr)
        html = report_path.read_text(encoding="utf-8")

        self.assertFalse(embedded_payload(html)["availability"]["current"])
        self.assertIn(
            "['summary', 'ranking', 'stores', 'channels', 'stall-mix', 'product-sales-per-10k', "
            "'drivers', 'stall-drivers', 'daypart-drivers', 'dayparts'].forEach(hideSection);",
            html,
        )

    def test_monthly_report_can_render_when_every_query_returns_no_rows(self) -> None:
        bundle = json.loads((FIXTURES / "monthly_bundle.json").read_text(encoding="utf-8"))
        bundle["notices"] = []
        for result in bundle["resultsByJobId"].values():
            result["rows"] = []
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        output_dir = Path(tmp.name)
        bundle_path = output_dir / "empty-bundle.json"
        bundle_path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")

        profile = run_script("scripts/profile_monthly_data.py", "--bundle", str(bundle_path), "--output-dir", str(output_dir))
        self.assertEqual(profile.returncode, 0, profile.stderr)
        report_path = output_dir / "empty.html"
        rendered = run_script("scripts/generate_monthly_report_html.py", "--input-dir", str(output_dir), "--report", str(report_path))
        self.assertEqual(rendered.returncode, 0, rendered.stderr)
        html = report_path.read_text(encoding="utf-8")
        payload = embedded_payload(html)

        assert_self_contained(self, html)
        self.assertEqual(payload["availability"], {"current": False, "trend": False, "channels": False, "dayparts": False})
        self.assertFalse(payload["stall_sales_mix"]["enabled"])
        self.assertFalse(payload["product_sales_per_10k_order_revenue"]["enabled"])
        visible_html = strip_embedded_scripts(html)
        self.assertIn("本月暂无可用经营数据，经营指标与分析板块未展示。", visible_html)
        self.assertNotIn("缺少历史营业数据，趋势图未展示。", visible_html)
        self.assertNotIn("COVERAGE_", html)
        self.assertNotIn("business_current_store_totals", html)

    def test_runners_profile_render_and_print_final_json(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        output_dir = Path(tmp.name)
        report_path = output_dir / "weekly.html"

        completed = run_script(
            "scripts/run_weekly_report.py",
            "--bundle",
            str(FIXTURES / "weekly_bundle.json"),
            "--output-dir",
            str(output_dir),
            "--report",
            str(report_path),
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(Path(result["artifacts"]["report"]), report_path)
        self.assertEqual(Path(result["artifacts"]["summary"]), output_dir / "weekly_meeting_summary.json")
        self.assertIn("weekly_store_comparison.csv", result["artifacts"]["facts"])
        self.assertEqual(result["notices"], [])
        self.assertTrue(report_path.exists())

    def test_weekly_and_monthly_runners_accept_company_title_override(self) -> None:
        cases = [
            ("run_weekly_report.py", "weekly_bundle.json", "周经营会报"),
            ("run_monthly_report.py", "monthly_bundle.json", "月经营会报"),
        ]
        for runner, fixture_name, suffix in cases:
            with self.subTest(runner=runner):
                temporary = tempfile.TemporaryDirectory()
                self.addCleanup(temporary.cleanup)
                output_dir = Path(temporary.name)
                report_path = output_dir / "report.html"
                completed = run_script(
                    f"scripts/{runner}",
                    "--bundle",
                    str(FIXTURES / fixture_name),
                    "--current-user",
                    str(FIXTURES / "current_user_response.json"),
                    "--output-dir",
                    str(output_dir / "facts"),
                    "--report",
                    str(report_path),
                    "--company",
                    "董事会展示名称",
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                html = report_path.read_text(encoding="utf-8")
                payload = embedded_payload(html)
                self.assertIn(f"<h1>董事会展示名称{suffix}</h1>", html)
                self.assertEqual(payload["meta"]["title"], f"董事会展示名称{suffix}")
                self.assertEqual(payload["meta"]["organization_name"], ORG_NAME)

    def test_weekly_and_monthly_renderers_escape_dynamic_company_titles(self) -> None:
        malicious_company = '<img src=x onerror="alert(1)">'
        cases = [
            ("profile_weekly_data.py", "weekly_bundle.json", "meeting_report_weekly.py", "--output"),
            ("profile_weekly_data.py", "weekly_bundle.json", "generate_weekly_report_html.py", "--report"),
            ("profile_monthly_data.py", "monthly_bundle.json", "meeting_report_monthly.py", "--output"),
            ("profile_monthly_data.py", "monthly_bundle.json", "generate_monthly_report_html.py", "--report"),
        ]
        for profile_script, fixture_name, renderer, output_flag in cases:
            with self.subTest(renderer=renderer):
                output_dir = self.profile_to_directory(profile_script, fixture_name)
                report_path = output_dir / f"{renderer}.html"
                completed = run_script(
                    f"scripts/{renderer}",
                    "--input-dir",
                    str(output_dir),
                    output_flag,
                    str(report_path),
                    "--company",
                    malicious_company,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                html = report_path.read_text(encoding="utf-8")
                self.assertNotIn("<img src=x", html)
                self.assertIn("&lt;img src=x", html)
                self.assertEqual(embedded_payload(html)["meta"]["company"], malicious_company)
