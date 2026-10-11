#!/usr/bin/env python3
"""Validate agent-authored feedback against saved facts and embed it in a report.

This helper does not generate judgments, hypotheses, or recommendations.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import tempfile
from decimal import Decimal, InvalidOperation
from html import escape
from pathlib import Path
from typing import Any

from identity import organization_name_from_metadata

SUMMARY_FILES = {"diagnosis": "analysis_summary.json", "weekly": "weekly_meeting_summary.json",
                 "monthly": "monthly_meeting_summary.json"}
MODULES = {"growth": "经营变化与优先问题", "stores": "门店改善与经验复制", "channels": "渠道与折扣质量",
           "dayparts": "餐段与运营核查", "menu": "菜单与档口机会", "synthesis": "跨板块经营判断"}
CONFIDENCE = {"high": "高", "medium": "中", "low": "低"}
MARKERS = ("SMEDC_ADVISORY", "SMEDC_ADVISORY_STYLE")
REVIEW_SECTIONS = {"meal_periods": "餐段分析", "dishes": "菜品分析", "stalls": "档口分析"}


def read_table(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def section_sources(report_type: str) -> dict[str, tuple[str, ...]]:
    if report_type == "diagnosis":
        return {"meal_periods": ("store_meal_period_summary.csv",), "dishes": (), "stalls": ()}
    return {
        "meal_periods": (f"{report_type}_store_meal_period_comparison.csv",),
        "dishes": (f"{report_type}_store_product_sales_per_10k.csv", f"{report_type}_store_stall_dish_drivers.csv"),
        "stalls": (f"{report_type}_store_stall_comparison.csv", f"{report_type}_store_stall_metrics.csv"),
    }


def current_cell(filename: str, row: dict, field: str, report_type: str) -> bool:
    if number(row.get(field)) is None:
        return False
    if report_type == "diagnosis":
        return True
    if filename.endswith(("_comparison.csv", "_dish_drivers.csv")):
        return field.startswith("current_")
    return row.get("period_key") == "current"


def store_coverage(sources: dict[str, Path], report_type: str) -> list[dict]:
    filename = "store_summary.csv" if report_type == "diagnosis" else f"{report_type}_store_comparison.csv"
    stores = sorted({row["门店名称"] for row in read_table(sources[filename])
                     if report_type == "diagnosis" or any(number(row.get(field)) is not None for field in
                        ("current_net_revenue", "current_gross_sales", "current_positive_orders", "current_rows"))})
    allowed = section_sources(report_type)
    # Product rows are the current-period source of coverage; driver rows may
    # contain historical-only products and cannot establish current availability.
    tables = {name: read_table(sources[name]) for names in allowed.values() for name in names if name in sources}
    coverage = []
    for store in stores:
        sections = {}
        for section, names in allowed.items():
            primary = names[:1] if section == "dishes" else names
            sections[section] = any(
                row.get("门店名称") == store and any(current_cell(name, row, field, report_type) for field in row)
                for name in primary for row in tables.get(name, [])
            )
        coverage.append({"store_name": store, "sections": sections})
    return coverage


def fact_inputs(facts_dir: Path, report_type: str) -> tuple[dict, dict[str, Path], str]:
    summary_path = facts_dir / SUMMARY_FILES[report_type]
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    filenames = summary.get("outputs", summary["meta"].get("outputs", []))
    sources = {}
    digest = hashlib.sha256(summary_path.read_bytes())
    for name in sorted(filenames):
        if not name.endswith(".csv"):
            continue
        source = (facts_dir / name).resolve()
        if Path(name).name != name or source.parent != facts_dir.resolve():
            raise ValueError("invalid fact source path")
        digest.update(name.encode("utf-8"))
        digest.update(source.read_bytes())
        sources[name] = source
    return summary, sources, digest.hexdigest()


def prepare(facts_dir: Path, report_type: str) -> dict[str, Any]:
    summary, sources, digest = fact_inputs(facts_dir, report_type)
    meta = summary["meta"]
    source = summary["source"] if report_type == "diagnosis" else meta
    windows = source["windows"] if report_type == "diagnosis" else meta["target_windows"]
    coverage = store_coverage(sources, report_type)
    return {"schema_version": 2, "context": {
        "organization_name": organization_name_from_metadata(summary), "report_type": report_type,
        "windows": windows, "store_name_contains": source.get("store_name_contains", []),
        "facts_digest": digest,
        "store_coverage": coverage,
    }, "store_reviews": [
        {"store_name": item["store_name"], **{
            section: {"status": "supported" if available else "unavailable", "observation": "" if available else "本期未覆盖该项数据。",
                      "judgment": "", "next_step": "", "evidence": []}
            for section, available in item["sections"].items()}}
        for item in coverage
    ], "findings": [], "management_questions": []}


def text_field(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be nonblank text")
    return value.strip()


def number(value: Any) -> Decimal | None:
    try:
        result = Decimal(str(value))
        return result if result.is_finite() else None
    except InvalidOperation:
        return None


def validate_evidence(evidence, sources, tables, *, store_name=None, allowed_sources=(), report_type="weekly"):
    if not isinstance(evidence, list) or not evidence:
        raise ValueError("each analysis needs evidence")
    numeric_evidence = False
    current_evidence = False
    for item in evidence:
        filename = item.get("file")
        if filename not in sources:
            raise ValueError("evidence source is not a generated fact table")
        if filename not in tables:
            with sources[filename].open(encoding="utf-8-sig", newline="") as stream:
                tables[filename] = list(csv.DictReader(stream))
        row_number = item.get("row")
        if type(row_number) is not int or not 1 <= row_number <= len(tables[filename]):
            raise ValueError("evidence row is outside its fact table")
        value = tables[filename][row_number - 1].get(item.get("field"))
        if value is None or not value.strip():
            raise ValueError("evidence value is missing in saved facts")
        actual, expected = number(value), number(item.get("value"))
        if (actual != expected if actual is not None else value != item.get("value")):
            raise ValueError("evidence value does not match saved facts")
        if store_name is not None:
            row = tables[filename][row_number - 1]
            if row.get("门店名称") != store_name:
                raise ValueError("store review evidence must belong to that store")
            if filename not in allowed_sources:
                raise ValueError("store review evidence must use its section fact tables")
            current_evidence |= current_cell(filename, row, item.get("field", ""), report_type)
        numeric_evidence |= actual is not None
        text_field(item.get("label"), "evidence label")
        if item.get("format", "number") not in ("number", "percent"):
            raise ValueError("unsupported evidence format")
        if item.get("format") == "percent" and actual is None:
            raise ValueError("percentage evidence must be numeric")
    if not numeric_evidence:
        raise ValueError("each analysis needs numeric evidence")
    if store_name is not None and not current_evidence:
        raise ValueError("store review needs current-period evidence")


def validate_findings(advisory: dict, sources: dict[str, Path]) -> None:
    findings = advisory.get("findings")
    if not isinstance(findings, list):
        raise ValueError("findings must be a list")
    tables = {}
    identifiers = set()
    for finding in findings:
        identifier = text_field(finding.get("id"), "id")
        if not re.fullmatch(r"F[1-9][0-9]*", identifier) or identifier in identifiers:
            raise ValueError("finding ids must be unique F1, F2, ... identifiers")
        identifiers.add(identifier)
        if finding.get("module") not in MODULES or finding.get("priority") not in ("P1", "P2", "P3"):
            raise ValueError("unsupported module or priority")
        if finding.get("confidence") not in CONFIDENCE:
            raise ValueError("unsupported confidence")
        for key in ("title", "observation", "interpretation", "hypothesis"):
            text_field(finding.get(key), key)
        for key in ("alternative", "caveat"):
            if key in finding and not isinstance(finding[key], str):
                raise ValueError(f"{key} must be text when supplied")
        action = finding.get("action", {})
        for key in ("owner_role", "scope", "review_after", "primary_metric", "guardrail", "stop_rule"):
            text_field(action.get(key), key)
        steps = action.get("steps")
        if not isinstance(steps, list) or not steps:
            raise ValueError("action steps must be a nonempty list")
        for step in steps:
            text_field(step, "action step")
        evidence = finding.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            raise ValueError("each finding needs evidence")
        validate_evidence(evidence, sources, tables)
    questions = advisory.get("management_questions", [])
    if not isinstance(questions, list):
        raise ValueError("management_questions must be a list")
    for question in questions:
        text_field(question.get("question"), "question")
        text_field(question.get("decision_impact"), "decision_impact")


def validate_store_reviews(advisory: dict, sources: dict[str, Path], report_type: str) -> None:
    expected = {item["store_name"]: item["sections"] for item in advisory["context"]["store_coverage"]}
    reviews = advisory.get("store_reviews")
    if not isinstance(reviews, list) or any(not isinstance(item, dict) for item in reviews):
        raise ValueError("store_reviews must cover every current-period store")
    names = [item.get("store_name") for item in reviews]
    if any(not isinstance(name, str) for name in names) or len(names) != len(set(names)) or set(names) != set(expected):
        raise ValueError("store_reviews must cover every current-period store exactly once")
    tables = {}
    allowed = section_sources(report_type)
    for review in reviews:
        store = review["store_name"]
        for section in REVIEW_SECTIONS:
            analysis = review.get(section)
            if not isinstance(analysis, dict):
                raise ValueError("every store needs meal_periods, dishes and stalls analysis")
            available = expected[store][section]
            if analysis.get("status") != ("supported" if available else "unavailable"):
                raise ValueError("store section availability must match saved facts")
            text_field(analysis.get("observation"), "store observation")
            if available:
                text_field(analysis.get("judgment"), "store judgment")
                text_field(analysis.get("next_step"), "store next_step")
                validate_evidence(analysis.get("evidence"), sources, tables, store_name=store,
                                  allowed_sources=allowed[section], report_type=report_type)
            elif analysis.get("evidence") or analysis.get("judgment") or analysis.get("next_step"):
                raise ValueError("unavailable store section cannot contain invented advice")


def strip_advisory(html: str) -> str:
    for marker in MARKERS:
        html = re.sub(rf"<!-- {marker}_START -->.*?<!-- {marker}_END -->", "", html, flags=re.DOTALL)
    return html


def render_evidence(evidence: list[dict]) -> str:
    parts = ['<ul aria-label="判断所依据的经营事实">']
    for item in evidence:
        value = number(item["value"])
        display = f'{value * 100:,.2f}%' if item.get("format") == "percent" else (
            f'{value:,f}' if value is not None else str(item["value"]))
        parts.append(f'<li>{escape(item["label"])}：{escape(display)}</li>')
    return ''.join(parts) + '</ul>'


def render_feedback(advisory: dict) -> str:
    esc = lambda value: escape(str(value), quote=True)
    findings = sorted(advisory["findings"], key=lambda finding: finding["priority"])
    parts = ['<section class="section" id="business-advisory" aria-labelledby="advisory-title">',
             '<h2 id="advisory-title">经营顾问反馈</h2>',
             '<p>先逐店复盘餐段、菜品与档口，再看企业层面的优先事项。</p>',
             '<h3>逐店基础分析</h3><div class="store-review-grid">']
    for index, review in enumerate(advisory.get("store_reviews", []), 1):
        parts.append(f'<details class="store-review-card" id="store-review-{index}"><summary>'
                     f'{esc(review["store_name"])}</summary><div class="store-review-body">')
        for section, label in REVIEW_SECTIONS.items():
            analysis = review[section]
            parts.append(f'<section data-review-section="{section}"><h4>{label}</h4>'
                         f'<p><b>本期表现：</b>{esc(analysis["observation"])}</p>')
            if analysis["status"] == "supported":
                parts.append(f'<p><b>经营判断：</b>{esc(analysis["judgment"])}</p>'
                             f'<p><b>下一步：</b>{esc(analysis["next_step"])}</p>'
                             '<details class="review-evidence"><summary>查看事实依据</summary>'
                             f'{render_evidence(analysis["evidence"])}</details>')
            parts.append('</section>')
        parts.append('</div></details>')
    parts.append('</div><h3>企业层面重点建议</h3>')
    if findings:
        parts.append('<h4>本期优先行动</h4><ol>')
    for finding in findings[:3]:
        action = finding["action"]
        parts.append(f'<li><a href="#advisory-{esc(finding["id"])}">{esc(finding["title"])}</a>'
                     f' · {esc(action["owner_role"])} · {esc(action["review_after"])}</li>')
    if findings:
        parts.append('</ol><p>展开查看具体判断、原因分析和执行建议。</p>')
    for finding in findings:
        parts.append(f'<details id="advisory-{esc(finding["id"])}"><summary>'
                     f'{esc(finding["priority"])} · {esc(MODULES[finding["module"]])} · '
                     f'{esc(finding["title"])}</summary>')
        for key, label in (("observation", "本期表现"), ("interpretation", "经营判断"),
                           ("hypothesis", "可能原因")):
            parts.append(f'<p><b>{label}：</b>{esc(finding[key])}</p>')
        if finding.get("alternative", "").strip():
            parts.append(f'<p><b>其他可能：</b>{esc(finding["alternative"])}</p>')
        parts.append(render_evidence(finding["evidence"]))
        if finding.get("caveat", "").strip():
            parts.append(f'<p><b>补充说明：</b>{esc(finding["caveat"])}</p>')
        action = finding["action"]
        parts.append(f'<p><b>建议责任角色：</b>{esc(action["owner_role"])}；'
                     f'<b>行动范围：</b>{esc(action["scope"])}</p><ol>')
        parts.extend(f'<li>{esc(step)}</li>' for step in action["steps"])
        parts.append(f'</ol><p><b>复盘时间：</b>{esc(action["review_after"])}；'
                     f'<b>主观察指标：</b>{esc(action["primary_metric"])}</p>'
                     f'<p><b>同时观察：</b>{esc(action["guardrail"])}；'
                     f'<b>何时调整：</b>{esc(action["stop_rule"])}</p></details>')
    if advisory.get("management_questions"):
        parts.append('<h3>下次经营会要确认的问题</h3><ul>')
        parts.extend(f'<li>{esc(item["question"])}<br>影响的决策：{esc(item["decision_impact"])}</li>'
                     for item in advisory["management_questions"])
        parts.append('</ul>')
    parts.append('</section>')
    return ''.join(parts)


def attach(facts_dir: Path, report_type: str, report_path: Path, advisory: dict) -> dict:
    expected = prepare(facts_dir, report_type)
    if advisory.get("schema_version") != 2 or advisory.get("context") != expected["context"]:
        raise ValueError("advisory context does not match this report's saved facts; prepare again")
    _, sources, _ = fact_inputs(facts_dir, report_type)
    validate_findings(advisory, sources)
    original = report_path.read_text(encoding="utf-8")
    html = strip_advisory(original)
    payload_match = re.search(r'<script type="application/json" id="report-data">(.*?)</script>', html, re.DOTALL)
    if payload_match is None:
        raise ValueError("expected generated report payload")
    payload = json.loads(payload_match.group(1))
    context, meta = expected["context"], payload["meta"]
    if meta.get("organization_name", meta.get("company")) != context["organization_name"]:
        raise ValueError("report organization does not match advisory context")
    if meta.get("store_name_contains", []) != context["store_name_contains"]:
        raise ValueError("report scope does not match advisory context")
    if report_type == "diagnosis":
        current = context["windows"]["current"]
        matches = meta.get("period", "").startswith(f'{current["start"]}—{current["end"]}')
    else:
        matches = meta.get("target_windows") == context["windows"] and meta.get("report_grain") == (
            "week" if report_type == "weekly" else "month")
    if not matches:
        raise ValueError("report period does not match advisory context")
    has_current = payload.get("availability", {}).get("current", False)
    if not has_current and (advisory["findings"] or advisory.get("store_reviews") or advisory.get("management_questions")):
        raise ValueError("cannot attach advice without current-period evidence")
    if has_current:
        validate_store_reviews(advisory, sources, report_type)
    if advisory["findings"] or advisory.get("store_reviews"):
        marker = MARKERS[0]
        block = f'<!-- {marker}_START -->{render_feedback(advisory)}<!-- {marker}_END -->'
        position = html.index('</section>', html.index('<main')) + len('</section>')
        html = html[:position] + block + html[position:]
        marker = MARKERS[1]
        style = ('#business-advisory details{border:1px solid #d9e1e7;border-radius:12px;padding:16px;margin:12px 0;}'
                 '#business-advisory summary{cursor:pointer;font-weight:700;}'
                 '#business-advisory p,#business-advisory li{line-height:1.7;}'
                 '#business-advisory .store-review-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;align-items:start;margin:16px 0 28px;}'
                 '#business-advisory .store-review-card{margin:0;padding:0;overflow-wrap:anywhere;background:#f5f8fb;}'
                 '#business-advisory .store-review-card>summary{padding:24px 16px;min-height:76px;box-sizing:border-box;}'
                 '#business-advisory .store-review-body{padding:0 16px 16px;font-size:14px;}'
                 '#business-advisory .store-review-body h4{margin:18px 0 8px;}'
                 '#business-advisory .review-evidence{padding:8px;margin:8px 0;font-size:12px;}'
                 '@media(max-width:900px){#business-advisory .store-review-grid{grid-template-columns:repeat(2,minmax(0,1fr));}}'
                 '@media(max-width:600px){#business-advisory .store-review-grid{grid-template-columns:1fr;}}'
                 '@media print{#business-advisory .store-review-grid{display:block;}'
                 '#business-advisory details{break-inside:avoid;}'
                 '#business-advisory details>*{display:block!important;}}')
        html = html.replace('</head>', f'<!-- {marker}_START --><style>{style}</style><!-- {marker}_END --></head>', 1)
    if html != original:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=report_path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            try:
                stream.write(html)
            except BaseException:
                temporary.unlink(missing_ok=True)
                raise
        try:
            os.replace(temporary, report_path)
        finally:
            temporary.unlink(missing_ok=True)
    return {"report": str(report_path), "findings": len(advisory["findings"]),
            "store_reviews": len(advisory.get("store_reviews", [])),
            "status": "attached" if advisory["findings"] or advisory.get("store_reviews") else "insufficient_evidence"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("prepare", "attach"):
        sub = commands.add_parser(command)
        sub.add_argument("--facts-dir", required=True, type=Path)
        sub.add_argument("--report-type", required=True, choices=SUMMARY_FILES)
        if command == "prepare":
            sub.add_argument("--output", required=True, type=Path)
        else:
            sub.add_argument("--advisory", required=True, type=Path)
            sub.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    if args.command == "prepare":
        if args.output.exists():
            raise ValueError("advisory file already exists; preserve it or choose a new draft path")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(prepare(args.facts_dir, args.report_type), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"advisory": str(args.output), "status": "awaiting_agent_analysis"}, ensure_ascii=False))
    else:
        advisory = json.loads(args.advisory.read_text(encoding="utf-8"))
        print(json.dumps(attach(args.facts_dir, args.report_type, args.report, advisory), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    main()
