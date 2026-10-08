---
name: smedc-delivery-ledger
description: Use when uploading original SMEDC delivery receipts, checking automatically updated daily ledger PDF readiness and coordinating ZIP download, or managing receipt-linked quarantine-certificate photos.
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
launcher is `smedc-mcp-launcher@0.8.1`, MCP entry `smedc`. Launcher 0.8.1 is published and
independently verified. This archive workflow also requires service archive delivery enabled.
Use the core Skill's approved installation flow; do not change its pin from service metadata.

If the core Skill is missing, stop before ledger/photo access, identify
<https://github.com/YinXiaoyu-1998/smedc-mcp-skill>, and install only with employee authorization.
Never install another companion automatically. Discover all four archive tools from the connected
host; an absent tool or `LEDGER_PDF_NOT_ENABLED` means the PDF workflow is unavailable/pending.
Report the blocker; do not promise PDFs or recreate them locally. Existing original uploads and
photo operations may proceed through the current approved tools when independently requested.
Read the core Skill's `references/ledger-pdf-tools.md` for strict inputs and error semantics.

## Boundaries

- Use MCP only; no direct HTTP, database, storage, service configuration, passwords, or tokens.
- Admin role is required for original/photo uploads. Preparing a download requires
  service-authorized access to the existing PDFs. Employee agents, including admins, cannot
  trigger PDF generation through MCP or another API; do not bypass these boundaries.
- Do not create local PDF, XLSX, or CSV ledgers, dynamically query rows to export them, append to
  monthly files, or run retired exporter scripts. No OCR, photo conversion/classification,
  authenticity judgment, business analysis, or sibling runtime imports.
- Do not overwrite or edit existing receipts. `RECEIPT_ID_CONFLICT` stays a conflict; explain it
  without changing receipt IDs, reshaping input, deleting old data, or treating it as an update.
- After archive cutover, ledger detail and original ledger CSV/XLSX signing are disabled for all
  roles. Only `count` (no field), `countDistinct(receipt_id)`, and `sum(purchase_amount)` are
  supported, with filters/groups on `store_name` and `purchase_date`. Other datasets are unaffected.
- Ordinary supplier-catalog updates do not trigger historical PDF refresh. Internal operator
  regeneration uses the then-current catalog; employee agents must not request historical refresh.

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
4. After every requested import is actually `applied` and requested photo changes have succeeded,
   confirm the data upload. Use visible `affectedLedgerPartitions` only to summarize the exact
   affected stores/dates; deduplicate them without guessing hidden dates or broadening the scope.
   Do not submit a generation request. The service automatically updates the affected daily PDFs.
   Explain that upload completion does not mean PDF completion. A suitable user-facing reply is:
   “系统会自动更新台账，完成后即可下载；是否就绪以查询结果为准。”
   Keep internal scheduling details out of user-facing replies. Do not infer a fixed run time or
   promise completion within 24 hours; give a completion window only if the service explicitly
   provides one. The ZIP retention period is not an update deadline.
5. For a user-requested download, call `describe_ledger_pdf_coverage` and paginate visible facts
   (200 per page). If a partition is pending, missing, or stale, report that its latest PDF awaits
   automatic updates. Do not claim an old PDF contains new receipts/photos or repeatedly prepare
   ZIPs to force rendering. Recheck coverage when the user returns; do not keep an agent
   polling overnight or set up reminders unless the user asks.
6. Once the requested scope is ready, call `prepare_ledger_pdf_download` with `storeNames`, the exact
   date selection, and a stable operation-specific `idempotencyKey`. It packages existing ready PDFs
   only and never renders/repairs PDFs. Poll `get_ledger_pdf_request_status` while queued/running,
   read all partition pages via `nextCursor`, and inspect the terminal result before claiming success.
7. After successful preparation call `get_ledger_pdf_download_url` with `requestId` for a fresh
   `downloadUrl`/`expiresAt`. Return the short link and scope to the user. The signature lasts
   **15 minutes**; the ZIP is retained **24 hours**. Status contains no URL. Do not proxy/cache PDF
   or ZIP bytes, emit base64, or create local ledger artifacts. If only the link expired, ask the
   service for a fresh URL; if the ZIP expired, prepare again with a new key.

Automatic PDF updates are the normal workflow after uploads and photo changes.
Internal operator CLI backfill/recovery belongs to service operations, not this employee Skill.

## Scope And Failure Handling

Dates must be real `YYYY-MM-DD` calendar dates (years 1000–9999). Choose exactly one of explicit
`dates` or inclusive `startDate`/`endDate`; ranges must be ordered. Each call accepts at most
**50 stores**, **366 dates**, and **5,000 actual partitions** enforced by the server. Use bounded
chunks when necessary, preserving each store's actual date set; do not broaden scope to fill a
limit. Only coverage may omit stores. Cursors are opaque continuations used with the same scope or
request. Inputs are flat strict objects; do not send organization IDs, force/renderer flags,
local paths, binary data, or base64 to PDF tools. Reuse a key only for the same operation/scope;
changed scope or new preparation after terminal failure needs a new key.

- `partial_failed`: inspect every returned partition page and report exact visible successful and
  failed scopes. Do not label the whole request complete; recheck coverage before preparing again
  with a new key. Any partial deliverable must be explicitly described.
- `failed`: report the safe error and affected visible scope; never substitute an old/local PDF.
- `superseded` partition: report that the request was replaced; recheck current coverage before
  preparing another ZIP. Never count it as success, guess another request ID, or trigger generation.
- `empty` partition: no ledger PDF exists for that day; do not generate an empty document.
- `unavailable`, forbidden, or missing: report the safe result. Current permission to every ledger,
  supplier, and certificate source is required on coverage, status, prepare, and each fresh URL.
  Earlier access grants no permission now. Do not infer hidden counts/source IDs or drop photos to
  get a less restricted PDF.
- `LEDGER_PDF_NOT_READY`: explain that the latest PDF awaits an automatic update.
  Preparation/download never causes rendering; retry only after readiness is established.
- `LEDGER_PDF_BUNDLE_STALE`: the old prepared bundle cannot be reused. Recheck coverage and wait
  for automatic updates if needed, then prepare with a new key and obtain a fresh URL.
- `LEDGER_PDF_NOT_ENABLED` / absent tools: stop the PDF workflow and report pending rollout;
  `LEDGER_DETAIL_DISABLED` does not authorize a local detail/export workaround.

Preserve upload idempotency: original uploads reuse a key only for identical bytes/metadata;
photos only for identical bytes, receipt ID, and classification. Map “对账单编号”, “单据号”, and
“收货单号” to `receiptId`; do not change that public field name.
