---
name: smedc-delivery-ledger
description: Use when querying SMEDC delivery ledger rows, exporting or maintaining food-purchase ledger spreadsheets with text-safe phone numbers, or managing receipt-linked quarantine-certificate photos.
---

# SMEDC Delivery Ledger

Query and present the SMEDC `delivery_ledger` structured dataset, export its statutory table as XLSX by default or CSV when explicitly requested, and manage quarantine-certificate photos linked to receipt IDs. The employee-owned agent performs all SMEDC MCP calls through the user's authenticated launcher session.

**Required prerequisite:** Use `smedc-mcp` for official SMEDC install, update, repair, login, and MCP session setup. The official launcher package is `smedc-mcp-launcher@0.6.0`, and the MCP entry is `smedc`.

If `smedc-mcp` is not installed, do not begin ledger or photo access. Explain that it is required, identify the official source at <https://github.com/YinXiaoyu-1998/smedc-mcp-skill>, and offer to install it only if the employee explicitly authorizes that installation. Never install it silently. Never install or import `smedc-business-analysis` automatically.

## Boundaries

- Do not perform business analysis, dashboarding, OCR, photo classification, authenticity judgment, PDF output, or sibling skill runtime imports.
- Use only the user's authenticated SMEDC MCP session. Do not use direct HTTP, service databases, service configuration, internal storage, passwords, or tokens.
- Present `收货单号` / `receipt_id` in normal ledger tables and exported files. Present `entry_id`, `store_name`, and `source_document_id` only if the user separately asks for operational provenance, except that `store_name` is required as internal routing input for per-store monthly maintenance.
- Never add quarantine-certificate photo metadata or URLs to exported files.
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

## Spreadsheet Export

When the user asks to export/download a ledger or generate an Excel/spreadsheet file without choosing a format, use **XLSX**. Preserve an explicit CSV request. For a table to display in chat, follow Ledger Workflow without creating a file. Use `scripts/export_ledger.py` for file exports; do not recreate the exporter, coerce phone numbers to numbers, or round identifiers yourself.

XLSX needs `openpyxl` from this skill's `requirements.txt`. Check the selected Python interpreter with `python3 -c 'import openpyxl'`. If missing, create an agent-owned virtual environment outside the output directory, install with `VENV/bin/python -m pip install -r requirements.txt`, and run the exporter with that interpreter. Do not modify unrelated Python environments or silently fall back to CSV. If dependency setup fails, report the narrow blocker.

Treat the raw query result as an internal transient input, not a user deliverable. Create an agent-owned file in a system temporary directory outside the requested output directory, install a finally/trap cleanup before writing it, and save one exact `query_structured_dataset` result object containing the service `presentation` key, or an array of paginated result objects in request order, as UTF-8 JSON. Run the exporter with `--delete-input`; it removes that input after both successful export and handled validation failure:

```bash
python3 scripts/export_ledger.py TEMP_INPUT_JSON OUTPUT.xlsx --delete-input
```

For an explicit CSV request, use an `.csv` output filename (or `--format csv` in monthly mode):

```bash
python3 scripts/export_ledger.py TEMP_INPUT_JSON OUTPUT.csv --delete-input
```

XLSX saves phone numbers, receipt IDs, batches, dates, and other non-measure columns as literal string cells with text format `@`, preserving leading zeros and `+` prefixes without formulas or extra apostrophes. Quantities and amounts remain numeric. The exporter sets readable column widths, a frozen header, and filters. It rejects numeric or scientific-notation phone inputs rather than guessing lost digits; ask for the original phone string when that validation fails. CSV retains exact characters and formula-prefix protection, but cannot encode cell types; spreadsheet viewers may still infer numeric phones. Do not promise text-type preservation for CSV. The legacy `export_ledger_csv.py` entry point remains compatible and defaults to CSV.

Use `--overwrite` only when the user explicitly asks to replace an existing single output file. The surrounding finally/trap must remove the exact temporary input and its empty temporary directory if execution is interrupted or the exporter never starts. Do not place the input JSON in the output directory or leave it anywhere after the run. Do not present, link, or mention the temporary query JSON. Present only the requested exported files and a concise result. If the user explicitly requests the raw query response as a separate deliverable, write that artifact separately.

In either format, zero validated rows produce a successful no-op summary, create no output, and leave an existing target byte-identical even with `--overwrite`.

For requests such as “生成通州店 2026 年 9 月的台账”, use per-store monthly create-or-maintain mode. Query the bounded requested scope in `detail` mode and include internal `store_name` in each returned row in addition to the eleven profile fields. Save the exact result JSON at the temporary input path described above, then run:

```bash
python3 scripts/export_ledger.py TEMP_INPUT_JSON --store-month-dir OUTPUT_DIR --month 2026-09 --delete-input
```

This mode defaults to `食品经营单位进货台帐_<门店名>_<YYYY-MM>.xlsx`; add `--format csv` only for an explicit CSV request. It maintains valid conventional files of the selected format: a receipt already present skips the entire receipt, while a new receipt appends all its rows without row-level deduplication. Do not ask for extra overwrite/update wording for this normal generate request. Existing CSV files are not automatically migrated, removed, or overwritten when choosing XLSX. Existing XLSX must contain one ledger worksheet with the exact headers, literal text identifiers/phones, and dates in the requested month; invalid files fail before any store is written. Maintenance regenerates the standard ledger layout, so custom worksheet formatting is not preserved. The internal `store_name` may not contain control characters or Windows-invalid filename characters `<>:"/\|?*`. Filename collisions after Unicode normalization and case-folding fail closed; ask the user to disambiguate the store scope.

Both formats use the eleven Chinese headers in statutory order, render nullable absent values/JSON `null`/literal `"null"` as empty cells, validate inputs and affected existing files before writing, and atomically replace each output through a temporary file. CSV uses UTF-8 with BOM and Python `csv.writer`. Monthly mode emits a compact JSON run summary on stdout.

## Quarantine-Certificate Photos

Map user phrases “对账单编号”, “单据号”, and “收货单号” to the public field `receiptId`. Do not rename the API field and do not require a matching ledger row to exist.

- Upload: call `upload_quarantine_certificate` once per JPG/JPEG/PNG image with exactly one `receiptId`, one stable `idempotencyKey`, and only a user-specified `confidentialityLevel`; otherwise omit it so the service default applies. Multiple photos require multiple calls. Prefer path encoding where supported.
- Query: call `query_quarantine_certificates` with 1-100 explicit `receiptIds`. Empty visible results reveal nothing about higher-confidentiality images.
- Download: call `get_source_document_download_url` with a returned visible `sourceDocumentId`; return the time-limited link and do not proxy or fetch bytes.
- Archive one: call `archive_quarantine_certificates` with `sourceDocumentId`.
- Archive all for receipt: use `receiptId` only when the authenticated user is an admin and explicitly requested bulk archive.
- Reuse an idempotency key only for the exact same bytes, receipt ID, and confidentiality level.
