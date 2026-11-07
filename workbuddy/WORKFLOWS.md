# Three runbooks on WorkBuddy

The authoritative business definitions stay in the upstream workflow
references (`execution.md`, `runtime.md`, `review-execution-policy.md` and
`gmail.md`); the WorkBuddy overlay copies of those references carry a priority
notice pointing here. When any upstream paragraph about browser choice, login
state, save dialogs, download waits or host tools conflicts with this adapter,
`HOST_MAP.md` and this file win. This file contains no tenant data: stores,
source accounts, recipients, brand facts and schedules are read from the frozen
central snapshot at run time.

## Common start (every invocation)

1. Host `automation_update` triggers one conversation. One trigger = one
   invocation; continuation turns of the same run are not new runs.
2. `python3 workbuddy/scripts/wb_state.py resume --root <runRoot>` verifies the
   hash chain of the local state. If an open run exists, keep its `runId`,
   window and binding. Only when the central status confirms no unfinished run
   may `init` open a new one.
3. Read current identity, frozen configuration, designated installation and
   permission card through native tools. Re-check control, assignment epoch and
   lease before any external write.
4. Central `upload` / `download` / `review_sync` / `review_publish` / `email`
   actions go through the native claim/check/record sequence. A long stage
   renews the lease at each bounded step; an unknown result is never replayed.
5. Browser source reads use `wb_browser.py`: `doctor` → `session-start` →
   `navigate` → `snapshot`; `sync --policy target` before any `click`.
   Reuse the same session/tab for the whole scope; revalidate the source
   account, group/brand, exact store name and date filters on the page.
6. Each stage saves verified evidence (exact filters, original files, hashes,
   readback) then updates progress with `save-progress`. Missing or partial
   scope stays pending; a blocked stage uses `mark-blocked`.
7. Close with `wb_state.py close --outcome ...` only after the central run is
   closed and read back. A blocked mail stage makes the outcome `partial`.

## 1. Daily Meituan ingestion

Window: previous complete business day. Only the datasets enabled in
`snapshot.configuration.datasets`, each independently recoverable.

- `business` / `dishes` / `in_store_orders` / `takeaway_orders` /
  `delivery_ledger` map to the same five source skills as upstream. Keep the
  `settled_only` order scope, `全量数据` / `全量菜品` selections, full result
  exports, async export IDs, bounded waits and per-page reconciliation.
- Verify exact columns, row counts, filter evidence, SHA-256 and original
  source store before upload. Never rewrite store names from a mapping.
- Upload only through the core skill's contract; only `published`/`applied`
  receipts permit confirmation and per-file cleanup. Receipt-ledger mappings
  (naturalKey / importBatchId / actionId) are retained outside the cleanup set.
- Zero-result is recorded as `observed_zero` with evidence; it is distinct from
  a missing source, a failed download or a missing column.

## 2. Meituan / Dianping review operations

Window: previous day + today. Read `executionPolicy` and the review skill's
scheduled-run reference before collecting.

- Generate the round `task.json` from the frozen snapshot; iterate the exact
  `sourceIdentityMappings` (account, POI, channel). Do not cross-expand by
  channel. Preserve existing replies, skip rating-only rows, keep the nine
  columns, exact time/score, source reply and feedbackId.
- `review_sync`: freeze the complete identity, payload and existingId; claim,
  then read back every page and compare full fields before recording.
- New-draft notification: **blocked** on this host. `wb_mail.py plan` writes a
  hash-bound local delivery record; no mail is sent and no `email` intent is
  claimed. The frozen workbook and the new-draft list are retained.
- `review_publish`: only when `publication.enabled` and the exact store/channel
  are inside the current central standing authorization. Claim/check, publish,
  read back the real merchant reply, then record `provider_readback`. A
  `partialOverlap` only occupies the listed identities; never resend the batch.
- Archive/cleanup still requires the full seven-gate success check plus the
  central unresolved-action proof. A blocked mail stage does not satisfy them.

## 3. Weekly business report

Window: previous natural week. Use the existing business-analysis chain in
order: `build_query_plan` → official range download → `load_partition_extract`
→ `assemble_query_bundle` → `run_weekly_report` → advisory prepare/attach.

- Pass exact full store names; apply exact-match filtering again after
  extraction. Similar long names must not enter the result. Groups come from
  the central `groups` field; each store belongs to one group only.
- Keep the existing association, quantity and tableware-fee rules. Keep data
  gaps, partial reads and failures distinct.
- Only a report that passes fact/advisory/HTML integrity checks may enter
  delivery. With no native mail, `wb_mail.py plan` records the blocked stage
  and keeps the final HTML locally (`retain_final_report`). No incomplete
  report is delivered.

## Reporting

A normal successful run leaves a short result. Report precisely which stage
was blocked and why, which evidence files were retained, and the exact pending
scope. Never describe a blocked mail stage or a local delivery as a sent
message, and never describe a local state file as a central receipt.
