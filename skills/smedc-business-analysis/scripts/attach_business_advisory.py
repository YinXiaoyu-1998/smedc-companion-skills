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
    summary, _, digest = fact_inputs(facts_dir, report_type)
    meta = summary["meta"]
    source = summary["source"] if report_type == "diagnosis" else meta
    windows = source["windows"] if report_type == "diagnosis" else meta["target_windows"]
    return {"schema_version": 1, "context": {
        "organization_name": organization_name_from_metadata(summary), "report_type": report_type,
        "windows": windows, "store_name_contains": source.get("store_name_contains", []),
        "facts_digest": digest,
    }, "findings": [], "management_questions": []}


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
        numeric_evidence = False
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
            numeric_evidence |= actual is not None
            text_field(item.get("label"), "evidence label")
            if item.get("format", "number") not in ("number", "percent"):
                raise ValueError("unsupported evidence format")
            if item.get("format") == "percent" and actual is None:
                raise ValueError("percentage evidence must be numeric")
        if not numeric_evidence:
            raise ValueError("each finding needs numeric evidence")
    questions = advisory.get("management_questions", [])
    if not isinstance(questions, list):
        raise ValueError("management_questions must be a list")
    for question in questions:
        text_field(question.get("question"), "question")
        text_field(question.get("decision_impact"), "decision_impact")


def strip_advisory(html: str) -> str:
    for marker in MARKERS:
        html = re.sub(rf"<!-- {marker}_START -->.*?<!-- {marker}_END -->", "", html, flags=re.DOTALL)
    return html


def render_feedback(advisory: dict) -> str:
    esc = lambda value: escape(str(value), quote=True)
    findings = sorted(advisory["findings"], key=lambda finding: finding["priority"])
    parts = ['<section class="section" id="business-advisory" aria-labelledby="advisory-title">',
             '<h2 id="advisory-title">经营顾问反馈</h2>',
             '<p>结合本期经营变化，建议优先关注以下事项。每项建议已注明门店与业务范围。</p>',
             '<h3>本期优先行动</h3><ol>']
    for finding in findings[:3]:
        action = finding["action"]
        parts.append(f'<li><a href="#advisory-{esc(finding["id"])}">{esc(finding["title"])}</a>'
                     f' · {esc(action["owner_role"])} · {esc(action["review_after"])}</li>')
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
        parts.append('<ul aria-label="判断所依据的经营事实">')
        for item in finding["evidence"]:
            value = number(item["value"])
            display = f'{value * 100:,.2f}%' if item.get("format") == "percent" else (
                f'{value:,f}' if value is not None else str(item["value"]))
            parts.append(f'<li>{esc(item["label"])}：{esc(display)}</li>')
        parts.append('</ul>')
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
    if advisory.get("schema_version") != 1 or advisory.get("context") != expected["context"]:
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
    if not has_current and (advisory["findings"] or advisory.get("management_questions")):
        raise ValueError("cannot attach advice without current-period evidence")
    if advisory["findings"]:
        marker = MARKERS[0]
        block = f'<!-- {marker}_START -->{render_feedback(advisory)}<!-- {marker}_END -->'
        position = html.index('</section>', html.index('<main')) + len('</section>')
        html = html[:position] + block + html[position:]
        marker = MARKERS[1]
        style = ('#business-advisory details{border:1px solid #d9e1e7;border-radius:12px;padding:16px;margin:12px 0;}'
                 '#business-advisory summary{cursor:pointer;font-weight:700;}'
                 '#business-advisory p,#business-advisory li{line-height:1.7;}'
                 '@media print{#business-advisory details{break-inside:avoid;}'
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
            "status": "attached" if advisory["findings"] else "insufficient_evidence"}


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
