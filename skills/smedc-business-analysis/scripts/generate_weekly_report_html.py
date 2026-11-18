#!/usr/bin/env python3
"""Render the weekly meeting experience from SMEDC-derived facts."""

from __future__ import annotations

import argparse
import json
import re
import sys
from html import escape
from pathlib import Path
from typing import Any

from generate_business_report_html import public_payload
from weekly_dashboard import PANEL_SOURCE, render_dashboard
from meeting_report_weekly import HTML_TEMPLATE, build_payload, escaped_report_title, serialized_payload_for_html


def accessible_html(html: str) -> str:
    """Add static accessibility metadata without changing the original interactions."""
    html = re.sub(r"<table(?![^>]*\baria-label=)", '<table aria-label="经营事实表"', html)
    html = re.sub(r"<th(?![a-z])(?![^>]*\bscope=)", '<th scope="col"', html)
    return html


def presentation_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Keep only report-facing data in the embedded payload."""
    technical_keys = {"bundle", "coverage", "jobs", "output", "outputs", "outputContract"}

    def scrub(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: scrub(item) for key, item in value.items() if key not in technical_keys}
        if isinstance(value, list):
            return [scrub(item) for item in value]
        return value

    result = public_payload(scrub(payload))
    if not result.get("availability", {}).get("current"):
        period = "本月" if result.get("meta", {}).get("report_grain") == "month" else "本周"
        result["data_gaps"] = [f"{period}暂无可用经营数据，经营指标与分析板块未展示。"]
    return result


def inject_missing_data_notice(html: str, messages: list[str]) -> str:
    placeholder = '<div id="missingDataNotice" class="callout" hidden></div>'
    if not messages:
        return html
    body = "；".join(escape(str(message)) for message in messages if str(message).strip())
    if not body:
        return html
    notice = f'<div id="missingDataNotice" class="callout"><b>数据提示：</b>{body}</div>'
    return html.replace(placeholder, notice)


def render(input_dir: Path, report_path: Path, company: str | None = None, *, detail_facts: dict | None = None) -> dict[str, Any]:
    summary_path = input_dir / "weekly_meeting_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    payload = build_payload(input_dir, company)
    report_payload = presentation_payload(payload)
    title = escaped_report_title(payload["meta"]["title"])
    html = re.sub(r"<!-- standalone-report:start -->.*?<!-- standalone-report:end -->\n", "", HTML_TEMPLATE, flags=re.DOTALL)
    html = html.replace("__TITLE__", title)
    html = html.replace("<main>", PANEL_SOURCE, 1).replace("</main>", "</div>", 1)
    html = html.replace(
        '<script id="payload" type="application/json">',
        '<script type="application/json" id="report-data">',
    )
    html = html.replace("getElementById('payload')", "getElementById('report-data')")
    html = html.replace(
        "__PAYLOAD__",
        serialized_payload_for_html(report_payload),
    )
    html = inject_missing_data_notice(html, list(report_payload.get("data_gaps", [])))
    html = render_dashboard(accessible_html(html), input_dir, report_payload, set(payload["meta"].get("outputs", [])), detail_facts)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(html, encoding="utf-8")
    return {
        "artifacts": {
            "report": str(report_path),
            "summary": str(summary_path),
            "facts": [name for name in payload.get("meta", {}).get("outputs", []) if str(name).endswith(".csv")],
        },
        "notices": summary.get("data_gaps", []),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--company")
    parser.add_argument("--dashboard-facts", type=Path, help="Optional scoped product and order aggregates.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        detail_facts = json.loads(args.dashboard_facts.read_text(encoding="utf-8")) if args.dashboard_facts else None
        result = render(args.input_dir, args.report, args.company, detail_facts=detail_facts)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
