---
name: smedc-delivery-ledger
description: Use when uploading original SMEDC delivery receipts, coordinating server daily ledger PDF refresh and ZIP download, or managing receipt-linked quarantine-certificate photos.
---

# SMEDC Delivery Ledger

Coordinate original receipt uploads, receipt-linked photos, and service-generated daily PDF archives
through the employee's authenticated `smedc` MCP session. Each PDF covers one exact store and
purchase date, including **all existing receipts and linked photos for that full day**. Its fixed
body is the service's eleven-column `food-purchase-ledger-cn-v2` statutory table; photos follow the
body by receipt ID. A requested month means the daily PDFs in that month, not a local monthly file.
No ledger rows means no empty PDF.

## Prerequisite And Pending Rollout

Use `smedc-mcp` for official installation, updates, repair, and browser login. The current approved
launcher is `smedc-mcp-launcher@0.6.0`, MCP entry `smedc`. This archive workflow requires launcher
**0.7.0 once published** and service archive delivery enabled; 0.7.0 remains unpublished by this
change. Keep installation instructions at 0.6.0 until the separately verified release updates the
core Skill pin. Do not install an unpublished launcher or alter the pin from service metadata.

If the core Skill is missing, stop before ledger/photo access, identify
<https://github.com/YinXiaoyu-1998/smedc-mcp-skill>, and install only with employee authorization.
Never install another companion automatically. Discover all five archive tools from the connected
host; an absent tool or `LEDGER_PDF_NOT_ENABLED` means the PDF workflow is unavailable/pending.
Report the blocker; do not promise PDFs or recreate them locally. Existing original uploads and
photo operations may proceed through the current approved tools when independently requested.
Read the core Skill's `references/ledger-pdf-tools.md` for strict inputs and error semantics.

## Boundaries

- Use MCP only; no direct HTTP, database, storage, service configuration, passwords, or tokens.
- Admin role is required for original/photo uploads and `refresh_ledger_pdfs`. Preparing a download
  requires service-authorized access to the existing PDFs. Do not bypass either boundary.
- Do not create local PDF, XLSX, or CSV ledgers, dynamically query rows to export them, append to
  monthly files, or run retired exporter scripts. No OCR, photo conversion/classification,
  authenticity judgment, business analysis, or sibling runtime imports.
- Do not overwrite or edit existing receipts. `RECEIPT_ID_CONFLICT` stays a conflict; explain it
  without changing receipt IDs, reshaping input, deleting old data, or treating it as an update.
- After archive cutover, ledger detail and original ledger CSV/XLSX signing are disabled for all
  roles. Only `count` (no field), `countDistinct(receipt_id)`, and `sum(purchase_amount)` are
  supported, with filters/groups on `store_name` and `purchase_date`. Other datasets are unaffected.
- Ordinary supplier-catalog updates do not trigger historical PDF refresh. An explicitly requested
  regeneration uses the then-current catalog; do not automatically refresh all historical dates.

## Upload, Refresh And Download

1. Confirm the authenticated session and discover `delivery_ledger` through
   `list_structured_datasets`. For a requested upload, send each original complete receipt CSV/XLSX
   using `upload_structured_dataset` with `dataset: "delivery_ledger"`, `enterpriseName`, file,
   stable `idempotencyKey`, and only an explicit user-specified `confidentialityLevel` (otherwise
   omit it). Prefer path upload. Do not send date bounds or snapshotDate, normalize receipt data,
   or convert photos into a table.
2. HTTP **202** is accepted, not applied. Keep `importBatchId` and poll `get_import_status` until
   `importBatch.status=applied`. Never treat queued/pending/rejected/failed as success. An applied
   import returns `affectedLedgerPartitions` (also in its applied `importBatch`); collect those
   server facts only after actual application. Replays may return the same facts; deduplicate them.
3. For user-requested photo changes, upload each JPG/JPEG/PNG with
   `upload_quarantine_certificate`, one `receiptId`, stable `idempotencyKey`, and only explicit
   classification. Photos do not require an existing receipt. Query with
   `query_quarantine_certificates` using 1–100 explicit `receiptIds`. Archive one visible photo
   with `archive_quarantine_certificates` and `sourceDocumentId`; archive by `receiptId` only for
   an admin's explicit bulk request. After successful synchronous photo upload/archive, collect
   top-level `affectedLedgerPartitions`; archive also returns `archivedCount`. Do not invent dates
   for a photo with no affected ledger. Eligible photo originals use
   `get_source_document_download_url`; return its link without fetching the bytes.
4. Deduplicate affected facts by exact `(storeName, purchaseDate)`. Build **one refresh scope per
   store and that store's actual date set**, using `storeNames: [storeName]` and `dates`. Never
   combine different stores' differing date sets into a Cartesian product. Example: facts A/10-01,
   A/10-03, B/10-02 require A dates [10-01,10-03] and B dates [10-02], not both stores over all three
   dates. Preserve full YYYY-MM-DD values and exact store names; no trimming or inferred dates.
   If hints are absent/empty, do not invent a refresh scope or assume no hidden data exists.
5. For each bounded scope call `refresh_ledger_pdfs` with a stable operation-specific
   `idempotencyKey`. Poll `get_ledger_pdf_request_status` while `queued`/`running` and read all
   partition pages through `nextCursor`. Wait for terminal `succeeded`, `partial_failed`, or
   `failed`; resolve failures as below before claiming the requested archive is ready.
6. For the user's requested download scope, use `describe_ledger_pdf_coverage` and paginate all
   visible facts (200 per page). Use `prepare_ledger_pdf_download` with `storeNames`, the exact
   date selection, and a separate `idempotencyKey`. It packages existing ready PDFs only and never
   renders/repairs missing or stale PDFs. Poll the returned request to terminal and inspect pages.
7. After successful preparation call `get_ledger_pdf_download_url` with `requestId` for a fresh
   `downloadUrl`/`expiresAt`. Return the short link and scope to the user. The signature lasts
   **15 minutes**; the ZIP is retained **24 hours**. Status contains no URL. Do not proxy/cache PDF
   or ZIP bytes, emit base64, or create local ledger artifacts. If only the link expired, ask the
   service for a fresh URL; if the ZIP expired, prepare again with a new key.

The daily **03:00 Asia/Shanghai** reconciliation is a fallback. It does not replace proactive
refresh after an applied original upload or successful photo mutation. Missing readiness requires
an authorized refresh, not waiting until tomorrow while claiming upload produced the final PDF.

## Scope And Failure Handling

Dates must be real `YYYY-MM-DD` calendar dates (years 1000–9999). Choose exactly one of explicit
`dates` or inclusive `startDate`/`endDate`; ranges must be ordered. Each call accepts at most
**50 stores**, **366 dates**, and **5,000 actual partitions** enforced by the server. Use bounded
chunks when necessary, preserving each store's actual date set; do not broaden scope to fill a
limit. Only coverage may omit stores. Cursors are opaque continuations used with the same scope or
request. Inputs are flat strict objects; do not send organization IDs, force/renderer flags,
local paths, binary data, or base64 to PDF tools. Reuse a key only for the same operation/scope;
changed scope, a new retry after terminal failure, or new preparation needs a new key.

- `partial_failed`: inspect every returned partition page and report exact visible successful and
  failed scopes. Do not label the whole request complete; retry only failed visible store/date
  scopes when appropriate with a new key. Any partial deliverable must be explicitly described.
- `failed`: report the safe error and affected visible scope; never substitute an old/local PDF.
- `superseded` partition: the requested generation did not complete. Follow its visible
  `latestRequest` reference and wait for that request; absent a visible reference, report the safe
  blocker. Never count it as success or guess another request ID.
- `empty` partition: no ledger PDF exists for that day; do not generate an empty document.
- `unavailable`, forbidden, or missing: report the safe result. Current permission to every ledger,
  supplier, and certificate source is required on coverage, status, prepare, and each fresh URL.
  Earlier access grants no permission now. Do not infer hidden counts/source IDs or drop photos to
  get a less restricted PDF.
- `LEDGER_PDF_NOT_READY`: wait for the authorized refresh or explain that an admin must refresh.
  Preparation/download never causes rendering; retry only after readiness is established.
- `LEDGER_PDF_BUNDLE_STALE`: the old prepared bundle cannot be reused. Complete the needed refresh,
  then prepare a new request with a new key and obtain a fresh URL.
- `LEDGER_PDF_NOT_ENABLED` / absent tools: stop the PDF workflow and report pending rollout;
  `LEDGER_DETAIL_DISABLED` does not authorize a local detail/export workaround.

Preserve upload idempotency: original uploads reuse a key only for identical bytes/metadata;
photos only for identical bytes, receipt ID, and classification. Map “对账单编号”, “单据号”, and
“收货单号” to `receiptId`; do not change that public field name.
