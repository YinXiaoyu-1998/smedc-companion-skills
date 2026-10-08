---
name: smedc-business-analysis
description: Use when generating tenant-neutral SMEDC diagnosis, weekly, or monthly operating reports from structured business datasets.
---

# SMEDC Business Analysis

Generate operating diagnosis, weekly meeting, and monthly meeting reports from SMEDC structured data. The employee-owned agent performs the MCP calls through the user's authenticated launcher session; the local scripts validate saved SMEDC envelopes, aggregate launcher-managed partition extracts, and render self-contained HTML.

**Required prerequisite:** Use `smedc-mcp` for official SMEDC install, update, repair, login, and MCP session setup. The official launcher package is `smedc-mcp-launcher@0.7.1`, and the MCP entry is `smedc`.

**Release gate for this branch:** Generated plans use filtered range downloads. Wait until Launcher **0.8.0 is published and independently verified** and the matching filtered range service is deployed. The installed/pinned 0.7.1 does not accept new filter inputs. Keep pins unchanged until verification; unfiltered existing range downloads remain available on 0.7.1.

If `smedc-mcp` is not installed, do not begin report data access. Explain that it is required, identify the official source at <https://github.com/YinXiaoyu-1998/smedc-mcp-skill>, and offer to install it only if the employee explicitly authorizes that installation. Never install it silently. Never install or import `smedc-delivery-ledger` automatically.

## Optional bundle download mode

Range is the default. Add `--download-mode bundle` to `build_query_plan.py` only after Launcher **0.8.1 is published and independently verified** and the matching ZIP service deployment is known available. `--download-mode range` explicitly selects the foundation workflow. Tools/list alone cannot establish service availability: Launcher contracts are statically registered. The installed pin remains 0.7.1 until release verification.

Bundle extracts alone emit these steps:

1. `prepare_structured_partition_download` takes the selector and persisted `idempotencyKey`. Save the full response and retain its `requestId`.
2. `get_structured_partition_download_status` takes only `requestId`; wait `retryAfterSeconds` while queued/running. Check MCP `isError` and failed/expired status on every call.
3. Only succeeded packaging permits `download_structured_partitions` with only `requestId`, without selectors. Save the full verified local envelope at `outputFile`; packaging success alone is not a local success.

Each bundle run gets a persisted preparation generation/key. Saved exact retries retain it. `record-result` also accepts bundle prepare/status envelopes. On stale/expired bundle failures, `split-failed` renews the same scope with a fresh generation/key, including one day; other failed batches keep the common date splitting rules. Merge and split preserve the selected downloadMode. Mixed range/bundle plans are rejected clearly; regenerate all inputs in one selected mode. Legacy bundle JSON without an explicit mode also requires regeneration.

If ZIP support is removed or unsupported, regenerate saved plans with `--download-mode range`. Do not silently retry a bundle failure as range. Authentication, integrity and source-scope failures stop the workflow; they must never be bypassed. Source filters and successful-local-batch validation/sharing/refcount cleanup apply identically to both modes.

## Boundaries

- Before querying report data, call `smedc_get_current_user` and save the full response as `current_user.json`.
- The only report-company source is `smedc_get_current_user.user.organizationName`. Missing, non-string, or blank organization names are a contract error; stop and tell the user their SMEDC account organization must be corrected.
- Do not infer a report company from display name, email/domain, filenames, partition `enterpriseName`, store names, configuration defaults, or examples.
- `enterpriseName` remains only the structured-data selector used for coverage and partition downloads.
- Use these SMEDC MCP tools for reports: `smedc_get_current_user`, `list_structured_datasets`, `describe_structured_dataset_coverage`, `download_structured_partitions`, `query_structured_dataset`, and, when an upload is still processing, `get_partition_import_status`.
- Do not use direct HTTP, service databases, service configuration, or internal storage.
- Do not handle passwords or tokens.
- Do not request, reveal, copy, or persist presigned URLs. Let `download_structured_partitions` consume them inside the launcher and return a launcher-managed local directory.
- Do not ingest user-provided local CSV, XLSX, or workbook files as a compatibility report source.
- Do not add monthly profit or profit-rate reporting.

## Workflow

1. Use `smedc-mcp` to install or verify `smedc-mcp-launcher@0.7.1`, configure the `smedc` MCP entry, and complete login. Continue only after the authenticated MCP session exposes the business tools.

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

5. Call `describe_structured_dataset_coverage` once for each canonical dataset, in this order: `business`, `dishes`, `dish_catalog`. Save the envelopes as `coverage_business.json`, `coverage_dishes.json`, and `coverage_dish_catalog.json`. After selecting `enterpriseName`, obtain scoped business/dishes coverage with that enterprise and the same `storeNameContains` used for the report, once the release gate is met. Generated `coverageRequests[]` records these exact inputs; repeat coverage and regenerate the plan if the selection changes. Do not infer `storeIds` from coverage.

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

   Use `--report-type diagnosis`, `weekly`, or `monthly`. Add `--store-name-contains` only when the employee requests a store-name scope; omit it for the complete enterprise. The option accepts 1–20 trimmed, NFC-normalized nonblank fragments of at most 255 characters each and keeps a store when its name contains any fragment (case-sensitive). The same filter applies to business and dishes before local aggregation, across current, previous, YoY, and trend windows. `全体门店` in a filtered report means the selected stores' combined total. Every extract selector and business/dishes coverage request carries the same service-side scope. Local name checks validate the service result; a scoped download containing an out-of-scope store is a contract failure, not a reason to silently drop its rows. Do not narrow it using `storeIds` inferred from coverage, which can omit stores without merchant IDs. Do not apply a one-off filter only to the rendered report or only to the current week. Data coverage decides which modules can be shown; it must never change the requested reporting period.

7. Check `releaseGate` before executing any generated extract. Business slices stay within a natural month; dishes slices contain at most seven inclusive days. Adjacent/overlapping reporting windows are merged before slicing, so current/previous/YoY/year-trend coverage does not duplicate downloads.

   For each extract, follow its `steps[]` through the employee's ordinary MCP session:
   - Execute each extract's single range `download_structured_partitions` step with its dataset, enterprise, dates and optional store filters. Save the complete successful local envelope at `outputFile`.
   - Check MCP `isError`; failed downloads stop materialization and never imply empty data. A range extract never requires a server-side preparation request.

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

Every runner cleans launcher extracts in a `finally` block. For a shared bundle it releases that report in the persisted consumer ledger; only the last consumer deletes the shared directory. An unavailable or malformed shared ledger never falls back to unconditional deletion.

## Shared Plans and Failure Recovery

Merge plans before data access, giving each report a distinct optional `reportId` (otherwise deterministic IDs are assigned):

```bash
python3 scripts/partition_download_plan.py merge --plans runs/WEEK/query_manifest.json runs/MONTH/query_manifest.json --output runs/shared_download_index.json --reports-dir runs/shared_reports
```

The saved JSON index owns each unique extract and its consumer/release/download state. `reports` contains independently materializable query plans with `extractRefs` and `sharedDownload`; `--reports-dir` saves those plans as JSON files. Use a common responses directory for their shared extract `outputFile` paths and deterministic per-report aggregate/result subdirectories and preserve `sharedDownload` through bundle assembly. Scope identity includes dataset, enterprise, organization, date range, and normalized filters. Same-scope overlapping report windows are subdivided at common coverage boundaries into bounded batches, even when weekly and monthly boundaries differ. Verified successful local batches remain intact; only uncovered dates need a new download. Different enterprises, organizations or store filters never share. Plans retain their range download steps through sharing and date splits. Execute only extracts that are not already verified `succeeded`. Reuse a successful batch only while its saved full envelope and local files pass validation; keep its response at the shared `outputFile`. Local partition store/date identities are deduplicated to prevent double counting; conflicting versions fail.

Record each saved local download envelope in the index, including errors:

```bash
python3 scripts/partition_download_plan.py record-result --index runs/shared_download_index.json --extract-id EXTRACT_ID --response runs/SAVED_RESPONSE.json
```

For a timed-out or oversized failed batch, record failure first, then replace it deterministically with two nonoverlapping date halves:

```bash
python3 scripts/partition_download_plan.py split-failed --plan runs/shared_download_index.json --extract-id EXTRACT_ID --output runs/shared_download_index.json
```

The failed parent is removed from every consumer reference; an already planned matching child retains its state and combines consumers. Only replacement children participate in aggregation. Saved shared reports resolve the current index, so a failed parent cannot be counted. A one-day failure stops and requires a narrower employee-approved store scope. Never guess merchant IDs, silently exclude stores or treat failures as missing business data.

If a shared report stops before a runner can finalize it, release it explicitly:

```bash
python3 scripts/partition_download_plan.py release-report --index runs/shared_download_index.json --report-id REPORT_ID
```

Release is idempotent; the ledger persists after source CSV cleanup. Release and result-recording CLI updates serialize on a local ledger lock (POSIX flock or Windows byte-range locking). Plan merging/splitting must finish before concurrent consumers read or release that ledger.

## Revenue Trend Interaction

Weekly reports download and aggregate the latest 52 complete seven-day windows ending on the requested current-period end, plus 52 matching windows ending on the requested YoY-period end. Treat this as a rolling year (364 days), not a calendar year. Keep the requested reporting period and other report modules unchanged. Missing weeks retain their positions and unknown values; do not connect lines across gaps.

The self-contained HTML starts with the full year. Employees can drag either edge of the overview to resize the displayed interval, drag the selected interval to move it, or choose its start and end from labeled selectors. Shortcuts show the latest 2, 5, or 16 weeks and restore the full year. Both comparison lines use the same selected positions; switching stores preserves the interval. Monthly reports download and aggregate the latest 12 complete calendar months, plus the matching 12 months from the previous year. If the requested end falls within an incomplete month, end the trend at the last complete month. Month-specific controls show the latest two months or restore the full year; arbitrary monthly intervals use the same overview and selectors. Previously generated HTML is static; generate a new report with a new query plan to obtain the expanded history.

## Partial Reports

Data gaps are normal. Always build the best available partial or empty report, including when every query returns no rows.

- Hide charts, tables, navigation items, or analysis modules with no supporting facts.
- In the HTML and user-facing summary, describe omissions in concise business language, for example “缺少历史营业数据，趋势图未展示。”
- Never expose coverage tables, source file names, document/import IDs, query job IDs, internal dataset names, transport error codes, or raw MCP errors in the report.
- Do not fabricate zeros, fill gaps from old workbooks, or describe missing optional dish/catalog modules as service failures.
- Preserve failed or missing saved row-query MCP payloads as `QUERY_RESPONSE_ERROR` or `QUERY_RESPONSE_MISSING` notices during bundle assembly. Partition download failures stop materialization and require recovery; they never yield successful empty aggregates.

## Provenance and Cleanup

Ordinary handoff should lead with the HTML report and briefly name any omitted business sections. Keep technical provenance in the run directory: current user, registry, coverage, manifest, aggregate query results, bundle, facts, summaries, and report. Launcher partition CSVs are temporary source data, not durable evidence.

If any step fails after download but before a bundle reaches a report runner, immediately run:

```bash
python3 scripts/load_partition_extract.py --manifest runs/RUN_ID/query_manifest.json --responses-dir runs/RUN_ID --cleanup-only
```

Do not delete durable evidence before the user has the report. Do not use broad recursive deletion commands for cleanup.
