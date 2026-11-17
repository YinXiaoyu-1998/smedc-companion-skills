"""Render the weekly dashboard and bind independently authored commentary to facts."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from assemble_query_bundle import is_error_envelope, unwrap_success_envelope
from meeting_report_weekly import read_optional_csv, serialized_payload_for_html

ASSETS = Path(__file__).resolve().parents[1] / "assets" / "weekly"
CONTENT = re.compile(r'<script id="weekly-dashboard-content" type="application/json">.*?</script>', re.DOTALL)
PAYLOAD = re.compile(r'<script type="application/json" id="report-data">(.*?)</script>', re.DOTALL)
DETAIL_FIELDS = {
    "meals": ("weekly_store_meal_period_comparison.csv", {"门店名称", "餐段", "current_net_revenue", "previous_net_revenue"}),
    "stalls": ("weekly_store_stall_comparison.csv", {"门店名称", "档口", "current_income", "previous_income"}),
    "products": ("weekly_store_product_sales_per_10k.csv", {"门店名称", "档口", "原始品项", "产品名称", "销售分类", "quantity", "dish_income", "units_per_10k", "period_key", "record_kind"}),
}


def content_tag(content: dict) -> str:
    return ('<script id="weekly-dashboard-content" type="application/json">'
            + serialized_payload_for_html(content) + '</script>')


def report_details(facts_dir: Path, store_names: set[str], outputs: set[str]) -> dict:
    details = {}
    for key, (filename, fields) in DETAIL_FIELDS.items():
        results = []
        rows = read_optional_csv(facts_dir / filename) if filename in outputs else []
        if key == "products" and "weekly_store_product_previous.csv" in outputs:
            rows.extend(read_optional_csv(facts_dir / "weekly_store_product_previous.csv"))
        for row in rows:
            if row.get("门店名称") not in store_names:
                continue
            record = {k: v for k, v in row.items() if k in fields}
            if key == "stalls":
                record.update(current_net_revenue=row.get("current_income"), previous_net_revenue=row.get("previous_income"))
            results.append(record)
        details[key] = results
    return details


def render_dashboard(html: str, facts_dir: Path, payload: dict, outputs: set[str]) -> str:
    names = {row["门店名称"] for row in payload["comparison"] if row.get("current_rows")}
    content = {"headline": "", "advisory": None, "customer_voice": None, "details": report_details(facts_dir, names, outputs)}
    style = (ASSETS / "dashboard.css").read_text(encoding="utf-8")
    script = (ASSETS / "dashboard.js").read_text(encoding="utf-8")
    for part in ("charts", "details"):
        marker = f"/*__WEEKLY_{part.upper()}__*/"
        script = script.replace(marker, (ASSETS / f"{part}.js").read_text(encoding="utf-8"), 1)
    return html.replace("</head>", f"<style>{style}</style></head>", 1).replace(
        "</body>", f"{content_tag(content)}<script>{script}</script></body>", 1
    )


def digest(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def review_facts(report: Path, pages: list[Path]) -> dict:
    """Compile authorized, cursor-linked responses in the exact weekly store and date scope."""
    match = PAYLOAD.search(report.read_text(encoding="utf-8"))
    if not match or not pages:
        raise ValueError("expected factual weekly report and at least one complete review page")
    payload = json.loads(match.group(1))
    window = payload["meta"]["target_windows"]["current"]
    store_names = {row["门店名称"] for row in payload["comparison"] if row.get("current_rows")}
    entries, seen, covered_stores = {}, set(), set()
    cursor, enterprise = None, None
    scope = payload["meta"]["organization_name"], window, sorted(store_names)
    for index, path in enumerate(pages):
        saved = json.loads(path.read_text(encoding="utf-8"))
        request, response = saved["request"], saved["response"]
        if cursor is None:
            incoming = request.get("enterpriseName")
            if not isinstance(incoming, str) or not incoming.strip() or (enterprise and enterprise != incoming):
                raise ValueError("all review batches must identify the same authorized enterprise")
            enterprise = incoming
            requested_names = request.get("storeNames", [])
            batch_stores = set(requested_names)
            if (not batch_stores or len(requested_names) != len(batch_stores)
                    or not batch_stores <= store_names or batch_stores & covered_stores):
                raise ValueError("review batches must select disjoint in-scope stores")
            covered_stores |= batch_stores
            base = request
            cursors = set()
        if ({k: v for k, v in request.items() if k != "cursor"} != {k: v for k, v in base.items() if k != "cursor"}
                or request.get("cursor") != cursor
                or request.get("reviewedAtFrom") != window["start"] + " 00:00:00"
                or request.get("reviewedAtTo") != window["end"] + " 23:59:59"
                or set(request) - {"enterpriseName", "storeNames", "reviewedAtFrom", "reviewedAtTo", "limit", "cursor"}):
            raise ValueError("review request/pagination does not match the full report scope")
        if is_error_envelope(response):
            raise ValueError("SMEDC review read failed")
        page = unwrap_success_envelope(response)
        for row in page["rows"]:
            date_value = datetime.fromisoformat(row["reviewedAt"])
            if date_value.utcoffset() is None:
                raise ValueError("review time must include a timezone")
            date = date_value.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat()
            store = row["storeName"]
            if (row["enterpriseName"] != request["enterpriseName"] or store not in batch_stores
                    or not window["start"] <= date <= window["end"]):
                raise ValueError("review outside the exact store/week scope")
            if not row.get("id") or row["id"] in seen:
                raise ValueError("missing or duplicate review identity")
            seen.add(row["id"])
            body = (row.get("content") or "").strip()
            merged = re.sub(r"\s+", "", re.sub(r"\[[^\]]+\]", "", body))
            if merged:
                entries.setdefault((store, merged), {"store_name": store, "source": row["source"], "date": date, "text": body})
        cursor = page["page"]["nextCursor"]
        if cursor in cursors or (cursor is not None and index == len(pages) - 1):
            raise ValueError("review pagination is incomplete or repeated")
        cursors.add(cursor)
    if covered_stores != store_names:
        raise ValueError("review batches must cover all selected current-period stores")
    return {"context": list(scope), "review_count": len(seen), "groups": [
        {"id": f"R{index}", **entry} for index, entry in enumerate(entries.values(), 1)
    ]}


def text_field(value, label: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit:
        raise ValueError(f"{label} must contain 1–{limit} characters")
    return value.strip()


def voice_draft(facts: dict) -> dict:
    stores = sorted({entry["store_name"] for entry in facts["groups"]})
    return {"facts_digest": digest(facts), "overview": "",
            "stores": [{"store_name": name, "headline": "", "themes": []} for name in stores]}


def render_voice(voice: dict | None, facts: dict | None, context: dict) -> dict | None:
    if facts is None or not facts["groups"]:
        if voice is not None and (voice.get("overview") or voice.get("stores")):
            raise ValueError("customer voice requires readable review text")
        return None
    expected_scope = [context["organization_name"], context["windows"]["current"],
                      sorted(item["store_name"] for item in context["store_coverage"])]
    expected = voice_draft(facts)
    if facts["context"] != expected_scope or not isinstance(voice, dict) or voice.get("facts_digest") != expected["facts_digest"]:
        raise ValueError("customer voice does not match the saved store and week facts")
    by_id = {row["id"]: row for row in facts["groups"]}
    stores = voice["stores"]
    if sorted(item["store_name"] for item in stores) != [item["store_name"] for item in expected["stores"]]:
        raise ValueError("customer voice needs one review for every store with text")
    public = {"overview": text_field(voice["overview"], "customer voice overview", 280), "stores": []}
    for entry in stores:
        name = entry["store_name"]
        result = {"store_name": name, "headline": text_field(entry["headline"], "store voice judgment", 180), "themes": []}
        if not 0 <= len(entry["themes"]) <= 4:
            raise ValueError("use at most four review themes per store")
        for theme in entry["themes"]:
            safe_theme = {key: text_field(theme.get(key), key, limit) for key, limit in (
                ("title", 62), ("cloud_label", 18), ("observation", 240), ("judgment", 240), ("action", 240)
            )}
            if theme["tone"] not in {"keep", "check"} or not 1 <= len(theme["evidence"]) <= 4:
                raise ValueError("customer voice theme needs a supported tone and 1–4 excerpts")
            evidence, ids = [], set()
            for citation in theme["evidence"]:
                key = citation["review_id"]
                row = by_id.get(key)
                excerpt = text_field(citation.get("excerpt"), "review excerpt", 120)
                if key in ids or row is None or row["store_name"] != name or excerpt not in row["text"]:
                    raise ValueError("review excerpt must be verbatim, distinct and from the same store")
                ids.add(key)
                evidence.append({"source": row["source"], "date": row["date"], "excerpt": excerpt})
            result["themes"].append({**safe_theme, "tone": theme["tone"], "evidence": evidence})
        public["stores"].append(result)
    return public


def bind_dashboard(html: str, advisory: dict, review_data: dict | None, has_current: bool) -> str:
    match = CONTENT.search(html)
    if not match:
        return html
    body = json.loads(match.group().split(">", 1)[1].rsplit("</script>", 1)[0])
    body["headline"] = text_field(advisory.get("dashboard_headline"), "dashboard headline", 120) if has_current else ""
    body["customer_voice"] = render_voice(advisory.get("customer_voice"), review_data, advisory["context"])
    # The dashboard only consumes these business fields. Keep filenames, row references and hashes out of its embedded data.
    def public_feedback(value):
        if isinstance(value, dict):
            return {key: public_feedback(item) for key, item in value.items() if key not in {"file", "row", "field"}}
        if isinstance(value, list):
            return [public_feedback(item) for item in value]
        return value

    body["advisory"] = public_feedback({
        **{key: advisory.get(key, []) for key in ("store_reviews","management_questions")},
        "findings": sorted(advisory["findings"], key=lambda item: item["priority"]),
    })
    return html[:match.start()] + content_tag(body) + html[match.end():]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("pages", nargs="+", type=Path)
    args = parser.parse_args()
    facts = review_facts(args.report, args.pages)
    args.output.write_text(json.dumps(facts, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"review_count":facts["review_count"],"text_groups":len(facts["groups"])}))


if __name__ == "__main__":
    main()
