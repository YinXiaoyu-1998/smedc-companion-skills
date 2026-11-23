---
name: smedc-inspection
description: 在授权门店读取企业智脑（SMEDC）巡检卷、按现场证据填报并管理巡检模板草稿。 Use for inspection questionnaires, evidence-backed answers, photo evidence, and template drafts in SMEDC.
---

# SMEDC Inspection

Read and fill one authorized store's inspection questionnaire for a business date, or prepare a
template draft for explicit review and activation. The agent works through the employee's
authenticated `smedc` MCP session. The service locks each sheet to a template version; the agent
collects evidence and submits explicit changes, but does not certify the inspection or invent
business judgments.

## Prerequisite And Candidate Rollout

Use `smedc-mcp` for official installation, updates, repair, browser login, and the approved exact
launcher pin. This companion owns no separate installation version; never choose npm `latest` or
derive a pin from service metadata. Do not install this Skill or the core Skill silently. Do not
create a recurring task or add a server endpoint for this workflow.

The inspection service is a **source candidate**, not a launch claim. This repository, an installed
copy, or a tools/list entry does not prove deployment, tenant enablement, authorization, or release.
Before actual use, require all four public tools:

- `query_inspections`
- `manage_inspection_templates`
- `write_inspections`
- `upload_inspection_photo`

Also require a compatible running service and current permission for the exact target: an
authorized store for reading/filling sheets and photos, or enterprise template-maintenance (T)
permission for drafts. Tool discovery alone cannot establish service availability. If a tool, the
service, or the live permission is missing, stop and report that actual gap. Do not substitute
structured-data upload, quarantine-certificate, import, browser, or direct HTTP workarounds.

## Scope And Authority

- Resolve the business enterprise, official store, and inspection date from `context` and the
  user's request. Never infer `enterpriseKey`, `storeId`, or the date from a display name, filename,
  previous tenant, or another enterprise's same-named store. Use dates that exist as calendar dates.
- Keep the user's delegation. Do not broaden to other stores, dates, sheets, questions, or photos,
  and do not treat a template list as a store roster.
- Store read and write permission is required for sheets and photos; every write rechecks the
  target sheet, component, photo, and current status. T permission covers template list, draft
  definitions, and empty-draft preview; it does not grant access to an actual sheet or photo. A
  template draft does not create or grant access to a store sheet.
- Revocation, suspension, cross-tenant, or cross-store access stops the task. Reusing an old
  `sheetId`, `photoId`, cursor, or cached answer never restores access.

## Tool Shapes

The first three tools take one top-level `command` object with a discriminated `action`.
`upload_inspection_photo` is a single flat operation and has no `command` wrapper.

- `query_inspections`: `command.action` is `context`, `day`, `sheet`, or `photo`.
- `manage_inspection_templates`: `command.action` is `list`, `preview`, `create`, `save`,
  `activate`, or `deactivate`.
- `write_inspections`: `command.action` is `create`, `void`, `patch`,
  `preview_replacement`, or `replace`.
- `upload_inspection_photo`: flat scope plus `requestId`, `mediaType`, and an absolute
  `filePath`.

`query_inspections` with action `photo` writes a verified original to a private temporary file and
returns its `localPath` plus `photoId`, `mediaType`, `byteLength`, and `sha256`. Read the image from
that local file. `localPath` is a download result, never upload content: do not pass `localPath`,
file bytes, or a data URL as a base64 argument. For upload, pass the readable absolute path as
`filePath`; the launcher performs the scoped write preflight and reads the original bytes.

## Read And Select The Actual Sheet

1. Call `query_inspections` with `command.action: "context"`. Page through the authorized enterprises
   and stores; use the exact `enterpriseKey` and `storeId`. An optional exact store/date preflight
   reports the capabilities for that scope. Confirm the required read or fill capability before
   continuing.
2. Call action `day` with `enterpriseKey`, `storeId`, `inspectionDate`, and pagination. Page until
   `nextCursor` is null. Items of kind `template` are entry points, not empty sheets; items of kind
   `sheet` are existing effective sheets. Viewing a date never creates a sheet.
3. If several effective sheets match the same store and date, present the names and `sheetId`
   values and ask the user to choose. Names may repeat; do not select by position, guessed name, or
   the latest row. A single-copy template can return an `ambiguous` create conflict when candidates
   exist: re-read `day` and choose among them instead of retrying creation.
4. Call action `sheet` with the chosen `sheetId` and page through every question page. Read the
   sheet's fixed `templateVersionId`, `sheetRevision`, each `questionRevision`,
   `componentRevision`, current answers, and missing required items. A cursor is bound to the
   sheet revision; on `stale_cursor` or another revision conflict, restart from the sheet's first
   page and re-evaluate.
5. Use the sheet's locked `templateVersionId` for writes. A newer active template does not change an
   existing sheet. Never patch according to the current template definition or silently replace the
   sheet to make the versions agree.

## Fill With Evidence

The default is to fill blank components and append relevant photo references. Preserve existing
answers, statuses, comments, scores, and photo references unless the user explicitly asks to
correct or remove them.

- Attach each submitted change to evidence actually available in this request, such as the user's
  observation, a readable source, or an image the model can see. A filename, path, upload receipt,
  template SOP, or old answer is not proof of the current site condition.
- Leave items blank when evidence is missing, unreadable, or needs a site demonstration. Say which
  `sheetId`, `questionId`, and `componentId` still need evidence or a photo.
- Scores are integer tenths: 8.5 displayed points is `85`. Status values use the option `id`, not
  its label. Comments must be nonblank after trimming. Photo components use `photoId` arrays.
- Before correcting an existing value, show the current value, the proposed value, and the evidence,
  and obtain explicit user direction. Then use the read `expectedComponentRevision` with `set`,
  `clear`, or `removePhotos`. `fill` is only for an empty component and fails with `nonempty`;
  a conflicting observation is not permission to overwrite.

### Photo branches

- **Launcher can read a path:** upload once for the exact enterprise/store/date with a
  `requestId` stable for identical bytes and scope, the declared `mediaType`, and an absolute
  `filePath` to an original JPEG or PNG. The launcher verifies current fill permission and the file
  bytes. Reference the returned `photoId` with `appendPhotos` before its `expiresAt` (up to 24 hours).
  If the model cannot see the image, do not infer its content from the filename or receipt.
- **The model sees image content but the launcher has no readable path:** do not claim an upload and
  do not fabricate a `photoId`. Preserve the supported textual finding, leave the photo component
  blank, and report the exact sheet/question/component location for the employee to add the photo in
  the web page. If the user later supplies a readable absolute path, upload then and append it.

One uploaded photo can be referenced by multiple components or effective sheets in the same store
and date; appending the same `photoId` again must not duplicate the reference. Reuse the existing
reference instead of re-uploading the same evidence. A photo outside that exact scope needs its own
upload. Track uploaded-but-not-yet-referenced photos and report them as unassigned rather than
silently discarding them.

## Patch, Retry, And Report

Use `write_inspections` action `patch` with 1–10 distinct sheets per batch. Each sheet entry has its
own `sheetId`, locked `templateVersionId`, stable `requestId`, and 1–50 distinct component
changes. Every change must be evidence-backed. Do not batch unrelated sheets merely to reduce calls,
and never include answers for a sheet the user did not authorize.

Before a patch, persist the sheet and component identities, expected revisions, proposed change,
evidence, and request key. If the response is lost, replay the identical per-sheet request with the
same `requestId`, or re-read the sheet to observe the committed result. Reuse a key only for the
same canonical operation and target; changed content needs a new key. Never retry `create` with a
new key blindly: first re-read `day` to avoid duplicate sheets.

Read every per-sheet result:

- `applied` returns the actual `sheetRevision`, progress, optional `scoreSummary`,
  `missingRequiredCount`, and the first 20 missing required items. Page the sheet detail for the
  complete remaining list.
- `conflict` covers `nonempty`, `revision`, `version`, `ambiguous`, and `stale_cursor`. Re-read
  only the affected sheet and re-decide; never force an overwrite.
- `failed` may report hidden, invalid, limit, media, or internal errors. Preserve already successful
  sheets, report each failure separately, and do not describe the batch as complete.
- Revocation or a permission failure stops retries. A template-version change invalidates old
  writes; re-read the locked sheet and do not auto-replace it.

`create` requires the scope, `templateId`, and `requestId`; `multiple` also needs a nonblank
`name`, and repeated names still require selecting by `sheetId`. `void` requires the current
`expectedSheetRevision` and an operation-specific `requestId`, and only when the user asks to void.
Replacement is explicit: call `preview_replacement`, show retained, cleared, added, and removed
questions, then, only on user direction, call `replace` with the previewed source/target versions,
`expectedActiveRevision`, `expectedSheetRevision`, and a new `requestId`. Do not replace a sheet
automatically because a new template was activated.

The final report names the actual sheets, revisions, progress, score summary, all missing required
items, conflicts/failures, and unassigned photos. A partial or conflicted batch is not a completed
inspection.

## Template Drafts And Explicit Activation

Template operations require current T permission. Use `list` and paged `preview` to inspect a
draft; empty-draft preview is read-only and does not require store read/write. `create` uses a new
client-generated `templateId`, `enterpriseKey`, and a complete definition. `save` replaces the full
definition and requires the current `expectedDraftRevision`. Drafts may be incomplete and may be
saved for review; preview reports definition issues and a static maximum score.

Activation is a separate, explicit user decision. Save the previewed `draftRevision`, re-preview if
it changed, and call `activate` with that exact revision. `deactivate` also requires the current
revision and stops only new sheets; existing sheets keep their locked versions. Saving changes to
stores or copy count does not take effect until a later explicit activation. Never activate,
deactivate, or replace from inferred intent alone.

Do not automate official questionnaire rows, section full scores, red lines, pass/fail lines, or
conditional evidence exceptions. Preserve source SOP text and flag those decisions to the template
maintainer; do not turn a red line or a conditional exception into scoring logic or an automatic
conclusion. A generated draft is a proposal for human review, not an approved or activated official
template. This Skill ships only a pure synthetic example and must never contain a real customer
template, tenant roster, official score table, or historical inspection answer.

## Synthetic Example

The identifiers, enterprise, store, and content below are placeholders. Replace them only with
values the user and the live service authorize.

```json
{
  "command": {
    "action": "create",
    "templateId": "11111111-1111-4111-8111-111111111111",
    "enterpriseKey": "synthetic-enterprise",
    "definition": {
      "title": "合成巡检示例",
      "copyMode": "single",
      "storeIds": ["22222222-2222-4222-8222-222222222222"],
      "questions": [
        {
          "questionId": "33333333-3333-4333-8333-333333333333",
          "title": "合成检查项",
          "category": "合成分类",
          "components": [
            {
              "componentId": "44444444-4444-4444-8444-444444444444",
              "kind": "sop",
              "label": "合成依据",
              "text": "按用户确认的合成步骤核对。"
            },
            {
              "componentId": "55555555-5555-4555-8555-555555555555",
              "kind": "score",
              "label": "合成评分",
              "required": true,
              "minTenths": 0,
              "maxTenths": 10
            }
          ]
        }
      ]
    }
  }
}
```

After reading the locked sheet and confirming the evidence with the user, a patch looks like this:

```json
{
  "command": {
    "action": "patch",
    "patches": [
      {
        "sheetId": "66666666-6666-4666-8666-666666666666",
        "templateVersionId": "77777777-7777-4777-8777-777777777777",
        "requestId": "synthetic-patch-1",
        "changes": [
          {
            "componentId": "55555555-5555-4555-8555-555555555555",
            "op": "fill",
            "value": 8
          },
          {
            "componentId": "88888888-8888-4888-8888-888888888888",
            "op": "appendPhotos",
            "photoIds": ["99999999-9999-4999-8999-999999999999"]
          }
        ]
      }
    ]
  }
}
```

The separate photo upload is flat:

```json
{
  "enterpriseKey": "synthetic-enterprise",
  "storeId": "22222222-2222-4222-8222-222222222222",
  "inspectionDate": "2026-01-15",
  "requestId": "synthetic-photo-1",
  "mediaType": "image/png",
  "filePath": "/absolute/path/synthetic-photo.png"
}
```
