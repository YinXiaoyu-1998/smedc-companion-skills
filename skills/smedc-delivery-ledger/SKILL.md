---
name: smedc-delivery-ledger
description: Use when querying SMEDC delivery ledger rows, exporting the statutory food-purchase ledger CSV, or managing receipt-linked quarantine-certificate photos.
---

# SMEDC Delivery Ledger

Query and present the SMEDC `delivery_ledger` structured dataset, optionally export its statutory CSV table, and manage quarantine-certificate photos linked to receipt IDs. The employee-owned agent performs all SMEDC MCP calls through the user's authenticated launcher session.

**Required prerequisite:** Use `smedc-mcp` for official SMEDC install, update, repair, login, and MCP session setup. The official launcher package is `smedc-mcp-launcher@0.6.0`, and the MCP entry is `smedc`.

If `smedc-mcp` is not installed, do not begin ledger or photo access. Explain that it is required, identify the official source at <https://github.com/YinXiaoyu-1998/smedc-mcp-skill>, and offer to install it only if the employee explicitly authorizes that installation. Never install it silently. Never install or import `smedc-business-analysis` automatically.

## Boundaries

- Do not perform business analysis, dashboarding, OCR, photo classification, authenticity judgment, PDF/XLSX output, or sibling skill runtime imports.
- Use only the user's authenticated SMEDC MCP session. Do not use direct HTTP, service databases, service configuration, internal storage, passwords, or tokens.
- Present `收货单号` / `receipt_id` in normal ledger tables and CSV output. Present `entry_id`, `store_name`, and `source_document_id` only if the user separately asks for operational provenance, except that `store_name` is required as internal routing input for per-store monthly CSV maintenance.
- Never add quarantine-certificate photo metadata or URLs to CSV output.
- Never OCR, classify, modify, or authenticate certificate images.

## Ledger Workflow

1. Confirm the `smedc-mcp` prerequisite and authenticated `smedc` MCP session.
2. Call `list_structured_datasets` and confirm dataset `delivery_ledger` exposes profile `food-purchase-ledger-cn-v2`.
3. Compare the service profile with local `config/food-purchase-ledger-cn-v2.json`. The `id`, `title`, column count, canonical names, display names, and order must match exactly. If they differ, fail closed and ask the user to update the Skill or launcher before continuing.
4. Query `query_structured_dataset` in `detail` mode with these canonical fields in this exact order:

   ```text
   receipt_id
   item_name
   specification
   purchase_quantity
   purchase_amount
   production_date_or_batch
   shelf_life
   supplier_name
   supplier_unit_address
   supplier_contact_phone
   purchase_date
   ```

5. Paginate only through the bounded scope the user requested. Do not broaden the query window, store scope, or row count to make the table look fuller.
6. Present the table title `食品经营单位进货台帐` and Chinese display names verbatim from the service profile:

   ```text
   收货单号
   食品名称
   规格
   进货数量
   进货金额
   生产日期或生产批号
   保质期
   供货单位名称
   供货单位地址
   供货单位联系方式
   进货日期
   ```

## CSV Export

Use `scripts/export_ledger_csv.py` only when the user requests CSV output. Treat the raw query result as an internal transient input, not a user deliverable. Create an agent-owned file in a system temporary directory outside the requested output directory, install a finally/trap cleanup before writing it, and save one exact `query_structured_dataset` result object containing the service `presentation` key, or an array of paginated result objects in request order, as UTF-8 JSON. Run the exporter with `--delete-input`; it removes that input after both successful export and handled validation failure:

```bash
python3 scripts/export_ledger_csv.py TEMP_INPUT_JSON OUTPUT_CSV --delete-input
```

Use `--overwrite` only when the user explicitly asks to replace an existing CSV:

```bash
python3 scripts/export_ledger_csv.py TEMP_INPUT_JSON OUTPUT_CSV --overwrite --delete-input
```

The surrounding finally/trap must remove the exact temporary input and its empty temporary directory if execution is interrupted or the exporter never starts. Do not place the input JSON in the CSV output directory or leave it anywhere after the run. Do not present, link, or mention the temporary query JSON. Present only the requested CSV file or files and a concise export/maintenance result. If the user explicitly requests the raw query response as a separate deliverable, write that requested artifact separately; it is not the exporter's temporary input.

In any CSV mode, if the validated result contains zero rows, the exporter exits successfully, prints a compact JSON no-op summary, creates no CSV, and leaves any existing target byte-identical even when `--overwrite` was supplied.

For common requests such as “生成通州店 2026 年 9 月的台账 CSV”, use the per-store monthly create-or-maintain mode. Query the bounded requested scope in `detail` mode and include internal `store_name` in each returned row in addition to the eleven profile fields. Save the exact result JSON only at the temporary input path described above, then run:

```bash
python3 scripts/export_ledger_csv.py TEMP_INPUT_JSON --store-month-dir OUTPUT_DIR --month 2026-09 --delete-input
```

This mode writes conventional files named `食品经营单位进货台帐_<门店名>_<YYYY-MM>.csv`. If a conventional valid CSV already exists, the exporter automatically maintains it: an incoming `收货单号` already present in that file skips the entire receipt, while a new `收货单号` appends all rows for that receipt without row-level deduplication. Do not ask for extra overwrite/update wording for this normal generate request. The internal `store_name` may not contain control characters or Windows-invalid filename characters `<>:"/\|?*`. If two distinct store names would resolve to the same filename after Unicode normalization and case-folding on a typical macOS filesystem, fail closed and ask the user to disambiguate the store scope before writing.

The exporter writes UTF-8 with BOM, uses the eleven Chinese headers in statutory order, renders absent values, JSON `null`, and the service's literal `"null"` sentinel as empty cells for nullable columns, validates dataset/mode/presentation/rows before writing, quotes with Python standard-library `csv.writer`, prefixes spreadsheet formula-leading cells with a single quote, validates requested month/store filenames/affected existing CSV files for per-store maintenance, and atomically replaces output through a temporary file. The per-store monthly mode emits a compact JSON run summary on stdout.

## Quarantine-Certificate Photos

Map user phrases “对账单编号”, “单据号”, and “收货单号” to the public field `receiptId`. Do not rename the API field and do not require a matching ledger row to exist.

- Upload: call `upload_quarantine_certificate` once per JPG/JPEG/PNG image with exactly one `receiptId`, one stable `idempotencyKey`, and only a user-specified `confidentialityLevel`; otherwise omit it so the service default applies. Multiple photos require multiple calls. Prefer path encoding where supported.
- Query: call `query_quarantine_certificates` with 1-100 explicit `receiptIds`. Empty visible results reveal nothing about higher-confidentiality images.
- Download: call `get_source_document_download_url` with a returned visible `sourceDocumentId`; return the time-limited link and do not proxy or fetch bytes.
- Archive one: call `archive_quarantine_certificates` with `sourceDocumentId`.
- Archive all for receipt: use `receiptId` only when the authenticated user is an admin and explicitly requested bulk archive.
- Reuse an idempotency key only for the exact same bytes, receipt ID, and confidentiality level.
