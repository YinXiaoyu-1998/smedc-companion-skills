---
name: smedc-inspection
description: 使用企业智脑（SMEDC）查询门店巡检卷、按现场证据填报及补图，或把检查标准整理成模板草稿。 Use for SMEDC store inspections and inspection templates.
---

# SMEDC Inspection

## Check the connection

Use the employee's authenticated `smedc` MCP connection. Follow `smedc-mcp` for installation,
login, repair, and the approved launcher pin. This companion is candidate source. Live use
requires a compatible launcher and service, all four tools below, and current access to the
target. If any prerequisite fails, identify the missing tool, unavailable service, or denied
scope. Use the inspection tools for inspection data and photos.

| Tool | Actions |
| --- | --- |
| `query_inspections` | `context`, `day`, `sheet`, `photo` |
| `write_inspections` | `create`, `patch`, `void`, `preview_replacement`, `replace` |
| `manage_inspection_templates` | `list`, `preview`, `create`, `save`, `activate`, `deactivate` |
| `upload_inspection_photo` | Flat upload input, with no action |

Put `action` and its fields inside `command` for the first three tools. See
[synthetic examples](references/examples.md) when building a draft, uploading a photo, or
patching a sheet.

## Find the sheet

1. Use `context` to resolve the exact enterprise and official store IDs. Read access covers
   sheets and their authorized photos. Fill access is required for writes and uploads.
   Template maintenance authorizes drafts for that enterprise. Use the user's inspection date
   and keep to their selected scope.
2. Use `day` with `enterpriseKey`, `storeId`, and `inspectionDate` to find sheets and eligible
   template entries. Page until `nextCursor` is null. If several sheets could match, ask which
   one by name and `sheetId`. A read request ends with the requested read results.
3. When asked to create a sheet, use the scope, `templateId`, and `requestId`. A multiple-copy
   template also requires a nonblank `name`. On an `ambiguous` result, re-read `day` and resolve
   the candidate sheets before continuing.
4. Read the selected `sheetId` through all relevant question pages. Use the sheet's fixed
   `templateVersionId`, SOP, answers, and revisions when preparing changes. Restart at the first
   page on `stale_cursor` and re-evaluate against the current revision.

## Fill with evidence

Use observed facts, readable source material, or the user's account of what they saw. Leave gaps
where the available evidence cannot establish an answer or the SOP calls for an on-site
demonstration. Use score tenths (`85` for 8.5 points), status option IDs, and nonblank comments.
Use `fill` for an empty score, status, or comment and `appendPhotos` for relevant photo IDs.
If new evidence conflicts with an existing answer, show the discrepancy and request direction
unless the user already authorized that correction. Use the current `expectedComponentRevision`
with `set`, `clear`, or `removePhotos`.

### Photo evidence

- Upload an original JPEG or PNG with flat `enterpriseKey`, `storeId`, `inspectionDate`,
  `requestId`, and an absolute, readable `filePath`. The launcher checks current fill access
  before reading the file. `mediaType` is optional and must match the bytes when supplied.
  Use the returned `photoId` before its staging `expiresAt`. Reuse the ID for relevant
  components or sheets in the same store and date.
- For an existing photo, `query_inspections` action `photo` takes `photoId`. The launcher
  verifies the original and returns `localPath` with `photoId`, `mediaType`, `byteLength`,
  and `sha256`. Open that file if available to the agent. An upload takes `filePath`.
- If the model can see the image but the launcher cannot read the original, save the supported
  textual findings and leave the photo component open. Give the employee the official store
  name, inspection date, sheet name (or the template title for an unnamed sheet), question
  title, and photo component label so they can find the field in the web app. When titles or
  labels repeat, include the question's position across the full ordered sheet and the
  component's position within that question. Include `sheetId`, `questionId`, and
  `componentId` for traceability. Base observations on the evidence you could actually see.

### Save and reconcile

Use `patch` for 1–10 distinct sheets with 1–50 distinct component changes per sheet. Each
entry carries `sheetId`, `templateVersionId`, and its own `requestId`. The service applies
each sheet atomically and returns results in request order.

- `applied` gives the committed revision, progress, optional score, total required gaps, and
  the first 20 gaps. Page the sheet detail when you need the full list.
- On a conflict such as `nonempty`, `revision`, or `version`, re-read the affected sheet,
  preserve its saved answers, and use a new key for a changed command.
- For a lost response, replay the identical command and `requestId` within the first 24 hours
  while the target remains authorized. After that window, inspect the target before deciding
  on a new command. For an uncertain create, read `day` before attempting another create.
  Report inaccessible or failed targets separately and preserve successful results.

Report applied and pending work by sheet, including missing evidence and unassigned photos.
Use the service's progress and scoring results. Pass/fail judgments, red lines, and on-site
exceptions require the evidence and human decisions specified in the SOP.

## Maintain templates and sheet versions

Template maintenance uses the selected enterprise's current permission. When drafting from a
provided rubric, extract the actual criteria, exclude sample answers and duplicate totals, and
preserve conditional evidence and red-line guidance in the SOP. Flag unresolved criteria or
score discrepancies to the maintainer.

Use `list` and paged `preview` for drafts. Create with a new `templateId`, then save revisions
using the complete definition and `expectedDraftRevision`. Preserve IDs for retained questions
and components, and use new IDs for additions or copies. Check preview issues and static maximum
score before presenting the draft. After explicit approval, call `activate` with the previewed
`draftRevision` as `expectedDraftRevision` to apply the definition, stores, and copy settings.
Re-preview after changes. On explicit direction, `deactivate` with the current revision to
stop creating sheets from the template.

For an explicit sheet replacement, use `preview_replacement` and show the retained, cleared,
added, and removed questions. Submit `replace` only after authorization for that comparison,
using both previewed versions, `expectedActiveRevision`, `expectedSheetRevision`, and
`requestId`. Void only on explicit direction with the current `expectedSheetRevision` and
`requestId`.
