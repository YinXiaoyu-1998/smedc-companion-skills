---
name: smedc-business-analysis
description: Use when generating tenant-neutral SMEDC diagnosis, weekly, or monthly operating reports from structured business datasets.
---

# SMEDC Business Analysis

Generate operating diagnosis, weekly meeting, and monthly meeting reports from SMEDC structured data. The employee-owned agent performs the MCP calls through the user's authenticated launcher session; the local scripts validate saved SMEDC envelopes, aggregate launcher-managed partition extracts, and render self-contained HTML.

**Required prerequisite:** Use `smedc-mcp` for official SMEDC install, update, repair, login, and MCP session setup. The official launcher package is `smedc-mcp-launcher@0.7.0`, and the MCP entry is `smedc`.

If `smedc-mcp` is not installed, do not begin report data access. Explain that it is required, identify the official source at <https://github.com/YinXiaoyu-1998/smedc-mcp-skill>, and offer to install it only if the employee explicitly authorizes that installation. Never install it silently. Never install or import `smedc-delivery-ledger` automatically.

## Boundaries

- Before querying report data, call `smedc_get_current_user` and save the full response as `current_user.json`.
- The only report-company source is `smedc_get_current_user.user.organizationName`. Missing, non-string, or blank organization names are a contract error; stop and tell the user their SMEDC account organization must be corrected.
- Do not infer a report company from display name, email/domain, filenames, partition `enterpriseName`, store names, configuration defaults, or examples.
- `enterpriseName` remains only the structured-data selector used for coverage and partition downloads.
- Use only these SMEDC MCP tools for reports: `smedc_get_current_user`, `list_structured_datasets`, `describe_structured_dataset_coverage`, `download_structured_partitions`, `query_structured_dataset`, and, when an upload is still processing, `get_partition_import_status`.
- Do not use direct HTTP, service databases, service configuration, or internal storage.
- Do not handle passwords or tokens.
- Do not request, reveal, copy, or persist presigned URLs. Let `download_structured_partitions` consume them inside the launcher and return a launcher-managed local directory.
- Do not ingest user-provided local CSV, XLSX, or workbook files as a compatibility report source.
- Do not add monthly profit or profit-rate reporting.

## Workflow

1. Use `smedc-mcp` to install or verify `smedc-mcp-launcher@0.7.0`, configure the `smedc` MCP entry, and complete login. Continue only after the authenticated MCP session exposes the business tools.

   If the same request first uploads a `business` or `dishes` source through the prerequisite skill, poll the returned `partitionImportJobId` with `get_partition_import_status` until `published`. Treat `failed` as terminal and report the service error.

2. Create a run directory, for example `runs/2026-09-05-weekly/`, with durable evidence paths:

   ```text
   current_user.json
   registry_response.json
   coverage_business.json
   coverage_dishes.json
   coverage_dish_catalog.json
   query_manifest.json
   partition-extracts/
   query-results/
   bundle.json
   facts/
   report.html
   ```

3. Call `smedc_get_current_user` and save the full returned envelope as `current_user.json`.

4. Call `list_structured_datasets` and save the full returned envelope as `registry_response.json`.

5. Call `describe_structured_dataset_coverage` once for each canonical dataset, in this order: `business`, `dishes`, `dish_catalog`. Save the envelopes as `coverage_business.json`, `coverage_dishes.json`, and `coverage_dish_catalog.json`.

6. Choose the exact `enterpriseName` shown in both partition coverage responses, then run `python3 scripts/build_query_plan.py` with that selector, the saved current-user response, the requested report type, and date windows:

   ```bash
   python3 scripts/build_query_plan.py \
     --report-type weekly \
     --current-user runs/RUN_ID/current_user.json \
     --current-start YYYY-MM-DD \
     --current-end YYYY-MM-DD \
     --previous-start YYYY-MM-DD \
     --previous-end YYYY-MM-DD \
     --yoy-start YYYY-MM-DD \
     --yoy-end YYYY-MM-DD \
     --enterprise-name "示例企业" \
     --store-name-contains "示例品牌" \
     --registry-response runs/RUN_ID/registry_response.json \
     --coverage-dir runs/RUN_ID \
     --output runs/RUN_ID/query_manifest.json
   ```

   Use `--report-type diagnosis`, `weekly`, or `monthly`. Add `--store-name-contains` only when the employee requests a store-name scope; omit it for the complete enterprise. The option accepts one or more nonblank fragments and keeps a store when its name contains any fragment (case-sensitive). The same filter applies to business and dishes before local aggregation, across current, previous, YoY, and trend windows. `全体门店` in a filtered report means the selected stores' combined total. The partition download remains enterprise-wide because the MCP download tool has no store-name condition; do not narrow it using `storeIds` inferred from coverage, which can omit stores without merchant IDs. Do not apply a one-off filter only to the rendered report or only to the current week. Data coverage decides which modules can be shown; it must never change the requested reporting period.

7. For every `extracts[]` entry, call `download_structured_partitions` with its `input` exactly as emitted. Save the full tool response at `extracts[].outputFile`.

8. Call `query_structured_dataset` only for manifest jobs whose `tool` is `query_structured_dataset`; currently that is the controlled `dish_catalog` snapshot query. Follow `nextCursor` until the returned `nextCursor` is `null`; save an array of page envelopes in request order at `jobs[].outputFile`.

9. Stream the downloaded canonical CSV partitions into local aggregate job results:

   ```bash
   python3 scripts/load_partition_extract.py \
     --manifest runs/RUN_ID/query_manifest.json \
     --registry-response runs/RUN_ID/registry_response.json \
     --responses-dir runs/RUN_ID
   ```

10. Run `python3 scripts/assemble_query_bundle.py` to assemble the bundle:

   ```bash
   python3 scripts/assemble_query_bundle.py \
     --manifest runs/RUN_ID/query_manifest.json \
     --responses-dir runs/RUN_ID \
     --output runs/RUN_ID/bundle.json
   ```

11. Run the report runner for the requested report type, passing the saved current-user response:

   ```bash
   python3 scripts/run_business_report.py --bundle runs/RUN_ID/bundle.json --current-user runs/RUN_ID/current_user.json --output-dir runs/RUN_ID/facts --report runs/RUN_ID/report.html
   python3 scripts/run_weekly_report.py --bundle runs/RUN_ID/bundle.json --current-user runs/RUN_ID/current_user.json --output-dir runs/RUN_ID/facts --report runs/RUN_ID/report.html
   python3 scripts/run_monthly_report.py --bundle runs/RUN_ID/bundle.json --current-user runs/RUN_ID/current_user.json --output-dir runs/RUN_ID/facts --report runs/RUN_ID/report.html
   ```

   For weekly or monthly reports only, append `--company "展示标题公司名"` when the user explicitly wants a different company name in the rendered title. This is a nonblank presentation-only override: still require and validate `--current-user`, keep `organizationName` in report metadata, and never use the override for authorization, enterprise/data selection, query planning, jobs, or partitions. Diagnosis reports do not accept this override.

Every runner deletes only the launcher extract directories recorded in the bundle in a `finally` block.

## Partial Reports

Data gaps are normal. Always build the best available partial or empty report, including when every query returns no rows.

- Hide charts, tables, navigation items, or analysis modules with no supporting facts.
- In the HTML and user-facing summary, describe omissions in concise business language, for example “缺少历史营业数据，趋势图未展示。”
- Never expose coverage tables, source file names, document/import IDs, query job IDs, internal dataset names, transport error codes, or raw MCP errors in the report.
- Do not fabricate zeros, fill gaps from old workbooks, or describe missing optional dish/catalog modules as service failures.
- Preserve failed or missing saved MCP payloads as `QUERY_RESPONSE_ERROR` or `QUERY_RESPONSE_MISSING` notices during bundle assembly.

## Provenance and Cleanup

Ordinary handoff should lead with the HTML report and briefly name any omitted business sections. Keep technical provenance in the run directory: current user, registry, coverage, manifest, aggregate query results, bundle, facts, summaries, and report. Launcher partition CSVs are temporary source data, not durable evidence.

If any step fails after download but before a bundle reaches a report runner, immediately run:

```bash
python3 scripts/load_partition_extract.py --manifest runs/RUN_ID/query_manifest.json --responses-dir runs/RUN_ID --cleanup-only
```

Do not delete durable evidence before the user has the report. Do not use broad recursive deletion commands for cleanup.
